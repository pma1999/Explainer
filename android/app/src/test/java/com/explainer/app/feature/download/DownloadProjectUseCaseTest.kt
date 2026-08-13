package com.explainer.app.feature.download

import com.explainer.app.core.model.SnapshotContractException
import com.explainer.app.core.model.SnapshotError
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.snapshot.SnapshotStoreError
import com.explainer.app.data.local.snapshot.SnapshotStoreException
import com.explainer.app.data.remote.contract.RemoteResult
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * Aceptación del motor puro (T06): stream → validación → prepare → commit
 * con fakes del remote (T02), store/DAOs (T03) y sesión (T04). Cubre el happy
 * path, estimación/preflight, cancelación, clasificación de reintentos y que
 * ningún fallo borra ni reemplaza el snapshot previo.
 */
class DownloadProjectUseCaseTest {

    private lateinit var tempDir: File
    private val remote = FakeRemote()
    private val store = FakeStore()
    private val dao = InMemoryDownloadStateDao()
    private val summaryDao = InMemorySummaryDao()

    private var freeBytes: Long = Long.MAX_VALUE
    private var sessionOwner: String? = TEST_OWNER_A
    private var now: Long = 0L
    private var uuidCounter = 0

    private val states = mutableListOf<DownloadState>()

    @Before
    fun setUp() {
        tempDir = File.createTempFile("download-engine", ".dir").apply {
            delete()
            mkdirs()
        }
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    private fun engine(): DownloadProjectUseCase = DownloadProjectUseCase(
        remote = remote,
        store = store,
        downloadDao = dao,
        summaryDao = summaryDao,
        tempDirProvider = { tempDir },
        diskFreeBytes = { freeBytes },
        sessionOwner = { sessionOwner },
        uuidProvider = { "uuid-${++uuidCounter}" },
        nowMillis = { now },
    )

    private fun execute(
        workId: String = "w1",
        attempt: Int = 1,
    ): DownloadOutcome = runBlocking {
        states.clear()
        engine().execute(
            DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, workId, attempt),
            emitState = { states.add(it) },
        )
    }

    private fun setPreviousSnapshot(generation: String = "gen-old", totalBytes: Long = 845L) {
        store.manifest = com.explainer.app.data.local.snapshot.OfflineProjectManifest(
            ownerId = TEST_OWNER_A,
            projectId = TEST_PROJECT_ID,
            name = "previo",
            description = null,
            status = com.explainer.app.core.model.ProjectStatus.Completed,
            sourceType = "pdf",
            parts = emptyList(),
            usage = kotlinx.serialization.json.JsonObject(emptyMap()),
            readingProgress = com.explainer.app.core.model.ReadingProgress(),
            activeGeneration = generation,
            sourceUpdatedAt = "2026-08-01T00:00:00Z",
            downloadedAt = 1L,
            totalBytes = totalBytes,
        )
    }

    private fun emissions(): List<DownloadState> = states

    private fun downloadingStates(): List<DownloadState.Downloading> =
        states.filterIsInstance<DownloadState.Downloading>()

    // ------------------------------------------------------------------
    // Happy path
    // ------------------------------------------------------------------

    @Test
    fun `happy path emits full sequence and commits once with expected work id`() {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_QUEUED, requestedAt = 7L)
        remote.body = "abc"
        val outcome = execute()

        assertEquals(DownloadOutcome.Succeeded, outcome)
        // Transiciones + valor final SIEMPRE publicados: para un body de un
        // solo chunk, el final (3 bytes) se emite además del throttled.
        assertEquals(
            listOf(
                DownloadState.Queued::class,
                DownloadState.Downloading::class,
                DownloadState.Downloading::class,
                DownloadState.Downloading::class,
                DownloadState.Preparing::class,
                DownloadState.Committing::class,
            ),
            states.dropLast(1).map { it::class },
        )
        assertTrue(states.last() is DownloadState.Succeeded)
        assertEquals(listOf("w1"), store.commitCalls)
        assertEquals(1, store.committedDescriptors.size)
        // Temporal con namespace owner/proyecto + UUID bajo cacheDir (R-T06-06),
        // eliminado al terminar.
        assertEquals(
            "download-${TEST_OWNER_A}-${TEST_PROJECT_ID.value}-uuid-1.json",
            remote.lastDestination?.name,
        )
        assertEquals(tempDir, remote.lastDestination?.parentFile)
        assertTrue(tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `content length arrives and final total is exact when verified`() {
        dao.seed(TEST_OWNER_A)
        remote.body = "abc"
        remote.totalBytes = 3L
        val outcome = execute()

        assertEquals(DownloadOutcome.Succeeded, outcome)
        val downloading = downloadingStates()
        // HEADER desde el primer chunk; EXACT en el valor final verificado.
        assertEquals(SizeConfidence.HEADER, downloading[1].estimate?.confidence)
        assertEquals(3L, downloading[1].totalBytes)
        val finalState = downloadingStates().last()
        assertEquals(3L, finalState.downloadedBytes)
        assertEquals(3L, finalState.totalBytes)
        assertEquals(SizeConfidence.EXACT, finalState.estimate?.confidence)
    }

    @Test
    fun `preflight estimate uses segmentation bytes and current snapshot size`() {
        dao.seed(TEST_OWNER_A)
        summaryDao.seed(TEST_OWNER_A, segmentationSourceBytes = 2_000_000L)
        setPreviousSnapshot()
        remote.body = "abc"

        val outcome = execute()
        assertEquals(DownloadOutcome.Succeeded, outcome)
        val first = downloadingStates().first()
        assertEquals(SizeConfidence.HEURISTIC, first.estimate?.confidence)
        assertEquals(4_000_000L, first.estimate?.lowBytes)
        assertEquals(12_000_000L, first.estimate?.highBytes)
        assertEquals(845L, first.estimate?.currentSnapshotBytes)
    }

    @Test
    fun `work id is synced into the coordinator row on first contact`() {
        dao.seed(TEST_OWNER_A, workId = "", state = DownloadStateEntity.STATE_QUEUED)
        remote.body = "abc"

        assertEquals(DownloadOutcome.Succeeded, execute())
        assertEquals("w1", dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).workId)
    }

    // ------------------------------------------------------------------
    // Espacio
    // ------------------------------------------------------------------

    @Test
    fun `no space at preflight fails before any remote call and keeps snapshot`() {
        dao.seed(TEST_OWNER_A)
        setPreviousSnapshot()
        freeBytes = 0L

        val outcome = execute()
        assertEquals(DownloadOutcome.Failed(DownloadError.NotEnoughSpace), outcome)
        assertEquals(0, remote.downloadCalls)
        assertTrue(store.commitCalls.isEmpty())
        assertTrue(store.committedDescriptors.isEmpty())
        // Snapshot previo intacto.
        assertEquals("gen-old", store.manifest?.activeGeneration)
        assertTrue(tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `content length larger than available space trips during stream and never commits`() {
        dao.seed(TEST_OWNER_A)
        remote.body = "abc"
        remote.totalBytes = 100L * 1024 * 1024 // 100 MiB
        // Preflight con heurístico (suelo 1 MiB) cabe; el header real no.
        freeBytes = StorageGuard.requiredFreeBytes(SizeEstimator.FLOOR_BYTES)

        val outcome = execute()
        assertEquals(DownloadOutcome.Failed(DownloadError.NotEnoughSpace), outcome)
        assertTrue(store.prepareCalls.isEmpty())
        assertTrue(store.commitCalls.isEmpty())
        assertTrue(store.committedDescriptors.isEmpty())
        assertTrue(tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `progress emissions are throttled while the final value is always published`() {
        dao.seed(TEST_OWNER_A)
        remote.body = "x".repeat(1024 * 1024) // 1 MiB en 16 chunks de 64 KiB
        remote.totalBytes = (1024 * 1024).toLong()
        now = 0L // reloj congelado: solo el umbral de 256 KiB emite

        assertEquals(DownloadOutcome.Succeeded, execute())
        val downloads = downloadingStates()
        // 1 inicial + ~4 a mitad de stream (cada 256 KiB) + 1 final << 16 chunks.
        assertTrue(
            "emisiones ${downloads.size} deben ser mucho menores que los chunks reportados",
            downloads.size < remote.progressReports.size,
        )
        // El valor final SIEMPRE se publica (bytes exactos verificados).
        val finalState = downloads.last()
        assertEquals((1024 * 1024).toLong(), finalState.downloadedBytes)
        assertEquals((1024 * 1024).toLong(), finalState.totalBytes)
    }

    // ------------------------------------------------------------------
    // Cancelación y fallos
    // ------------------------------------------------------------------

    @Test
    fun `cancellation mid stream cleans temp and keeps previous snapshot`() {
        dao.seed(TEST_OWNER_A)
        store.manifest = null
        remote.body = "x".repeat(1024 * 1024)
        remote.cancelAfterChunks = 2

        val outcome = execute()
        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertTrue(store.commitCalls.isEmpty())
        assertTrue(tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `remote cancelled result maps to cancelled without commit`() {
        dao.seed(TEST_OWNER_A)
        remote.resultOverride = RemoteResult.Cancelled

        val outcome = execute()
        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertTrue(states.last() is DownloadState.Cancelled)
        assertTrue(store.commitCalls.isEmpty())
    }

    @Test
    fun `commit rejection by cancel or delete race maps to cancelled`() {
        dao.seed(TEST_OWNER_A)
        remote.body = "abc"
        store.rejectCommits = true // cancel/delete marcaron la fila antes del commit

        val outcome = execute()
        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertTrue(states.last() is DownloadState.Cancelled)
        assertTrue(store.committedDescriptors.isEmpty())
        assertTrue(tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `terminal row at start returns cancelled without touching remote`() {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_CANCELLED)

        val outcome = execute()
        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertEquals(0, remote.downloadCalls)
        assertTrue(store.commitCalls.isEmpty())
    }

    @Test
    fun `deleted row at start returns cancelled without touching remote`() {
        // deleteLocal borró la fila: un worker tardío no descarga ni republica.
        val outcome = execute()
        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertEquals(0, remote.downloadCalls)
    }

    @Test
    fun `session owner mismatch never downloads foreign data`() {
        dao.seed(TEST_OWNER_A)
        sessionOwner = TEST_OWNER_B

        val outcome = execute()
        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertEquals(0, remote.downloadCalls)
    }

    @Test
    fun `null session never downloads either`() {
        // R-T06-03: la igualdad es ESTRICTA con un owner de sesión no nulo;
        // sin sesión (logout) el worker tampoco descarga.
        dao.seed(TEST_OWNER_A)
        sessionOwner = null

        val outcome = execute()
        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertEquals(0, remote.downloadCalls)
    }

    @Test
    fun `404 auth and permanent map to their failure categories`() {
        dao.seed(TEST_OWNER_A)

        remote.resultOverride = RemoteResult.NotFound
        assertEquals(DownloadOutcome.Failed(DownloadError.NotFound), execute())

        remote.resultOverride = RemoteResult.AuthRequired
        assertEquals(DownloadOutcome.Failed(DownloadError.AuthRequired), execute())

        remote.resultOverride = RemoteResult.PermanentFailure("http:400")
        assertEquals(DownloadOutcome.Failed(DownloadError.Permanent("http:400")), execute())

        remote.resultOverride = RemoteResult.InvalidPayload("json")
        assertEquals(DownloadOutcome.Failed(DownloadError.InvalidPayload("json")), execute())
    }

    // ------------------------------------------------------------------
    // R-T06-02: el fallo terminal SIEMPRE se persiste como Failed (durable)
    // ------------------------------------------------------------------

    @Test
    fun `every failed path emits a durable failed state and keeps the previous snapshot`() {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        setPreviousSnapshot()

        // Preflight sin espacio.
        freeBytes = 0L
        assertEquals(DownloadOutcome.Failed(DownloadError.NotEnoughSpace), execute())
        assertLastFailed(DownloadError.NotEnoughSpace)

        // Espacio agotado durante el stream (Content-Length mayor que el libre).
        freeBytes = StorageGuard.requiredFreeBytes(SizeEstimator.FLOOR_BYTES)
        remote.body = "abc"
        remote.totalBytes = 100L * 1024 * 1024
        assertEquals(DownloadOutcome.Failed(DownloadError.NotEnoughSpace), execute())
        assertLastFailed(DownloadError.NotEnoughSpace)

        // 404 / 401 definitivo / 4xx permanente / payload inválido de red.
        freeBytes = Long.MAX_VALUE
        remote.resultOverride = RemoteResult.NotFound
        assertEquals(DownloadOutcome.Failed(DownloadError.NotFound), execute())
        assertLastFailed(DownloadError.NotFound)

        remote.resultOverride = RemoteResult.AuthRequired
        assertEquals(DownloadOutcome.Failed(DownloadError.AuthRequired), execute())
        assertLastFailed(DownloadError.AuthRequired)

        remote.resultOverride = RemoteResult.PermanentFailure("http:400")
        assertEquals(DownloadOutcome.Failed(DownloadError.Permanent("http:400")), execute())
        assertLastFailed(DownloadError.Permanent("http:400"))

        remote.resultOverride = RemoteResult.InvalidPayload("json")
        assertEquals(DownloadOutcome.Failed(DownloadError.InvalidPayload("json")), execute())
        assertLastFailed(DownloadError.InvalidPayload("json"))

        // Parse (contrato) y fallo local durante prepare.
        remote.resultOverride = null
        store.prepareError = SnapshotContractException(SnapshotError.InvalidProjectId("x"))
        assertEquals(DownloadOutcome.Failed(DownloadError.InvalidPayload("json")), execute())
        assertLastFailed(DownloadError.InvalidPayload("json"))

        store.prepareError = SnapshotStoreException(SnapshotStoreError.PayloadNotReadable("file"))
        assertEquals(DownloadOutcome.Failed(DownloadError.Local("file")), execute())
        assertLastFailed(DownloadError.Local("file"))

        // Retry agotado (quinto intento) → Network terminal.
        store.prepareError = null
        remote.resultOverride = RemoteResult.Retryable
        assertEquals(DownloadOutcome.Failed(DownloadError.Network), execute(attempt = 5))
        assertLastFailed(DownloadError.Network)

        // Ninguna ruta de fallo borró ni sustituyó la versión anterior.
        assertEquals("gen-old", store.manifest?.activeGeneration)
        assertTrue(store.committedDescriptors.isEmpty())
    }

    @Test
    fun `retryable outcomes never emit a terminal failed state`() {
        // R-T06-02: el intermedio Retryable NO se convierte en terminal; la
        // fila permanece activa para el siguiente intento de WorkManager.
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        remote.resultOverride = RemoteResult.Retryable

        assertEquals(DownloadOutcome.Retryable, execute(attempt = 1))
        assertTrue("intento 1 no debe emitir Failed", states.none { it is DownloadState.Failed })

        assertEquals(DownloadOutcome.Retryable, execute(attempt = 4))
        assertTrue("intento 4 no debe emitir Failed", states.none { it is DownloadState.Failed })
    }

    private fun assertLastFailed(error: DownloadError) {
        val last = states.last()
        assertTrue("la última emisión debe ser Failed($error), fue $last", last is DownloadState.Failed)
        assertEquals(error, (last as DownloadState.Failed).error)
    }

    // ------------------------------------------------------------------
    // R-T06-06: temporal no borrable → orphan registrado y sweep posterior
    // ------------------------------------------------------------------

    @Test
    fun `temp file that cannot be deleted is registered as orphan and swept by the next run`() {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        // El stream ESCRIBE el temporal (body "abc") y prepare falla después:
        // así el fichero existe de verdad cuando el finally intenta borrarlo.
        remote.body = "abc"
        store.prepareError = SnapshotContractException(SnapshotError.InvalidProjectId("x"))
        var deleteWorks = false
        // Fake del FS: cuando "coopera", borra de verdad; si no, se niega.
        val cleaner = TempFileCleaner({ tempDir }, { deleteWorks && it.delete() })
        val engine = DownloadProjectUseCase(
            remote = remote,
            store = store,
            downloadDao = dao,
            summaryDao = summaryDao,
            tempDirProvider = { tempDir },
            diskFreeBytes = { freeBytes },
            sessionOwner = { sessionOwner },
            tempFileCleaner = cleaner,
        )

        // 1er run: el filesystem se niega a borrar el temporal → orphan.
        runBlocking {
            assertEquals(
                DownloadOutcome.Failed(DownloadError.InvalidPayload("json")),
                engine.execute(DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, "w1", 1), emitState = {}),
            )
        }
        assertEquals(1, cleaner.orphansPending)
        assertEquals(1, tempDir.listFiles()?.size)

        // 2º run: el sweep de arranque elimina el orphan (el FS ya coopera) y
        // el temporal propio se borra con normalidad.
        deleteWorks = true
        store.prepareError = null
        runBlocking {
            assertEquals(
                DownloadOutcome.Succeeded,
                engine.execute(DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, "w1", 1), emitState = {}),
            )
        }
        assertTrue("el orphan debe desaparecer con el sweep posterior", tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `retryable and rate limited retry until the fifth attempt is final`() {
        dao.seed(TEST_OWNER_A)

        remote.resultOverride = RemoteResult.Retryable
        assertEquals(DownloadOutcome.Retryable, execute(attempt = 1))
        assertEquals(DownloadOutcome.Retryable, execute(attempt = 4))
        assertEquals(DownloadOutcome.Failed(DownloadError.Network), execute(attempt = 5))

        remote.resultOverride = RemoteResult.RateLimited
        assertEquals(DownloadOutcome.Retryable, execute(attempt = 3))
        assertEquals(DownloadOutcome.Failed(DownloadError.Network), execute(attempt = 5))
    }

    @Test
    fun `parse failure during prepare maps to invalid payload and keeps snapshot`() {
        dao.seed(TEST_OWNER_A)
        remote.body = "abc"
        store.prepareError = SnapshotContractException(SnapshotError.InvalidProjectId("x"))

        val outcome = execute()
        assertEquals(DownloadOutcome.Failed(DownloadError.InvalidPayload("json")), outcome)
        assertTrue(store.commitCalls.isEmpty())
        assertTrue(tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `unreadable temp maps to local failure and keeps snapshot`() {
        dao.seed(TEST_OWNER_A)
        remote.body = "abc"
        store.prepareError = SnapshotStoreException(SnapshotStoreError.PayloadNotReadable("file"))

        val outcome = execute()
        assertEquals(DownloadOutcome.Failed(DownloadError.Local("file")), outcome)
        assertTrue(store.commitCalls.isEmpty())
        assertTrue(tempDir.listFiles().isNullOrEmpty())
    }

    @Test
    fun `sweep at engine start does not delete an active temp of another project`() {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_QUEUED)
        remote.body = "abc"
        // Temporal ACTIVO de otro proyecto (misma cache compartida): aunque el
        // motor de ESTE proyecto barra huérfanos al arrancar, no debe tocarlo.
        val foreignLive = File(
            tempDir,
            TempFileCleaner.prefixFor(TEST_OWNER_A, OTHER_PROJECT_ID.value) + "live-uuid.json",
        ).apply { writeText("{}") }
        // Huérfano del MISMO proyecto de una corrida previa: el sweep lo borra.
        val ownOrphan = File(
            tempDir,
            TempFileCleaner.prefixFor(TEST_OWNER_A, TEST_PROJECT_ID.value) + "dead-uuid.json",
        ).apply { writeText("{}") }

        assertEquals(DownloadOutcome.Succeeded, execute())

        assertTrue("el temporal ACTIVO de otro proyecto sobrevive al sweep y al run", foreignLive.exists())
        assertFalse("el huérfano del mismo proyecto se barre al arrancar", ownOrphan.exists())
        // El temporal propio del run se limpió: en cache solo queda el ajeno.
        assertEquals(listOf(foreignLive.name), tempDir.listFiles()?.map { it.name })
    }

    @Test
    fun `failed download never deletes the previous snapshot`() {
        dao.seed(TEST_OWNER_A)
        remote.body = "abc"
        val previous = store.committedDescriptors.size

        remote.resultOverride = RemoteResult.Retryable
        assertEquals(DownloadOutcome.Failed(DownloadError.Network), execute(attempt = 5))
        remote.resultOverride = RemoteResult.NotFound
        execute()
        remote.resultOverride = null
        store.rejectCommits = true
        execute()

        assertEquals(previous, store.committedDescriptors.size)
        assertNull(store.manifest) // nunca se creó snapshot nuevo
    }
}

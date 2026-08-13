package com.explainer.app.feature.download

import com.explainer.app.data.local.db.DownloadStateEntity
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * Carreras con barrera determinista (R-T06-01): cancel/delete intercalados
 * con persist / sync (reclamo del workId) / commit. El compare-and-set
 * atómico de [DownloadStateDao.casUpdate] garantiza que una escritura stale
 * jamás reactiva una fila borrada, sobrescribe un estado terminal ni pisa el
 * workId de otro intento; el commit (T03) rechaza al worker tardío.
 *
 * Cada test bloquea la escritura del worker en una barrera, ejecuta la
 * acción del coordinador (cancel/delete) y luego libera la barrera: el CAS
 * debe perder la carrera sin efectos.
 */
class DownloadRaceBarrierTest {

    private lateinit var tempDir: File
    private val dao = InMemoryDownloadStateDao()
    private var now = 0L
    private val persister = DownloadStatePersister(dao) { now }

    @Before
    fun setUp() {
        tempDir = File.createTempFile("download-race", ".dir").apply {
            delete()
            mkdirs()
        }
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    // ------------------------------------------------------------------
    // persist vs delete / cancel
    // ------------------------------------------------------------------

    @Test
    fun `persist loses to a concurrent delete and never recreates the row`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 10L)
        dao.casStarted = CompletableDeferred()
        dao.casGate = CompletableDeferred()

        val job = launch {
            persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Downloading(50L, 100L))
        }
        dao.casStarted!!.await() // la escritura del worker está en vuelo
        dao.delete(TEST_OWNER_A, TEST_PROJECT_ID.value) // deleteLocal borra la fila
        dao.casGate!!.complete(Unit)
        job.join()

        assertTrue("el persist stale no debe recrear la fila borrada", dao.rows.isEmpty())
    }

    @Test
    fun `persist loses to a concurrent cancel and leaves the terminal state`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 10L)
        dao.casStarted = CompletableDeferred()
        dao.casGate = CompletableDeferred()

        val job = launch {
            persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Downloading(50L, 100L))
        }
        dao.casStarted!!.await()
        // cancel() marcó la fila terminal ANTES de cancelar WorkManager.
        dao.upsert(
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).copy(
                state = DownloadStateEntity.STATE_CANCELLED,
                finishedAt = 999L,
            ),
        )
        dao.casGate!!.complete(Unit)
        job.join()

        val row = dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals(DownloadStateEntity.STATE_CANCELLED, row.state)
        assertEquals("el progreso stale no se aplica sobre un estado terminal", 10L, row.downloadedBytes)
        assertEquals(999L, row.finishedAt)
    }

    // ------------------------------------------------------------------
    // sync (reclamo del workId) vs cancel / delete
    // ------------------------------------------------------------------

    @Test
    fun `worker claim loses to a concurrent cancel and never touches the network`() = runBlocking {
        val remote = FakeRemote()
        val store = FakeStore()
        val summaryDao = InMemorySummaryDao()
        dao.seed(TEST_OWNER_A, workId = "", state = DownloadStateEntity.STATE_QUEUED)
        dao.casStarted = CompletableDeferred()
        dao.casGate = CompletableDeferred()
        val engine = engine(remote, store, summaryDao)

        val deferred = async {
            engine.execute(DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, "w1", 1), emitState = {})
        }
        dao.casStarted!!.await() // el reclamo (sync) está en vuelo
        dao.upsert(
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).copy(
                state = DownloadStateEntity.STATE_CANCELLED,
                finishedAt = 999L,
            ),
        )
        dao.casGate!!.complete(Unit)

        assertEquals(DownloadOutcome.Cancelled, deferred.await())
        assertEquals("un worker tardío no descarga tras cancel", 0, remote.downloadCalls)
        assertEquals(DownloadStateEntity.STATE_CANCELLED, dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).state)
    }

    @Test
    fun `worker claim loses to a concurrent delete and never recreates the row`() = runBlocking {
        val remote = FakeRemote()
        val store = FakeStore()
        val summaryDao = InMemorySummaryDao()
        dao.seed(TEST_OWNER_A, workId = "", state = DownloadStateEntity.STATE_QUEUED)
        dao.casStarted = CompletableDeferred()
        dao.casGate = CompletableDeferred()
        val engine = engine(remote, store, summaryDao)

        val deferred = async {
            engine.execute(DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, "w1", 1), emitState = {})
        }
        dao.casStarted!!.await()
        dao.delete(TEST_OWNER_A, TEST_PROJECT_ID.value) // deleteLocal borró la fila
        dao.casGate!!.complete(Unit)

        assertEquals(DownloadOutcome.Cancelled, deferred.await())
        assertEquals(0, remote.downloadCalls)
        assertTrue("el reclamo stale no recrea la fila borrada", dao.rows.isEmpty())
    }

    @Test
    fun `worker claim never overwrites a row claimed by a newer attempt`() = runBlocking {
        val remote = FakeRemote()
        val store = FakeStore()
        val summaryDao = InMemorySummaryDao()
        // La fila ya la reclamó el intento nuevo (workId "w2"): el worker
        // viejo (espera "w1") NO puede pisar el workId ajeno.
        dao.seed(TEST_OWNER_A, workId = "w2", state = DownloadStateEntity.STATE_QUEUED)
        val engine = engine(remote, store, summaryDao)

        val outcome = engine.execute(DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, "w1", 1), emitState = {})

        assertEquals(DownloadOutcome.Cancelled, outcome)
        assertEquals(0, remote.downloadCalls)
        assertEquals("w2", dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).workId)
    }

    // ------------------------------------------------------------------
    // commit vs cancel
    // ------------------------------------------------------------------

    @Test
    fun `commit loses to a concurrent cancel and never publishes`() = runBlocking {
        val remote = FakeRemote().apply { body = "abc" }
        val store = FakeStore()
        val summaryDao = InMemorySummaryDao()
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        store.commitStarted = CompletableDeferred()
        store.commitGate = CompletableDeferred()
        // Paridad con `SnapshotCommitPolicy.workStillActive` (T03): el commit
        // solo publica si la fila sigue activa en el momento de la transacción.
        store.workStillActive = {
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).state == DownloadStateEntity.STATE_DOWNLOADING
        }
        val engine = engine(remote, store, summaryDao)

        val deferred = async {
            engine.execute(DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, "w1", 1), emitState = {})
        }
        store.commitStarted!!.await() // el commit está en vuelo
        dao.upsert(
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).copy(
                state = DownloadStateEntity.STATE_CANCELLED,
                finishedAt = 999L,
            ),
        )
        store.commitGate!!.complete(Unit)

        assertEquals(DownloadOutcome.Cancelled, deferred.await())
        assertTrue("el commit tardío no publica nada", store.committedDescriptors.isEmpty())
        assertEquals(listOf("w1"), store.commitCalls)
        assertEquals(DownloadStateEntity.STATE_CANCELLED, dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).state)
    }

    private fun engine(
        remote: FakeRemote,
        store: FakeStore,
        summaryDao: InMemorySummaryDao,
    ) = DownloadProjectUseCase(
        remote = remote,
        store = store,
        downloadDao = dao,
        summaryDao = summaryDao,
        tempDirProvider = { tempDir },
        diskFreeBytes = { Long.MAX_VALUE },
        sessionOwner = { TEST_OWNER_A },
        uuidProvider = { "uuid-race" },
    )
}

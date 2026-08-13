package com.explainer.app.feature.download

import androidx.work.BackoffPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.work.DownloadProjectWorker
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Aceptación del coordinador sobre fakes de scheduler/DAO/store (JVM, sin
 * WorkManager real): enqueue único con KEEP, marcar antes de cancelar, delete
 * solo local y observe owner-scoped. El request real se construye para
 * verificar constraints/backoff/tags/Data pequeños.
 */
class WorkManagerDownloadCoordinatorTest {

    private class FakeScheduler(
        private val events: MutableList<String>,
    ) : DownloadWorkScheduler {
        val enqueued = mutableListOf<Pair<String, OneTimeWorkRequest>>()
        val cancelled = mutableListOf<String>()
        var failEnqueue = false

        override fun enqueueUnique(name: String, request: OneTimeWorkRequest) {
            events.add("scheduler:enqueue:$name")
            if (failEnqueue) throw IllegalStateException("WorkManager no inicializado")
            enqueued.add(name to request)
        }

        override fun cancelUnique(name: String) {
            events.add("scheduler:cancel:$name")
            cancelled.add(name)
        }
    }

    private val events = mutableListOf<String>()
    private val scheduler = FakeScheduler(events)
    private val dao = InMemoryDownloadStateDao(events)
    private val store = FakeStore().also {
        it.events = events
        // Paridad con T03: deleteProject también elimina la fila de descarga.
        it.onDelete = { owner, project -> dao.rows.remove(owner to project) }
    }
    private val summaryDao = InMemorySummaryDao()
    private val requestFactory = DownloadWorkRequestFactory()
    private var sessionOwner: String? = TEST_OWNER_A
    private var now = 1000L
    private val tempSweepScopes = mutableListOf<Pair<String, String>>()

    private fun coordinator(): WorkManagerDownloadCoordinator = WorkManagerDownloadCoordinator(
        scheduler = scheduler,
        requestFactory = requestFactory,
        downloadDao = dao,
        store = store,
        summaryDao = summaryDao,
        sessionOwner = { sessionOwner },
        nowMillis = { now },
        sessionPollMillis = 1L, // tests: detección inmediata del cambio de sesión
        tempOrphanSweep = { owner, project -> tempSweepScopes.add(owner to project) },
    )

    // ------------------------------------------------------------------
    // Enqueue
    // ------------------------------------------------------------------

    @Test
    fun `enqueue creates one unique work with connected constraint backoff tags and small input`() = runBlocking {
        val result = coordinator().enqueue(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(EnqueueResult.Enqueued, result)
        assertEquals(1, scheduler.enqueued.size)
        val (name, request) = scheduler.enqueued.single()
        assertEquals(DownloadWorkNames.forProject(TEST_OWNER_A, TEST_PROJECT_ID), name)

        // Data solo con IDs pequeños.
        assertEquals(TEST_OWNER_A, request.workSpec.input.getString(DownloadProjectWorker.KEY_OWNER_ID))
        assertEquals(TEST_PROJECT_ID.value, request.workSpec.input.getString(DownloadProjectWorker.KEY_PROJECT_ID))
        assertEquals(2, request.workSpec.input.keyValueMap.size)

        // Constraints/backoff/etiquetas contractuales.
        assertEquals(NetworkType.CONNECTED, request.workSpec.constraints.requiredNetworkType)
        assertEquals(BackoffPolicy.EXPONENTIAL, request.workSpec.backoffPolicy)
        assertEquals(30_000L, request.workSpec.backoffDelayDuration)
        assertTrue(request.tags.contains(DownloadWorkNames.ownerTag(TEST_OWNER_A)))
        assertTrue(request.tags.contains(DownloadWorkNames.projectTag(TEST_PROJECT_ID)))

        // Fila durable encolada (workId lo fija el Worker al arrancar).
        val row = dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals(DownloadStateEntity.STATE_QUEUED, row.state)
        assertEquals("", row.workId)
        assertEquals(1000L, row.requestedAt)

        // R-T06-04: la fila se persiste ANTES de hacer visible el WorkRequest,
        // para que un Worker que arranque inmediatamente la encuentre.
        assertEquals(
            listOf(
                "dao:upsert:${DownloadStateEntity.STATE_QUEUED}",
                "scheduler:enqueue:${DownloadWorkNames.forProject(TEST_OWNER_A, TEST_PROJECT_ID)}",
            ),
            events,
        )
    }

    @Test
    fun `worker starting immediately after enqueue sees the queued row and downloads`() = runBlocking {
        // R-T06-04: el fake del scheduler ARRANCA el worker dentro del
        // enqueue (como WorkManager con red disponible): debe ver la fila
        // Queued ya persistida y completar la descarga.
        val tempDir = File.createTempFile("download-coordinator", ".dir").apply {
            delete()
            mkdirs()
        }
        try {
            val remote = FakeRemote().apply { body = "abc" }
            val store = FakeStore()
            val dao = InMemoryDownloadStateDao()
            val summaryDao = InMemorySummaryDao()
            val engine = DownloadProjectUseCase(
                remote = remote,
                store = store,
                downloadDao = dao,
                summaryDao = summaryDao,
                tempDirProvider = { tempDir },
                diskFreeBytes = { Long.MAX_VALUE },
                sessionOwner = { TEST_OWNER_A },
                uuidProvider = { "uuid-1" },
            )
            val persister = DownloadStatePersister(dao)
            var rowAtWorkerStart: DownloadStateEntity? = null
            val workerWorkId = "wm-1"

            val immediateScheduler = object : DownloadWorkScheduler {
                override fun enqueueUnique(name: String, request: OneTimeWorkRequest) {
                    // El Worker arranca DENTRO del enqueue (ejecución inmediata).
                    runBlocking {
                        rowAtWorkerStart = dao.row(TEST_OWNER_A, TEST_PROJECT_ID.value)
                        engine.execute(
                            DownloadRequest(TEST_OWNER_A, TEST_PROJECT_ID, workerWorkId, 1),
                            emitState = { state ->
                                persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, workerWorkId, state)
                            },
                        )
                    }
                }

                override fun cancelUnique(name: String) = Unit
            }
            val coordinator = WorkManagerDownloadCoordinator(
                scheduler = immediateScheduler,
                requestFactory = requestFactory,
                downloadDao = dao,
                store = store,
                summaryDao = summaryDao,
                sessionOwner = { TEST_OWNER_A },
            )

            val result = coordinator.enqueue(TEST_OWNER_A, TEST_PROJECT_ID)

            assertEquals(EnqueueResult.Enqueued, result)
            assertNotNull("el worker inmediato debe ver la fila Queued", rowAtWorkerStart)
            assertEquals(DownloadStateEntity.STATE_QUEUED, rowAtWorkerStart?.state)
            assertEquals(listOf(workerWorkId), store.commitCalls)
            assertEquals(
                DownloadStateEntity.STATE_SUCCEEDED,
                dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).state,
            )
        } finally {
            tempDir.deleteRecursively()
        }
    }

    @Test
    fun `enqueue failure reconciles the orphan queued row`() = runBlocking {
        // R-T06-04: si WorkManager rechaza el trabajo, la fila Queued sin
        // trabajo real no puede quedar huérfana.
        scheduler.failEnqueue = true

        val result = coordinator().enqueue(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(EnqueueResult.EnqueueFailed, result)
        assertTrue(dao.rows.isEmpty())
        assertTrue(scheduler.enqueued.isEmpty())
    }

    @Test
    fun `second enqueue while active returns AlreadyActive without scheduling`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)

        val result = coordinator().enqueue(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(EnqueueResult.AlreadyActive, result)
        assertTrue(scheduler.enqueued.isEmpty())
    }

    @Test
    fun `enqueue after a terminal state schedules a fresh work`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_FAILED)

        assertEquals(EnqueueResult.Enqueued, coordinator().enqueue(TEST_OWNER_A, TEST_PROJECT_ID))
        assertEquals(1, scheduler.enqueued.size)
    }

    @Test
    fun `enqueue with a foreign session owner is rejected without scheduling`() = runBlocking {
        sessionOwner = TEST_OWNER_B

        val result = coordinator().enqueue(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(EnqueueResult.InvalidOwner, result)
        assertTrue(scheduler.enqueued.isEmpty())
        assertTrue(dao.rows.isEmpty())
    }

    @Test
    fun `enqueue with an unsafe owner id is rejected without scheduling`() = runBlocking {
        val result = coordinator().enqueue("../evil", TEST_PROJECT_ID)

        assertEquals(EnqueueResult.InvalidOwner, result)
        assertTrue(scheduler.enqueued.isEmpty())
        assertTrue(dao.rows.isEmpty())
    }

    // ------------------------------------------------------------------
    // Cancel / delete (orden: marcar ANTES de cancelar WorkManager)
    // ------------------------------------------------------------------

    @Test
    fun `cancel marks the row cancelled before cancelling the work`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        events.clear()

        coordinator().cancel(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(
            listOf(
                "dao:upsert:${DownloadStateEntity.STATE_CANCELLED}",
                "scheduler:cancel:${DownloadWorkNames.forProject(TEST_OWNER_A, TEST_PROJECT_ID)}",
            ),
            events,
        )
        val row = dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals(DownloadStateEntity.STATE_CANCELLED, row.state)
        assertEquals(1000L, row.finishedAt)
    }

    @Test
    fun `cancel does not downgrade a terminal state`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_SUCCEEDED)

        coordinator().cancel(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(DownloadStateEntity.STATE_SUCCEEDED, dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).state)
        assertEquals(1, scheduler.cancelled.size)
    }

    @Test
    fun `delete local marks then cancels then removes snapshot and state without remote`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        store.manifest = null
        events.clear()

        coordinator().deleteLocal(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(
            listOf(
                "dao:upsert:${DownloadStateEntity.STATE_CANCELLED}",
                "scheduler:cancel:${DownloadWorkNames.forProject(TEST_OWNER_A, TEST_PROJECT_ID)}",
                "store:delete:$TEST_OWNER_A:${TEST_PROJECT_ID.value}",
            ),
            events,
        )
        assertTrue(dao.rows.isEmpty())
        assertEquals(listOf(TEST_OWNER_A to TEST_PROJECT_ID.value), store.deleteCalls)
        // deleteLocal nunca invoca el remoto: no hay ProjectRemoteDataSource aquí.
    }

    @Test
    fun `delete local without an active row still cancels and deletes`() = runBlocking {
        coordinator().deleteLocal(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(listOf(DownloadWorkNames.forProject(TEST_OWNER_A, TEST_PROJECT_ID)), scheduler.cancelled)
        assertEquals(listOf(TEST_OWNER_A to TEST_PROJECT_ID.value), store.deleteCalls)
    }

    // ------------------------------------------------------------------
    // R-T06-03: igualdad estricta con la sesión en los mutadores
    // ------------------------------------------------------------------

    @Test
    fun `cancel with a foreign session owner is a no-op`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        sessionOwner = TEST_OWNER_B
        events.clear()

        coordinator().cancel(TEST_OWNER_A, TEST_PROJECT_ID)

        assertTrue(events.isEmpty())
        assertEquals(
            DownloadStateEntity.STATE_DOWNLOADING,
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).state,
        )
        assertTrue(scheduler.cancelled.isEmpty())
    }

    @Test
    fun `cancel without a session is a no-op`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        sessionOwner = null
        events.clear()

        coordinator().cancel(TEST_OWNER_A, TEST_PROJECT_ID)

        assertTrue(events.isEmpty())
        assertTrue(scheduler.cancelled.isEmpty())
    }

    @Test
    fun `delete local with a foreign session owner is a no-op`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        summaryDao.seed(TEST_OWNER_A, 100L)
        sessionOwner = TEST_OWNER_B
        events.clear()

        coordinator().deleteLocal(TEST_OWNER_A, TEST_PROJECT_ID)

        assertTrue(events.isEmpty())
        assertTrue(store.deleteCalls.isEmpty())
        assertTrue(scheduler.cancelled.isEmpty())
        assertTrue("el índice de catálogo no se borra con owner extranjero", summaryDao.rows.isNotEmpty())
    }

    // ------------------------------------------------------------------
    // R-T06-05: deleteLocal borra también la fila índice (ProjectSummary)
    // ------------------------------------------------------------------

    @Test
    fun `delete local removes the catalog index row as part of the local delete`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        summaryDao.seed(TEST_OWNER_A, 100L)
        events.clear()

        coordinator().deleteLocal(TEST_OWNER_A, TEST_PROJECT_ID)

        assertTrue(summaryDao.rows.isEmpty())
        assertTrue(dao.rows.isEmpty())
        assertEquals(listOf(TEST_OWNER_A to TEST_PROJECT_ID.value), store.deleteCalls)
        // Sigue sin invocar el remoto: el coordinador no tiene ProjectRemoteDataSource.
    }

    // ------------------------------------------------------------------
    // R-T06-06: deleteLocal limpia temporales huérfanos, SCOPED al proyecto
    // ------------------------------------------------------------------

    @Test
    fun `delete local sweeps leftover temp files scoped to the deleted project`() = runBlocking {
        coordinator().deleteLocal(TEST_OWNER_A, TEST_PROJECT_ID)

        assertEquals(1, tempSweepScopes.size)
        assertEquals(TEST_OWNER_A to TEST_PROJECT_ID.value, tempSweepScopes.single())
    }

    // ------------------------------------------------------------------
    // Observe
    // ------------------------------------------------------------------

    @Test
    fun `observe maps the durable row to download state`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 50L, totalBytes = 200L)

        val state = coordinator().observe(TEST_OWNER_A, TEST_PROJECT_ID).first()
        assertEquals(
            DownloadState.Downloading(50L, 200L, SizeEstimate(200L, 200L, SizeConfidence.HEADER)),
            state,
        )
    }

    @Test
    fun `observe without a row emits nothing`() = runBlocking {
        // El flujo de observación es infinito (re-evalúa la sesión): se
        // verifica con un collect acotado, no con firstOrNull (que colgaría).
        val received = mutableListOf<DownloadState>()
        val job = launch {
            coordinator().observe(TEST_OWNER_A, TEST_PROJECT_ID).collect { received.add(it) }
        }
        delay(100)
        job.cancel()

        assertTrue(received.isEmpty())
    }

    @Test
    fun `observe with a foreign session owner emits nothing`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING)
        sessionOwner = TEST_OWNER_B

        val received = mutableListOf<DownloadState>()
        val job = launch {
            coordinator().observe(TEST_OWNER_A, TEST_PROJECT_ID).collect { received.add(it) }
        }
        delay(100)
        job.cancel()

        assertTrue(received.isEmpty())
    }

    @Test
    fun `observe succeeded resolves the descriptor from the store manifest`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_SUCCEEDED, downloadedBytes = 845L)
        val manifest = com.explainer.app.data.local.snapshot.OfflineProjectManifest(
            ownerId = TEST_OWNER_A,
            projectId = TEST_PROJECT_ID,
            name = "previo",
            description = null,
            status = com.explainer.app.core.model.ProjectStatus.Completed,
            sourceType = "pdf",
            parts = emptyList(),
            usage = kotlinx.serialization.json.JsonObject(emptyMap()),
            readingProgress = com.explainer.app.core.model.ReadingProgress(),
            activeGeneration = "gen-9",
            sourceUpdatedAt = "2026-08-01T00:00:00Z",
            downloadedAt = 55L,
            totalBytes = 845L,
        )
        store.manifest = manifest

        val state = coordinator().observe(TEST_OWNER_A, TEST_PROJECT_ID).first() as DownloadState.Succeeded
        assertEquals("gen-9", state.descriptor.generation)
        assertEquals(845L, state.descriptor.totalBytes)
        assertEquals(55L, state.descriptor.downloadedAt)
    }

    // ------------------------------------------------------------------
    // R-T06-08: reinicio — el total en curso se observa como grado cabecera
    // ------------------------------------------------------------------

    @Test
    fun `observe after restart maps an in progress total conservatively as header`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 50L, totalBytes = 200L)

        val state = coordinator().observe(TEST_OWNER_A, TEST_PROJECT_ID).first() as DownloadState.Downloading

        assertEquals(200L, state.totalBytes)
        assertEquals(SizeConfidence.HEADER, state.estimate?.confidence)
        assertEquals(SizeEstimate(200L, 200L, SizeConfidence.HEADER), state.estimate)
    }

    // ------------------------------------------------------------------
    // R-T06-03: observe corta/recalcula al cambiar el owner de sesión
    // ------------------------------------------------------------------

    @Test
    fun `observe cuts the dao subscription on logout`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 10L, totalBytes = 100L)
        val states = mutableListOf<DownloadState>()
        val job = launch {
            coordinator().observe(TEST_OWNER_A, TEST_PROJECT_ID).collect { states.add(it) }
        }
        withTimeout(2_000) { while (states.isEmpty()) delay(5) }

        sessionOwner = null // logout
        delay(50) // el poll detecta el cambio y flatMapLatest corta la suscripción
        dao.upsert(
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).copy(downloadedBytes = 42L),
        )
        delay(100) // si NO se hubiera cortado, la re-emisión del DAO llegaría
        job.cancel()

        assertEquals("tras logout no llegan más emisiones de datos ajenos", 1, states.size)
    }

    @Test
    fun `observe recalculates when the session owner returns`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 10L, totalBytes = 100L)
        val states = mutableListOf<DownloadState>()
        val job = launch {
            coordinator().observe(TEST_OWNER_A, TEST_PROJECT_ID).collect { states.add(it) }
        }
        withTimeout(2_000) { while (states.isEmpty()) delay(5) }

        sessionOwner = TEST_OWNER_B // cambio A -> B: se corta la observación
        delay(50)
        dao.upsert(
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).copy(downloadedBytes = 42L),
        )
        sessionOwner = TEST_OWNER_A // vuelta a A: se recalcula y re-suscribe
        delay(50)
        job.cancel()

        assertEquals(2, states.size)
        assertEquals(42L, (states.last() as DownloadState.Downloading).downloadedBytes)
    }

    // ------------------------------------------------------------------
    // R-T11-05: owner Flow/StateFlow del container en vez de polling 250 ms.
    // El container inyecta `sessionOwnerFlow`; el flujo corta/recalcula la
    // observación en logout y cambio de cuenta SIN while(true)+delay.
    // ------------------------------------------------------------------

    private fun flowCoordinator(ownerFlow: MutableStateFlow<String?>): WorkManagerDownloadCoordinator =
        WorkManagerDownloadCoordinator(
            scheduler = scheduler,
            requestFactory = requestFactory,
            downloadDao = dao,
            store = store,
            summaryDao = summaryDao,
            sessionOwner = { ownerFlow.value },
            sessionOwnerFlow = ownerFlow,
            tempOrphanSweep = { owner, project -> tempSweepScopes.add(owner to project) },
        )

    @Test
    fun `observe with an owner flow cuts the dao subscription on logout without polling`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 10L, totalBytes = 100L)
        val ownerFlow = MutableStateFlow<String?>(TEST_OWNER_A)
        val states = mutableListOf<DownloadState>()
        val job = launch {
            flowCoordinator(ownerFlow).observe(TEST_OWNER_A, TEST_PROJECT_ID).collect { states.add(it) }
        }
        withTimeout(2_000) { while (states.isEmpty()) delay(5) }

        ownerFlow.value = null // logout: el flow emite el cambio sin polling
        delay(50)
        dao.upsert(
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).copy(downloadedBytes = 42L),
        )
        delay(100)
        job.cancel()

        assertEquals("tras logout no llegan más emisiones de datos ajenos", 1, states.size)
    }

    @Test
    fun `observe with an owner flow recalculates on owner A to B to A`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 10L, totalBytes = 100L)
        val ownerFlow = MutableStateFlow<String?>(TEST_OWNER_A)
        val states = mutableListOf<DownloadState>()
        val job = launch {
            flowCoordinator(ownerFlow).observe(TEST_OWNER_A, TEST_PROJECT_ID).collect { states.add(it) }
        }
        withTimeout(2_000) { while (states.isEmpty()) delay(5) }

        ownerFlow.value = TEST_OWNER_B // A -> B: se corta la observación
        delay(50)
        dao.upsert(
            dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).copy(downloadedBytes = 42L),
        )
        ownerFlow.value = TEST_OWNER_A // B -> A: se recalcula y re-suscribe
        delay(50)
        job.cancel()

        assertEquals(2, states.size)
        assertEquals(42L, (states.last() as DownloadState.Downloading).downloadedBytes)
    }
}

package com.explainer.app.work

import android.app.Application
import android.content.Context
import androidx.work.ListenableWorker
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.TestListenableWorkerBuilder
import androidx.work.workDataOf
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.feature.download.DownloadProjectUseCase
import com.explainer.app.feature.download.DownloadStatePersister
import com.explainer.app.feature.download.FakeRemote
import com.explainer.app.feature.download.FakeStore
import com.explainer.app.feature.download.InMemoryDownloadStateDao
import com.explainer.app.feature.download.InMemorySummaryDao
import com.explainer.app.feature.download.TEST_OWNER_A
import com.explainer.app.feature.download.TEST_PROJECT_ID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * R-T11-01 (CRITICAL): la disponibilidad de auth se coordina ANTES de
 * ejecutar el worker. Mientras `awaitInitialization()` sigue en curso, un
 * worker despertado por WorkManager no debe interpretar el owner nulo como
 * cancelación exitosa (que dejaría la fila `Queued` huérfana y sin trabajo
 * activo): reintenta de forma durable (`Result.retry()`) sin marcar éxito y,
 * cuando la inicialización termina, la descarga se reanuda y completa.
 */
class DownloadProjectWorkerAuthGateTest {

    private val context: Application = Application()
    private lateinit var tempDir: File

    @Before
    fun setUp() {
        tempDir = File.createTempFile("worker-auth-gate", ".dir").apply {
            delete()
            mkdirs()
        }
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    /** Motor completo sobre fakes (mismo patrón que WorkerFactoryTest/T06). */
    private class Harness(
        private val tempDir: File,
        private val context: Application,
    ) {
        val dao = InMemoryDownloadStateDao()
        val summaryDao = InMemorySummaryDao()
        val remote = FakeRemote()
        val store = FakeStore()

        init {
            // Fila encolada por un enqueue previo (workId aún sin reclamar).
            dao.seed(TEST_OWNER_A, workId = "", state = DownloadStateEntity.STATE_QUEUED)
            summaryDao.seed(TEST_OWNER_A, 100L)
            remote.body = "abc"
        }

        fun buildWorker(authReady: () -> Boolean): DownloadProjectWorker {
            val useCase = DownloadProjectUseCase(
                remote = remote,
                store = store,
                downloadDao = dao,
                summaryDao = summaryDao,
                tempDirProvider = { tempDir },
                diskFreeBytes = { Long.MAX_VALUE },
                sessionOwner = { TEST_OWNER_A },
            )
            val deps = DownloadWorkerDeps(
                useCase = useCase,
                persister = DownloadStatePersister(dao),
                authReady = authReady,
            )
            val factory = object : WorkerFactory() {
                override fun createWorker(
                    appContext: Context,
                    workerClassName: String,
                    workerParameters: WorkerParameters,
                ): ListenableWorker? = DownloadProjectWorker(appContext, workerParameters, deps)
            }
            return TestListenableWorkerBuilder.from(context, ListenableWorker::class.java)
                .setWorkerFactory(factory)
                .setInputData(
                    workDataOf(
                        DownloadProjectWorker.KEY_OWNER_ID to TEST_OWNER_A,
                        DownloadProjectWorker.KEY_PROJECT_ID to TEST_PROJECT_ID.value,
                    ),
                )
                .build(DownloadProjectWorker::class.java) as DownloadProjectWorker
        }
    }

    @Test
    fun `auth bloqueada reintenta sin marcar exito ni tocar la fila`() = runBlocking {
        val harness = Harness(tempDir, context)

        val result = harness.buildWorker(authReady = { false }).doWork()

        assertEquals(Result.retry(), result)
        assertEquals("el motor no se ejecuta con auth inicializando", 0, harness.remote.downloadCalls)
        assertTrue(harness.store.commitCalls.isEmpty())
        val row = harness.dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals("la fila Queued no queda huérfana: sigue activa para el reintento", DownloadStateEntity.STATE_QUEUED, row.state)
        assertEquals("", row.workId)
    }

    @Test
    fun `auth bloqueada no pierde el intento de la fila (workId sin reclamar)`() = runBlocking {
        val harness = Harness(tempDir, context)

        harness.buildWorker(authReady = { false }).doWork()
        harness.buildWorker(authReady = { false }).doWork()

        assertEquals(0, harness.remote.downloadCalls)
        assertEquals("", harness.dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value).workId)
    }

    @Test
    fun `descarga reanudada tras la inicializacion completa y commitea`() = runBlocking {
        val harness = Harness(tempDir, context)
        var authReady = false

        // Primer run con awaitInitialization en curso.
        assertEquals(Result.retry(), harness.buildWorker(authReady = { authReady }).doWork())

        // La inicialización termina (el gateway pasa a Authenticated/SignedOut).
        authReady = true

        // WorkManager relanza el trabajo: una instancia NUEVA del worker.
        val resumed = harness.buildWorker(authReady = { authReady })
        assertEquals(Result.success(), resumed.doWork())

        assertEquals(1, harness.remote.downloadCalls)
        assertEquals(1, harness.store.commitCalls.size)
        val row = harness.dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals(DownloadStateEntity.STATE_SUCCEEDED, row.state)
    }
}

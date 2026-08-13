package com.explainer.app.ui.library

import com.explainer.app.data.auth.SessionState
import com.explainer.app.data.local.snapshot.SnapshotDescriptor
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.RefreshOutcome
import com.explainer.app.feature.download.DownloadError
import com.explainer.app.feature.download.DownloadState
import com.explainer.app.feature.download.SizeConfidence
import com.explainer.app.feature.download.SizeEstimate
import com.explainer.app.ui.auth.FakeSessionGateway
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ViewModel de biblioteca (T09): combina catálogo, estados de descarga y
 * sesión a través de puertos (nunca Ktor/Room/WorkManager directos) y
 * traduce acciones en llamadas únicas y no destructivas. Scope Unconfined
 * para propagación síncrona en tests JVM.
 */
class LibraryViewModelTest {

    private fun scope() = CoroutineScope(Dispatchers.Unconfined)

    private fun authenticatedGateway() =
        FakeSessionGateway(SessionState.Authenticated(TEST_OWNER, "a@b.com"))

    private fun vm(
        gateway: FakeSessionGateway = authenticatedGateway(),
        catalog: FakeCatalog = FakeCatalog(),
        downloads: FakeDownloadCoordinator = FakeDownloadCoordinator(),
        now: () -> Long = { 4242L },
    ) = LibraryViewModel(scope(), TEST_OWNER, gateway, catalog, downloads, now)

    private fun contentOf(vm: LibraryViewModel): LibraryUiState.Content {
        val state = vm.uiState.value
        assertTrue("esperaba Content pero fue $state", state is LibraryUiState.Content)
        return state as LibraryUiState.Content
    }

    @Test
    fun `arranque con sesion valida refresca una vez y muestra filas`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem()))
        val viewModel = vm(catalog = catalog)

        assertEquals(listOf(TEST_OWNER), catalog.refreshCalls)
        val state = contentOf(viewModel)
        assertEquals(1, state.rows.size)
        assertEquals(4242L, state.lastSyncAtMillis)
    }

    @Test
    fun `sesion offline muestra banner y no refresca`() {
        val gateway = FakeSessionGateway(SessionState.OfflineAvailable(TEST_OWNER, "a@b.com"))
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(availability = ProjectAvailability.OFFLINE, snapshotBytes = 1024L)))
        val viewModel = vm(gateway = gateway, catalog = catalog)

        assertTrue(catalog.refreshCalls.isEmpty())
        val state = contentOf(viewModel)
        assertTrue(state.isOffline)
        assertEquals(1, state.rows.size)
    }

    @Test
    fun `refresh fallido conserva filas y muestra mensaje accionable`() {
        val catalog = FakeCatalog().apply { refreshOutcome = RefreshOutcome.Retryable }
        catalog.emit(listOf(testItem()))
        val viewModel = vm(catalog = catalog)

        val state = contentOf(viewModel)
        assertEquals(1, state.rows.size)
        assertEquals(LibraryMessageKind.REFRESH_FAILED_RETRYABLE, state.message!!.kind)
    }

    @Test
    fun `refresh auth required muestra sesion requerida`() {
        val catalog = FakeCatalog().apply { refreshOutcome = RefreshOutcome.AuthRequired }
        catalog.emit(listOf(testItem()))
        val viewModel = vm(catalog = catalog)

        assertEquals(LibraryMessageKind.REFRESH_FAILED_AUTH, contentOf(viewModel).message!!.kind)
    }

    @Test
    fun `pull to refresh no relanza mientras refresca`() {
        val catalog = FakeCatalog().apply { refreshDelayMillis = 50L }
        catalog.emit(listOf(testItem()))
        val viewModel = vm(catalog = catalog)
        val callsAfterStart = catalog.refreshCalls.size

        viewModel.onAction(LibraryAction.Refresh)
        viewModel.onAction(LibraryAction.Refresh)

        assertEquals(callsAfterStart, catalog.refreshCalls.size)
    }

    @Test
    fun `pedir descarga abre sheet con estimacion y confirmar encola una vez`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(segmentationSourceBytes = 100_000L)))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(catalog = catalog, downloads = downloads)

        viewModel.onAction(LibraryAction.Download(TEST_PROJECT_ID))
        val confirmation = contentOf(viewModel).confirmation
        assertNotNull(confirmation)
        assertEquals(TEST_PROJECT_ID, confirmation!!.projectId)
        assertFalse(confirmation.isUpdate)

        viewModel.onAction(LibraryAction.ConfirmDownload(TEST_PROJECT_ID))
        viewModel.onAction(LibraryAction.ConfirmDownload(TEST_PROJECT_ID))

        assertEquals(listOf(TEST_PROJECT_ID.value), downloads.enqueueCalls)
        assertNull(contentOf(viewModel).confirmation)
        assertEquals(LibraryMessageKind.DOWNLOAD_STARTED, contentOf(viewModel).message!!.kind)
    }

    @Test
    fun `actualizar abre sheet de actualizacion con tamano exacto actual`() {
        val catalog = FakeCatalog()
        catalog.emit(
            listOf(
                testItem(
                    availability = ProjectAvailability.UPDATE_POSSIBLE,
                    segmentationSourceBytes = 100_000L,
                    snapshotBytes = 3_000_000L,
                ),
            ),
        )
        val viewModel = vm(catalog = catalog)

        viewModel.onAction(LibraryAction.Download(TEST_PROJECT_ID))
        val confirmation = contentOf(viewModel).confirmation!!
        assertTrue(confirmation.isUpdate)
        assertEquals(3_000_000L, confirmation.currentSnapshotBytes)
    }

    @Test
    fun `dismiss cierra el sheet sin encolar`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem()))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(catalog = catalog, downloads = downloads)

        viewModel.onAction(LibraryAction.Download(TEST_PROJECT_ID))
        viewModel.onAction(LibraryAction.DismissSheet)

        assertNull(contentOf(viewModel).confirmation)
        assertTrue(downloads.enqueueCalls.isEmpty())
    }

    @Test
    fun `cancelar detiene la descarga y conserva el snapshot previo`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(availability = ProjectAvailability.UPDATING, snapshotBytes = 2048L)))
        val downloads = FakeDownloadCoordinator()
        downloads.emit(
            TEST_PROJECT_ID,
            DownloadState.Downloading(512L, 1024L, SizeEstimate(512L, 1024L, SizeConfidence.EXACT)),
        )
        val viewModel = vm(catalog = catalog, downloads = downloads)

        viewModel.onAction(LibraryAction.CancelDownload(TEST_PROJECT_ID))

        assertEquals(listOf(TEST_PROJECT_ID.value), downloads.cancelCalls)
        val row = contentOf(viewModel).rows.single()
        assertEquals(DownloadResultKind.CANCELLED, row.downloadResult!!.kind)
        assertTrue(row.hasSnapshot)
    }

    @Test
    fun `borrar local exige confirmacion y solo borra en el dispositivo`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(availability = ProjectAvailability.OFFLINE, snapshotBytes = 2048L)))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(catalog = catalog, downloads = downloads)

        viewModel.onAction(LibraryAction.DeleteLocal(TEST_PROJECT_ID))
        assertNotNull(contentOf(viewModel).deleteTarget)
        assertTrue(downloads.deleteCalls.isEmpty())

        viewModel.onAction(LibraryAction.ConfirmDeleteLocal(TEST_PROJECT_ID))

        assertEquals(listOf(TEST_PROJECT_ID.value), downloads.deleteCalls)
        assertNull(contentOf(viewModel).deleteTarget)
        assertEquals(LibraryMessageKind.DELETE_SUCCEEDED, contentOf(viewModel).message!!.kind)
    }

    @Test
    fun `cancelar el borrado no borra nada`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(availability = ProjectAvailability.OFFLINE)))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(catalog = catalog, downloads = downloads)

        viewModel.onAction(LibraryAction.DeleteLocal(TEST_PROJECT_ID))
        viewModel.onAction(LibraryAction.DismissSheet)

        assertTrue(downloads.deleteCalls.isEmpty())
        assertNull(contentOf(viewModel).deleteTarget)
    }

    @Test
    fun `fallo de actualizacion conserva abrir la version descargada`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(availability = ProjectAvailability.OFFLINE, snapshotBytes = 4096L)))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(catalog = catalog, downloads = downloads)

        downloads.emit(TEST_PROJECT_ID, DownloadState.Failed(TEST_PROJECT_ID, DownloadError.Network))

        val row = contentOf(viewModel).rows.single()
        assertEquals(DownloadError.Network, row.downloadResult!!.error)
        assertTrue(row.hasSnapshot)
    }

    @Test
    fun `descarga exitosa emite haptic event y mensaje`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(name = "Mi proyecto", availability = ProjectAvailability.UPDATING)))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(catalog = catalog, downloads = downloads)
        val events = mutableListOf<LibraryEvent>()
        scope().launch { viewModel.events.collect { events.add(it) } }

        downloads.emit(
            TEST_PROJECT_ID,
            DownloadState.Succeeded(
                SnapshotDescriptor(
                    ownerId = TEST_OWNER,
                    projectId = TEST_PROJECT_ID,
                    generation = "g1",
                    totalBytes = 4096L,
                    sourceUpdatedAt = "2026-08-01T10:00:00Z",
                    downloadedAt = 1L,
                ),
            ),
        )

        assertEquals(listOf(LibraryEvent.DownloadSucceeded), events)
        val message = contentOf(viewModel).message
        assertEquals(LibraryMessageKind.DOWNLOAD_SUCCEEDED, message!!.kind)
        assertEquals("Mi proyecto", message.projectName)
    }

    @Test
    fun `dismiss de mensaje lo limpia`() {
        val catalog = FakeCatalog().apply { refreshOutcome = RefreshOutcome.Retryable }
        catalog.emit(listOf(testItem()))
        val viewModel = vm(catalog = catalog)

        viewModel.onAction(LibraryAction.DismissMessage)

        assertNull(contentOf(viewModel).message)
    }

    @Test
    fun `sesion que termina no muestra filas`() {
        val gateway = authenticatedGateway()
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem()))
        val viewModel = vm(gateway = gateway, catalog = catalog)
        assertEquals(1, contentOf(viewModel).rows.size)

        gateway.stateFlow.value = SessionState.SignedOut

        assertEquals(LibraryUiState.SignedOut, viewModel.uiState.value)
    }

    @Test
    fun `cambio a otro owner no muestra filas del owner previo`() {
        val gateway = authenticatedGateway()
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem()))
        val viewModel = vm(gateway = gateway, catalog = catalog)

        gateway.stateFlow.value = SessionState.Authenticated("otro-owner", "b@c.com")

        assertEquals(LibraryUiState.SignedOut, viewModel.uiState.value)
    }

    // ------------------------------------------------------------------
    // R-T11-05: reconciliación de observadores de descarga (sin flows
    // colgados cuando un proyecto sale del catálogo o la sesión termina)
    // ------------------------------------------------------------------

    @Test
    fun `proyecto eliminado del catalogo cancela su observador y lo recrea al reaparecer`() {
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(), testItem(projectId = TEST_PROJECT_ID_2)))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(catalog = catalog, downloads = downloads)
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID.value, 1) }
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID_2.value, 1) }

        // El proyecto 2 sale del catálogo: su observador se cancela.
        catalog.emit(listOf(testItem()))
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID_2.value, 0) }
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID.value, 1) }

        // El proyecto 2 reaparece: se vuelve a observar.
        catalog.emit(listOf(testItem(), testItem(projectId = TEST_PROJECT_ID_2)))
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID_2.value, 1) }
    }

    @Test
    fun `logout cancela todos los observadores de descarga`() {
        val gateway = authenticatedGateway()
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem(), testItem(projectId = TEST_PROJECT_ID_2)))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(gateway = gateway, catalog = catalog, downloads = downloads)
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID.value, 1) }

        gateway.stateFlow.value = SessionState.SignedOut

        runBlocking { awaitActive(downloads, TEST_PROJECT_ID.value, 0) }
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID_2.value, 0) }
        assertEquals(LibraryUiState.SignedOut, viewModel.uiState.value)
    }

    @Test
    fun `cambio a otro owner cancela los observadores del owner previo`() {
        val gateway = authenticatedGateway()
        val catalog = FakeCatalog()
        catalog.emit(listOf(testItem()))
        val downloads = FakeDownloadCoordinator()
        val viewModel = vm(gateway = gateway, catalog = catalog, downloads = downloads)
        runBlocking { awaitActive(downloads, TEST_PROJECT_ID.value, 1) }

        gateway.stateFlow.value = SessionState.Authenticated("otro-owner", "b@c.com")

        runBlocking { awaitActive(downloads, TEST_PROJECT_ID.value, 0) }
        assertEquals(LibraryUiState.SignedOut, viewModel.uiState.value)
    }

    private suspend fun awaitActive(downloads: FakeDownloadCoordinator, projectKey: String, expected: Int) {
        withTimeout(2_000) {
            while ((downloads.activeObservers[projectKey] ?: 0) != expected) {
                kotlinx.coroutines.delay(5)
            }
        }
    }
}

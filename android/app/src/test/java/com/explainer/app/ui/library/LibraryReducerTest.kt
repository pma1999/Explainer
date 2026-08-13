package com.explainer.app.ui.library

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.data.auth.SessionState
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.RefreshOutcome
import com.explainer.app.feature.download.DownloadError
import com.explainer.app.feature.download.DownloadState
import com.explainer.app.feature.download.SizeConfidence
import com.explainer.app.feature.download.SizeEstimate
import com.explainer.app.feature.download.SizeEstimator
import com.explainer.app.feature.download.StorageGuard
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Reducer puro de la biblioteca (T09): filas, estados de disponibilidad y
 * descarga, estimado vs exacto, refresh no destructivo, sheets de
 * confirmación y aislamiento de owner. No toca Ktor/Room/WorkManager: los
 * puertos los consume el ViewModel.
 */
class LibraryReducerTest {

    private fun model(
        items: List<com.explainer.app.feature.catalog.ProjectListItem> = emptyList(),
        receivedFirst: Boolean = true,
        session: SessionState = SessionState.Authenticated(TEST_OWNER, "a@b.com"),
    ) = LibraryModel(
        ownerId = TEST_OWNER,
        items = items,
        receivedFirst = receivedFirst,
        session = session,
    )

    private fun content(
        model: LibraryModel,
        downloads: Map<String, DownloadState> = emptyMap(),
    ): LibraryUiState.Content {
        val state = LibraryReducer.toUiState(model, downloads)
        assertTrue("esperaba Content pero fue $state", state is LibraryUiState.Content)
        return state as LibraryUiState.Content
    }

    // ---- Estados raíz ----

    @Test
    fun `sesion inicial muestra carga`() {
        val state = LibraryReducer.toUiState(model(session = SessionState.Initializing), emptyMap())
        assertEquals(LibraryUiState.Loading, state)
    }

    @Test
    fun `sin primera emision del catalogo muestra carga`() {
        val state = LibraryReducer.toUiState(model(receivedFirst = false), emptyMap())
        assertEquals(LibraryUiState.Loading, state)
    }

    @Test
    fun `sesion signed out no muestra filas`() {
        val state = LibraryReducer.toUiState(model(session = SessionState.SignedOut), emptyMap())
        assertEquals(LibraryUiState.SignedOut, state)
    }

    @Test
    fun `owner distinto no muestra filas del owner previo`() {
        val state = LibraryReducer.toUiState(
            model(session = SessionState.Authenticated("otro-owner", "b@c.com")),
            emptyMap(),
        )
        assertEquals(LibraryUiState.SignedOut, state)
    }

    @Test
    fun `cambio de sesion a signed out limpia las filas del modelo`() {
        val withRows = model(items = listOf(testItem()))
        val cleared = LibraryReducer.onSession(withRows, SessionState.SignedOut)
        assertTrue(cleared.items.isEmpty())
    }

    // ---- Mapeo de filas ----

    @Test
    fun `items se mapean a filas con metadatos y orden preservado`() {
        val items = listOf(
            testItem(projectId = TEST_PROJECT_ID, name = "A", updatedAt = "2026-08-02T10:00:00Z"),
            testItem(projectId = TEST_PROJECT_ID_2, name = "B", updatedAt = "2026-08-01T10:00:00Z"),
        )
        val state = content(model(items = items))

        assertEquals(listOf("A", "B"), state.rows.map { it.name })
        assertEquals(TEST_PROJECT_ID, state.rows[0].projectId)
        assertEquals(
            Instant.parse("2026-08-02T10:00:00Z").toEpochMilli(),
            state.rows[0].updatedAtEpochMillis,
        )
        assertEquals(3, state.rows[0].partCount)
        assertEquals(ProjectStatus.Completed, state.rows[0].status)
    }

    @Test
    fun `estados processing y error se muestran honestamente`() {
        val processing = content(
            model(items = listOf(testItem(status = ProjectStatus.Processing))),
        ).rows.single()
        assertEquals(ProjectStatus.Processing, processing.status)

        val error = content(
            model(items = listOf(testItem(status = ProjectStatus.Error))),
        ).rows.single()
        assertEquals(ProjectStatus.Error, error.status)
    }

    @Test
    fun `solo snapshot existente habilita abrir`() {
        val remote = content(model(items = listOf(testItem(availability = ProjectAvailability.REMOTE_ONLY)))).rows.single()
        assertFalse(remote.hasSnapshot)

        val offline = content(
            model(items = listOf(testItem(availability = ProjectAvailability.OFFLINE, snapshotBytes = 2048L))),
        ).rows.single()
        assertTrue(offline.hasSnapshot)
        assertEquals(2048L, offline.snapshotBytes)

        val update = content(
            model(items = listOf(testItem(availability = ProjectAvailability.UPDATE_POSSIBLE))),
        ).rows.single()
        assertTrue(update.hasSnapshot)

        val updating = content(
            model(items = listOf(testItem(availability = ProjectAvailability.UPDATING))),
        ).rows.single()
        assertTrue(updating.hasSnapshot)
    }

    @Test
    fun `offline disponible activa el banner sin afirmar online`() {
        val state = LibraryReducer.toUiState(
            model(session = SessionState.OfflineAvailable(TEST_OWNER, "a@b.com"), items = listOf(testItem())),
            emptyMap(),
        ) as LibraryUiState.Content
        assertTrue(state.isOffline)
        assertFalse(state.isRefreshing)
    }

    // ---- Estados de descarga ----

    @Test
    fun `descargando con total conocido muestra bytes y total exacto`() {
        val item = testItem(availability = ProjectAvailability.UPDATING)
        val download = DownloadState.Downloading(
            downloadedBytes = 1024L,
            totalBytes = 2048L,
            estimate = SizeEstimate(1024L, 2048L, SizeConfidence.EXACT),
        )
        val row = content(model(items = listOf(item)), mapOf(item.projectId.value to download)).rows.single()

        val progress = row.downloadProgress
        assertTrue(progress != null)
        assertEquals(1024L, progress!!.downloadedBytes)
        assertEquals(2048L, progress.totalBytes)
        assertFalse(progress.isEstimate)
        assertNull(row.downloadResult)
    }

    @Test
    fun `descargando con rango heuristico rotula estimado`() {
        val item = testItem(availability = ProjectAvailability.UPDATING)
        val download = DownloadState.Downloading(
            downloadedBytes = 100L,
            totalBytes = null,
            estimate = SizeEstimate(1024L, 4096L, SizeConfidence.HEURISTIC),
        )
        val row = content(model(items = listOf(item)), mapOf(item.projectId.value to download)).rows.single()
        assertTrue(row.downloadProgress!!.isEstimate)
        assertNull(row.downloadProgress.totalBytes)
    }

    @Test
    fun `encolado muestra progreso indeterminado`() {
        val item = testItem(availability = ProjectAvailability.UPDATING)
        val download = DownloadState.Queued(item.projectId, requestedAt = 1L)
        val row = content(model(items = listOf(item)), mapOf(item.projectId.value to download)).rows.single()
        assertNull(row.downloadProgress!!.totalBytes)
        assertNull(row.downloadResult)
    }

    @Test
    fun `cancelado expone resultado cancelado`() {
        val item = testItem(availability = ProjectAvailability.OFFLINE)
        val download = DownloadState.Cancelled(item.projectId)
        val row = content(model(items = listOf(item)), mapOf(item.projectId.value to download)).rows.single()
        assertEquals(DownloadResultKind.CANCELLED, row.downloadResult!!.kind)
        assertNull(row.downloadResult.error)
        // El snapshot previo sigue abrible.
        assertTrue(row.hasSnapshot)
    }

    @Test
    fun `fallo por espacio expone la categoria y conserva el snapshot`() {
        val item = testItem(availability = ProjectAvailability.OFFLINE, snapshotBytes = 4096L)
        val download = DownloadState.Failed(item.projectId, DownloadError.NotEnoughSpace)
        val row = content(model(items = listOf(item)), mapOf(item.projectId.value to download)).rows.single()
        assertEquals(DownloadResultKind.FAILED, row.downloadResult!!.kind)
        assertEquals(DownloadError.NotEnoughSpace, row.downloadResult.error)
        assertTrue(row.hasSnapshot)
    }

    @Test
    fun `fallo por auth expone sesion requerida`() {
        val item = testItem()
        val download = DownloadState.Failed(item.projectId, DownloadError.AuthRequired)
        val row = content(model(items = listOf(item)), mapOf(item.projectId.value to download)).rows.single()
        assertEquals(DownloadError.AuthRequired, row.downloadResult!!.error)
    }

    @Test
    fun `descarga exitosa no marca resultado`() {
        val item = testItem(availability = ProjectAvailability.OFFLINE)
        val download = DownloadState.Succeeded(
            com.explainer.app.data.local.snapshot.SnapshotDescriptor(
                ownerId = TEST_OWNER,
                projectId = item.projectId,
                generation = "g1",
                totalBytes = 4096L,
                sourceUpdatedAt = "2026-08-01T10:00:00Z",
                downloadedAt = 1L,
            ),
        )
        val row = content(model(items = listOf(item)), mapOf(item.projectId.value to download)).rows.single()
        assertNull(row.downloadProgress)
        assertNull(row.downloadResult)
        assertTrue(row.hasSnapshot)
    }

    // ---- Sheet de confirmación (estimado vs exacto) ----

    @Test
    fun `confirmacion remota solo estima rango heuristico y espacio requerido`() {
        val item = testItem(
            availability = ProjectAvailability.REMOTE_ONLY,
            segmentationSourceBytes = 100_000L,
        )
        val confirmation = LibraryReducer.onDownloadRequested(model(items = listOf(item)), item.projectId)
        val sheet = content(confirmation).confirmation

        assertTrue(sheet != null)
        val estimate = SizeEstimator.fromSegmentation(100_000L)
        assertEquals(estimate.lowBytes, sheet!!.estimateLowBytes)
        assertEquals(estimate.highBytes, sheet.estimateHighBytes)
        assertEquals(SizeConfidence.HEURISTIC, estimate.confidence)
        assertEquals(StorageGuard.requiredFreeBytes(estimate.highBytes), sheet.requiredFreeBytes)
        assertFalse(sheet.isUpdate)
        assertNull(sheet.currentSnapshotBytes)
    }

    @Test
    fun `confirmacion de actualizacion incluye tamano exacto actual`() {
        val item = testItem(
            availability = ProjectAvailability.UPDATE_POSSIBLE,
            segmentationSourceBytes = 100_000L,
            snapshotBytes = 3_000_000L,
        )
        val confirmation = LibraryReducer.onDownloadRequested(model(items = listOf(item)), item.projectId)
        val sheet = content(confirmation).confirmation

        assertTrue(sheet!!.isUpdate)
        assertEquals(3_000_000L, sheet.currentSnapshotBytes)
    }

    @Test
    fun `pedir descarga mientras actualiza no abre sheet`() {
        val item = testItem(availability = ProjectAvailability.UPDATING)
        val state = LibraryReducer.onDownloadRequested(model(items = listOf(item)), item.projectId)
        assertNull(state.confirmationProjectId)
    }

    @Test
    fun `doble tap de descarga abre un unico sheet`() {
        val item = testItem()
        val first = LibraryReducer.onDownloadRequested(model(items = listOf(item)), item.projectId)
        val second = LibraryReducer.onDownloadRequested(first, item.projectId)
        assertEquals(first, second)
        assertTrue(content(second).confirmation != null)
    }

    @Test
    fun `confirmar cierra el sheet`() {
        val item = testItem()
        val opened = LibraryReducer.onDownloadRequested(model(items = listOf(item)), item.projectId)
        val confirmed = LibraryReducer.onDownloadConfirmed(opened)
        assertNull(confirmed.confirmationProjectId)
    }

    // ---- Borrado local con confirmación ----

    @Test
    fun `borrar pide confirmacion y confirmar la cierra`() {
        val item = testItem(availability = ProjectAvailability.OFFLINE)
        val requested = LibraryReducer.onDeleteRequested(model(items = listOf(item)), item.projectId)
        val state = content(requested)
        assertTrue(state.deleteTarget != null)
        assertEquals(item.name, state.deleteTarget!!.name)

        val confirmed = LibraryReducer.onDeleteConfirmed(requested)
        assertNull(confirmed.deleteProjectId)
    }

    @Test
    fun `dismiss cierra cualquier sheet`() {
        val item = testItem()
        val opened = LibraryReducer.onDownloadRequested(model(items = listOf(item)), item.projectId)
        assertNull(LibraryReducer.onDismissSheet(opened).confirmationProjectId)

        val delete = LibraryReducer.onDeleteRequested(model(items = listOf(item)), item.projectId)
        assertNull(LibraryReducer.onDismissSheet(delete).deleteProjectId)
    }

    // ---- Refresh no destructivo ----

    @Test
    fun `refresh exitoso registra ultima sincronizacion`() {
        val withItems = model(items = listOf(testItem()))
        val finished = LibraryReducer.onRefreshFinished(
            LibraryReducer.onRefreshStarted(withItems),
            RefreshOutcome.Success(1),
            nowMillis = 1234L,
        )
        assertFalse(finished.isRefreshing)
        assertEquals(1234L, finished.lastSyncAtMillis)
    }

    @Test
    fun `refresh fallido conserva filas y muestra mensaje`() {
        val withItems = model(items = listOf(testItem()))
        val finished = LibraryReducer.onRefreshFinished(
            LibraryReducer.onRefreshStarted(withItems),
            RefreshOutcome.Retryable,
            nowMillis = 1L,
        )
        assertFalse(finished.isRefreshing)
        assertEquals(LibraryMessageKind.REFRESH_FAILED_RETRYABLE, finished.message!!.kind)
        val state = content(finished)
        assertEquals(1, state.rows.size)
    }

    @Test
    fun `refresh auth required y permanente mapean a mensajes accionables`() {
        val base = model(items = listOf(testItem()))
        assertEquals(
            LibraryMessageKind.REFRESH_FAILED_AUTH,
            LibraryReducer.onRefreshFinished(base, RefreshOutcome.AuthRequired, 1L).message!!.kind,
        )
        assertEquals(
            LibraryMessageKind.REFRESH_FAILED_OTHER,
            LibraryReducer.onRefreshFinished(base, RefreshOutcome.PermanentFailure("x"), 1L).message!!.kind,
        )
    }

    @Test
    fun `refresh cancelado es silencioso`() {
        val base = model(items = listOf(testItem()))
        val finished = LibraryReducer.onRefreshFinished(base, RefreshOutcome.Cancelled, 1L)
        assertNull(finished.message)
        assertFalse(finished.isRefreshing)
    }

    @Test
    fun `refresh en curso no se relanza`() {
        val started = LibraryReducer.onRefreshStarted(model())
        assertEquals(started, LibraryReducer.onRefreshStarted(started))
    }

    @Test
    fun `exito de refresh limpia el mensaje anterior`() {
        val withMessage = model(items = listOf(testItem())).copy(
            message = LibraryMessage(LibraryMessageKind.REFRESH_FAILED_RETRYABLE),
        )
        val finished = LibraryReducer.onRefreshFinished(withMessage, RefreshOutcome.Success(1), 1L)
        assertNull(finished.message)
    }

    @Test
    fun `dismiss de mensaje lo elimina`() {
        val withMessage = model(items = listOf(testItem())).copy(
            message = LibraryMessage(LibraryMessageKind.DELETE_SUCCEEDED, "A"),
        )
        assertNull(LibraryReducer.onMessageDismissed(withMessage).message)
    }

    // ---- Fila sin resumen (snapshot-only) ----

    @Test
    fun `fila sin resumen ni snapshot es no disponible`() {
        val item = testItem(availability = ProjectAvailability.UNAVAILABLE)
        val row = content(model(items = listOf(item))).rows.single()
        assertEquals(ProjectAvailability.UNAVAILABLE, row.availability)
        assertFalse(row.hasSnapshot)
    }
}

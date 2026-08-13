package com.explainer.app.ui.library

import com.explainer.app.R
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.download.DownloadError
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Labels de la biblioteca (T09): cada estado de disponibilidad, resultado
 * de descarga, estado remoto y mensaje tiene copia textual explícita (nunca
 * depende solo del color) y un [StatusTone] coherente.
 */
class LibraryLabelsTest {

    // ---- Disponibilidad ----

    @Test
    fun `disponibilidad mapea a copia y tono`() {
        assertEquals(R.string.availability_offline, LibraryLabels.availabilityLabelRes(ProjectAvailability.OFFLINE))
        assertEquals(R.string.availability_remote_only, LibraryLabels.availabilityLabelRes(ProjectAvailability.REMOTE_ONLY))
        assertEquals(R.string.availability_update_possible, LibraryLabels.availabilityLabelRes(ProjectAvailability.UPDATE_POSSIBLE))
        assertEquals(R.string.availability_updating, LibraryLabels.availabilityLabelRes(ProjectAvailability.UPDATING))
        assertEquals(R.string.availability_unavailable, LibraryLabels.availabilityLabelRes(ProjectAvailability.UNAVAILABLE))

        assertEquals(StatusTone.SUCCESS, LibraryLabels.availabilityTone(ProjectAvailability.OFFLINE))
        assertEquals(StatusTone.WARNING, LibraryLabels.availabilityTone(ProjectAvailability.UPDATE_POSSIBLE))
        assertEquals(StatusTone.WARNING, LibraryLabels.availabilityTone(ProjectAvailability.UPDATING))
        assertEquals(StatusTone.NEUTRAL, LibraryLabels.availabilityTone(ProjectAvailability.REMOTE_ONLY))
        assertEquals(StatusTone.NEUTRAL, LibraryLabels.availabilityTone(ProjectAvailability.UNAVAILABLE))
    }

    // ---- Estado remoto ----

    @Test
    fun `estado remoto mapea a copia honesta`() {
        assertEquals(R.string.status_pending, LibraryLabels.statusLabelRes(ProjectStatus.Pending))
        assertEquals(R.string.status_uploading, LibraryLabels.statusLabelRes(ProjectStatus.Uploading))
        assertEquals(R.string.status_segmenting, LibraryLabels.statusLabelRes(ProjectStatus.Segmenting))
        assertEquals(R.string.status_processing, LibraryLabels.statusLabelRes(ProjectStatus.Processing))
        assertEquals(R.string.status_completed, LibraryLabels.statusLabelRes(ProjectStatus.Completed))
        assertEquals(R.string.status_error, LibraryLabels.statusLabelRes(ProjectStatus.Error))
        assertEquals(R.string.status_unknown, LibraryLabels.statusLabelRes(ProjectStatus.Unknown("futuro")))

        assertEquals(StatusTone.WARNING, LibraryLabels.statusTone(ProjectStatus.Processing))
        assertEquals(StatusTone.ERROR, LibraryLabels.statusTone(ProjectStatus.Error))
    }

    // ---- Resultado de descarga ----

    @Test
    fun `cancelado y fallido mapean a copia y tono`() {
        assertEquals(R.string.download_cancelled_label, LibraryLabels.downloadLabelRes(DownloadResultUi(DownloadResultKind.CANCELLED)))
        assertEquals(StatusTone.NEUTRAL, LibraryLabels.downloadTone(DownloadResultUi(DownloadResultKind.CANCELLED)))

        assertEquals(R.string.download_failed_space, LibraryLabels.downloadLabelRes(DownloadResultUi(DownloadResultKind.FAILED, DownloadError.NotEnoughSpace)))
        assertEquals(R.string.download_failed_auth, LibraryLabels.downloadLabelRes(DownloadResultUi(DownloadResultKind.FAILED, DownloadError.AuthRequired)))
        assertEquals(StatusTone.ERROR, LibraryLabels.downloadTone(DownloadResultUi(DownloadResultKind.FAILED, DownloadError.Network)))
    }

    @Test
    fun `cada categoria de error de descarga tiene explicacion`() {
        assertEquals(R.string.download_failed_network, LibraryLabels.downloadErrorRes(DownloadError.Network))
        assertEquals(R.string.download_failed_auth, LibraryLabels.downloadErrorRes(DownloadError.AuthRequired))
        assertEquals(R.string.download_failed_not_found, LibraryLabels.downloadErrorRes(DownloadError.NotFound))
        assertEquals(R.string.download_failed_space, LibraryLabels.downloadErrorRes(DownloadError.NotEnoughSpace))
        assertEquals(R.string.download_failed_invalid, LibraryLabels.downloadErrorRes(DownloadError.InvalidPayload("json")))
        assertEquals(R.string.download_failed_permanent, LibraryLabels.downloadErrorRes(DownloadError.Permanent("http:400")))
        assertEquals(R.string.download_failed_local, LibraryLabels.downloadErrorRes(DownloadError.Local("io")))
    }

    // ---- Mensajes transitorios ----

    @Test
    fun `mensajes mapean a copia`() {
        assertEquals(R.string.msg_download_started, LibraryLabels.messageRes(LibraryMessageKind.DOWNLOAD_STARTED))
        assertEquals(R.string.msg_download_succeeded, LibraryLabels.messageRes(LibraryMessageKind.DOWNLOAD_SUCCEEDED))
        assertEquals(R.string.msg_delete_succeeded, LibraryLabels.messageRes(LibraryMessageKind.DELETE_SUCCEEDED))
        assertEquals(R.string.msg_refresh_retryable, LibraryLabels.messageRes(LibraryMessageKind.REFRESH_FAILED_RETRYABLE))
        assertEquals(R.string.msg_refresh_auth, LibraryLabels.messageRes(LibraryMessageKind.REFRESH_FAILED_AUTH))
        assertEquals(R.string.msg_refresh_other, LibraryLabels.messageRes(LibraryMessageKind.REFRESH_FAILED_OTHER))
    }

    // ---- Prioridad de la línea de estado ----

    @Test
    fun `resultado de descarga domina sobre estado remoto y disponibilidad`() {
        val row = ProjectRowUiModel(
            projectId = TEST_PROJECT_ID,
            name = "A",
            status = ProjectStatus.Processing,
            availability = ProjectAvailability.OFFLINE,
            hasSnapshot = true,
            snapshotBytes = 1024L,
            updatedAtEpochMillis = 0L,
            partCount = 0,
            downloadResult = DownloadResultUi(DownloadResultKind.FAILED, DownloadError.NotEnoughSpace),
        )
        assertEquals(R.string.download_failed_space, LibraryLabels.primaryStatusRes(row))
        assertEquals(StatusTone.ERROR, LibraryLabels.primaryStatusTone(row))
    }

    @Test
    fun `estado processing o error domina sobre disponibilidad`() {
        val processing = ProjectRowUiModel(
            projectId = TEST_PROJECT_ID, name = "A", status = ProjectStatus.Processing,
            availability = ProjectAvailability.REMOTE_ONLY, hasSnapshot = false, snapshotBytes = 0L,
            updatedAtEpochMillis = 0L, partCount = 0,
        )
        assertEquals(R.string.status_processing, LibraryLabels.primaryStatusRes(processing))

        val error = processing.copy(status = ProjectStatus.Error)
        assertEquals(R.string.status_error, LibraryLabels.primaryStatusRes(error))
    }

    @Test
    fun `sin resultado ni estado activo se muestra la disponibilidad`() {
        val offline = ProjectRowUiModel(
            projectId = TEST_PROJECT_ID, name = "A", status = ProjectStatus.Completed,
            availability = ProjectAvailability.OFFLINE, hasSnapshot = true, snapshotBytes = 1024L,
            updatedAtEpochMillis = 0L, partCount = 0,
        )
        assertEquals(R.string.availability_offline, LibraryLabels.primaryStatusRes(offline))
        assertEquals(StatusTone.SUCCESS, LibraryLabels.primaryStatusTone(offline))
    }
}

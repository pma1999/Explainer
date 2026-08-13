package com.explainer.app.ui.library

import com.explainer.app.R
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.download.DownloadError

/**
 * Re-export del tono semántico de T05 para el etiquetado de estados de la
 * biblioteca (el paquete lo expone sin imports adicionales).
 */
typealias StatusTone = com.explainer.app.ui.components.StatusTone

/**
 * Labels y tonos de la biblioteca (T09): cada estado de disponibilidad,
 * estado remoto, resultado de descarga y mensaje tiene copia textual
 * explícita (nunca solo color) y un [StatusTone] coherente. Copy en
 * `strings_auth_library.xml`.
 */
object LibraryLabels {

    // ---- Disponibilidad ----

    fun availabilityLabelRes(availability: ProjectAvailability): Int = when (availability) {
        ProjectAvailability.OFFLINE -> R.string.availability_offline
        ProjectAvailability.REMOTE_ONLY -> R.string.availability_remote_only
        ProjectAvailability.UPDATE_POSSIBLE -> R.string.availability_update_possible
        ProjectAvailability.UPDATING -> R.string.availability_updating
        ProjectAvailability.UNAVAILABLE -> R.string.availability_unavailable
    }

    fun availabilityTone(availability: ProjectAvailability): StatusTone = when (availability) {
        ProjectAvailability.OFFLINE -> StatusTone.SUCCESS
        ProjectAvailability.UPDATE_POSSIBLE, ProjectAvailability.UPDATING -> StatusTone.WARNING
        ProjectAvailability.REMOTE_ONLY, ProjectAvailability.UNAVAILABLE -> StatusTone.NEUTRAL
    }

    // ---- Estado remoto ----

    fun statusLabelRes(status: ProjectStatus): Int = when (status) {
        ProjectStatus.Pending -> R.string.status_pending
        ProjectStatus.Uploading -> R.string.status_uploading
        ProjectStatus.Segmenting -> R.string.status_segmenting
        ProjectStatus.Processing -> R.string.status_processing
        ProjectStatus.Completed -> R.string.status_completed
        ProjectStatus.Error -> R.string.status_error
        is ProjectStatus.Unknown -> R.string.status_unknown
    }

    fun statusTone(status: ProjectStatus): StatusTone = when (status) {
        ProjectStatus.Processing -> StatusTone.WARNING
        ProjectStatus.Error -> StatusTone.ERROR
        ProjectStatus.Pending, ProjectStatus.Uploading, ProjectStatus.Segmenting -> StatusTone.WARNING
        ProjectStatus.Completed -> StatusTone.SUCCESS
        is ProjectStatus.Unknown -> StatusTone.NEUTRAL
    }

    // ---- Resultado de descarga ----

    fun downloadLabelRes(result: DownloadResultUi): Int = when (result.kind) {
        DownloadResultKind.CANCELLED -> R.string.download_cancelled_label
        DownloadResultKind.FAILED -> downloadErrorRes(result.error ?: DownloadError.Permanent("unknown"))
    }

    fun downloadTone(result: DownloadResultUi): StatusTone = when (result.kind) {
        DownloadResultKind.CANCELLED -> StatusTone.NEUTRAL
        DownloadResultKind.FAILED -> StatusTone.ERROR
    }

    fun downloadErrorRes(error: DownloadError): Int = when (error) {
        DownloadError.Network -> R.string.download_failed_network
        DownloadError.AuthRequired -> R.string.download_failed_auth
        DownloadError.NotFound -> R.string.download_failed_not_found
        DownloadError.NotEnoughSpace -> R.string.download_failed_space
        is DownloadError.InvalidPayload -> R.string.download_failed_invalid
        is DownloadError.Permanent -> R.string.download_failed_permanent
        is DownloadError.Local -> R.string.download_failed_local
    }

    // ---- Mensajes transitorios ----

    fun messageRes(kind: LibraryMessageKind): Int = when (kind) {
        LibraryMessageKind.DOWNLOAD_STARTED -> R.string.msg_download_started
        LibraryMessageKind.DOWNLOAD_SUCCEEDED -> R.string.msg_download_succeeded
        LibraryMessageKind.DELETE_SUCCEEDED -> R.string.msg_delete_succeeded
        LibraryMessageKind.REFRESH_FAILED_RETRYABLE -> R.string.msg_refresh_retryable
        LibraryMessageKind.REFRESH_FAILED_AUTH -> R.string.msg_refresh_auth
        LibraryMessageKind.REFRESH_FAILED_OTHER -> R.string.msg_refresh_other
    }

    // ---- Línea de estado principal (prioridad: resultado > procesando/error > disponibilidad) ----

    fun primaryStatusRes(row: ProjectRowUiModel): Int = when {
        row.downloadResult != null -> downloadLabelRes(row.downloadResult)
        row.status == ProjectStatus.Processing || row.status == ProjectStatus.Error ->
            statusLabelRes(row.status)

        else -> availabilityLabelRes(row.availability)
    }

    fun primaryStatusTone(row: ProjectRowUiModel): StatusTone = when {
        row.downloadResult != null -> downloadTone(row.downloadResult)
        row.status == ProjectStatus.Processing || row.status == ProjectStatus.Error ->
            statusTone(row.status)

        else -> availabilityTone(row.availability)
    }
}

package com.explainer.app.feature.catalog

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.db.OfflineSnapshotEntity
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.PendingOverlayBuilder
import com.explainer.app.data.local.snapshot.SnapshotJsonCodec
import com.explainer.app.feature.progress.ProgressMerge
import java.time.Instant
import java.time.DateTimeException

/**
 * Disponibilidad de contenido de un item de catálogo:
 * - [REMOTE_ONLY]: resumen remoto sin snapshot (descargable).
 * - [OFFLINE]: snapshot activo utilizable sin red.
 * - [UPDATING]: descarga en curso (no molesta al snapshot previo).
 * - [UPDATE_POSSIBLE]: snapshot activo + remoto con versión de contenido
 *   (`content_updated_at`) más nueva (badge conservador; el snapshot NUNCA se
 *   reemplaza automáticamente).
 * - [UNAVAILABLE]: sin resumen ni snapshot (defensivo; la lista es la unión).
 */
enum class ProjectAvailability {
    REMOTE_ONLY,
    OFFLINE,
    UPDATING,
    UPDATE_POSSIBLE,
    UNAVAILABLE,
}

/**
 * Item de lista: vista ligera sin JSON pesado (el texto de las partes vive
 * solo en los snapshots fijados). El progreso mostrado ya está mezclado
 * (remoto ∪ local ∪ overlay optimista con la policy T02).
 */
data class ProjectListItem(
    val projectId: ProjectId,
    val name: String,
    val description: String?,
    val status: ProjectStatus,
    val sourceType: String,
    val pdfFilename: String?,
    val createdAt: String,
    /** Reloj de actividad (`updated_at`) para ordenación/display; NO es la versión de contenido (`content_updated_at`), que gobierna [availability]. */
    val updatedAt: String,
    val partCount: Int,
    val segmentationSourceBytes: Long,
    val snapshotBytes: Long,
    val readingProgress: ReadingProgress,
    val availability: ProjectAvailability,
    /**
     * R-T07-07: el último refresh terminó en 404 (remoto no disponible).
     * Owner/project-scoped; nunca borra snapshot ni cola — el contenido
     * offline sigue utilizable y la UI puede distinguir la condición.
     */
    val remoteUnavailable: Boolean = false,
)

/** Constructor puro del item (testeable sin Room). */
internal fun buildProjectListItem(
    projectId: ProjectId,
    summary: ProjectSummaryEntity?,
    snapshot: OfflineSnapshotEntity?,
    download: DownloadStateEntity?,
    pending: List<PendingProgressEntity>,
    remoteUnavailable: Boolean = false,
): ProjectListItem {
    val availability = when {
        download?.state in ACTIVE_DOWNLOAD_STATES -> ProjectAvailability.UPDATING
        snapshot != null -> {
            if (isNewerTimestamp(remoteContentUpdatedAt(summary), snapshot.sourceUpdatedAt)) {
                ProjectAvailability.UPDATE_POSSIBLE
            } else {
                ProjectAvailability.OFFLINE
            }
        }

        summary != null -> ProjectAvailability.REMOTE_ONLY
        else -> ProjectAvailability.UNAVAILABLE
    }
    return ProjectListItem(
        projectId = projectId,
        name = summary?.name ?: snapshot?.name.orEmpty(),
        description = summary?.description ?: snapshot?.description,
        status = summary?.let { ProjectStatus.fromWire(it.status) } ?: ProjectStatus.fromWire(snapshot?.status.orEmpty()),
        sourceType = summary?.sourceType ?: snapshot?.sourceType ?: "pdf",
        pdfFilename = summary?.pdfFilename,
        createdAt = summary?.createdAt.orEmpty(),
        updatedAt = summary?.remoteUpdatedAt ?: snapshot?.sourceUpdatedAt.orEmpty(),
        partCount = summary?.let { CatalogSummaryMapper.decodePartIndex(it.partIndexJson).size } ?: 0,
        segmentationSourceBytes = summary?.segmentationSourceBytes ?: 0L,
        snapshotBytes = snapshot?.totalBytes ?: 0L,
        readingProgress = ProgressMerge.merged(
            summaryProgress = summary?.let { SnapshotJsonCodec.decodeReadingProgress(it.readingProgressJson) },
            snapshotProgress = snapshot?.let { SnapshotJsonCodec.decodeReadingProgress(it.readingProgressJson) },
            overlay = PendingOverlayBuilder.fromRows(pending),
        ),
        availability = availability,
        remoteUnavailable = remoteUnavailable,
    )
}

/**
 * Parseo seguro de un timestamp ISO-8601 (R-T07-06/08): total ante
 * `DateTimeException` (parse inválido) y null/blank; `Instant` ya resuelto
 * evita el overflow de `toEpochMilli()` en las comparaciones.
 */
internal fun parseInstantOrNull(raw: String?): Instant? = try {
    if (raw.isNullOrBlank()) null else Instant.parse(raw)
} catch (_: DateTimeException) {
    null
}

/**
 * Orden por `updated_at` ISO descendente; inválido degrada a epoch.
 * Total (R-T07-06): también captura el overflow de `toEpochMilli()` para
 * años fuera del rango de epoch-millis (p.ej. `±1000000000-01-01`).
 */
internal fun timestampEpochMillis(raw: String?): Long = try {
    parseInstantOrNull(raw)?.toEpochMilli() ?: 0L
} catch (_: ArithmeticException) {
    0L
}

private fun isNewerTimestamp(remote: String?, source: String?): Boolean =
    timestampEpochMillis(remote) > timestampEpochMillis(source)

/**
 * Versión de contenido remota (`content_updated_at`), con fallback legacy a
 * `updated_at` para backends sin `content_updated_at`. La comparación de
 * disponibilidad usa SOLO la versión de contenido: `updated_at` (reloj de
 * actividad) avanza también con el progreso de lectura y no implica contenido
 * nuevo.
 */
private fun remoteContentUpdatedAt(summary: ProjectSummaryEntity?): String? =
    summary?.remoteContentUpdatedAt?.takeIf { it.isNotBlank() } ?: summary?.remoteUpdatedAt

private val ACTIVE_DOWNLOAD_STATES = setOf(
    DownloadStateEntity.STATE_QUEUED,
    DownloadStateEntity.STATE_DOWNLOADING,
    DownloadStateEntity.STATE_PREPARING,
    DownloadStateEntity.STATE_COMMITTING,
)

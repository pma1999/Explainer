package com.explainer.app.feature.catalog

import com.explainer.app.core.model.PartDescriptor
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.core.model.ReadingProgress

/**
 * Vista de lectura de un proyecto (manifest del snapshot activo + progreso
 * mezclado remoto/local/overlay). Self-contained: funciona sin red ni token
 * y no depende de la fila de catálogo para el contenido.
 */
data class ReaderProject(
    val projectId: ProjectId,
    val name: String,
    val description: String?,
    val status: ProjectStatus,
    val sourceType: String,
    /** `segmentation.partes` recortada a numero/titulo/contenido. */
    val parts: List<PartDescriptor>,
    val readingProgress: ReadingProgress,
    /** `updated_at` ISO-8601 (catálogo fresco o fuente del snapshot). */
    val updatedAt: String,
    val totalBytes: Long,
    val downloadedAt: Long,
    val activeGeneration: String,
)

package com.explainer.app.core.model

import kotlinx.serialization.json.JsonObject

/**
 * Resumen de proyecto (lista o detalle) en dominio.
 *
 * El snapshot permitido EXCLUYE PDF, `source_text`, `file_uri`, paths
 * internos, API keys y `user_id`: esos campos no existen aquí; `ownerId`
 * siempre viene de la sesión local, nunca del payload. `usage` y
 * `sourceMetadata` se conservan crudos (sin pérdida) porque su shape no está
 * congelado por el contrato de lectura.
 */
data class ProjectSummary(
    val id: ProjectId,
    val name: String,
    val description: String?,
    val pdfFilename: String?,
    val sourceType: String,
    val sourceUrl: String?,
    val sourceMetadata: JsonObject,
    val status: ProjectStatus,
    /** `segmentation.partes` recortado a `numero/titulo/contenido`. */
    val parts: List<PartDescriptor>,
    val usage: JsonObject,
    val readingProgress: ReadingProgress,
    val errorMessage: String?,
    val createdAt: String,
    val updatedAt: String,
    /**
     * Versión de contenido (ISO-8601) del remoto: solo avanza cuando cambia
     * `segmentation`/`partes_contenido`, no con el progreso de lectura.
     * Vacío en backends antiguos (fallback legacy a [updatedAt]).
     */
    val contentUpdatedAt: String = "",
)

package com.explainer.app.feature.generation

import com.explainer.app.core.model.ProjectId
import kotlinx.coroutines.CancellationException

/**
 * Generación on-demand de `esquema` (Mermaid) y `repaso` (review) desde el
 * lector (T14): reemplaza la redirección "genéralo en la web" por generación
 * in-app, con persistencia en el snapshot local activo.
 *
 * El repositorio orquesta el flujo completo: llama al remoto FastAPI
 * (`POST /api/projects/{id}/parts/{pid}/mermaid` y `.../review`), y en éxito
 * fusiona el resultado (`mermaid`/`review`) en la fila de la parte de la
 * generación activa del snapshot (Room) para que el lector lo recargue y lo
 * conserve offline. `regenerate=true` fuerza regeneración aunque exista
 * contenido previo (paridad web).
 *
 * La cancelación de la corrutina (p. ej. cambiar de parte) se propaga como
 * [CancellationException]; nunca produce [GenerationOutcome.Failure].
 */
interface PartGenerationRepository {

    /**
     * Genera (o regenera) el esquema visual Mermaid de la parte y lo persiste
     * en el snapshot activo. [GenerationOutcome.Success] implica contenido ya
     * escrito en Room: el lector debe recargar la parte para re-renderizar.
     */
    suspend fun generateDiagram(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): GenerationOutcome

    /**
     * Genera (o regenera) el repaso activo de la parte y lo persiste en el
     * snapshot activo. Mismas garantías que [generateDiagram].
     */
    suspend fun generateReview(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): GenerationOutcome
}

/** Resultado de una generación on-demand. */
sealed interface GenerationOutcome {
    /** Generado y persistido; la UI debe recargar la parte. */
    data object Success : GenerationOutcome

    /** Fallo categorizado; el mensaje visible lo resuelve la UI desde [reason]. */
    data class Failure(val reason: GenerationFailureReason) : GenerationOutcome
}

/**
 * Categorías de fallo de generación (nunca se propagan `{detail}`/JWT/bodies,
 * paridad con [com.explainer.app.data.remote.RemoteResult]). La UI mapea cada
 * categoría a una string resource accionable.
 */
enum class GenerationFailureReason {
    /** Sin red, timeout o error 5xx transitorio: reintentar más tarde. */
    OFFLINE,

    /** 401 tras refresh: sesión inválida o caducada; volver a autenticar. */
    AUTH,

    /** 400/403: proyecto sin completar, sin API key configurada, explainer con error. */
    PERMISSION,

    /** 404: el proyecto o la parte ya no existen. */
    NOT_FOUND,

    /** 429: límite de peticiones al proveedor; esperar y reintentar. */
    RATE_LIMITED,

    /** Respuesta malformada o inesperada del servidor. */
    INVALID,

    /** Cualquier otro fallo. */
    UNKNOWN,
}

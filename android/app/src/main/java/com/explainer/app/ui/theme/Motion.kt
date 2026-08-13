package com.explainer.app.ui.theme

/**
 * Tokens de movimiento: navegación/parte, progreso de descarga y reveal de
 * respuesta (global-constraints.md UX). Rápidos, coherentes y sin haptics:
 * los componentes presentacionales nunca disparan haptics.
 *
 * Compose multiplica estas duraciones por la escala de animación del sistema
 * (MotionDurationScale) cuando el host la provee; en previews se usa 1x.
 */
object MotionTokens {
    /** Cambios de parte/tab y reveal cortos. */
    const val FastMs = 150

    /** Progreso de descarga y transiciones de panel. */
    const val NormalMs = 250

    /** Reveal de respuesta (expansión de contenido). */
    const val EmphasisMs = 400
}

package com.explainer.app.core.model

/**
 * Una parte de `segmentation.partes` recortada a lo que el snapshot lógico
 * conserva: `numero`, `titulo` y `contenido` (descripción de sección).
 * El texto de `contenido` no se copia en múltiples modelos/UI states.
 */
data class PartDescriptor(
    val numero: Int,
    val titulo: String,
    val contenido: String,
)

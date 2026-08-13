package com.explainer.app.core.model

/**
 * Estado remoto de una parte dentro de `partes_contenido[part_id]`.
 * Valores futuros se representan como [Unknown] con el raw preservado.
 *
 * Wire: `pending|processing|completed|failed`.
 */
sealed interface PartStatus {
    data object Pending : PartStatus
    data object Processing : PartStatus
    data object Completed : PartStatus
    data object Failed : PartStatus
    data class Unknown(val raw: String) : PartStatus

    companion object {
        fun fromWire(raw: String): PartStatus = when (raw) {
            "pending" -> Pending
            "processing" -> Processing
            "completed" -> Completed
            "failed" -> Failed
            else -> Unknown(raw)
        }
    }
}

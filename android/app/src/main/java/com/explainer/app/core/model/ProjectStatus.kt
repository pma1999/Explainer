package com.explainer.app.core.model

/**
 * Estado remoto de un proyecto. Valores futuros se representan como
 * [Unknown] con el raw preservado y nunca rompen el decode ni el mapeo.
 *
 * Wire: `pending|uploading|segmenting|processing|completed|error`.
 */
sealed interface ProjectStatus {
    data object Pending : ProjectStatus
    data object Uploading : ProjectStatus
    data object Segmenting : ProjectStatus
    data object Processing : ProjectStatus
    data object Completed : ProjectStatus
    data object Error : ProjectStatus
    data class Unknown(val raw: String) : ProjectStatus

    companion object {
        fun fromWire(raw: String): ProjectStatus = when (raw) {
            "pending" -> Pending
            "uploading" -> Uploading
            "segmenting" -> Segmenting
            "processing" -> Processing
            "completed" -> Completed
            "error" -> Error
            else -> Unknown(raw)
        }
    }
}

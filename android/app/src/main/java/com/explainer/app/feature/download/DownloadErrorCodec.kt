package com.explainer.app.feature.download

/**
 * Codificación estable de [DownloadError] a la columna `error_category` de
 * `DownloadStateEntity` (y viceversa). Formato `categoria` o
 * `categoria:razon` con razones cortas y seguras (`json`, `http:400`);
 * categorías desconocidas decodifican como [DownloadError.Permanent] con
 * prefijo `unknown:` (nunca lanza).
 */
object DownloadErrorCodec {

    fun encode(error: DownloadError): String = when (error) {
        is DownloadError.Network -> "network"
        is DownloadError.AuthRequired -> "auth_required"
        is DownloadError.NotFound -> "not_found"
        is DownloadError.NotEnoughSpace -> "not_enough_space"
        is DownloadError.InvalidPayload -> "invalid_payload:${error.reason}"
        is DownloadError.Permanent -> "permanent:${error.reason}"
        is DownloadError.Local -> "local:${error.reason}"
    }

    fun decode(wire: String?): DownloadError? {
        if (wire.isNullOrEmpty()) return null
        val category = wire.substringBefore(':')
        val reason = wire.substringAfter(':', "")
        return when (category) {
            "network" -> DownloadError.Network
            "auth_required" -> DownloadError.AuthRequired
            "not_found" -> DownloadError.NotFound
            "not_enough_space" -> DownloadError.NotEnoughSpace
            "invalid_payload" -> DownloadError.InvalidPayload(reason)
            "permanent" -> DownloadError.Permanent(reason)
            "local" -> DownloadError.Local(reason)
            else -> DownloadError.Permanent("unknown:$category")
        }
    }
}

package com.explainer.app.core.model

import java.io.File

/**
 * Resultado de `downloadProjectTo`: el archivo temporal ya transmitido a
 * disco. `contentLength` es el total real si el servidor lo declaró;
 * `receivedBytes` es lo realmente recibido (bytes lógicos).
 */
data class DownloadedProjectFile(
    val file: File,
    val contentLength: Long?,
    val receivedBytes: Long,
)

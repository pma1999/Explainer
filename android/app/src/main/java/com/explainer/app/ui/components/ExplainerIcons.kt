package com.explainer.app.ui.components

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.dp

/**
 * Iconoteca propia de la app (el APK no incluye material-icons: material3
 * 1.4.0 ya no lo arrastra y el catálogo está congelado). Trazados 24dp de la
 * familia Material, dibujados como [ImageVector] locales con relleno negro:
 * el color lo aplica siempre el host vía `Icon(tint = …)`.
 *
 * Solo se dibujan los iconos que la UI usa; si falta uno, se añade aquí (no
 * se agrega material-icons-extended). Los iconos son decorativos: toda
 * información crítica viaja también como texto (global-constraints.md UX).
 */
object ExplainerIcons {

    /** Navegación atrás. */
    val ArrowBack: ImageVector by lazy {
        materialIcon("ArrowBack", "M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z")
    }

    /** Refrescar / sincronizar / regenerar. */
    val Refresh: ImageVector by lazy {
        materialIcon(
            "Refresh",
            "M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8" +
                "c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6" +
                "s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z",
        )
    }

    /** Confirmado / leído. */
    val Check: ImageVector by lazy {
        materialIcon("Check", "M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z")
    }

    /** Cierre / descartar. */
    val Close: ImageVector by lazy {
        materialIcon("Close", "M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z")
    }

    /** Añadir. */
    val Add: ImageVector by lazy {
        materialIcon("Add", "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z")
    }

    /** Borrar (copia local). */
    val Delete: ImageVector by lazy {
        materialIcon("Delete", "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z")
    }

    /** Ajustes. */
    val Settings: ImageVector by lazy {
        materialIcon(
            "Settings",
            "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61" +
                "l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54" +
                "c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94" +
                "l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63" +
                "-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39" +
                "-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54" +
                "c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61" +
                "l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z",
        )
    }

    /** Descargar. */
    val Download: ImageVector by lazy {
        materialIcon("Download", "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z")
    }

    /** Advertencia. */
    val Warning: ImageVector by lazy {
        materialIcon("Warning", "M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z")
    }

    /** Error (círculo con signo). */
    val Error: ImageVector by lazy {
        materialIcon("Error", "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z")
    }

    /** Información. */
    val Info: ImageVector by lazy {
        materialIcon("Info", "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z")
    }

    /** Desplegar hacia abajo. */
    val KeyboardArrowDown: ImageVector by lazy {
        materialIcon("KeyboardArrowDown", "M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z")
    }

    /** Desplegar hacia arriba. */
    val KeyboardArrowUp: ImageVector by lazy {
        materialIcon("KeyboardArrowUp", "M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6z")
    }

    /** Anterior. */
    val KeyboardArrowLeft: ImageVector by lazy {
        materialIcon("KeyboardArrowLeft", "M15.41 16.59L10.83 12l4.58-4.59L14 6l-6 6 6 6 1.41-1.41z")
    }

    /** Siguiente. */
    val KeyboardArrowRight: ImageVector by lazy {
        materialIcon("KeyboardArrowRight", "M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.41z")
    }

    /** Mostrar contraseña. */
    val Visibility: ImageVector by lazy {
        materialIcon(
            "Visibility",
            "M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5z" +
                "M12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3" +
                "3-1.34 3-3-1.34-3-3-3z",
        )
    }

    /** Ocultar contraseña. */
    val VisibilityOff: ImageVector by lazy {
        materialIcon(
            "VisibilityOff",
            "M12 7c2.76 0 5 2.24 5 5 0 .65-.13 1.26-.36 1.83l2.92 2.92c1.51-1.26 2.7-2.89 3.43-4.75" +
                "-1.73-4.39-6-7.5-11-7.5-1.4 0-2.74.25-3.98.7l2.16 2.16C10.74 7.13 11.35 7 12 7zM2 4.27l2.28 2.28" +
                ".46.46C3.08 8.3 1.78 10.02 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L19.73 22" +
                "21 20.73 3.27 3 2 4.27zM7.53 9.8l1.55 1.55c-.05.21-.08.43-.08.65 0 1.66 1.34 3 3 3 .22 0 .44-.03" +
                ".65-.08l1.55 1.55c-.67.33-1.41.53-2.2.53-2.76 0-5-2.24-5-5 0-.79.2-1.53.53-2.2zm4.31-.78l3.15 3.15" +
                ".02-.16c0-1.66-1.34-3-3-3l-.17.01z",
        )
    }

    /** Abrir enlace externo. */
    val OpenInNew: ImageVector by lazy {
        materialIcon("OpenInNew", "M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z")
    }

    /** Copiar código. */
    val ContentCopy: ImageVector by lazy {
        materialIcon("ContentCopy", "M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z")
    }

    /** Correo electrónico. */
    val Email: ImageVector by lazy {
        materialIcon("Email", "M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z")
    }

    /** Contraseña. */
    val Lock: ImageVector by lazy {
        materialIcon("Lock", "M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z")
    }

    /** Sin conexión. */
    val CloudOff: ImageVector by lazy {
        materialIcon(
            "CloudOff",
            "M19.35 10.04C18.67 6.59 15.64 4 12 4c-1.48 0-2.85.43-4.01 1.17l1.46 1.46C10.21 6.23 11.08 6 12 6" +
                "c3.04 0 5.5 2.46 5.5 5.5v.5H19c1.66 0 3 1.34 3 3 0 1.13-.64 2.11-1.56 2.62l1.45 1.45" +
                "C23.16 18.16 24 16.68 24 15c0-2.64-2.05-4.78-4.65-4.96zM3 5.27l2.75 2.74C2.56 8.15 0 10.77 0 14" +
                "c0 3.31 2.69 6 6 6h11.73l2 2L21 20.73 4.27 4 3 5.27zM7.73 10l8 8H6c-2.21 0-4-1.79-4-4s1.79-4 4-4h1.73z",
        )
    }

    /** Carpeta / proyecto. */
    val FolderOpen: ImageVector by lazy {
        materialIcon("FolderOpen", "M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 12H4V8h16v10z")
    }

    /** Almacenamiento local. */
    val Storage: ImageVector by lazy {
        materialIcon("Storage", "M2 20h20v-4H2v4zm2-3h2v2H4v-2zM2 4v4h20V4H2zm4 3H4V5h2v2zm-4 7h20v-4H2v4zm2-3h2v2H4v-2z")
    }

    /** Cerrar sesión. */
    val Logout: ImageVector by lazy {
        materialIcon("Logout", "M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5-5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z")
    }

    /** Tab Explicación (libro). */
    val MenuBook: ImageVector by lazy {
        materialIcon(
            "MenuBook",
            "M21 5c-1.11-.35-2.33-.5-3.5-.5-1.95 0-4.05.4-5.5 1.5-1.45-1.1-3.55-1.5-5.5-1.5S2.45 4.9 1 6v14.65" +
                "c0 .25.25.5.5.5.1 0 .15-.05.25-.05C3.1 20.45 5.05 20 6.5 20c1.95 0 4.05.4 5.5 1.5 1.35-.85" +
                "3.8-1.5 5.5-1.5 1.65 0 3.35.3 4.75 1.05.1.05.15.05.25.05.25 0 .5-.25.5-.5V6c-.6-.45-1.25-.75-2-1zm0 13.5" +
                "c-1.1-.35-2.3-.5-3.5-.5-1.7 0-4.15.65-5.5 1.5V8c1.35-.85 3.8-1.5 5.5-1.5 1.2 0 2.4.15 3.5.5v11.5z",
        )
    }

    /** Tab Recorrido (mapa). */
    val Map: ImageVector by lazy {
        materialIcon("Map", "M20.5 3l-.16.03L15 5.1 9 3 3.36 4.9c-.21.07-.36.25-.36.48V20.5c0 .28.22.5.5.5l.16-.03L9 18.9l6 2.1 5.64-1.9c.21-.07.36-.25.36-.48V3.5c0-.28-.22-.5-.5-.5zM15 19l-6-2.11V5l6 2.11V19z")
    }

    /** Tab Recursos (enlace). */
    val Link: ImageVector by lazy {
        materialIcon("Link", "M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z")
    }

    /** Tab Esquema (árbol de nodos). */
    val AccountTree: ImageVector by lazy {
        materialIcon("AccountTree", "M22 11V3h-7v3H9V3H2v8h7V8h2v10h4v3h7v-8h-7v3h-2V8h2v3h7zM7 9H4V5h3v4zm10 6h3v4h-3v-4zm0-10h3v4h-3V5z")
    }

    /** Tab Repaso (pregunta). */
    val Quiz: ImageVector by lazy {
        materialIcon(
            "Quiz",
            "M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4" +
                "c0-1.1-.9-2-2-2zm-5.99 14c-.59 0-1.05-.47-1.05-1.05 0-.59.46-1.05 1.05-1.05.59 0 1.04.46 1.04 1.05" +
                " 0 .58-.45 1.05-1.04 1.05zm2.24-3.89c-.62.61-1.02 1.05-1.02 1.93h-2.06c0-1.22.5-2.04 1.28-2.79.73" +
                "-.7 1.05-1.15 1.05-2.03 0-.98-.78-1.7-1.84-1.7-.82 0-1.45.39-1.78.9l-1.75-.88c.6-1.2 1.92-2.02" +
                "3.61-2.02 2.13 0 3.78 1.21 3.78 3.1 0 1.11-.57 1.9-1.27 2.56z",
        )
    }

    /** Diagrama a pantalla (zoom). */
    val OpenInFull: ImageVector by lazy {
        materialIcon("OpenInFull", "M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z")
    }

    /** Bandeja de entrada (vacío). */
    val Inbox: ImageVector by lazy {
        materialIcon("Inbox", "M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 12h-4c0 1.66-1.35 3-3 3s-3-1.34-3-3H4.99V5H19v10z")
    }

    /** Hecho / completado. */
    val Done: ImageVector by lazy {
        materialIcon("Done", "M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z")
    }
}

private fun materialIcon(name: String, pathData: String): ImageVector =
    ImageVector.Builder(
        name = name,
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).apply {
        // Pipeline canónico (el mismo que usan los iconos oficiales de
        // material-icons-core): el renderer nativo de Compose resuelve TODOS
        // los tipos de nodo, incluidos los relativos (h/v/c/s/q… en minúscula)
        // que dominan los trazados Material. Los nodos se pasan tal cual;
        // reemitirlos a mano por el DSL descartaba los relativos y rompía la
        // geometría de la mayoría de los iconos.
        addPath(
            pathData = PathParser().parsePathString(pathData).toNodes(),
            fill = SolidColor(Color.Black),
        )
    }.build()

package com.explainer.app.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.unit.Dp

/**
 * Breakpoints estables de la app (sin dependencia de Activity ni de la
 * librería windowsizeclass): mismos umbrales que Material WindowSizeClass
 * (compact < 600dp, medium 600–839dp, expanded >= 840dp de ancho).
 *
 * Compact: biblioteca y reader a pantalla completa; selector de partes en
 * sheet/drawer y tabs desplazables. Medium/expanded: rail y reader de dos
 * paneles (plan.md §8).
 */
enum class WindowSize { COMPACT, MEDIUM, EXPANDED }

object AppBreakpoints {
    const val CompactMaxWidthDp = 599
    const val MediumMaxWidthDp = 839
    const val ExpandedMinWidthDp = 840
}

/**
 * Observa el tamaño de ventana actual. Es "observable" porque lee
 * [LocalWindowInfo]: al redimensionar/rotar el host, la composición se
 * recomputa con el nuevo tamaño del contenedor. Sin lógica de dominio.
 */
@Composable
fun rememberWindowSize(): WindowSize {
    val containerSize = LocalWindowInfo.current.containerSize
    val density = LocalDensity.current
    val widthDp: Dp = with(density) { containerSize.width.toDp() }
    return remember(widthDp) {
        when {
            widthDp.value >= AppBreakpoints.ExpandedMinWidthDp -> WindowSize.EXPANDED
            widthDp.value >= 600 -> WindowSize.MEDIUM
            else -> WindowSize.COMPACT
        }
    }
}

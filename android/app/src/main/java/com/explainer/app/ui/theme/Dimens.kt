package com.explainer.app.ui.theme

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Tokens de espaciado, targets táctiles y métricas de lectura.
 * Escala única (4dp) para composición serena, sin mosaico de tarjetas.
 */
object Spacing {
    val Xs = 4.dp
    val Sm = 8.dp
    val Md = 12.dp
    val Lg = 16.dp
    val Xl = 24.dp
    val Xxl = 32.dp
}

/**
 * Métricas de lectura larga: ancho de línea acotado (~72ch a 17sp) y
 * separación de párrafos; el lector centra el contenido dentro del ancho.
 */
object ReadingMetrics {
    val MaxLineWidth = 640.dp
    val ParagraphSpacing = 16.dp
}

/** Alturas de chrome mínimo (top bar, tabs). */
object AppBarMetrics {
    val TopBarHeight = 64.dp
    val TabStripHeight = 48.dp
}

/**
 * Targets táctiles mínimos declarados por componente (ver
 * [com.explainer.app.ui.components]). Cada componente expone su propio
 * `Defaults.MinimumTargetSize`; [ComponentTargetsTest] verifica >= 48dp.
 */
object MinimumTargets {
    /** Target táctil mínimo universal (WCAG 2.5.8 / Material). */
    val Touch = 48.dp
    /** Altura mínima de fila interactiva en listas (pane de partes). */
    val Row = 48.dp
    /** Botón de acción dentro de paneles de estado. */
    val ActionButton = 48.dp
}

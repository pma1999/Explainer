package com.explainer.app.ui.theme

import androidx.compose.runtime.Composable

/**
 * Puente de T01 → T05: [MainActivity] (congelado hasta T11) seguía llamando
 * a [BootstrapTheme]; delega en el tema real con el modo por defecto DARK
 * (T13/R-T13-04: el default de arranque es DARK, nunca SYSTEM). T11
 * re-cablea la raíz de composición y elimina este puente.
 */
@Deprecated("Reemplazado por ExplainerTheme; T11 re-cablea MainActivity.")
@Composable
fun BootstrapTheme(content: @Composable () -> Unit) {
    ExplainerTheme(content = content)
}

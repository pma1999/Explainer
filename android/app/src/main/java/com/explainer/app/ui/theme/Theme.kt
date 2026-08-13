package com.explainer.app.ui.theme

import android.app.Activity
import android.graphics.drawable.ColorDrawable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

/**
 * Modo de tema de la app. El valor persistido se integra con DataStore en
 * T11; este task solo produce el modo y el tema.
 */
enum class ThemeMode { SYSTEM, LIGHT, DARK }

/**
 * R-T13-04: modo de arranque y default de [ExplainerTheme] cuando el llamador
 * no especifica modo. Es DARK (identidad "Scholarly Forge"), NUNCA SYSTEM: la
 * rama sin container de `ExplainerApp` (setup error) y cualquier llamada sin
 * modo no pueden destellar papel claro en un dispositivo claro. SYSTEM sigue
 * existiendo como opción persistida (ThemePreferences/SettingsScreen).
 */
internal val DefaultThemeMode: ThemeMode = ThemeMode.DARK

/**
 * Tema "Scholarly Forge": superficies tinta/papel, acento dorado único,
 * claro/oscuro/sistema y sin dynamic color (la identidad y el contraste no
 * dependen del wallpaper del dispositivo).
 *
 * @param mode modo de tema solicitado; [ThemeMode.SYSTEM] sigue al sistema.
 * @param content contenido bajo el tema.
 */
@Composable
fun ExplainerTheme(
    mode: ThemeMode = DefaultThemeMode,
    content: @Composable () -> Unit,
) {
    val dark = when (mode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    val colors = if (dark) ExplainerColors.Dark else ExplainerColors.Light

    // T13: las barras del sistema siguen al tema ACTIVO (no al modo del
    // dispositivo): con default DARK en un dispositivo en modo claro, los
    // iconos de estado se aclaran para no desaparecer sobre la tinta.
    // R-T13-01: la ventana del sistema sigue al tema ACTIVO (papel en LIGHT,
    // tinta en DARK); la #0d1117 de themes.xml solo cubre el primer frame
    // pre-Compose (default DARK). Sin esto, LIGHT dejaría texto oscuro sobre
    // la ventana tinta (~1.16:1).
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.setBackgroundDrawable(ColorDrawable(colors.background.toArgb()))
            val controller = WindowCompat.getInsetsController(window, view)
            controller.isAppearanceLightStatusBars = !dark
            controller.isAppearanceLightNavigationBars = !dark
        }
    }

    CompositionLocalProvider(LocalExplainerColors provides colors) {
        MaterialTheme(
            colorScheme = colors.toMaterialColorScheme(dark = dark),
            typography = ExplainerTypography,
            shapes = ExplainerShapes.material(),
            content = content,
        )
    }
}

/** Paleta semántica del tema activo para los componentes. */
val MaterialTheme.explainerColors: ExplainerColors
    @Composable
    @ReadOnlyComposable
    get() = LocalExplainerColors.current

/** Tipografía de lectura larga del tema (independiente de la tipografía UI). */
val MaterialTheme.readingTypography: ReadingTypography
    @Composable
    @ReadOnlyComposable
    get() = DefaultReadingTypography

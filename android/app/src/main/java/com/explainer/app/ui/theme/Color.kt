package com.explainer.app.ui.theme

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * Paleta "Scholarly Forge": una biblioteca académica contemporánea tallada en
 * tinta y papel con un único acento dorado.
 *
 * Origen de identidad: `frontend/style.css` (--bg-base/--bg-surface/--gold,
 * L8-33 y L1157-1174). Dark parte de `#0d1117/#161b22` y oro `#e8b86d`;
 * light usa papel cálido e ink. No se usa dynamic color: la identidad y el
 * contraste son fijos por tema.
 *
 * Auditoría de legibilidad T13: cada rol textual mantiene contraste WCAG AA
 * (>= 4.5:1) sobre su contenedor real de la UI (fondo, superficie,
 * surfaceVariant y tarjetas surfaceContainerHigh/Highest), el texto de
 * lectura larga alcanza >= 7:1, los bordes/divisores oscuros >= 3:1
 * (1.4.11) y los contenedores tienen elevación distinguible; los tests
 * `ThemeTokensTest` lo verifican.
 */
data class ExplainerColors(
    // Fondos y superficies (papel / tinta)
    val background: Color,
    val onBackground: Color,
    val surface: Color,
    val onSurface: Color,
    val surfaceVariant: Color,
    val onSurfaceVariant: Color,
    val surfaceContainerHigh: Color,
    val surfaceContainerHighest: Color,
    // Acento dorado único
    val primary: Color,
    val onPrimary: Color,
    val primaryContainer: Color,
    val onPrimaryContainer: Color,
    // Secundario/terciario: grises cálidos de apoyo, nunca un segundo acento
    val secondary: Color,
    val onSecondary: Color,
    val secondaryContainer: Color,
    val onSecondaryContainer: Color,
    val tertiary: Color,
    val onTertiary: Color,
    val tertiaryContainer: Color,
    val onTertiaryContainer: Color,
    // Errores
    val error: Color,
    val onError: Color,
    val errorContainer: Color,
    val onErrorContainer: Color,
    // Límites y divisores
    val outline: Color,
    val outlineVariant: Color,
    // Estados semánticos operativos (descarga, sincronización, offline)
    val status: StatusColors,
) {
    /** Estados semánticos: éxito (descarga/sync), aviso (estimado) y offline. */
    data class StatusColors(
        val success: Color,
        val onSuccess: Color,
        val successContainer: Color,
        val onSuccessContainer: Color,
        val warning: Color,
        val onWarning: Color,
        val warningContainer: Color,
        val onWarningContainer: Color,
        val offline: Color,
        val onOffline: Color,
        val offlineContainer: Color,
        val onOfflineContainer: Color,
    )

    /** Convierte la paleta al [ColorScheme] de Material 3 usado por [ExplainerTheme]. */
    fun toMaterialColorScheme(dark: Boolean): ColorScheme = if (dark) {
        darkColorScheme(
            background = background,
            onBackground = onBackground,
            surface = surface,
            onSurface = onSurface,
            surfaceVariant = surfaceVariant,
            onSurfaceVariant = onSurfaceVariant,
            primary = primary,
            onPrimary = onPrimary,
            primaryContainer = primaryContainer,
            onPrimaryContainer = onPrimaryContainer,
            secondary = secondary,
            onSecondary = onSecondary,
            secondaryContainer = secondaryContainer,
            onSecondaryContainer = onSecondaryContainer,
            tertiary = tertiary,
            onTertiary = onTertiary,
            tertiaryContainer = tertiaryContainer,
            onTertiaryContainer = onTertiaryContainer,
            error = error,
            onError = onError,
            errorContainer = errorContainer,
            onErrorContainer = onErrorContainer,
            outline = outline,
            outlineVariant = outlineVariant,
        )
    } else {
        lightColorScheme(
            background = background,
            onBackground = onBackground,
            surface = surface,
            onSurface = onSurface,
            surfaceVariant = surfaceVariant,
            onSurfaceVariant = onSurfaceVariant,
            primary = primary,
            onPrimary = onPrimary,
            primaryContainer = primaryContainer,
            onPrimaryContainer = onPrimaryContainer,
            secondary = secondary,
            onSecondary = onSecondary,
            secondaryContainer = secondaryContainer,
            onSecondaryContainer = onSecondaryContainer,
            tertiary = tertiary,
            onTertiary = onTertiary,
            tertiaryContainer = tertiaryContainer,
            onTertiaryContainer = onTertiaryContainer,
            error = error,
            onError = onError,
            errorContainer = errorContainer,
            onErrorContainer = onErrorContainer,
            outline = outline,
            outlineVariant = outlineVariant,
        )
    }

    companion object {
        /** Dark "Scholarly Forge": tinta `#0d1117/#161b22`, oro `#e8b86d`, papel `#f0ece3`. */
        val Dark = ExplainerColors(
            background = Color(0xFF0D1117),
            onBackground = Color(0xFFF0ECE3),
            surface = Color(0xFF161B22),
            onSurface = Color(0xFFF0ECE3),
            surfaceVariant = Color(0xFF1F2937),
            // T13: secundario más claro (7.7:1 sobre surface) y contenedores
            // elevados distinguibles (>= 1.5:1 sobre surface).
            onSurfaceVariant = Color(0xFFA7AEB9),
            surfaceContainerHigh = Color(0xFF2F3B4F),
            surfaceContainerHighest = Color(0xFF354156),
            primary = Color(0xFFE8B86D),
            onPrimary = Color(0xFF201A10),
            primaryContainer = Color(0xFF3A2F14),
            onPrimaryContainer = Color(0xFFF5DFB4),
            secondary = Color(0xFFB8B0A0),
            onSecondary = Color(0xFF1C1917),
            secondaryContainer = Color(0xFF2A2720),
            onSecondaryContainer = Color(0xFFE4DCC8),
            tertiary = Color(0xFFB9B2A6),
            onTertiary = Color(0xFF241F16),
            tertiaryContainer = Color(0xFF2C2820),
            onTertiaryContainer = Color(0xFFE6DFD2),
            error = Color(0xFFEF4444),
            onError = Color(0xFF2B0A0A),
            errorContainer = Color(0xFF5C1A14),
            onErrorContainer = Color(0xFFF7D5CF),
            // T13: bordes y divisores visibles (>= 3:1, WCAG 1.4.11) sobre
            // tinta, conservando la familia gris-pizarra de la web.
            outline = Color(0xFF5D677B),
            outlineVariant = Color(0xFF5B677E),
            status = StatusColors(
                success = Color(0xFF10B981),
                onSuccess = Color(0xFF04150E),
                successContainer = Color(0xFF0B2B1E),
                onSuccessContainer = Color(0xFFA7F3D0),
                warning = Color(0xFFFBBF24),
                onWarning = Color(0xFF211703),
                warningContainer = Color(0xFF3A2E0B),
                onWarningContainer = Color(0xFFFDE9B8),
                offline = Color(0xFF9CA3AF),
                onOffline = Color(0xFF131720),
                // Mantiene el valor de surfaceContainerHighest (elevación).
                offlineContainer = Color(0xFF354156),
                onOfflineContainer = Color(0xFFD1D5DB),
            ),
        )

        /** Light: papel cálido e ink; acento dorado oscurecido para AA sobre papel. */
        val Light = ExplainerColors(
            background = Color(0xFFF6F1E5),
            onBackground = Color(0xFF241F17),
            surface = Color(0xFFFBF7EE),
            onSurface = Color(0xFF241F17),
            surfaceVariant = Color(0xFFECE3CF),
            onSurfaceVariant = Color(0xFF5C554A),
            // T13: contenedores con jerarquía visible sobre el papel
            // (>= 1.4:1 sobre surface) sin romper el AA del texto que alojan.
            surfaceContainerHigh = Color(0xFFD8CBA8),
            surfaceContainerHighest = Color(0xFFD0C4A4),
            // T13: el oro se oscurece a bronce para AA >= 4.5:1 también sobre
            // las tarjetas (era 4.17:1 sobre surfaceContainerHigh).
            // R-T13-03: #6a4a0c (un paso más oscuro) para que la acción de
            // cierre de los banners (texto primary por defecto de M3 sobre
            // surfaceContainerHighest/offlineContainer) pase AA en LIGHT:
            // 4.66:1 sobre el contenedor más elevado (el #6e4e0f daba 4.39:1);
            // el resto de usos del oro suben (tarjeta 5.02:1, superficie
            // 7.56:1, fondo 7.17:1, onPrimary 7.51:1).
            primary = Color(0xFF6A4A0C),
            onPrimary = Color(0xFFFDF6E7),
            primaryContainer = Color(0xFFF2E2B8),
            onPrimaryContainer = Color(0xFF3F2D05),
            secondary = Color(0xFF6E6557),
            onSecondary = Color(0xFFFBF7EE),
            secondaryContainer = Color(0xFFE8DEC8),
            onSecondaryContainer = Color(0xFF2E291E),
            // T13: tertiary oscurecido para >= 4.5:1 sobre papel.
            tertiary = Color(0xFF726A5C),
            onTertiary = Color(0xFFFBF7EE),
            tertiaryContainer = Color(0xFFEBE2CE),
            onTertiaryContainer = Color(0xFF322C20),
            error = Color(0xFFB42318),
            onError = Color(0xFFFFF5F2),
            errorContainer = Color(0xFFF7D8D2),
            onErrorContainer = Color(0xFF57130D),
            // T13: borde de botones oscurecido (>= 3:1 también sobre tarjetas).
            outline = Color(0xFF6E675A),
            outlineVariant = Color(0xFFD4C9B2),
            status = StatusColors(
                success = Color(0xFF0D7A52),
                onSuccess = Color(0xFFF2FBF6),
                successContainer = Color(0xFFC9EAD9),
                onSuccessContainer = Color(0xFF073A27),
                // T13: ámbar oscurecido para AA sobre tarjetas (era 4.02:1).
                warning = Color(0xFF77480A),
                onWarning = Color(0xFFFFF8E6),
                warningContainer = Color(0xFFF4E3B4),
                onWarningContainer = Color(0xFF4A3203),
                offline = Color(0xFF5C554A),
                onOffline = Color(0xFFF6F1E5),
                // Mantiene el valor de surfaceContainerHighest (elevación).
                offlineContainer = Color(0xFFD0C4A4),
                onOfflineContainer = Color(0xFF2E291E),
            ),
        )
    }
}

/** Paleta semántica del tema activo, accesible por los componentes. */
val LocalExplainerColors = staticCompositionLocalOf { ExplainerColors.Light }

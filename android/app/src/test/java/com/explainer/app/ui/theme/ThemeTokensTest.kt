package com.explainer.app.ui.theme

import androidx.compose.ui.graphics.Color
import com.explainer.app.ui.components.StatusTone
import com.explainer.app.ui.components.labelColor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verificación determinista de los tokens de tema: paletas claro/oscuro
 * (origen frontend/style.css L8-33 y L1157-1174), contraste WCAG AA y
 * tipografía de lectura. No requiere dispositivo ni emulador.
 */
class ThemeTokensTest {

    private val dark = ExplainerColors.Dark
    private val light = ExplainerColors.Light

    // ── Tokens raíz ──

    @Test
    fun darkPalette_startsWithScholarlyForgeInkAndGold() {
        assertEquals(Color(0xFF0D1117), dark.background)
        assertEquals(Color(0xFF161B22), dark.surface)
        assertEquals(Color(0xFFE8B86D), dark.primary)
    }

    @Test
    fun lightPalette_isWarmPaperNotPureWhite() {
        assertEquals(Color(0xFFF6F1E5), light.background)
        assertNotEquals(Color.White, light.background)
        // El acento dorado se oscurece sobre papel y sobre contenedores
        // (auditoría T13): AA >= 4.5:1 también sobre surfaceContainerHigh.
        // R-T13-03: #6a4a0c (un paso más oscuro) para que la acción de cierre
        // de los banners pase AA sobre surfaceContainerHighest/offlineContainer.
        assertEquals(Color(0xFF6A4A0C), light.primary)
    }

    @Test
    fun lightAndDark_doNotMixRoles() {
        assertNotEquals(light.background, dark.background)
        assertNotEquals(light.surface, dark.surface)
        assertNotEquals(light.primary, dark.primary)
        assertNotEquals(light.onSurface, dark.onSurface)
        // El papel cálido claro no es la tinta del oscuro, ni al revés.
        assertNotEquals(light.background, dark.onSurface)
        assertNotEquals(dark.background, light.onSurface)
    }

    @Test
    fun darkSurfaceVariants_areElevatedInk() {
        assertEquals(Color(0xFF1F2937), dark.surfaceVariant)
        // Auditoría T13: el contenedor más elevado se aclara lo suficiente
        // para distinguir la elevación (>= 1.5:1 sobre surface) sin romper
        // el contraste del texto que aloja.
        assertEquals(Color(0xFF354156), dark.surfaceContainerHighest)
    }

    // ── Contraste WCAG ──

    @Test
    fun darkTextRoles_meetAALargeSurface() {
        assertTrue("onSurface/background", contrastRatio(dark.onSurface, dark.background) >= 4.5)
        assertTrue("onSurface/surface", contrastRatio(dark.onSurface, dark.surface) >= 4.5)
        assertTrue("onSurfaceVariant/background", contrastRatio(dark.onSurfaceVariant, dark.background) >= 4.5)
        assertTrue("onPrimary/primary", contrastRatio(dark.onPrimary, dark.primary) >= 4.5)
        assertTrue("onError/error", contrastRatio(dark.onError, dark.error) >= 4.5)
        assertTrue("onPrimaryContainer/primaryContainer", contrastRatio(dark.onPrimaryContainer, dark.primaryContainer) >= 4.5)
    }

    @Test
    fun lightTextRoles_meetAALargeSurface() {
        assertTrue("onSurface/background", contrastRatio(light.onSurface, light.background) >= 4.5)
        assertTrue("onSurface/surface", contrastRatio(light.onSurface, light.surface) >= 4.5)
        assertTrue("onSurfaceVariant/background", contrastRatio(light.onSurfaceVariant, light.background) >= 4.5)
        assertTrue("onPrimary/primary", contrastRatio(light.onPrimary, light.primary) >= 4.5)
        assertTrue("onError/error", contrastRatio(light.onError, light.error) >= 4.5)
        assertTrue("onPrimaryContainer/primaryContainer", contrastRatio(light.onPrimaryContainer, light.primaryContainer) >= 4.5)
    }

    @Test
    fun statusDots_meet3to1OnTheirSurfaces() {
        // Indicadores gráficos: WCAG 1.4.11 exige >= 3:1 sobre el fondo vivo.
        assertTrue("dark success/surface", contrastRatio(dark.status.success, dark.surface) >= 3.0)
        assertTrue("dark warning/surface", contrastRatio(dark.status.warning, dark.surface) >= 3.0)
        assertTrue("dark offline/background", contrastRatio(dark.status.offline, dark.background) >= 3.0)
        assertTrue("dark error/surface", contrastRatio(dark.error, dark.surface) >= 3.0)
        assertTrue("light success/surface", contrastRatio(light.status.success, light.surface) >= 3.0)
        assertTrue("light warning/surface", contrastRatio(light.status.warning, light.surface) >= 3.0)
        assertTrue("light offline/background", contrastRatio(light.status.offline, light.background) >= 3.0)
        assertTrue("light error/surface", contrastRatio(light.error, light.surface) >= 3.0)
    }

    @Test
    fun offlineBannerText_meetsAAOnContainer() {
        assertTrue("dark", contrastRatio(dark.status.onOfflineContainer, dark.status.offlineContainer) >= 4.5)
        assertTrue("light", contrastRatio(light.status.onOfflineContainer, light.status.offlineContainer) >= 4.5)
    }

    // ── Auditoría T13: contraste sobre contenedores reales ──

    @Test
    fun readingText_meetsEnhanced7to1OnRealContainers() {
        // Texto de lectura larga (cuerpo Markdown y títulos) sobre el fondo
        // real del lector: >= 7:1 (AAA) en ambos temas.
        assertTrue("dark onSurface/background", contrastRatio(dark.onSurface, dark.background) >= 7)
        assertTrue("dark onSurface/surface", contrastRatio(dark.onSurface, dark.surface) >= 7)
        assertTrue("light onSurface/background", contrastRatio(light.onSurface, light.background) >= 7)
        assertTrue("light onSurface/surface", contrastRatio(light.onSurface, light.surface) >= 7)
    }

    @Test
    fun markdownUsages_keepAAOnRealContainers() {
        // Código (texto onSurface sobre surfaceVariant), enlaces (primary
        // sobre fondo) y tablas (onSurface sobre surfaceContainerHigh).
        assertTrue("dark code", contrastRatio(dark.onSurface, dark.surfaceVariant) >= 4.5)
        assertTrue("light code", contrastRatio(light.onSurface, light.surfaceVariant) >= 4.5)
        assertTrue("dark link", contrastRatio(dark.primary, dark.background) >= 4.5)
        assertTrue("light link", contrastRatio(light.primary, light.background) >= 4.5)
        assertTrue("dark table", contrastRatio(dark.onSurface, dark.surfaceContainerHigh) >= 4.5)
        assertTrue("light table", contrastRatio(light.onSurface, light.surfaceContainerHigh) >= 4.5)
        // Acento dorado como texto sobre las tarjetas (ReviewContent).
        assertTrue("dark primary/card", contrastRatio(dark.primary, dark.surfaceContainerHigh) >= 4.5)
        assertTrue("light primary/card", contrastRatio(light.primary, light.surfaceContainerHigh) >= 4.5)
    }

    @Test
    fun secondaryText_meetsAAOnRealContainers() {
        // Texto secundario (onSurfaceVariant) y roles de apoyo (tertiary,
        // warning) sobre sus contenedores reales.
        for (container in listOf("background", "surface", "surfaceVariant", "surfaceContainerHigh")) {
            val darkBg = when (container) {
                "background" -> dark.background
                "surface" -> dark.surface
                "surfaceVariant" -> dark.surfaceVariant
                else -> dark.surfaceContainerHigh
            }
            val lightBg = when (container) {
                "background" -> light.background
                "surface" -> light.surface
                "surfaceVariant" -> light.surfaceVariant
                else -> light.surfaceContainerHigh
            }
            assertTrue("dark onSurfaceVariant/$container", contrastRatio(dark.onSurfaceVariant, darkBg) >= 4.5)
            assertTrue("light onSurfaceVariant/$container", contrastRatio(light.onSurfaceVariant, lightBg) >= 4.5)
        }
        assertTrue("light tertiary/background", contrastRatio(light.tertiary, light.background) >= 4.5)
        assertTrue("light tertiary/surface", contrastRatio(light.tertiary, light.surface) >= 4.5)
        assertTrue("light warning/card", contrastRatio(light.status.warning, light.surfaceContainerHigh) >= 4.5)
        assertTrue("light onWarning/warning", contrastRatio(light.status.onWarning, light.status.warning) >= 4.5)
    }

    @Test
    fun darkDividersAndBorders_areVisible() {
        // WCAG 1.4.11 (no-texto): bordes y divisores >= 3:1 sobre el fondo
        // y la superficie donde se dibujan en el tema oscuro.
        assertTrue("dark outline/background", contrastRatio(dark.outline, dark.background) >= 3)
        assertTrue("dark outline/surface", contrastRatio(dark.outline, dark.surface) >= 3)
        assertTrue("dark outlineVariant/background", contrastRatio(dark.outlineVariant, dark.background) >= 3)
        assertTrue("dark outlineVariant/surface", contrastRatio(dark.outlineVariant, dark.surface) >= 3)
    }

    @Test
    fun lightBorders_meetNonTextContrastOnRealContainers() {
        assertTrue("light outline/surface", contrastRatio(light.outline, light.surface) >= 3)
        assertTrue("light outline/card", contrastRatio(light.outline, light.surfaceContainerHigh) >= 3)
    }

    @Test
    fun darkSurfaces_haveDistinguishableElevation() {
        // Jerarquía de elevación: contenedores >= 1.5:1 sobre surface y
        // orden creciente de luminancia (surface < High < Highest).
        assertTrue("dark high/surface", contrastRatio(dark.surfaceContainerHigh, dark.surface) >= 1.5)
        assertTrue("dark highest/surface", contrastRatio(dark.surfaceContainerHighest, dark.surface) >= 1.5)
        assertTrue(
            "dark elevation order",
            relativeLuminance(dark.surface) < relativeLuminance(dark.surfaceContainerHigh) &&
                relativeLuminance(dark.surfaceContainerHigh) < relativeLuminance(dark.surfaceContainerHighest),
        )
    }

    @Test
    fun lightSurfaces_haveDistinguishableElevation() {
        // Jerarquía de elevación en papel: contenedores distinguibles de la
        // superficie y orden decreciente de luminancia (surface > High > Highest).
        assertTrue("light high/surface", contrastRatio(light.surfaceContainerHigh, light.surface) >= 1.4)
        assertTrue("light highest/surface", contrastRatio(light.surfaceContainerHighest, light.surface) >= 1.4)
        assertTrue(
            "light elevation order",
            relativeLuminance(light.surface) > relativeLuminance(light.surfaceContainerHigh) &&
                relativeLuminance(light.surfaceContainerHigh) > relativeLuminance(light.surfaceContainerHighest),
        )
    }

    @Test
    fun markdownTypography_readableSizeAndHeadingHierarchy() {
        val reading = DefaultReadingTypography
        // Cuerpo >= 16sp con factor de línea >= 1.5 (también cubierto por
        // readingTypography_usesSereneLineHeightFactor) y jerarquía clara.
        assertTrue("body >= 16sp", reading.body.fontSize.value >= 16f)
        assertTrue("body line factor", reading.body.lineHeight.value / reading.body.fontSize.value >= 1.5f)
        assertTrue(
            "heading order",
            reading.heading1.fontSize.value > reading.heading2.fontSize.value &&
                reading.heading2.fontSize.value > reading.heading3.fontSize.value,
        )
    }

    // ── Tipografía ──

    @Test
    fun readingTypography_usesSereneLineHeightFactor() {
        // integration-content-rendering.md: factor de línea 1.55–1.7.
        val reading = DefaultReadingTypography
        val bodyFactor = reading.body.lineHeight.value / reading.body.fontSize.value
        val largeFactor = reading.bodyLarge.lineHeight.value / reading.bodyLarge.fontSize.value
        assertTrue("body $bodyFactor", bodyFactor in 1.55..1.7)
        assertTrue("bodyLarge $largeFactor", largeFactor in 1.55..1.7)
    }

    @Test
    fun readingTypography_bodyIsReadableSize() {
        val reading = DefaultReadingTypography
        assertTrue(reading.body.fontSize.value >= 16f)
        assertTrue(reading.body.fontSize.value <= 20f)
        // Máximo de línea de lectura acotado para anchos cómodos.
        assertEquals(640f, ReadingMetrics.MaxLineWidth.value, 0.001f)
    }

    @Test
    fun themeMode_hasExactlyThreeModes() {
        assertEquals(listOf("SYSTEM", "LIGHT", "DARK"), ThemeMode.entries.map { it.name })
    }

    // ── Remediación T13 (round 1): R-T13-01..04 ──

    @Test
    fun rootSurfaceAndWindow_followActiveThemeBackground() {
        // R-T13-01: ExplainerApp pinta una superficie raíz edge-to-edge con
        // background/onBackground del tema ACTIVO y la ventana del sistema
        // sigue al tema (SideEffect de Theme.kt); lector, biblioteca, setup y
        // paneles de estado (transparentes) nunca quedan sobre la ventana de
        // arranque fijada en #0d1117. El par de lectura sobre la raíz es
        // >= 7:1 en ambos temas; el fallo era 1.16:1 (texto #241F17 sobre la
        // ventana tinta en LIGHT).
        val lightScheme = light.toMaterialColorScheme(dark = false)
        val darkScheme = dark.toMaterialColorScheme(dark = true)
        assertEquals(light.background, lightScheme.background)
        assertEquals(light.onBackground, lightScheme.onBackground)
        assertEquals(dark.background, darkScheme.background)
        assertEquals(dark.onBackground, darkScheme.onBackground)
        assertTrue("light root text/background", contrastRatio(light.onBackground, light.background) >= 7)
        assertTrue("dark root text/background", contrastRatio(dark.onBackground, dark.background) >= 7)
        // La raíz sigue al tema activo: no es la ventana fija de arranque.
        assertNotEquals("root sigue al tema, no a la ventana fija", light.background, dark.background)
    }

    @Test
    fun offlineLabel_usesOnContainerColor_meetingAA() {
        // R-T13-02: el label de StatusIndicator usa el rol on-container de su
        // tono (OFFLINE -> onOfflineContainer), nunca onSurfaceVariant forzado
        // (fallaba 4.25:1 en LIGHT sobre offlineContainer). Verificado sobre
        // los pares que la UI realmente compone: el tono OFFLINE sobre el
        // contenedor offline del banner y todos los tonos sobre la superficie
        // de las filas de biblioteca, en ambos temas.
        for (tone in StatusTone.entries) {
            val lightLabel = tone.labelColor(light)
            val darkLabel = tone.labelColor(dark)
            assertTrue(
                "light $tone label/surface",
                contrastRatio(lightLabel, light.surface) >= 4.5,
            )
            assertTrue(
                "dark $tone label/surface",
                contrastRatio(darkLabel, dark.surface) >= 4.5,
            )
        }
        // El rol OFFLINE es el on-container de su contenedor (no el secundario
        // genérico que fallaba en LIGHT) y pasa AA sobre el banner.
        assertEquals(light.status.onOfflineContainer, StatusTone.OFFLINE.labelColor(light))
        assertEquals(dark.status.onOfflineContainer, StatusTone.OFFLINE.labelColor(dark))
        assertTrue(
            "light OFFLINE label/offlineContainer",
            contrastRatio(StatusTone.OFFLINE.labelColor(light), light.status.offlineContainer) >= 4.5,
        )
        assertTrue(
            "dark OFFLINE label/offlineContainer",
            contrastRatio(StatusTone.OFFLINE.labelColor(dark), dark.status.offlineContainer) >= 4.5,
        )
    }

    @Test
    fun bannerActions_meetAAOnRealContainers() {
        // R-T13-03: el TextButton de cierre (texto primary por defecto de M3)
        // vive sobre surfaceContainerHighest (MessageBanner de biblioteca) y
        // sobre offlineContainer (OfflineBanner con onDismiss); en LIGHT el
        // oro anterior fallaba (4.39:1) y ahora pasa AA sobre ambos
        // contenedores. También el texto del mensaje sobre el mismo contenedor.
        assertTrue(
            "light primary/surfaceContainerHighest",
            contrastRatio(light.primary, light.surfaceContainerHighest) >= 4.5,
        )
        assertTrue(
            "dark primary/surfaceContainerHighest",
            contrastRatio(dark.primary, dark.surfaceContainerHighest) >= 4.5,
        )
        assertTrue(
            "light primary/offlineContainer",
            contrastRatio(light.primary, light.status.offlineContainer) >= 4.5,
        )
        assertTrue(
            "dark primary/offlineContainer",
            contrastRatio(dark.primary, dark.status.offlineContainer) >= 4.5,
        )
        assertTrue(
            "light onSurface/surfaceContainerHighest",
            contrastRatio(light.onSurface, light.surfaceContainerHighest) >= 4.5,
        )
        assertTrue(
            "dark onSurface/surfaceContainerHighest",
            contrastRatio(dark.onSurface, dark.surfaceContainerHighest) >= 4.5,
        )
    }

    @Test
    fun containerlessBranch_bootstrapsDarkNotSystem() {
        // R-T13-04: la rama sin container (setup error) arranca SIEMPRE en
        // DARK: ExplainerApp la compone con DefaultThemeMode y el default del
        // parámetro de ExplainerTheme es ese mismo DARK. SYSTEM sigue
        // existiendo como opción persistida (ThemePreferences/SettingsScreen),
        // no como default de arranque.
        assertEquals(ThemeMode.DARK, DefaultThemeMode)
        assertNotEquals(ThemeMode.SYSTEM, DefaultThemeMode)
    }

    // ── Helpers WCAG ──

    private fun relativeLuminance(c: Color): Double {
        fun channel(v: Float): Double {
            val s = v.toDouble()
            return if (s <= 0.04045) s / 12.92 else Math.pow((s + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * channel(c.red) + 0.7152 * channel(c.green) + 0.0722 * channel(c.blue)
    }

    private fun contrastRatio(a: Color, b: Color): Double {
        val la = relativeLuminance(a)
        val lb = relativeLuminance(b)
        val lighter = maxOf(la, lb)
        val darker = minOf(la, lb)
        return (lighter + 0.05) / (darker + 0.05)
    }
}

package com.explainer.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.explainer.app.R

/**
 * Tipografías locales únicas (sin Google Fonts en runtime): Source Serif 4 para
 * lectura/display y DM Sans para UI. Solo se empaquetan los pesos usados
 * (regular 400, semibold 600 e itálica 400 en serif; regular/medium/semibold en
 * sans) con sus licencias OFL en `android/OFL-*.txt`.
 *
 * Origen: `frontend/index.html` L20-24 (la web usa cinco familias; Android
 * reduce a dos por APK y licencia, según global-constraints.md).
 */
object ExplainerFonts {
    /** Source Serif 4: contenido y display. */
    val SourceSerif4 = FontFamily(
        Font(R.font.source_serif_4_regular, FontWeight.Normal),
        Font(R.font.source_serif_4_semibold, FontWeight.SemiBold),
        Font(R.font.source_serif_4_italic, FontWeight.Normal, FontStyle.Italic),
    )

    /** DM Sans: controles y UI. */
    val DmSans = FontFamily(
        Font(R.font.dm_sans_regular, FontWeight.Normal),
        Font(R.font.dm_sans_medium, FontWeight.Medium),
        Font(R.font.dm_sans_semibold, FontWeight.SemiBold),
    )
}

/**
 * Tipografía Material 3 de la app: serif para jerarquía/display, sans para
 * controles. Las alturas de línea mantienen legibilidad a escala de fuente 200 %.
 */
val ExplainerTypography = Typography(
    displaySmall = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 36.sp,
        lineHeight = 44.sp,
    ),
    headlineLarge = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 32.sp,
        lineHeight = 40.sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 28.sp,
        lineHeight = 36.sp,
    ),
    headlineSmall = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 24.sp,
        lineHeight = 32.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 22.sp,
        lineHeight = 28.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 24.sp,
    ),
    titleSmall = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 20.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
    ),
    bodySmall = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 16.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 20.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 16.sp,
    ),
)

/**
 * Tipografía de lectura larga (Source Serif 4), pensada para el lector de
 * paridad: tamaño de lectura cómodo y factor de línea 1.55–1.7
 * (integration-content-rendering.md, UI Contract). El texto de lectura se
 * limita a [ReadingMetrics.MaxLineWidth] para anchos de línea legibles.
 */
data class ReadingTypography(
    /** Cuerpo de lectura principal. */
    val body: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.Normal,
        fontSize = 17.sp,
        lineHeight = 28.sp, // 1.65
    ),
    /** Párrafo destacado / entrada de sección. */
    val bodyLarge: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.Normal,
        fontSize = 19.sp,
        lineHeight = 31.sp, // 1.63
    ),
    /** Encabezado de nivel 1 dentro del contenido. */
    val heading1: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 28.sp,
        lineHeight = 36.sp,
    ),
    /** Encabezado de nivel 2 dentro del contenido. */
    val heading2: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 22.sp,
        lineHeight = 30.sp,
    ),
    /** Encabezado de nivel 3 dentro del contenido. */
    val heading3: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 19.sp,
        lineHeight = 28.sp,
    ),
    /** Cita o destacado en itálica. */
    val quote: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.SourceSerif4,
        fontWeight = FontWeight.Normal,
        fontStyle = FontStyle.Italic,
        fontSize = 17.sp,
        lineHeight = 28.sp,
    ),
    /** Código/fragmentos técnicos (DM Sans; solo dos familias en el APK). */
    val code: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Normal,
        fontSize = 13.sp,
        lineHeight = 20.sp,
    ),
    /** Notas al pie y metadatos de lectura. */
    val caption: TextStyle = TextStyle(
        fontFamily = ExplainerFonts.DmSans,
        fontWeight = FontWeight.Normal,
        fontSize = 13.sp,
        lineHeight = 20.sp,
    ),
)

/** Instancia por defecto de la tipografía de lectura. */
val DefaultReadingTypography = ReadingTypography()

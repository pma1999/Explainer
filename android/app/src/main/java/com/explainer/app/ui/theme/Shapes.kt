package com.explainer.app.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp

/**
 * Radios heredados de la identidad web (style.css L35-38: 6/10/16/24px) y
 * elevaciones restringidas a una escala corta: chrome mínimo, superficies
 * calmadas; las cards solo existen cuando todo el bloque es una acción.
 */
object ExplainerShapes {
    val Small = RoundedCornerShape(6.dp)
    val Medium = RoundedCornerShape(10.dp)
    val Large = RoundedCornerShape(16.dp)
    val ExtraLarge = RoundedCornerShape(24.dp)

    /** Shapes Material 3 del tema (extraSmall/extraLarge para componentes M3). */
    fun material(): Shapes = Shapes(
        extraSmall = Small,
        small = Small,
        medium = Medium,
        large = Large,
        extraLarge = ExtraLarge,
    )
}

/** Elevación restringida: 0/1/4/8dp. Nada flota sin necesidad. */
object ElevationTokens {
    val Level0 = 0.dp
    val Level1 = 1.dp
    val Level2 = 4.dp
    val Level3 = 8.dp
}

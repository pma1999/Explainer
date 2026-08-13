package com.explainer.app.ui.reader

import androidx.compose.ui.unit.dp
import com.explainer.app.ui.content.MissingStateDefaults
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Targets táctiles declarados por el reader (T10/T14, WCAG 2.5.8 / Material:
 * >= 48dp): selector de partes, barra de lectura (anterior/siguiente y
 * estado leído), pane de partes (T05 lo declara en su propio test) y los
 * controles de generación on-demand (reintentar/volver al contenido y CTA
 * de generación de los tabs esquema/repaso).
 */
class ReaderTargetsTest {

    @Test
    fun readerTargets_areAtLeast48dp() {
        assertTrue("barra de partes $PartSelectorBarDefaults.MinimumTargetSize < 48dp", PartSelectorBarDefaults.MinimumTargetSize >= 48.dp)
        assertTrue("barra de lectura $ReadingToolbarDefaults.MinimumTargetSize < 48dp", ReadingToolbarDefaults.MinimumTargetSize >= 48.dp)
    }

    @Test
    fun generationTargets_areAtLeast48dp() {
        assertTrue(
            "reintentar/volver $GenerationDefaults.MinimumActionHeight < 48dp",
            GenerationDefaults.MinimumActionHeight >= 48.dp,
        )
        assertTrue(
            "CTA de generacion ${MissingStateDefaults.MinimumActionHeight} < 48dp",
            MissingStateDefaults.MinimumActionHeight >= 48.dp,
        )
    }
}

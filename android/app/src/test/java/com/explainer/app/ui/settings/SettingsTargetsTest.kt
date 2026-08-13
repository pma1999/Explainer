package com.explainer.app.ui.settings

import androidx.compose.ui.unit.dp
import com.explainer.app.ui.theme.ThemeMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Targets táctiles y cobertura de labels de Ajustes (T11): filas/botones
 * >= 48dp y mapeo completo de tema/confirmaciones (nunca copy sin label).
 */
class SettingsTargetsTest {

    @Test
    fun `settings declara targets de al menos 48dp`() {
        assertTrue(
            "target ${SettingsScreenDefaults.MinimumTargetSize} < 48dp",
            SettingsScreenDefaults.MinimumTargetSize >= 48.dp,
        )
    }

    @Test
    fun `labels de tema cubren los tres modos`() {
        assertEquals(
            listOf("SYSTEM", "LIGHT", "DARK"),
            ThemeMode.entries.map { it.name },
        )
        ThemeMode.entries.forEach { mode ->
            assertTrue(SettingsLabels.themeModeLabelRes(mode) != 0)
        }
    }

    @Test
    fun `labels de confirmacion cubren las tres acciones`() {
        val confirmations = listOf<SettingsConfirmation>(
            SettingsConfirmation.SignOut,
            SettingsConfirmation.DeleteAll,
            SettingsConfirmation.DeleteProject(com.explainer.app.core.model.ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")),
        )
        confirmations.forEach { confirmation ->
            // R-T11-07: el título ya no recibe un parámetro muerto; el nombre
            // viaja como argumento de formato vía `confirmationTitle`.
            assertTrue(SettingsLabels.confirmationTitleRes(confirmation) != 0)
            assertTrue(SettingsLabels.confirmationMessageRes(confirmation) != 0)
            assertTrue(SettingsLabels.confirmationLabelRes(confirmation) != 0)
        }
    }
}

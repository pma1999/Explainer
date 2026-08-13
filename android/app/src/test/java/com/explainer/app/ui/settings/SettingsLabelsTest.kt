package com.explainer.app.ui.settings

import com.explainer.app.R
import com.explainer.app.ui.library.TEST_PROJECT_ID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * R-T11-07 (MEDIUM): la confirmación de borrado de proyecto usa el overload
 * formateado de `stringResource` (el recurso exige `%1$s`). El contrato del
 * título se modela puro ([SettingsLabels.confirmationTitle]): el nombre del
 * proyecto llega como argumento del formato y se renderiza en el diálogo.
 */
class SettingsLabelsTest {

    @Test
    fun `titulo de borrado de proyecto formatea el nombre del proyecto`() {
        val title = SettingsLabels.confirmationTitle(
            SettingsConfirmation.DeleteProject(TEST_PROJECT_ID),
            "Proyecto de prueba",
        )

        assertEquals(R.string.settings_delete_project_confirm_title, title.res)
        assertEquals("Proyecto de prueba", title.arg)
    }

    @Test
    fun `borrado de proyecto sin fila conocida no pasa argumento`() {
        val title = SettingsLabels.confirmationTitle(
            SettingsConfirmation.DeleteProject(TEST_PROJECT_ID),
            null,
        )

        assertEquals(R.string.settings_delete_project_confirm_title, title.res)
        assertNull(title.arg)
    }

    @Test
    fun `signOut y deleteAll no formatean nombre`() {
        val signOut = SettingsLabels.confirmationTitle(SettingsConfirmation.SignOut, "cualquiera")
        assertEquals(R.string.settings_sign_out_confirm_title, signOut.res)
        assertNull(signOut.arg)

        val deleteAll = SettingsLabels.confirmationTitle(SettingsConfirmation.DeleteAll, "cualquiera")
        assertEquals(R.string.settings_delete_all_confirm_title, deleteAll.res)
        assertNull(deleteAll.arg)
    }

    @Test
    fun `confirmationTitleRes cubre las tres confirmaciones sin parametro muerto`() {
        assertEquals(
            R.string.settings_sign_out_confirm_title,
            SettingsLabels.confirmationTitleRes(SettingsConfirmation.SignOut),
        )
        assertEquals(
            R.string.settings_delete_all_confirm_title,
            SettingsLabels.confirmationTitleRes(SettingsConfirmation.DeleteAll),
        )
        assertEquals(
            R.string.settings_delete_project_confirm_title,
            SettingsLabels.confirmationTitleRes(SettingsConfirmation.DeleteProject(TEST_PROJECT_ID)),
        )
    }

    @Test
    fun `el recurso de borrado de proyecto declara el placeholder del nombre`() {
        // Contrato con strings_settings.xml: el título de borrado exige %1$s.
        val xml = java.io.File("src/main/res/values/strings_settings.xml").readText()
        val entry = xml.lineSequence()
            .first { it.contains("settings_delete_project_confirm_title") }
        assertTrue("el recurso debe contener %1\$s: $entry", entry.contains("%1\$s"))
    }
}

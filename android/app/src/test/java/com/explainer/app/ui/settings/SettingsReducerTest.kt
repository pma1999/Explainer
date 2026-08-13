package com.explainer.app.ui.settings

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.auth.SessionState
import com.explainer.app.ui.library.TEST_OWNER
import com.explainer.app.ui.library.TEST_PROJECT_ID
import com.explainer.app.ui.library.TEST_PROJECT_ID_2
import com.explainer.app.ui.library.testItem
import com.explainer.app.ui.theme.ThemeMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Reducer de Ajustes (T11): tema persistido en el estado, identidad local,
 * almacenamiento (bytes lógicos por proyecto offline, ordenado) y
 * confirmaciones destructivas exclusivas (sin doble sheet ni loops).
 */
class SettingsReducerTest {

    private fun model(confirmation: SettingsConfirmation? = null) = SettingsModel(
        ownerId = TEST_OWNER,
        session = SessionState.Authenticated(TEST_OWNER, "a@b.com"),
        receivedFirst = true,
        confirmation = confirmation,
    )

    @Test
    fun `loading hasta la primera emision de catalogo o sesion`() {
        val loading = SettingsModel(ownerId = TEST_OWNER)
        assertTrue(SettingsReducer.toUiState(loading) is SettingsUiState.Loading)

        val sessionOnly = SettingsModel(ownerId = TEST_OWNER, session = SessionState.Authenticated(TEST_OWNER, "a@b.com"))
        assertTrue(SettingsReducer.toUiState(sessionOnly) is SettingsUiState.Loading)

        val itemsOnly = SettingsModel(ownerId = TEST_OWNER, receivedFirst = true)
        assertTrue(SettingsReducer.toUiState(itemsOnly) is SettingsUiState.Loading)
    }

    @Test
    fun `sesion terminada o de otro owner degrada a signed out`() {
        val signedOut = SettingsReducer.toUiState(
            SettingsModel(ownerId = TEST_OWNER, session = SessionState.SignedOut, receivedFirst = true),
        )
        assertEquals(SettingsUiState.SignedOut, signedOut)

        val otherOwner = SettingsReducer.toUiState(
            SettingsModel(
                ownerId = TEST_OWNER,
                session = SessionState.Authenticated("1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b", "b@c.com"),
                receivedFirst = true,
            ),
        )
        assertEquals(SettingsUiState.SignedOut, otherOwner)
    }

    @Test
    fun `contenido muestra tema email y filas de almacenamiento con bytes`() {
        val items = listOf(
            testItem(projectId = TEST_PROJECT_ID, name = "Grande", snapshotBytes = 4096L),
            testItem(projectId = TEST_PROJECT_ID_2, name = "Chico", snapshotBytes = 512L),
            testItem(name = "Sin descarga", snapshotBytes = 0L),
        )
        val state = SettingsReducer.toUiState(
            model().copy(
                themeMode = ThemeMode.DARK,
                ownerEmail = "a@b.com",
                items = items,
            ),
        ) as SettingsUiState.Content

        assertEquals(ThemeMode.DARK, state.themeMode)
        assertEquals("a@b.com", state.ownerEmail)
        assertEquals(
            listOf("Grande", "Chico"),
            state.storageRows.map { it.name },
        )
        assertEquals(4096L + 512L, state.totalBytes)
        // Ordenado por bytes desc.
        assertEquals(4096L, state.storageRows.first().bytes)
    }

    @Test
    fun `offline disponible del mismo owner muestra ajustes`() {
        val state = SettingsReducer.toUiState(
            SettingsModel(
                ownerId = TEST_OWNER,
                session = SessionState.OfflineAvailable(TEST_OWNER, "a@b.com"),
                receivedFirst = true,
            ),
        )
        assertTrue(state is SettingsUiState.Content)
    }

    @Test
    fun `confirmaciones destructivas son exclusivas`() {
        val withSignOut = SettingsReducer.onSignOutRequested(model())
        assertEquals(SettingsConfirmation.SignOut, withSignOut.confirmation)

        // Una confirmación abierta ignora otra petición.
        assertEquals(
            SettingsConfirmation.SignOut,
            SettingsReducer.onDeleteAllRequested(withSignOut).confirmation,
        )
        assertEquals(
            SettingsConfirmation.SignOut,
            SettingsReducer.onDeleteRequested(withSignOut, TEST_PROJECT_ID).confirmation,
        )

        val deleteAll = SettingsReducer.onDeleteAllRequested(model())
        assertEquals(SettingsConfirmation.DeleteAll, deleteAll.confirmation)
        assertEquals(
            SettingsConfirmation.DeleteAll,
            SettingsReducer.onSignOutRequested(deleteAll).confirmation,
        )

        val deleteOne = SettingsReducer.onDeleteRequested(model(), TEST_PROJECT_ID)
        assertEquals(SettingsConfirmation.DeleteProject(TEST_PROJECT_ID), deleteOne.confirmation)
    }

    @Test
    fun `dismiss y confirmed cierran la confirmacion sin ejecutar`() {
        val with = SettingsReducer.onSignOutRequested(model())
        assertNull(SettingsReducer.onDismiss(with).confirmation)
        assertNull(SettingsReducer.onConfirmed(with).confirmation)
    }

    @Test
    fun `sesion terminada limpia las filas visibles`() {
        val items = listOf(testItem(snapshotBytes = 1024L))
        val model = SettingsReducer.onItems(model(), items)
        val ended = SettingsReducer.onSession(model, SessionState.SignedOut)
        assertEquals(SettingsUiState.SignedOut, SettingsReducer.toUiState(ended))
        assertTrue(ended.items.isEmpty())
    }
}

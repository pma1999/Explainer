package com.explainer.app.ui.settings

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.emptyPreferences
import com.explainer.app.data.auth.SessionState
import com.explainer.app.data.preferences.LocalAccessPreferences
import com.explainer.app.data.preferences.ThemePreferences
import com.explainer.app.ui.auth.FakeSessionGateway
import com.explainer.app.ui.library.FakeCatalog
import com.explainer.app.ui.library.FakeDownloadCoordinator
import com.explainer.app.ui.library.TEST_OWNER
import com.explainer.app.ui.library.TEST_PROJECT_ID
import com.explainer.app.ui.library.testItem
import com.explainer.app.ui.theme.ThemeMode
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private fun testScope() = CoroutineScope(Dispatchers.Unconfined)

/**
 * ViewModel de Ajustes (T11): tema persistido vía DataStore (flujo reactivo,
 * sin recrear stores), identidad local, borrados con confirmación y logout
 * explícito orquestado por el container. Scope Unconfined para propagación
 * síncrona en JVM; el DataStore es un fake en memoria sin I/O.
 */
class SettingsViewModelTest {

    private class Harness(
        val gateway: FakeSessionGateway = FakeSessionGateway(SessionState.Authenticated(TEST_OWNER, "a@b.com")),
        val catalog: FakeCatalog = FakeCatalog(),
        val downloads: FakeDownloadCoordinator = FakeDownloadCoordinator(),
        val store: FakePreferencesStore = FakePreferencesStore(),
        val signOutCalls: MutableList<String> = mutableListOf(),
        val deleteAllCalls: MutableList<String> = mutableListOf(),
    ) {
        val theme = ThemePreferences(store)
        val localAccess = LocalAccessPreferences(store)

        fun vm() = SettingsViewModel(
            scope = testScope(),
            ownerId = TEST_OWNER,
            gateway = gateway,
            catalog = catalog,
            downloads = downloads,
            themePreferences = theme,
            localAccess = localAccess,
            onExplicitSignOut = {
                signOutCalls.add(TEST_OWNER)
                gateway.signOut()
            },
            onDeleteAllLocal = { deleteAllCalls.add(TEST_OWNER) },
        )
    }

    private fun collectEvents(vm: SettingsViewModel): MutableList<SettingsEvent> {
        val emitted = mutableListOf<SettingsEvent>()
        testScope().launch { vm.events.collect { emitted.add(it) } }
        return emitted
    }

    @Test
    fun `set theme mode persiste y el flujo lo refleja`() {
        val harness = Harness()
        val vm = harness.vm()

        vm.onAction(SettingsAction.SetThemeMode(ThemeMode.DARK))

        val state = vm.uiState.value as SettingsUiState.Content
        assertEquals(ThemeMode.DARK, state.themeMode)
        assertEquals("DARK", harness.store.updatedValue(ThemePreferences.KEY_THEME_MODE.name))
    }

    @Test
    fun `login exitoso previo muestra el email local no secreto`() {
        val harness = Harness()
        runBlockingSync { harness.localAccess.unlockAfterLogin(TEST_OWNER, "a@b.com") }
        val vm = harness.vm()

        val state = vm.uiState.value as SettingsUiState.Content
        assertEquals("a@b.com", state.ownerEmail)
    }

    @Test
    fun `sign out requiere confirmacion y ejecuta una sola vez`() {
        val harness = Harness()
        val vm = harness.vm()
        val emitted = collectEvents(vm)

        vm.onAction(SettingsAction.ConfirmSignOut)
        assertTrue(harness.signOutCalls.isEmpty())

        vm.onAction(SettingsAction.RequestSignOut)
        vm.onAction(SettingsAction.RequestSignOut) // doble petición: una confirmación
        vm.onAction(SettingsAction.ConfirmSignOut)

        assertEquals(1, harness.signOutCalls.size)
        assertEquals(listOf(SettingsEvent.SignedOut), emitted)
        assertEquals(1, harness.gateway.signOutCalls)
    }

    @Test
    fun `dismiss cancela la confirmacion sin ejecutar`() {
        val harness = Harness()
        val vm = harness.vm()

        vm.onAction(SettingsAction.RequestSignOut)
        vm.onAction(SettingsAction.DismissConfirm)
        vm.onAction(SettingsAction.ConfirmSignOut)

        assertTrue(harness.signOutCalls.isEmpty())
        assertNull((vm.uiState.value as SettingsUiState.Content).confirmation)
    }

    @Test
    fun `borrar un proyecto requiere confirmacion y borra solo local`() {
        val harness = Harness()
        harness.catalog.emit(listOf(testItem(snapshotBytes = 1024L)))
        val vm = harness.vm()
        val emitted = collectEvents(vm)

        vm.onAction(SettingsAction.ConfirmDeleteProject(TEST_PROJECT_ID))
        assertTrue(harness.downloads.deleteCalls.isEmpty())

        vm.onAction(SettingsAction.RequestDeleteProject(TEST_PROJECT_ID))
        vm.onAction(SettingsAction.ConfirmDeleteProject(TEST_PROJECT_ID))

        assertEquals(listOf(TEST_PROJECT_ID.value), harness.downloads.deleteCalls)
        assertEquals(listOf(SettingsEvent.DeleteConfirmed), emitted)
    }

    @Test
    fun `borrar todo requiere confirmacion y delega en el container`() {
        val harness = Harness()
        val vm = harness.vm()
        val emitted = collectEvents(vm)

        vm.onAction(SettingsAction.ConfirmDeleteAll)
        assertTrue(harness.deleteAllCalls.isEmpty())

        vm.onAction(SettingsAction.RequestDeleteAll)
        vm.onAction(SettingsAction.RequestDeleteAll)
        vm.onAction(SettingsAction.ConfirmDeleteAll)

        assertEquals(1, harness.deleteAllCalls.size)
        assertEquals(listOf(SettingsEvent.DeleteConfirmed), emitted)
    }

    @Test
    fun `sesion terminada degrada a signed out`() {
        val harness = Harness()
        val vm = harness.vm()

        harness.gateway.stateFlow.value = SessionState.SignedOut

        assertEquals(SettingsUiState.SignedOut, vm.uiState.value)
    }

    @Test
    fun `offline disponible muestra ajustes con filas locales`() {
        val harness = Harness(
            gateway = FakeSessionGateway(SessionState.OfflineAvailable(TEST_OWNER, "a@b.com")),
        )
        harness.catalog.emit(listOf(testItem(snapshotBytes = 2048L)))
        val vm = harness.vm()

        val state = vm.uiState.value as SettingsUiState.Content
        assertEquals(2048L, state.totalBytes)
    }

    private fun runBlockingSync(block: suspend () -> Unit) {
        runBlocking { block() }
    }
}

/** DataStore<Preferences> en memoria: sin I/O y síncrono para tests JVM. */
class FakePreferencesStore : DataStore<Preferences> {
    private val flow = MutableStateFlow(emptyPreferences())

    override val data: Flow<Preferences> = flow

    override suspend fun updateData(transform: suspend (t: Preferences) -> Preferences): Preferences {
        val updated = transform(flow.value)
        flow.value = updated
        return updated
    }

    fun updatedValue(keyName: String): String? =
        flow.value[androidx.datastore.preferences.core.stringPreferencesKey(keyName)]
}

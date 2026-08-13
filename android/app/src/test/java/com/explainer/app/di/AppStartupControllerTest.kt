package com.explainer.app.di

import com.explainer.app.core.config.AppConfig
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.data.auth.SessionState
import com.explainer.app.data.preferences.LocalAccessPreferences
import com.explainer.app.data.preferences.ThemePreferences
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.download.DownloadCoordinator
import com.explainer.app.feature.generation.GenerationOutcome
import com.explainer.app.feature.generation.PartGenerationRepository
import com.explainer.app.feature.progress.ReadingProgressRepository
import com.explainer.app.ui.auth.FakeSessionGateway
import com.explainer.app.ui.library.FakeCatalog
import com.explainer.app.ui.library.FakeDownloadCoordinator
import com.explainer.app.ui.library.TEST_OWNER
import com.explainer.app.ui.rootstate.ConfigErrorField
import com.explainer.app.ui.rootstate.RootAppState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * R-T11-06 (MEDIUM): el resultado del retry de configuración es estado
 * COMPOSE-OBSERVABLE ([AppStartupController.state]): pulsar "Reintentar"
 * reconstruye el container y la pantalla de setup desaparece; un retry
 * posterior cierra el container anterior. ConfigError → retry queda cubierto.
 */
class AppStartupControllerTest {

    private class FakeContainer : AppContainer {
        var closeCalls = 0
        override val config: AppConfig = AppConfig("https://supabase.example", "key", "https://api.example")
        override val session: SessionGateway = FakeSessionGateway(SessionState.SignedOut)
        override val catalog: ProjectCatalogRepository = FakeCatalog()
        override val progress: ReadingProgressRepository = FakeProgressRepository()
        override val downloads: DownloadCoordinator = FakeDownloadCoordinator()
        override val partGeneration: PartGenerationRepository = FakePartGenerationRepository()
        override val themePreferences: ThemePreferences = ThemePreferences(FakePreferencesStore())
        override val localAccess: LocalAccessPreferences = LocalAccessPreferences(FakePreferencesStore())
        override val rootState: MutableStateFlow<RootAppState> = MutableStateFlow(RootAppState.SignedOut)
        override val appScope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        override val sessionOwner: () -> String? = { null }
        override val sessionOwnerFlow: Flow<String?> = emptyFlow()
        override fun refreshCatalogOnResume() = Unit
        override suspend fun explicitSignOut() = Unit
        override suspend fun deleteAllLocal(ownerId: String) = Unit
        override fun close() {
            closeCalls++
        }
    }

    private class FakePartGenerationRepository : PartGenerationRepository {
        override suspend fun generateDiagram(
            ownerId: String,
            projectId: com.explainer.app.core.model.ProjectId,
            partId: Int,
            regenerate: Boolean,
        ): GenerationOutcome = GenerationOutcome.Success

        override suspend fun generateReview(
            ownerId: String,
            projectId: com.explainer.app.core.model.ProjectId,
            partId: Int,
            regenerate: Boolean,
        ): GenerationOutcome = GenerationOutcome.Success
    }

    private class FakeProgressRepository : ReadingProgressRepository {
        override fun observe(ownerId: String, projectId: com.explainer.app.core.model.ProjectId): Flow<com.explainer.app.core.model.ReadingProgress> =
            MutableStateFlow(com.explainer.app.core.model.ReadingProgress())
        override suspend fun setSectionCompleted(ownerId: String, projectId: com.explainer.app.core.model.ProjectId, partId: Int, completed: Boolean) = Unit
        override suspend fun recordSubsection(ownerId: String, projectId: com.explainer.app.core.model.ProjectId, event: com.explainer.app.feature.progress.SubsectionProgressEvent) = Unit
        override suspend fun requestSync(ownerId: String) = Unit
    }

    @Test
    fun `config invalida produce Broken sin crear container`() {
        var config = Triple("http://no-https", "key", "https://api.example")
        var created = 0

        val controller = AppStartupController(
            readConfig = { config },
            createContainer = { created++; FakeContainer() },
        )

        assertEquals(AppStartup.Broken(RootAppState.ConfigError(ConfigErrorField.SUPABASE_URL)), controller.state.value)
        assertEquals(0, created)
    }

    @Test
    fun `config valida produce Ready y crea el container una sola vez`() {
        var created = 0
        val controller = AppStartupController(
            readConfig = { Triple("https://supabase.example", "key", "https://api.example") },
            createContainer = { created++; FakeContainer() },
        )

        assertTrue(controller.state.value is AppStartup.Ready)
        assertEquals(1, created)
    }

    @Test
    fun `retry tras ConfigError con config corregida pasa a Ready`() {
        var config = Triple("https://supabase.example", "", "https://api.example")
        var created = 0
        val controller = AppStartupController(
            readConfig = { config },
            createContainer = { created++; FakeContainer() },
        )
        assertEquals(AppStartup.Broken(RootAppState.ConfigError(ConfigErrorField.ANON_KEY)), controller.state.value)
        assertEquals(0, created)

        config = Triple("https://supabase.example", "key", "https://api.example")
        controller.retry()

        assertTrue(controller.state.value is AppStartup.Ready)
        assertEquals(1, created)
    }

    @Test
    fun `retry tras Ready cierra el container anterior y crea uno nuevo`() {
        var created = 0
        val controller = AppStartupController(
            readConfig = { Triple("https://supabase.example", "key", "https://api.example") },
            createContainer = {
                created++
                FakeContainer()
            },
        )
        val first = (controller.state.value as AppStartup.Ready).container as FakeContainer

        controller.retry()

        assertEquals(2, created)
        assertEquals("el container anterior se cierra al reintentar", 1, first.closeCalls)
        assertTrue(controller.state.value is AppStartup.Ready)
    }

    @Test
    fun `factory lanza IllegalArgumentException y degrada a Broken API_BASE_URL`() {
        val controller = AppStartupController(
            readConfig = { Triple("https://supabase.example", "key", "https://api.example") },
            createContainer = { throw IllegalArgumentException("config rechazada") },
        )

        assertEquals(AppStartup.Broken(RootAppState.ConfigError(ConfigErrorField.API_BASE_URL)), controller.state.value)
    }

    @Test
    fun `retry mantiene Broken si la config sigue invalida`() {
        var config = Triple("http://no-https", "key", "https://api.example")
        var created = 0
        val controller = AppStartupController(
            readConfig = { config },
            createContainer = { created++; FakeContainer() },
        )

        controller.retry()

        assertEquals(AppStartup.Broken(RootAppState.ConfigError(ConfigErrorField.SUPABASE_URL)), controller.state.value)
        assertEquals(0, created)
    }
}

/** DataStore<Preferences> en memoria (mismo fake que SettingsViewModelTest). */
private class FakePreferencesStore : androidx.datastore.core.DataStore<androidx.datastore.preferences.core.Preferences> {
    private val flow = MutableStateFlow(androidx.datastore.preferences.core.emptyPreferences())
    override val data: Flow<androidx.datastore.preferences.core.Preferences> = flow
    override suspend fun updateData(transform: suspend (t: androidx.datastore.preferences.core.Preferences) -> androidx.datastore.preferences.core.Preferences): androidx.datastore.preferences.core.Preferences {
        val updated = transform(flow.value)
        flow.value = updated
        return updated
    }
}

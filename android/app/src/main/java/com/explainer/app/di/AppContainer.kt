package com.explainer.app.di

import com.explainer.app.core.config.AppConfig
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.data.preferences.LocalAccessPreferences
import com.explainer.app.data.preferences.ThemePreferences
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.download.DownloadCoordinator
import com.explainer.app.feature.generation.PartGenerationRepository
import com.explainer.app.feature.progress.ReadingProgressRepository
import com.explainer.app.ui.rootstate.RootAppState
import java.io.Closeable
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

/**
 * Composition root de la app (T11): una sola instancia por proceso de
 * config, Supabase/Auth, Ktor, Room, snapshot store, repositorios y
 * coordinadores, con ownership explícito ([Closeable]).
 *
 * Los Composables/ViewModels consumen SOLO estos puertos: nunca conocen
 * Ktor, Room, Supabase ni WorkManager. El owner de sesión proviene
 * únicamente de [session] (nunca es un argumento de ruta).
 */
interface AppContainer : Closeable {
    val config: AppConfig

    /** Sesión Supabase observable (T04); `awaitInitialization()` ya ocurrió. */
    val session: SessionGateway

    /** Catálogo owner-scoped (T07). */
    val catalog: ProjectCatalogRepository

    /** Progreso de lectura optimista + sync durable (T07). */
    val progress: ReadingProgressRepository

    /** Coordinador de descargas (T06), owner-scoped y WorkManager-based. */
    val downloads: DownloadCoordinator

    /**
     * Generación on-demand de esquema/repaso (T14): llama al remoto y
     * persiste el resultado en la parte activa del snapshot para consumo
     * offline por el lector.
     */
    val partGeneration: PartGenerationRepository

    /** Preferencia de tema (DataStore único). */
    val themePreferences: ThemePreferences

    /** Flag de acceso local offline (owner UUID/email, nunca tokens). */
    val localAccess: LocalAccessPreferences

    /** Estado raíz (Initializing/ConfigError/SignedOut/Offline/Authenticated). */
    val rootState: StateFlow<RootAppState>

    /** Scope de proceso para trabajo del container (nunca red desde UI). */
    val appScope: CoroutineScope

    /**
     * Owner de sesión actual (Authenticated u OfflineAvailable) o null sin
     * sesión. Los coordinadores lo usan para cortar/recalcular sus
     * suscripciones al cambiar de owner (R-T06-03).
     */
    val sessionOwner: () -> String?

    /**
     * Fuente REACTIVA del owner de sesión (R-T11-05): emite SOLO cambios
     * (deduplicado) de owner/logout. Los coordinadores la consumen en vez de
     * sondear, para cortar/recalcular suscripciones sin polling continuo.
     */
    val sessionOwnerFlow: Flow<String?>

    /**
     * Foreground/resume: refresco no destructivo del catálogo solo con
     * sesión válida (sin polling continuo). No-op en otro estado.
     */
    fun refreshCatalogOnResume()

    /**
     * Logout explícito del usuario: cancela la sync remota del owner,
     * limpia la sesión y el flag de acceso local (NO borra snapshots; el
     * mismo owner los desbloquea al autenticarse de nuevo).
     */
    suspend fun explicitSignOut()

    /**
     * Borra TODO lo local del owner activo (snapshots, índices, colas,
     * temporales) — acción separada del logout. Solo owner de sesión
     * estricto; los datos de otros owners nunca se tocan.
     */
    suspend fun deleteAllLocal(ownerId: String)
}

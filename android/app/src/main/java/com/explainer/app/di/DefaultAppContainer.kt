package com.explainer.app.di

import android.content.Context
import androidx.work.Configuration
import androidx.work.WorkManager
import com.explainer.app.core.config.AppConfig
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.data.auth.SessionState
import com.explainer.app.data.auth.SupabaseSessionGateway
import com.explainer.app.data.local.db.ExplainerDatabase
import com.explainer.app.data.local.snapshot.OfflineSnapshotStore
import com.explainer.app.data.local.snapshot.RoomSnapshotStore
import com.explainer.app.data.local.snapshot.SnapshotMaintenance
import com.explainer.app.data.preferences.LocalAccessPreferences
import com.explainer.app.data.preferences.ThemePreferences
import com.explainer.app.data.preferences.explainerDataStore
import com.explainer.app.data.remote.KtorProjectRemoteDataSource
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.catalog.RoomProjectCatalogRepository
import com.explainer.app.feature.download.DownloadProjectUseCase
import com.explainer.app.feature.download.DownloadStatePersister
import com.explainer.app.feature.download.DownloadWorkRequestFactory
import com.explainer.app.feature.download.TempFileCleaner
import com.explainer.app.feature.download.WorkManagerDownloadCoordinator
import com.explainer.app.feature.download.WorkManagerDownloadScheduler
import com.explainer.app.feature.generation.PartGenerationRepository
import com.explainer.app.feature.generation.RoomPartGenerationRepository
import com.explainer.app.feature.progress.ProgressSyncCoordinator
import com.explainer.app.feature.progress.ProgressThrottle
import com.explainer.app.feature.progress.RoomReadingProgressRepository
import com.explainer.app.feature.progress.WorkManagerProgressSyncScheduler
import com.explainer.app.ui.rootstate.RootAppState
import com.explainer.app.ui.rootstate.RootAppStateReducer
import com.explainer.app.work.DownloadWorkerDeps
import com.explainer.app.work.ExplainerWorkerFactory
import com.explainer.app.work.ProgressWorkerDeps
import com.explainer.app.work.ProgressSyncWorker
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Implementación del composition root (T11): inyección manual, una sola
 * instancia por proceso de Room, DataStore, Supabase/Auth, HttpClient Ktor,
 * WorkManager (configurado aquí con la custom [ExplainerWorkerFactory]) y
 * todos los repositorios/coordinadores.
 *
 * - [create] valida la config pública ANTES de construir nada y configura
 *   WorkManager una sola vez por proceso (flag atómico; el initializer de
 *   AndroidX Startup se elimina en el manifest, así que no hay service
 *   locator global mutable).
 * - Startup: espera `auth.awaitInitialization()` (el gateway la ejecuta en
 *   su propio scope antes de emitir estado) y ejecuta el cleanup seguro de
 *   Room (huérfanos + checkpoint best-effort) fuera del main thread.
 * - Al autenticarse (login, restauración o reconexión) desbloquea el acceso
 *   local del owner y solicita UNA sync de progreso (sin polling).
 * - [close] cierra el HttpClient con el proceso, la sesión, Room y el scope.
 */
class DefaultAppContainer internal constructor(
    override val config: AppConfig,
    override val session: SessionGateway,
    private val remote: KtorProjectRemoteDataSource,
    private val database: ExplainerDatabase,
    private val snapshotStore: OfflineSnapshotStore,
    override val catalog: ProjectCatalogRepository,
    override val progress: com.explainer.app.feature.progress.ReadingProgressRepository,
    override val downloads: com.explainer.app.feature.download.DownloadCoordinator,
    override val partGeneration: PartGenerationRepository,
    override val themePreferences: ThemePreferences,
    override val localAccess: LocalAccessPreferences,
    private val workManager: WorkManager,
    private val deleter: LocalDataDeleter,
    private val ownedSession: SupabaseSessionGateway,
    override val appScope: CoroutineScope,
    private val onSessionOwner: () -> String?,
    private val onSessionOwnerFlow: Flow<String?>,
) : AppContainer {

    override val sessionOwner: () -> String? = onSessionOwner

    override val sessionOwnerFlow: Flow<String?> = onSessionOwnerFlow

    /**
     * Logout explícito con ownership en el scope del container (R-T11-02):
     * la secuencia (cancelar sync remota → lock local → signOut) corre en
     * [appScope] y el lock ocurre ANTES de publicar `SignedOut`, de modo que
     * una cancelación de la UI (que se desmonta al cambiar el estado raíz)
     * nunca deja el owner desbloqueado.
     */
    private val signOutSequence = SignOutSequence(
        scope = appScope,
        currentOwner = sessionOwner,
        cancelRemoteSync = { owner ->
            workManager.cancelUniqueWork(ProgressSyncWorker.uniqueName(owner))
        },
        lockLocalAccess = localAccess::lockOnExplicitSignOut,
        signOut = session::signOut,
    )

    override val rootState: StateFlow<RootAppState> = combine(
        session.state,
        localAccess.unlockedOwnerId,
    ) { sessionState, unlockedOwnerId ->
        RootAppStateReducer.reduce(sessionState, unlockedOwnerId)
    }.stateIn(appScope, SharingStarted.Eagerly, RootAppState.Initializing)

    init {
        // Cleanup seguro de arranque (Room orphans + checkpoint) fuera del
        // main thread; nunca borra generaciones activas ni owners ajenos.
        appScope.launch {
            withContext(Dispatchers.Default) {
                snapshotStore.cleanupOrphans()
            }
        }

        // Login/restauración/reconexión: desbloquea el owner local y pide
        // una sync de progreso (una por transición, sin polling continuo).
        appScope.launch {
            session.state
                .map { it as? SessionState.Authenticated }
                .distinctUntilChanged()
                .collect { authed ->
                    if (authed != null) {
                        localAccess.unlockAfterLogin(authed.ownerId, authed.email)
                        progress.requestSync(authed.ownerId)
                    }
                }
        }
    }

    override fun refreshCatalogOnResume() {
        val owner = (session.state.value as? SessionState.Authenticated)?.ownerId ?: return
        appScope.launch { catalog.refresh(owner) }
    }

    override suspend fun explicitSignOut() {
        signOutSequence.run()
    }

    override suspend fun deleteAllLocal(ownerId: String) {
        deleter.deleteAllLocal(ownerId)
    }

    override fun close() {
        remote.close()
        // R-T11-04: el SupabaseClient real se cierra con teardown suspendido
        // y seguro ANTES de cancelar los recursos del container. `close()` no
        // es suspend (Closeable) y corre en main (onTerminate/retry), así que
        // el cierre se lanza en un scope aislado con NonCancellable (nunca se
        // interrumpe a mitad del cierre del cliente HTTP del SDK).
        CoroutineScope(Dispatchers.Default + NonCancellable).launch {
            ownedSession.closeSupabase()
        }
        database.close()
        appScope.cancel()
    }

    companion object {
        /** WorkManager se configura una sola vez por proceso. */
        private val workManagerConfigured = AtomicBoolean(false)

        /**
         * Construye el container; lanza [IllegalArgumentException] si la
         * configuración pública es inválida (el llamador decide la pantalla
         * de setup). Orden: validar config → deps → factory → WorkManager.
         */
        fun create(context: Context): DefaultAppContainer {
            val config = AppConfig.fromBuildConfig()
            val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

            val database = ExplainerDatabase.create(context)
            val dataStore = context.explainerDataStore
            val themePreferences = ThemePreferences(dataStore)
            val localAccess = LocalAccessPreferences(dataStore)

            val gateway = SupabaseSessionGateway.create(config, appScope)
            val remote = KtorProjectRemoteDataSource(gateway, config.apiBaseUrl)
            val snapshotStore = RoomSnapshotStore.forDatabase(database)
            val tempFileCleaner = TempFileCleaner(tempDirProvider = { context.cacheDir })
            val throttle = ProgressThrottle()

            val sessionOwner: () -> String? = {
                when (val state = gateway.state.value) {
                    is SessionState.Authenticated -> state.ownerId
                    is SessionState.OfflineAvailable -> state.ownerId
                    else -> null
                }
            }
            // Fuente REACTIVA del owner (R-T11-05): el coordinador de
            // descargas la consume en vez de sondear cada 250 ms; emite solo
            // cambios de owner/logout (deduplicado).
            val sessionOwnerFlow: Flow<String?> = gateway.state
                .map { state ->
                    when (state) {
                        is SessionState.Authenticated -> state.ownerId
                        is SessionState.OfflineAvailable -> state.ownerId
                        else -> null
                    }
                }
                .distinctUntilChanged()

            val useCase = DownloadProjectUseCase(
                remote = remote,
                store = snapshotStore,
                downloadDao = database.downloadStateDao(),
                summaryDao = database.projectSummaryDao(),
                tempDirProvider = { context.cacheDir },
                diskFreeBytes = { dir -> dir.usableSpace },
                sessionOwner = sessionOwner,
            )
            val progressCoordinator = ProgressSyncCoordinator(
                remote = remote,
                pendingDao = database.pendingProgressDao(),
                summaryDao = database.projectSummaryDao(),
                snapshotDao = database.snapshotDao(),
                throttle = throttle,
                // RC-01: el motor bloquea ANTES de leer/enviar si el owner de
                // la cola no coincide con el owner de la sesión actual.
                sessionOwner = sessionOwner,
            )

            val factory = ExplainerWorkerFactory(
                downloadDeps = DownloadWorkerDeps(
                    useCase = useCase,
                    persister = DownloadStatePersister(database.downloadStateDao()),
                    // R-T11-01: el worker no ejecuta descargas mientras
                    // awaitInitialization() no termina (reintento durable).
                    authReady = { gateway.state.value !is SessionState.Initializing },
                ),
                progressDeps = ProgressWorkerDeps(
                    coordinator = progressCoordinator,
                    // RC-01: gate de sesión del worker (un trabajo A que
                    // sobreviva a logout/login B no envía filas A con el
                    // bearer de B).
                    sessionOwner = sessionOwner,
                ),
            )
            if (workManagerConfigured.compareAndSet(false, true)) {
                WorkManager.initialize(
                    context,
                    Configuration.Builder().setWorkerFactory(factory).build(),
                )
            }
            val workManager = WorkManager.getInstance(context)

            val downloads = WorkManagerDownloadCoordinator(
                scheduler = WorkManagerDownloadScheduler(workManager),
                requestFactory = DownloadWorkRequestFactory(),
                downloadDao = database.downloadStateDao(),
                store = snapshotStore,
                summaryDao = database.projectSummaryDao(),
                sessionOwner = sessionOwner,
                sessionOwnerFlow = sessionOwnerFlow,
                tempOrphanSweep = { owner, project -> tempFileCleaner.sweepOrphans(owner, project) },
            )
            val progress = RoomReadingProgressRepository(
                pendingDao = database.pendingProgressDao(),
                summaryDao = database.projectSummaryDao(),
                snapshotDao = database.snapshotDao(),
                scheduler = WorkManagerProgressSyncScheduler(workManager),
                throttle = throttle,
            )
            val catalog: ProjectCatalogRepository = RoomProjectCatalogRepository(
                remote = remote,
                projectSummaryDao = database.projectSummaryDao(),
                snapshotDao = database.snapshotDao(),
                downloadStateDao = database.downloadStateDao(),
                pendingProgressDao = database.pendingProgressDao(),
                snapshotStore = snapshotStore,
            )
            val deleter = LocalDataDeleter(
                summaryDao = database.projectSummaryDao(),
                snapshotDao = database.snapshotDao(),
                downloadDao = database.downloadStateDao(),
                deleteProject = downloads::deleteLocal,
                checkpoint = { SnapshotMaintenance.bestEffortWalCheckpoint(database) },
            )
            val partGeneration: PartGenerationRepository = RoomPartGenerationRepository(
                remote = remote,
                store = snapshotStore,
            )

            return DefaultAppContainer(
                config = config,
                session = gateway,
                remote = remote,
                database = database,
                snapshotStore = snapshotStore,
                catalog = catalog,
                progress = progress,
                downloads = downloads,
                partGeneration = partGeneration,
                themePreferences = themePreferences,
                localAccess = localAccess,
                workManager = workManager,
                deleter = deleter,
                ownedSession = gateway,
                appScope = appScope,
                onSessionOwner = sessionOwner,
                onSessionOwnerFlow = sessionOwnerFlow,
            )
        }
    }
}

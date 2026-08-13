package com.explainer.app.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.explainer.app.di.AppContainer
import com.explainer.app.ui.auth.LoginRouteContent
import com.explainer.app.ui.library.LibraryRouteContent
import com.explainer.app.ui.reader.ReaderRouteContent
import com.explainer.app.ui.rootstate.RootAppState
import com.explainer.app.ui.rootstate.RootAppStateReducer
import com.explainer.app.ui.rootstate.RootDestination
import com.explainer.app.ui.settings.SettingsRouteContent

/**
 * Único NavHost de la app (T11): registra las CUATRO rutas del plan
 * ([AppNavGraph]) — Auth → Library → Reader → Settings — con navegación
 * type-safe y back behavior propio de cada ruta.
 *
 * - El owner NUNCA es un argumento de ruta: llega desde el estado raíz
 *   ([AppContainer.rootState]) y particiona todos los puertos.
 * - Auth es el start destination; la transición Auth ↔ Library la decide el
 *   estado raíz ([RootAppStateReducer.navigationDecision]): al autenticarse
 *   (o continuar offline desbloqueado) se navega a Library limpiando Auth de
 *   la pila; en SignedOut se limpia toda la pila hasta Auth. Sin loops: el
 *   efecto solo se dispara cuando el destino CAMBIA.
 * - Reader recibe projectId/partId/tab validados por T10 (ProjectId.parse,
 *   `resolveResumeTarget` y `normalizeTab` degradan sin crash).
 * - Al salir de la app interior (SignedOut), los scopes de composición de
 *   las pantallas se cancelan: sin doble enqueue ni flows colgados.
 */
@Composable
fun ExplainerNavHost(
    container: AppContainer,
) {
    val navController = rememberNavController()
    val root by container.rootState.collectAsStateWithLifecycle()

    // "Continuar sin conexión" es un flag EFÍMERO: solo abre la app mientras
    // la sesión offline siga siendo la misma; cualquier cambio de sesión
    // (logout/login) lo resetea (sin loops de navegación).
    var offlineUnlocked by remember { mutableStateOf(false) }
    LaunchedEffect(root) {
        when (root) {
            is RootAppState.SignedOut, is RootAppState.Authenticated -> offlineUnlocked = false
            else -> Unit
        }
    }

    val destination = RootAppStateReducer.navigationDecision(root, offlineUnlocked)

    // Arranque sin flash: si la sesión ya está lista en la PRIMERA
    // composición (proceso reiniciado con sesión restaurada), el grafo
    // arranca directamente en Library; en cualquier otro caso arranca en
    // Auth ([AppNavGraph.startRoute], start canónico del plan). Las
    // transiciones posteriores las decide el estado raíz abajo.
    val startDestination: Any = when (val r = root) {
        is RootAppState.Authenticated -> LibraryRoute
        is RootAppState.OfflineAvailable -> if (offlineUnlocked) LibraryRoute else AuthRoute
        else -> AppNavGraph.startRoute
    }

    // Transición Auth ↔ app interior por estado raíz (R-T11-03).
    LaunchedEffect(destination) {
        when (destination) {
            RootDestination.Login -> {
                if (navController.currentDestination?.hasRoute(AuthRoute::class) != true) {
                    navController.navigate(AuthRoute) {
                        popUpTo(navController.graph.id) { inclusive = true }
                        launchSingleTop = true
                    }
                }
            }

            is RootDestination.App -> {
                if (navController.currentDestination?.hasRoute(LibraryRoute::class) != true) {
                    navController.navigate(LibraryRoute) {
                        popUpTo<AuthRoute> { inclusive = true }
                        launchSingleTop = true
                    }
                }
            }

            RootDestination.Loading, RootDestination.SetupError -> Unit
        }
    }

    NavHost(
        navController = navController,
        startDestination = startDestination,
    ) {
        composable<AuthRoute> {
            LoginRouteContent(
                gateway = container.session,
                onAuthenticated = { offlineUnlocked = true },
            )
        }

        composable<LibraryRoute> {
            val ownerId = (root as? RootAppState.Authenticated)?.ownerId
                ?: (root as? RootAppState.OfflineAvailable)?.ownerId
            if (ownerId != null) {
                LibraryRouteContent(
                    ownerId = ownerId,
                    gateway = container.session,
                    catalog = container.catalog,
                    downloads = container.downloads,
                    onOpenProject = { projectId ->
                        navController.navigate(ReaderRoute(projectId = projectId.value))
                    },
                    onOpenSettings = { navController.navigate(SettingsRoute) },
                )
            }
        }

        composable<ReaderRoute> { entry ->
            val route = entry.toRoute<ReaderRoute>()
            val ownerId = (root as? RootAppState.Authenticated)?.ownerId
                ?: (root as? RootAppState.OfflineAvailable)?.ownerId
            if (ownerId != null) {
                ReaderRouteContent(
                    ownerId = ownerId,
                    catalog = container.catalog,
                    progress = container.progress,
                    generation = container.partGeneration,
                    projectId = route.projectId,
                    initialPartId = route.partId,
                    initialTab = route.tab,
                    onBack = { navController.popBackStack() },
                )
            }
        }

        composable<SettingsRoute> {
            val ownerId = (root as? RootAppState.Authenticated)?.ownerId
                ?: (root as? RootAppState.OfflineAvailable)?.ownerId
            if (ownerId != null) {
                SettingsRouteContent(
                    ownerId = ownerId,
                    session = container.session,
                    catalog = container.catalog,
                    downloads = container.downloads,
                    themePreferences = container.themePreferences,
                    localAccess = container.localAccess,
                    onExplicitSignOut = container::explicitSignOut,
                    onDeleteAllLocal = { container.deleteAllLocal(ownerId) },
                    onBack = { navController.popBackStack() },
                )
            }
        }
    }
}

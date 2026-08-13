package com.explainer.app.ui.navigation

import kotlin.reflect.KClass

/**
 * Grafo de navegación type-safe de la app (R-T11-03): modelo puro de las
 * CUATRO rutas del plan (Auth → Library → Reader → Settings), la ruta
 * inicial y las transiciones autorizadas. [ExplainerNavHost] lo materializa;
 * los tests fijan el conteo, el start destination y el back behavior sin
 * necesitar un dispositivo.
 *
 * El owner NUNCA es un argumento de ruta: llega desde el estado raíz del
 * container ([com.explainer.app.di.AppContainer.rootState]) y particiona
 * todos los puertos. Reader solo transporta projectId/partId/tab (T10 los
 * valida).
 */
object AppNavGraph {

    /** Ruta inicial del NavHost: Auth (el flujo empieza autenticándose). */
    val startRoute: Any = AuthRoute

    /**
     * Las cuatro rutas del plan, en orden del flujo. El NavHost registra
     * EXACTAMENTE estos destinos.
     */
    val routeTypes: List<KClass<*>> = listOf(
        AuthRoute::class,
        LibraryRoute::class,
        ReaderRoute::class,
        SettingsRoute::class,
    )

    /**
     * Transiciones autorizadas origen → destino (type-safe, sin owner):
     * - Auth → Library: sesión lista (login/restauración/reconexión).
     * - Library → Reader/Settings: apertura de proyecto o ajustes.
     * - Reader/Settings → Library: back.
     * La transición de estado raíz (App → Auth en SignedOut) la decide
     * [com.explainer.app.ui.rootstate.RootAppStateReducer.navigationDecision].
     */
    val transitions: Set<Pair<KClass<*>, KClass<*>>> = setOf(
        AuthRoute::class to LibraryRoute::class,
        LibraryRoute::class to ReaderRoute::class,
        LibraryRoute::class to SettingsRoute::class,
        ReaderRoute::class to LibraryRoute::class,
        SettingsRoute::class to LibraryRoute::class,
    )
}

package com.explainer.app.ui.navigation

import kotlinx.serialization.Serializable

/**
 * Rutas type-safe de la app (Navigation Compose 2.9.8, serialización kotlinx).
 * Contrato fijado por plan.md §Cross-task interfaces; T09/T10 las consumen y
 * T11 cablea el NavHost. Este task no crea el NavHost integrado.
 */

/** Pantalla de autenticación (email/password Supabase GoTrue). */
@Serializable
data object AuthRoute

/** Biblioteca offline: lista de proyectos y sus estados de descarga. */
@Serializable
data object LibraryRoute

/**
 * Lector de un proyecto descargado.
 *
 * @param projectId ID remoto del proyecto (wire name, igual que la web).
 * @param partId parte seleccionada; null = primera disponible.
 * @param tab tab canónica; por defecto `explicacion`, igual que la web
 *   (frontend/js/router.js: `VALID_TABS` / default). Valores desconocidos se
 *   degradan a `explicacion` en el consumidor.
 */
@Serializable
data class ReaderRoute(
    val projectId: String,
    val partId: Int? = null,
    val tab: String = "explicacion",
)

/** Ajustes: tema (claro/oscuro/sistema) y sesión. */
@Serializable
data object SettingsRoute

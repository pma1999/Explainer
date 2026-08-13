package com.explainer.app.ui.navigation

import com.explainer.app.ui.components.ReaderTabNames
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Contrato de rutas type-safe (plan.md §Cross-task): T09/T10 las consumen y
 * T11 cablea el NavHost. Los tests verifican serialización round-trip,
 * defaults y nombres wire canónicos frente a la web (frontend/js/router.js
 * `VALID_TABS`).
 */
class AppRoutesTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun authRoute_roundTrips() {
        val encoded = json.encodeToString(AuthRoute)
        assertEquals(AuthRoute, json.decodeFromString<AuthRoute>(encoded))
    }

    @Test
    fun libraryRoute_roundTrips() {
        val encoded = json.encodeToString(LibraryRoute)
        assertEquals(LibraryRoute, json.decodeFromString<LibraryRoute>(encoded))
    }

    @Test
    fun settingsRoute_roundTrips() {
        val encoded = json.encodeToString(SettingsRoute)
        assertEquals(SettingsRoute, json.decodeFromString<SettingsRoute>(encoded))
    }

    @Test
    fun readerRoute_defaults_projectIdOnly() {
        val route = ReaderRoute(projectId = "proj-123")
        assertEquals(null, route.partId)
        assertEquals("explicacion", route.tab)

        // Decodificar un JSON con solo projectId aplica los defaults.
        val decoded = json.decodeFromString<ReaderRoute>("""{"projectId":"proj-123"}""")
        assertEquals(route, decoded)
        assertNull(decoded.partId)
        assertEquals("explicacion", decoded.tab)
    }

    @Test
    fun readerRoute_roundTrips_withPartAndTab() {
        val route = ReaderRoute(projectId = "proj-123", partId = 4, tab = "esquema")
        val encoded = json.encodeToString(route)
        assertEquals(route, json.decodeFromString<ReaderRoute>(encoded))
        assertTrue(encoded.contains("\"partId\":4"))
        assertTrue(encoded.contains("\"tab\":\"esquema\""))
    }

    @Test
    fun readerRoute_roundTrips_withExplicitDefaults() {
        val route = ReaderRoute(projectId = "p1", partId = null, tab = "explicacion")
        assertEquals(route, json.decodeFromString<ReaderRoute>(json.encodeToString(route)))
    }

    @Test
    fun canonicalTabs_matchWebValidTabsOrder() {
        // frontend/js/router.js L7: export const VALID_TABS =
        // ['explicacion', 'recorrido', 'recursos', 'esquema', 'repaso'];
        val webValidTabs = listOf("explicacion", "recorrido", "recursos", "esquema", "repaso")
        assertEquals(webValidTabs, ReaderTabNames.CanonicalWireNames)
        assertEquals(5, ReaderTabNames.CanonicalWireNames.size)
    }

    @Test
    fun readerRoute_defaultTab_isWebDefault() {
        // router.js: si no hay tab se usa 'explicacion'.
        assertEquals("explicacion", ReaderRoute("p1").tab)
    }

    @Test
    fun unknownTab_doesNotCrashOnRouteLevel() {
        // La normalización a 'explicacion' ocurre en el consumidor; la ruta
        // acepta cualquier string sin romper serialización.
        val route = ReaderRoute("p1", tab = "no-existe")
        assertEquals(route, json.decodeFromString<ReaderRoute>(json.encodeToString(route)))
    }
}

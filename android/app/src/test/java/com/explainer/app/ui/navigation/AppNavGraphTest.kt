package com.explainer.app.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * R-T11-03 (HIGH): el NavHost materializa las CUATRO rutas del plan
 * (Auth → Library → Reader → Settings) con el flujo type-safe y back
 * behavior propios; el owner NUNCA es un argumento de ruta (llega desde el
 * estado raíz del container). El grafo se modela como datos puros
 * ([AppNavGraph]) que el NavHost consume; estos tests fijan el conteo, la
 * ruta inicial y las transiciones autorizadas.
 */
class AppNavGraphTest {

    @Test
    fun `el grafo registra exactamente las cuatro rutas del plan`() {
        assertEquals(4, AppNavGraph.routeTypes.size)
        assertTrue(
            AppNavGraph.routeTypes.containsAll(
                listOf(
                    AuthRoute::class,
                    LibraryRoute::class,
                    ReaderRoute::class,
                    SettingsRoute::class,
                ),
            ),
        )
    }

    @Test
    fun `la ruta inicial es Auth`() {
        assertEquals(AuthRoute, AppNavGraph.startRoute)
    }

    @Test
    fun `Auth esta en el grafo y conecta a Library`() {
        assertTrue(AppNavGraph.routeTypes.contains(AuthRoute::class))
        assertTrue(AppNavGraph.transitions.contains(AuthRoute::class to LibraryRoute::class))
    }

    @Test
    fun `las transiciones autorizadas cubren el flujo completo`() {
        assertEquals(
            setOf(
                AuthRoute::class to LibraryRoute::class,
                LibraryRoute::class to ReaderRoute::class,
                LibraryRoute::class to SettingsRoute::class,
                ReaderRoute::class to LibraryRoute::class,
                SettingsRoute::class to LibraryRoute::class,
            ),
            AppNavGraph.transitions,
        )
    }

    @Test
    fun `toda transicion referencia rutas del grafo`() {
        val types = AppNavGraph.routeTypes.toSet()
        for ((from, to) in AppNavGraph.transitions) {
            assertTrue("origen $from no registrado", types.contains(from))
            assertTrue("destino $to no registrado", types.contains(to))
        }
    }

    @Test
    fun `las rutas no transportan el owner`() {
        // Contrato del plan: el owner proviene solo de SessionGateway/estado
        // raíz, nunca como argumento de ruta. Reader solo lleva
        // projectId/partId/tab (sin ownerId); las demás rutas son data
        // objects sin parámetros (AuthRoute/LibraryRoute/SettingsRoute).
        val reader = ReaderRoute(projectId = "p1")
        assertEquals("p1", reader.projectId)
        assertTrue(reader.partId == null)
        assertTrue(reader.tab == "explicacion")
    }
}

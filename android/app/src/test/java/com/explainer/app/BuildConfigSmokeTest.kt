package com.explainer.app

import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Smoke test del gate de configuración pública (T01).
 *
 * Verifica que las tres constantes del BuildConfig se inyectan desde
 * env/explainer.properties. Falla con fallback vacío (""), demostrando que
 * el wiring existe; los valores reales viven solo en configuración local
 * ignorada por git (la anon key es pública por diseño, no un secreto).
 */
class BuildConfigSmokeTest {

    @Test
    fun buildConfigExposesSupabaseUrl() {
        assertTrue(BuildConfig.EXPLAINER_SUPABASE_URL.startsWith("https://"))
    }

    @Test
    fun buildConfigExposesSupabaseAnonKeyAsJwt() {
        // JWT público anon/publishable: exactamente 3 segmentos base64url.
        assertTrue(BuildConfig.EXPLAINER_SUPABASE_ANON_KEY.split('.').size == 3)
    }

    @Test
    fun buildConfigExposesApiBaseUrl() {
        // Backend pendiente de confirmar: vacío es válido, si se fija debe ser HTTPS.
        val base = BuildConfig.EXPLAINER_API_BASE_URL
        assertTrue(base.isBlank() || base.startsWith("https://"))
    }
}

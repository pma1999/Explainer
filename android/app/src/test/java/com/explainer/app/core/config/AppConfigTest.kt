package com.explainer.app.core.config

import com.explainer.app.BuildConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

/**
 * Validación de la configuración pública (T04): tres valores BuildConfig
 * validados "sin imprimirlos" — los mensajes de require nombran el campo,
 * nunca su valor.
 */
class AppConfigTest {

    private fun valid() = AppConfig.from(
        supabaseUrl = "https://abcd.supabase.co",
        anonKey = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.pub",
        apiBaseUrl = "https://api.explainer.example",
    )

    @Test
    fun acceptsValidHttpsConfig() {
        val config = valid()
        assertEquals("https://abcd.supabase.co", config.supabaseUrl)
        assertEquals("eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.pub", config.supabaseAnonKey)
        assertEquals("https://api.explainer.example", config.apiBaseUrl)
    }

    @Test
    fun rejectsNonHttpsSupabaseUrl() {
        assertThrows(IllegalArgumentException::class.java) {
            AppConfig.from(
                supabaseUrl = "http://abcd.supabase.co",
                anonKey = "key",
                apiBaseUrl = "https://api.explainer.example",
            )
        }
    }

    @Test
    fun rejectsBlankSupabaseUrl() {
        assertThrows(IllegalArgumentException::class.java) {
            AppConfig.from(
                supabaseUrl = "  ",
                anonKey = "key",
                apiBaseUrl = "https://api.explainer.example",
            )
        }
    }

    @Test
    fun rejectsBlankAnonKey() {
        assertThrows(IllegalArgumentException::class.java) {
            AppConfig.from(
                supabaseUrl = "https://abcd.supabase.co",
                anonKey = "",
                apiBaseUrl = "https://api.explainer.example",
            )
        }
    }

    @Test
    fun rejectsApiBaseUrlWithTrailingApiSuffix() {
        assertThrows(IllegalArgumentException::class.java) {
            AppConfig.from(
                supabaseUrl = "https://abcd.supabase.co",
                anonKey = "key",
                apiBaseUrl = "https://api.explainer.example/api",
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            AppConfig.from(
                supabaseUrl = "https://abcd.supabase.co",
                anonKey = "key",
                apiBaseUrl = "https://api.explainer.example/api/",
            )
        }
    }

    @Test
    fun rejectsNonHttpsApiBaseUrl() {
        assertThrows(IllegalArgumentException::class.java) {
            AppConfig.from(
                supabaseUrl = "https://abcd.supabase.co",
                anonKey = "key",
                apiBaseUrl = "http://api.explainer.example",
            )
        }
    }

    @Test
    fun acceptsBlankApiBaseUrlWhenBackendPending() {
        // T01: EXPLAINER_API_BASE_URL vacío es válido mientras el backend
        // pendiente de confirmar; solo https:// si está presente.
        val config = AppConfig.from(
            supabaseUrl = "https://abcd.supabase.co",
            anonKey = "key",
            apiBaseUrl = "",
        )
        assertEquals("", config.apiBaseUrl)
    }

    @Test
    fun fromBuildConfigReadsTheThreePublicConstants() {
        val config = AppConfig.fromBuildConfig()
        assertEquals(BuildConfig.EXPLAINER_SUPABASE_URL, config.supabaseUrl)
        assertEquals(BuildConfig.EXPLAINER_SUPABASE_ANON_KEY, config.supabaseAnonKey)
        assertEquals(BuildConfig.EXPLAINER_API_BASE_URL, config.apiBaseUrl)
    }
}

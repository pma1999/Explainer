package com.explainer.app.core.config

import com.explainer.app.BuildConfig

/**
 * Configuración pública de runtime (global-constraints.md): únicamente
 * URL de Supabase, anon/publishable key y origen HTTPS de FastAPI. Nunca
 * service-role, JWT secret, claves BYOK ni credenciales de prueba.
 *
 * La validación nombra el campo en los mensajes pero nunca imprime el valor.
 */
data class AppConfig(
    val supabaseUrl: String,
    val supabaseAnonKey: String,
    val apiBaseUrl: String,
) {
    init {
        require(supabaseUrl.startsWith("https://")) {
            "EXPLAINER_SUPABASE_URL debe ser una URL HTTPS"
        }
        require(supabaseAnonKey.isNotBlank()) {
            "EXPLAINER_SUPABASE_ANON_KEY no puede estar vacía"
        }
        if (apiBaseUrl.isNotBlank()) {
            require(apiBaseUrl.startsWith("https://")) {
                "EXPLAINER_API_BASE_URL debe ser una URL HTTPS"
            }
            require(!apiBaseUrl.endsWith("/api") && !apiBaseUrl.endsWith("/api/")) {
                "EXPLAINER_API_BASE_URL es el origen HTTPS sin el sufijo /api"
            }
        }
    }

    companion object {
        fun fromBuildConfig(): AppConfig = from(
            supabaseUrl = BuildConfig.EXPLAINER_SUPABASE_URL,
            anonKey = BuildConfig.EXPLAINER_SUPABASE_ANON_KEY,
            apiBaseUrl = BuildConfig.EXPLAINER_API_BASE_URL,
        )

        fun from(supabaseUrl: String, anonKey: String, apiBaseUrl: String): AppConfig =
            AppConfig(supabaseUrl, anonKey, apiBaseUrl)
    }
}

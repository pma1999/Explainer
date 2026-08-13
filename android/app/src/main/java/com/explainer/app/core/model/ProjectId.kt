package com.explainer.app.core.model

/**
 * ID de proyecto remoto. Se valida como UUID **antes** de usarse en paths o
 * keys (global-constraints.md: "UUID/part IDs se validan antes de usarse").
 *
 * El payload nunca determina el `ownerId`; este ID solo identifica el recurso.
 */
@JvmInline
value class ProjectId(val value: String) {
    init {
        require(isValidUuid(value)) { "ProjectId debe ser un UUID válido: $value" }
    }

    companion object {
        private val UUID_REGEX = Regex(
            "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        )

        fun isValidUuid(raw: String): Boolean = UUID_REGEX.matches(raw)

        /** Retorna `null` para valores no UUID (payload inválido); nunca lanza. */
        fun parse(raw: String): ProjectId? = if (isValidUuid(raw)) ProjectId(raw) else null
    }
}

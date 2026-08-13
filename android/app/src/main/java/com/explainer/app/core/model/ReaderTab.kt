package com.explainer.app.core.model

/**
 * Tabs canónicas del lector. Los nombres Kotlin son contrato compartido de
 * `plan.md` (L260-263): `EXPLANATION|WALKTHROUGH|RESOURCES|DIAGRAM|REVIEW`;
 * el wire name exacto es el español (router.js VALID_TABS):
 * `explicacion|recorrido|recursos|esquema|repaso` (orden web).
 */
enum class ReaderTab(val wireName: String) {
    EXPLANATION("explicacion"),
    WALKTHROUGH("recorrido"),
    RESOURCES("recursos"),
    DIAGRAM("esquema"),
    REVIEW("repaso");

    companion object {
        /** `null` para valores wire desconocidos. */
        fun fromWire(raw: String): ReaderTab? = entries.firstOrNull { it.wireName == raw }
    }
}

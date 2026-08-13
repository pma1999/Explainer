package com.explainer.app.ui.reader

/**
 * Política de visibilidad del chrome superior del lector (lectura-first).
 * Pura y sin Android, como [ReaderViewport]: el host (ReaderScreen) observa
 * el LazyListState y alimenta [decide] con el delta de scroll y la velocidad
 * del gesto — ya normalizados por densidad (dp y dp/s) — y recibe el
 * siguiente estado del chrome.
 *
 * Zona muerta + histéresis: los deltas pequeños no cambian el estado; el
 * chrome se oculta tras [HideThresholdDp] dp de scroll hacia abajo acumulado
 * y reaparece tras [ShowThresholdDp] dp hacia arriba. Los umbrales son
 * distintos por dirección y el acumulador se reinicia al invertir la
 * dirección, de modo que una ráfaga corta en contra no toglea el chrome
 * (estabilidad al leer, sin saltos de reflow). Un fling decidido
 * (≥ [HideFlingVelocityDpPerSec] hacia abajo, ≥ [ShowFlingVelocityDpPerSec]
 * hacia arriba) gana a la zona muerta y decide de inmediato; la velocidad ~0
 * (reposo o decay lento) nunca dispara nada. Sin contenido que leer
 * ([canScrollForward] = false) o arriba del todo ([atTop]) el chrome queda
 * forzosamente visible: no tiene sentido ocultarlo si no hay texto que leer.
 */
object ChromeVisibilityPolicy {

    /** Scroll hacia abajo acumulado (dp) que oculta el chrome. */
    const val HideThresholdDp = 24f

    /** Scroll hacia arriba acumulado (dp) que muestra el chrome. */
    const val ShowThresholdDp = 16f

    /**
     * Fling hacia abajo (dp/s) que oculta el chrome de inmediato, sin esperar
     * a la zona muerta: un gesto decidido de lectura debe ganar espacio ya.
     */
    const val HideFlingVelocityDpPerSec = 2500f

    /**
     * Fling hacia arriba (dp/s) que muestra el chrome de inmediato. Umbral
     * menor que el de ocultar: recuperar el chrome es menos invasivo que
     * quitarlo, así que se concede con un gesto algo más flojo.
     */
    const val ShowFlingVelocityDpPerSec = 2000f

    /**
     * Estado del detector: visibilidad actual del chrome y scroll acumulado
     * en la dirección del gesto en curso (positivo = hacia abajo), la "zona
     * muerta" que aún no ha cruzado su umbral.
     */
    data class State(
        val visible: Boolean = true,
        val accumulatedDp: Float = 0f,
    )

    /**
     * Decide el siguiente estado del chrome a partir del fotograma actual.
     *
     * @param previous estado anterior (visibilidad + acumulador).
     * @param deltaDp desplazamiento del contenido en este fotograma, en dp
     *   (positivo = hacia abajo, leer más).
     * @param velocityDpPerSec velocidad instantánea del gesto en dp/s
     *   (positiva = hacia abajo; ~0 en reposo o decay lento).
     * @param canScrollForward si la lista tiene contenido por delante; si no,
     *   el chrome permanece visible (contenido corto).
     * @param atTop si la lista está arriba del todo (primer item, offset 0);
     *   fuerza el chrome visible.
     * @param hideThresholdDp zona muerta de ocultar (por defecto
     *   [HideThresholdDp]).
     * @param showThresholdDp zona muerta de mostrar (por defecto
     *   [ShowThresholdDp]).
     * @param hideFlingVelocityDpPerSec velocidad de fling que oculta al
     *   instante (por defecto [HideFlingVelocityDpPerSec]).
     * @param showFlingVelocityDpPerSec velocidad de fling que muestra al
     *   instante (por defecto [ShowFlingVelocityDpPerSec]).
     */
    fun decide(
        previous: State,
        deltaDp: Float,
        velocityDpPerSec: Float,
        canScrollForward: Boolean,
        atTop: Boolean,
        hideThresholdDp: Float = HideThresholdDp,
        showThresholdDp: Float = ShowThresholdDp,
        hideFlingVelocityDpPerSec: Float = HideFlingVelocityDpPerSec,
        showFlingVelocityDpPerSec: Float = ShowFlingVelocityDpPerSec,
    ): State {
        // Guardias forzosas: sin contenido que leer o arriba del todo el
        // chrome no tiene razón de ocultarse. El acumulador se limpia para
        // que el siguiente gesto empiece de cero.
        if (!canScrollForward || atTop) return State(visible = true)

        // Fling decidido: gana a la zona muerta y decide de inmediato. La
        // velocidad ~0 (dedo quieto, decay lento) cae por debajo de ambos
        // umbrales y no dispara nada.
        if (velocityDpPerSec >= hideFlingVelocityDpPerSec) return State(visible = false)
        if (velocityDpPerSec <= -showFlingVelocityDpPerSec) return State(visible = true)

        // Reposo: ni velocidad ni desplazamiento, no hay nada que decidir.
        if (deltaDp == 0f) return previous

        // Zona muerta con histéresis. Al invertir la dirección el acumulador
        // se reinicia: un rebote corto en contra no arrastra el recorrido de
        // la dirección anterior (ni lo toglea ni lo acelera).
        val reversedDirection = previous.accumulatedDp > 0f != deltaDp > 0f
        val accumulated = if (reversedDirection) deltaDp else previous.accumulatedDp + deltaDp
        return when {
            accumulated >= hideThresholdDp -> State(visible = false, accumulatedDp = accumulated)
            accumulated <= -showThresholdDp -> State(visible = true, accumulatedDp = accumulated)
            else -> previous.copy(accumulatedDp = accumulated)
        }
    }
}

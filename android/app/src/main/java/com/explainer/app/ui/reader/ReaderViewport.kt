package com.explainer.app.ui.reader

/**
 * Zona de lectura activa (T10): paridad web `frontend/js/main.js`
 * `initSubsectionObserver` (rootMargin `-35% 0px -55% 0px` → banda
 * [35 %, 45 %] de la altura del viewport). Puro y sin Android: el Compose
 * host alimenta las posiciones de los headings visibles y decide qué
 * subsección está activa.
 *
 * La web elige la entrada intersectante con mayor `intersectionRatio` (empate
 * → primera en orden); aquí la intersección es el solapamiento en píxeles de
 * cada heading con la banda, y el empate gana el índice menor.
 */
object ReaderViewport {

    /** Banda de lectura: 35–45 % superior del viewport (constantes web). */
    const val BAND_TOP_RATIO = 0.35f
    const val BAND_BOTTOM_RATIO = 0.45f

    /** Heading visible: índice en la lista del LazyColumn + caja en px. */
    data class TrackedItem(val index: Int, val offset: Int, val size: Int)

    /**
     * Índice del heading activo entre los visibles, o `null` si ninguno
     * intersecta la banda (el anterior sigue activo, como en la web).
     *
     * @param items headings visibles con su caja en coordenadas del viewport.
     * @param viewportHeight altura del viewport del LazyColumn en px.
     */
    fun activeTrackedIndex(
        items: List<TrackedItem>,
        viewportHeight: Int,
        bandTopRatio: Float = BAND_TOP_RATIO,
        bandBottomRatio: Float = BAND_BOTTOM_RATIO,
    ): Int? {
        if (items.isEmpty() || viewportHeight <= 0) return null
        val bandTop = viewportHeight * bandTopRatio
        val bandBottom = viewportHeight * bandBottomRatio

        var bestIndex: Int? = null
        var bestOverlap = 0f
        for (item in items) {
            val itemBottom = (item.offset + item.size).toFloat()
            if (itemBottom <= bandTop || item.offset >= bandBottom) continue
            val overlap = minOf(itemBottom, bandBottom) - maxOf(item.offset.toFloat(), bandTop)
            if (overlap <= 0f) continue
            val isBetter = bestIndex == null ||
                overlap > bestOverlap ||
                (overlap == bestOverlap && item.index < bestIndex!!)
            if (isBetter) {
                bestIndex = item.index
                bestOverlap = overlap
            }
        }
        return bestIndex
    }
}

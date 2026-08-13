package com.explainer.app.ui.reader

import com.explainer.app.R
import com.explainer.app.core.model.PartStatus
import com.explainer.app.feature.generation.GenerationFailureReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Labels de estado de parte y de fallo de generación del lector (T10/T14). */
class ReaderLabelsTest {

    @Test
    fun `cada estado de parte tiene etiqueta explicita`() {
        assertEquals(R.string.reader_part_status_pending, ReaderLabels.partStatusLabelRes(PartStatus.Pending))
        assertEquals(R.string.reader_part_status_processing, ReaderLabels.partStatusLabelRes(PartStatus.Processing))
        assertEquals(R.string.reader_part_status_completed, ReaderLabels.partStatusLabelRes(PartStatus.Completed))
        assertEquals(R.string.reader_part_status_failed, ReaderLabels.partStatusLabelRes(PartStatus.Failed))
    }

    @Test
    fun `estado desconocido no muestra etiqueta`() {
        assertNull(ReaderLabels.partStatusLabelRes(PartStatus.Unknown("futuro")))
    }

    @Test
    fun `cada razon de fallo de generacion tiene mensaje accionable`() {
        assertEquals(R.string.generation_failure_offline, ReaderLabels.generationFailureMessageRes(GenerationFailureReason.OFFLINE))
        assertEquals(R.string.generation_failure_auth, ReaderLabels.generationFailureMessageRes(GenerationFailureReason.AUTH))
        assertEquals(R.string.generation_failure_permission, ReaderLabels.generationFailureMessageRes(GenerationFailureReason.PERMISSION))
        assertEquals(R.string.generation_failure_not_found, ReaderLabels.generationFailureMessageRes(GenerationFailureReason.NOT_FOUND))
        assertEquals(R.string.generation_failure_rate_limited, ReaderLabels.generationFailureMessageRes(GenerationFailureReason.RATE_LIMITED))
        assertEquals(R.string.generation_failure_invalid, ReaderLabels.generationFailureMessageRes(GenerationFailureReason.INVALID))
        assertEquals(R.string.generation_failure_unknown, ReaderLabels.generationFailureMessageRes(GenerationFailureReason.UNKNOWN))
    }
}

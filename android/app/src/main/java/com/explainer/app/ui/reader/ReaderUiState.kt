package com.explainer.app.ui.reader

import com.explainer.app.core.model.LastSubsection
import com.explainer.app.core.model.PartStatus
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.feature.generation.GenerationFailureReason
import com.explainer.app.ui.content.ParsedPartContent

/**
 * Fase de generación on-demand de un tab del lector (T14): esquema (Mermaid)
 * o repaso (review). `null` = sin operación en curso (se muestra el
 * contenido del tab, exista o no); [Generating] y [Failed] sustituyen al
 * contenido del tab para que nunca quede una pantalla vacía.
 */
sealed interface GenerationPhase {
    /** Generación en curso; la UI muestra progreso accesible (liveRegion). */
    data object Generating : GenerationPhase

    /** La generación falló con una [GenerationFailureReason] accionable. */
    data class Failed(val reason: GenerationFailureReason) : GenerationPhase
}

/**
 * Estado, acciones y eventos del lector offline de cinco pestañas (T10).
 *
 * Presentacional e inmutable: la UI recibe [ReaderUiState] y emite
 * [ReaderAction]; el ViewModel consume los puertos de T07 (catálogo y
 * progreso) y el reducer puro resuelve reanudación, partes, tabs y estados
 * de contenido. Nunca hay JSON pesado ni el proyecto completo en el estado
 * Compose: solo manifest/index ligero (títulos y estado por parte), la parte
 * seleccionada parseada y el progreso de lectura.
 */
sealed interface ReaderUiState {
    /** Manifest del snapshot aún sin primera emisión. */
    data object Loading : ReaderUiState

    /** Ruta con projectId no UUID: no se abre ningún snapshot. */
    data object InvalidProject : ReaderUiState

    /** Sin snapshot activo para el owner/proyecto (no descargado o borrado). */
    data object MissingSnapshot : ReaderUiState

    /** Lector listo: manifest ligero + parte seleccionada + progreso. */
    data class Content(val model: ReaderContentUi) : ReaderUiState
}

/** Vista de lectura ligera: nunca el proyecto completo ni todos los JsonObject. */
data class ReaderContentUi(
    val projectName: String,
    val projectDescription: String?,
    /** Catálogo remoto más nuevo que el snapshot → banner "Puede haber cambios". */
    val updatePossible: Boolean,
    val parts: List<PartNavUi>,
    /** null solo cuando el proyecto no tiene partes (estado vacío explícito). */
    val selectedPartId: Int?,
    /** `segmentation.partes[].contenido` de la parte seleccionada (colapsable). */
    val selectedPartDescription: String,
    val selectedTab: ReaderTab,
    val partState: PartContentUi,
    val completedParts: Set<Int>,
    val completedSubsections: Set<String>,
    val lastSubsection: LastSubsection?,
    val canGoPrevious: Boolean,
    val canGoNext: Boolean,
    val descriptionExpanded: Boolean,
    val partSelectorOpen: Boolean,
    /** Objetivo de scroll de reanudación pendiente (se aplica una vez). */
    val scrollTarget: SubsectionScrollTarget?,
    /** Fase de generación del tab `esquema`; null = sin operación. */
    val diagramGeneration: GenerationPhase? = null,
    /** Fase de generación del tab `repaso`; null = sin operación. */
    val reviewGeneration: GenerationPhase? = null,
)

/** Item del pane/sheet de partes: estado por parte y lectura. */
data class PartNavUi(
    val partId: Int,
    val title: String,
    val status: PartStatus,
    val isRead: Boolean,
    /** El toggle de leída solo se ofrece en partes con contenido real. */
    val canToggle: Boolean,
)

/**
 * Estado de la parte seleccionada: carga, lista para renderizar o uno de
 * los estados sin pantalla vacía (generándose, error, no descargada, fallo
 * local). [Ready] lleva el contenido parseado de los cinco tabs (T08).
 */
sealed interface PartContentUi {
    /** JSON + parse en curso (carga local, nunca red). */
    data object Loading : PartContentUi

    /** Contenido parseado; los tabs ausentes/error/malformado se resuelven por tab. */
    data class Ready(val parsed: ParsedPartContent) : PartContentUi

    /** Parte `pending`/`processing` sin ningún contenido del agente todavía. */
    data class Processing(val status: PartStatus) : PartContentUi

    /** Parte `failed` sin contenido del agente. */
    data object Failed : PartContentUi

    /** `loadPart` no devolvió documento (parte fuera del snapshot). */
    data class Missing(val partId: Int) : PartContentUi

    /** Fallo local de lectura/parse; el usuario puede reintentar. */
    data object LoadError : PartContentUi
}

/** Objetivo de scroll de reanudación: parte + tab + id exacto de subsección. */
data class SubsectionScrollTarget(
    val partId: Int,
    val subsectionId: String,
    val tab: ReaderTab,
)

/**
 * Acciones del lector; el ViewModel las traduce en llamadas únicas a los
 * puertos (catálogo/progreso), nunca a concreciones.
 */
sealed interface ReaderAction {
    /** Volver a la biblioteca; finaliza la sesión de actividad del tracker. */
    data object Back : ReaderAction

    /** Selecciona parte; mismo partId no resetea scroll (paridad web selectPart). */
    data class SelectPart(val partId: Int) : ReaderAction

    /** Selecciona tab por nombre wire; desconocido se normaliza a `explicacion`. */
    data class SelectTab(val wireName: String) : ReaderAction

    /** La subsección activa (zona 35–45 %) cambió; id wire `subsec-...`. */
    data class SubsectionActivated(val subsectionId: String) : ReaderAction

    /** Marca/desmarca la parte completa (optimista + haptic en el host). */
    data class ToggleSectionComplete(val partId: Int) : ReaderAction

    data object PreviousPart : ReaderAction

    data object NextPart : ReaderAction

    /** Descripción de sección (`partes[].contenido`) colapsable. */
    data object ToggleDescription : ReaderAction

    data object OpenPartSelector : ReaderAction

    data object ClosePartSelector : ReaderAction

    /** Reintenta la carga local de la parte tras LoadError/Missing. */
    data object RetryPartLoad : ReaderAction

    /** El scroll de reanudación ya se aplicó (o no aplica); limpiar objetivo. */
    data object ScrollTargetHandled : ReaderAction

    /**
     * Genera (o regenera) el esquema Mermaid de la parte. `regenerate=true`
     * fuerza regeneración aunque exista contenido previo (paridad web).
     */
    data class GenerateDiagram(val partId: Int, val regenerate: Boolean) : ReaderAction

    /** Genera (o regenera) el repaso de la parte (paridad web). */
    data class GenerateReview(val partId: Int, val regenerate: Boolean) : ReaderAction

    /** Descartar el error de generación de esquema y volver al contenido. */
    data object DismissDiagramError : ReaderAction

    /** Descartar el error de generación de repaso y volver al contenido. */
    data object DismissReviewError : ReaderAction

    /** URL http/https aprobada por la política; el host la abre en app externa. */
    data class OpenExternalUrl(val url: String) : ReaderAction
}

/** Eventos one-shot: el host los traduce en haptics (confirmación/lectura). */
sealed interface ReaderEvent {
    /** Toggle de parte leída/no leída aplicado (haptic de confirmación). */
    data object SectionCompleteToggled : ReaderEvent
}

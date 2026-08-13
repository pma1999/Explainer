package com.explainer.app.core.model

/**
 * Errores categorizados del mapeo de payload a snapshot (no son crashes
 * tardíos: se lanzan al validar, con la categoría accesible para la UI).
 */
sealed interface SnapshotError {
    data class InvalidProjectId(val raw: String) : SnapshotError
    data class InvalidPartNumber(val numero: Int?) : SnapshotError
    /** `partId` no positivo en la llamada directa al mapper. */
    data class InvalidPartId(val partId: Int) : SnapshotError
    data class DuplicatePartNumber(val numero: Int) : SnapshotError
    data class InvalidPartKey(val key: String) : SnapshotError
    /** Clave de `partes_contenido` sin `numero` declarado en `segmentation`. */
    data class OrphanContentKey(val key: String) : SnapshotError
    /** Parte declarada en `segmentation` sin entrada en `partes_contenido`. */
    data class MissingContentForPart(val numero: Int) : SnapshotError
}

class SnapshotContractException(val error: SnapshotError) :
    IllegalArgumentException("Snapshot inválido: $error")

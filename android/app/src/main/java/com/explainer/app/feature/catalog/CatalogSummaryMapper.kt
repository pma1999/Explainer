package com.explainer.app.feature.catalog

import com.explainer.app.core.model.LastSubsection
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.SnapshotJsonCodec
import com.explainer.app.data.remote.dto.ExplainerJson
import com.explainer.app.data.remote.dto.PartDto
import com.explainer.app.data.remote.dto.ProjectSummaryDto
import com.explainer.app.data.remote.dto.ReadingProgressDto
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Mapea los items de `GET /api/projects` a resúmenes owner-scoped (T07).
 * Al mapear calcula los bytes UTF-8 de `segmentation.partes[].contenido`
 * pero persiste SOLO numero/titulo + `segmentationSourceBytes`: el texto
 * vive únicamente en los snapshots fijados (T03). Items con id inválido se
 * saltan (el refresh no crashea ni borra por un item malo).
 */
object CatalogSummaryMapper {

    fun toEntity(ownerId: String, dto: ProjectSummaryDto, fetchedAt: Long): ProjectSummaryEntity? {
        if (ProjectId.parse(dto.id) == null) return null
        val parts = dto.segmentation?.partes.orEmpty()
        val sourceBytes = parts.sumOf { part ->
            (part.contenido?.toByteArray(Charsets.UTF_8)?.size ?: 0).toLong()
        }
        return ProjectSummaryEntity(
            ownerId = ownerId,
            projectId = dto.id,
            name = dto.name,
            description = dto.description,
            status = dto.status,
            sourceType = dto.sourceType,
            pdfFilename = dto.pdfFilename,
            sourceUrl = dto.sourceUrl,
            partIndexJson = encodePartIndex(parts),
            segmentationSourceBytes = sourceBytes,
            usageJson = ExplainerJson.json.encodeToString(JsonObject.serializer(), dto.usage),
            readingProgressJson = SnapshotJsonCodec.encodeReadingProgress(dto.readingProgress.toDomain()),
            createdAt = dto.createdAt,
            remoteUpdatedAt = dto.updatedAt,
            remoteContentUpdatedAt = dto.contentUpdatedAt.orEmpty(),
            fetchedAt = fetchedAt,
        )
    }

    /** `[{numero, titulo}]` sin `contenido`; corrupto degrada a vacío. */
    fun decodePartIndex(raw: String?): List<Pair<Int, String>> =
        SnapshotJsonCodec.decodeSegmentation(raw)
            ?.map { it.numero to it.titulo }
            .orEmpty()

    private fun encodePartIndex(parts: List<PartDto>): String {
        val array = JsonArray(
            parts.map { part ->
                buildJsonObject {
                    put("numero", part.numero ?: 0)
                    put("titulo", part.titulo.orEmpty())
                }
            },
        )
        return ExplainerJson.json.encodeToString(JsonArray.serializer(), array)
    }
}

/** Progreso del DTO al dominio (el merge vive en la policy T02, no aquí). */
internal fun ReadingProgressDto.toDomain(): ReadingProgress = ReadingProgress(
    completedParts = completedParts.filter { it > 0 }.toSet(),
    completedSubsections = completedSubsections.toSet(),
    lastSubsection = lastSubsection?.let {
        LastSubsection(
            partId = it.partId,
            subsectionId = it.subsectionId,
            tab = ReaderTab.fromWire(it.tab) ?: ReaderTab.EXPLANATION,
        )
    },
    lastReadAt = lastReadAt,
)

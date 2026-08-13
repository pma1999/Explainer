package com.explainer.app.feature.catalog

import com.explainer.app.data.remote.dto.ExplainerJson
import com.explainer.app.data.remote.dto.PartDto
import com.explainer.app.data.remote.dto.ProjectSummaryDto
import com.explainer.app.data.remote.dto.ReadingProgressDto
import com.explainer.app.data.remote.dto.SegmentationDto
import com.explainer.app.data.local.snapshot.SnapshotJsonCodec
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Mapeo de la lista remota a resúmenes owner-scoped:
 * - bytes UTF-8 de `segmentation.partes[].contenido` calculados al mapear,
 *   pero persiste solo numero/titulo + `segmentationSourceBytes` (el texto
 *   vive solo en snapshots fijados).
 * - progreso re-codificado al shape canónico; usage crudo sin pérdida.
 * - IDs inválidos se saltan (el refresh no puede crashear por un item malo).
 */
class CatalogSummaryMapperTest {

    private val owner = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val uuid = "3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f"

    @Test
    fun `calcula bytes UTF-8 de contenido y persiste solo numero titulo y total`() {
        val dto = ProjectSummaryDto(
            id = uuid,
            name = "Teoría del derecho",
            status = "completed",
            segmentation = SegmentationDto(
                partes = listOf(
                    PartDto(numero = 1, titulo = "Introducción", contenido = "héllo"), // é = 2 bytes -> 6
                    PartDto(numero = 2, titulo = "Desarrollo", contenido = "abc"), // 3
                    PartDto(numero = 3, titulo = "Sin texto", contenido = null), // 0
                ),
            ),
        )

        val entity = CatalogSummaryMapper.toEntity(owner, dto, fetchedAt = 42L)!!

        assertEquals(9L, entity.segmentationSourceBytes)
        val index = CatalogSummaryMapper.decodePartIndex(entity.partIndexJson)
        assertEquals(listOf(1 to "Introducción", 2 to "Desarrollo", 3 to "Sin texto"), index)
        assertTrue(!entity.partIndexJson.contains("contenido"))
        assertTrue(!entity.partIndexJson.contains("héllo"))
        assertEquals(42L, entity.fetchedAt)
        assertEquals("Teoría del derecho", entity.name)
        assertEquals("completed", entity.status)
    }

    @Test
    fun `progreso y usage se conservan en el shape canonico`() {
        val dto = ProjectSummaryDto(
            id = uuid,
            segmentation = SegmentationDto(partes = listOf(PartDto(numero = 1, titulo = "P1"))),
            usage = buildJsonObject { put("tokens", 5) },
            readingProgress = ReadingProgressDto(
                completedParts = listOf(1),
                completedSubsections = listOf("subsec-1-a-0"),
                lastReadAt = "2026-08-01T10:00:01.000Z",
            ),
        )

        val entity = CatalogSummaryMapper.toEntity(owner, dto, 0L)!!

        val progress = SnapshotJsonCodec.decodeReadingProgress(entity.readingProgressJson)
        assertEquals(setOf(1), progress.completedParts)
        assertEquals(setOf("subsec-1-a-0"), progress.completedSubsections)
        assertEquals("2026-08-01T10:00:01.000Z", progress.lastReadAt)
        assertTrue(entity.usageJson.contains("\"tokens\":5"))
    }

    @Test
    fun `id no UUID se salta sin lanzar`() {
        val dto = ProjectSummaryDto(id = "not-a-uuid", name = "Mal")
        assertNull(CatalogSummaryMapper.toEntity(owner, dto, 0L))
    }

    @Test
    fun `content_updated_at remoto se persiste como remoteContentUpdatedAt`() {
        val dto = ProjectSummaryDto(
            id = uuid,
            name = "Version",
            segmentation = SegmentationDto(partes = listOf(PartDto(numero = 1, titulo = "P1"))),
            updatedAt = "2026-08-01T10:00:01.000Z",
            contentUpdatedAt = "2026-08-01T10:00:00.000Z",
        )

        val entity = CatalogSummaryMapper.toEntity(owner, dto, 0L)!!

        assertEquals("2026-08-01T10:00:00.000Z", entity.remoteContentUpdatedAt)
        // El reloj de actividad se conserva independiente (ordenación/display).
        assertEquals("2026-08-01T10:00:01.000Z", entity.remoteUpdatedAt)
    }

    @Test
    fun `content_updated_at ausente persiste vacio para fallback legacy`() {
        val dto = ProjectSummaryDto(
            id = uuid,
            name = "Legacy",
            updatedAt = "2026-08-01T10:00:01.000Z",
        )

        val entity = CatalogSummaryMapper.toEntity(owner, dto, 0L)!!

        assertEquals("", entity.remoteContentUpdatedAt)
        assertEquals("2026-08-01T10:00:01.000Z", entity.remoteUpdatedAt)
    }

    @Test
    fun `content_updated_at null en el wire no rompe el decode y degrada a vacio`() {
        // Backend nuevo + BD sin migrar: la clave llega como JSON null, no
        // ausente. Con tipo no-nullable kotlinx.serialization lanzaría aunque
        // exista default; el DTO nullable + orEmpty degrada a fallback legacy.
        val dto = ExplainerJson.json.decodeFromString<ProjectSummaryDto>(
            """{"id":"$uuid","name":"Null","updated_at":"2026-08-01T10:00:01.000Z","content_updated_at":null}""",
        )

        val entity = CatalogSummaryMapper.toEntity(owner, dto, 0L)!!

        assertEquals("", entity.remoteContentUpdatedAt)
        assertEquals("2026-08-01T10:00:01.000Z", entity.remoteUpdatedAt)
    }

    @Test
    fun `part index corrupto degrada a lista vacia`() {
        assertEquals(emptyList<Pair<Int, String>>(), CatalogSummaryMapper.decodePartIndex("not json"))
        assertEquals(emptyList<Pair<Int, String>>(), CatalogSummaryMapper.decodePartIndex(null))
    }
}

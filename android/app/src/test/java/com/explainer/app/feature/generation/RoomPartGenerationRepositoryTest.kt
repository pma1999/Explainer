package com.explainer.app.feature.generation

import com.explainer.app.core.model.DownloadedProjectFile
import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.snapshot.OfflineProjectManifest
import com.explainer.app.data.local.snapshot.OfflineSnapshotStore
import com.explainer.app.data.local.snapshot.PreparedSnapshot
import com.explainer.app.data.local.snapshot.SnapshotCommitResult
import com.explainer.app.data.remote.contract.ProjectRemoteDataSource
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.data.remote.dto.ProjectSummaryDto
import com.explainer.app.data.remote.dto.SubsectionProgressPatch
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `RoomPartGenerationRepository` con fakes (remote + store en memoria):
 * mapeo completo RemoteResult → GenerationOutcome, clave de patch correcta
 * (`mermaid`/`review`), persistencia fallida → UNKNOWN, cancelación
 * propagada como [CancellationException] y `regenerate` reenviado al remoto.
 */
class RoomPartGenerationRepositoryTest {

    private val owner = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val projectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")

    private class FakeRemote(
        var diagramResult: RemoteResult<JsonObject> = RemoteResult.Success(mermaidObj()),
        var reviewResult: RemoteResult<JsonObject> = RemoteResult.Success(reviewObj()),
    ) : ProjectRemoteDataSource {
        var lastPartId: Int = -1
        var lastRegenerate: Boolean? = null
        var diagramCalls = 0
        var reviewCalls = 0

        override suspend fun listProjects(): RemoteResult<List<ProjectSummaryDto>> =
            error("no usado en T14")

        override suspend fun downloadProjectTo(
            projectId: ProjectId,
            destination: File,
            onProgress: suspend (downloadedBytes: Long, totalBytes: Long?) -> Unit,
        ): RemoteResult<DownloadedProjectFile> = error("no usado en T14")

        override suspend fun patchSection(
            projectId: ProjectId,
            partId: Int,
            completed: Boolean,
        ): RemoteResult<Unit> = error("no usado en T14")

        override suspend fun patchSubsections(
            projectId: ProjectId,
            patch: SubsectionProgressPatch,
        ): RemoteResult<Unit> = error("no usado en T14")

        override suspend fun generateDiagram(
            projectId: ProjectId,
            partId: Int,
            regenerate: Boolean,
        ): RemoteResult<JsonObject> {
            diagramCalls++
            lastPartId = partId
            lastRegenerate = regenerate
            return diagramResult
        }

        override suspend fun generateReview(
            projectId: ProjectId,
            partId: Int,
            regenerate: Boolean,
        ): RemoteResult<JsonObject> {
            reviewCalls++
            lastPartId = partId
            lastRegenerate = regenerate
            return reviewResult
        }
    }

    private class FakeStore : OfflineSnapshotStore {
        val patches = mutableListOf<JsonObject>()
        var updateResult: Boolean = true

        override suspend fun prepare(ownerId: String, source: File): PreparedSnapshot =
            error("no usado en T14")

        override suspend fun commit(prepared: PreparedSnapshot, expectedWorkId: String): SnapshotCommitResult =
            error("no usado en T14")

        override suspend fun readManifest(ownerId: String, projectId: ProjectId): OfflineProjectManifest? =
            null

        override suspend fun readPart(
            ownerId: String,
            projectId: ProjectId,
            partId: Int,
        ): PartContentDocument? = null

        override suspend fun delete(ownerId: String, projectId: ProjectId) = Unit

        override suspend fun cleanupOrphans() = Unit

        override suspend fun updatePartContent(
            ownerId: String,
            projectId: ProjectId,
            partId: Int,
            patch: JsonObject,
        ): Boolean {
            patches.add(patch)
            return updateResult
        }
    }

    @Test
    fun `diagram success persists mermaid patch and returns success`() = runBlocking {
        val remote = FakeRemote(diagramResult = RemoteResult.Success(mermaidObj()))
        val store = FakeStore()
        val repo = RoomPartGenerationRepository(remote, store)

        val outcome = repo.generateDiagram(owner, projectId, partId = 3, regenerate = true)

        assertEquals(GenerationOutcome.Success, outcome)
        assertEquals(1, store.patches.size)
        val patch = store.patches.single()
        assertEquals(setOf("mermaid"), patch.keys)
        assertEquals(
            "graph TD; A[Intro] --> B[Fin]",
            patch["mermaid"]!!.jsonObject["mermaid_code"]!!.jsonPrimitive.content,
        )
        // Regenerate y partId llegan al remoto tal cual.
        assertEquals(3, remote.lastPartId)
        assertEquals(true, remote.lastRegenerate)
        assertEquals(1, remote.diagramCalls)
        assertEquals(0, remote.reviewCalls)
    }

    @Test
    fun `review success persists review patch and returns success`() = runBlocking {
        val remote = FakeRemote(reviewResult = RemoteResult.Success(reviewObj()))
        val store = FakeStore()
        val repo = RoomPartGenerationRepository(remote, store)

        val outcome = repo.generateReview(owner, projectId, partId = 7, regenerate = false)

        assertEquals(GenerationOutcome.Success, outcome)
        val patch = store.patches.single()
        assertEquals(setOf("review"), patch.keys)
        assertEquals("Sigue practicando", patch["review"]!!.jsonObject["nota"]!!.jsonPrimitive.content)
        assertEquals(7, remote.lastPartId)
        assertEquals(false, remote.lastRegenerate)
        assertEquals(1, remote.reviewCalls)
        assertEquals(0, remote.diagramCalls)
    }

    @Test
    fun `failure mapping is complete for diagram and review`() = runBlocking {
        val cases: List<Pair<RemoteResult<JsonObject>, GenerationFailureReason>> = listOf(
            RemoteResult.AuthRequired to GenerationFailureReason.AUTH,
            RemoteResult.RateLimited to GenerationFailureReason.RATE_LIMITED,
            RemoteResult.Retryable to GenerationFailureReason.OFFLINE,
            RemoteResult.NotFound to GenerationFailureReason.NOT_FOUND,
            RemoteResult.InvalidPayload("shape") to GenerationFailureReason.INVALID,
            RemoteResult.PermanentFailure("http:400") to GenerationFailureReason.PERMISSION,
        )
        for ((remoteResult, expected) in cases) {
            val repoDiagram = RoomPartGenerationRepository(
                FakeRemote(diagramResult = remoteResult),
                FakeStore(),
            )
            val diagram = repoDiagram.generateDiagram(owner, projectId, partId = 3, regenerate = false)
            assertEquals("diagram: $remoteResult", GenerationOutcome.Failure(expected), diagram)

            val repoReview = RoomPartGenerationRepository(
                FakeRemote(reviewResult = remoteResult),
                FakeStore(),
            )
            val review = repoReview.generateReview(owner, projectId, partId = 3, regenerate = false)
            assertEquals("review: $remoteResult", GenerationOutcome.Failure(expected), review)
        }
    }

    @Test
    fun `failed persistence maps to unknown without content`() = runBlocking {
        val remote = FakeRemote()
        val store = FakeStore().apply { updateResult = false }
        val repo = RoomPartGenerationRepository(remote, store)

        val outcome = repo.generateDiagram(owner, projectId, partId = 3, regenerate = false)

        assertEquals(GenerationOutcome.Failure(GenerationFailureReason.UNKNOWN), outcome)
        // El remoto sí se llamó; la persistencia falló por ausencia de fila activa.
        assertEquals(1, remote.diagramCalls)
    }

    @Test
    fun `cancelled propagates cancellation exception and never a failure`() {
        val repo = RoomPartGenerationRepository(
            FakeRemote(diagramResult = RemoteResult.Cancelled),
            FakeStore(),
        )
        val ex = assertThrows(CancellationException::class.java) {
            runBlocking { repo.generateDiagram(owner, projectId, partId = 3, regenerate = false) }
        }
        assertNotNull(ex)
        val repoReview = RoomPartGenerationRepository(
            FakeRemote(reviewResult = RemoteResult.Cancelled),
            FakeStore(),
        )
        assertThrows(CancellationException::class.java) {
            runBlocking { repoReview.generateReview(owner, projectId, partId = 3, regenerate = false) }
        }
    }

    @Test
    fun `success with cached response persists the same way`() = runBlocking {
        // El repositorio trata igual generado y cacheado: ambos son Success del
        // remoto con el objeto interior ya extraído.
        val remote = FakeRemote(diagramResult = RemoteResult.Success(mermaidObj()))
        val store = FakeStore()
        val repo = RoomPartGenerationRepository(remote, store)

        assertTrue(repo.generateDiagram(owner, projectId, partId = 3, regenerate = false) is GenerationOutcome.Success)
        assertEquals(1, store.patches.size)
        assertFalse(store.patches.isEmpty())
    }

    private companion object {
        /** Objeto interior `mermaid` tal cual lo extrae el remoto. */
        fun mermaidObj(): JsonObject = buildJsonObject {
            put("mermaid_code", "graph TD; A[Intro] --> B[Fin]")
            put("analysis", "análisis")
            put("reading_guide", "guía")
            put("synthesis_decisions", "decisiones")
        }

        /** Objeto interior `review` tal cual lo extrae el remoto. */
        fun reviewObj(): JsonObject = buildJsonObject {
            put("nota", "Sigue practicando")
            put("preguntas", buildJsonObject { put("total", 5) })
        }
    }
}

package com.explainer.app.feature.progress

import com.explainer.app.core.model.LastSubsection
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.local.db.PendingProgressEntity
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Confirmación de filas ACKNOWLEDGED contra el progreso remoto de la lista:
 * solo se eliminan cuando el remoto refleja el valor deseado (global
 * constraints: "se conserva hasta observar el mismo valor en lista/detalle").
 */
class ProgressConfirmationTest {

    private val owner = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val project = "3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f"

    private fun sectionRow(partId: Int, completed: Boolean) = PendingProgressEntity(
        ownerId = owner,
        projectId = project,
        partId = partId,
        tab = "section",
        kindTarget = PendingProgressEntity.KIND_SECTION,
        desiredCompleted = completed,
        syncState = PendingProgressEntity.SYNC_ACKNOWLEDGED,
    )

    private fun subsectionRow(id: String, partId: Int, completed: Boolean) = PendingProgressEntity(
        ownerId = owner,
        projectId = project,
        partId = partId,
        tab = "explicacion",
        kindTarget = PendingProgressEntity.KIND_SUBSECTION_PREFIX + id,
        desiredCompleted = completed,
        syncState = PendingProgressEntity.SYNC_ACKNOWLEDGED,
    )

    private fun lastReadRow(id: String, partId: Int, tab: String = "explicacion", at: String) =
        PendingProgressEntity(
            ownerId = owner,
            projectId = project,
            partId = partId,
            tab = tab,
            kindTarget = PendingProgressEntity.KIND_LAST_READ,
            lastSubsectionId = id,
            lastReadAt = at,
            updatedAt = 1_000L,
            syncState = PendingProgressEntity.SYNC_ACKNOWLEDGED,
        )

    @Test
    fun `seccion completada confirmada cuando el remoto la incluye`() {
        val remote = ReadingProgress(completedParts = setOf(1, 2))
        assertTrue(ProgressConfirmation.isConfirmed(remote, sectionRow(partId = 1, completed = true)))
    }

    @Test
    fun `seccion tombstone confirmada cuando el remoto ya no la incluye`() {
        val remote = ReadingProgress(completedParts = setOf(2))
        assertTrue(ProgressConfirmation.isConfirmed(remote, sectionRow(partId = 1, completed = false)))
    }

    @Test
    fun `seccion no confirmada cuando el remoto no refleja el valor deseado`() {
        val remote = ReadingProgress(completedParts = setOf(2))
        assertFalse(ProgressConfirmation.isConfirmed(remote, sectionRow(partId = 1, completed = true)))
        assertFalse(ProgressConfirmation.isConfirmed(remote, sectionRow(partId = 2, completed = false)))
    }

    @Test
    fun `seccion con desired nulo nunca se confirma`() {
        val row = sectionRow(partId = 1, completed = true).copy(desiredCompleted = null)
        assertFalse(ProgressConfirmation.isConfirmed(ReadingProgress(completedParts = setOf(1)), row))
    }

    @Test
    fun `subseccion completada confirmada cuando el remoto la incluye`() {
        val remote = ReadingProgress(completedSubsections = setOf("subsec-1-a-0"))
        assertTrue(ProgressConfirmation.isConfirmed(remote, subsectionRow("subsec-1-a-0", 1, completed = true)))
    }

    @Test
    fun `subseccion tombstone confirmada cuando el remoto la omite`() {
        val remote = ReadingProgress(completedSubsections = setOf("subsec-1-b-1"))
        assertTrue(ProgressConfirmation.isConfirmed(remote, subsectionRow("subsec-1-a-0", 1, completed = false)))
    }

    @Test
    fun `last-read confirmado cuando remoto coincide en parte id y timestamp no anterior`() {
        val remote = ReadingProgress(
            lastSubsection = LastSubsection(partId = 1, subsectionId = "subsec-1-a-0", tab = ReaderTab.EXPLANATION),
            lastReadAt = "2026-08-01T10:00:02.000Z",
        )
        val row = lastReadRow("subsec-1-a-0", partId = 1, at = "2026-08-01T10:00:01.000Z")
        assertTrue(ProgressConfirmation.isConfirmed(remote, row))
    }

    @Test
    fun `last-read no confirmado si el remoto tiene last-read mas antiguo`() {
        val remote = ReadingProgress(
            lastSubsection = LastSubsection(partId = 1, subsectionId = "subsec-1-a-0", tab = ReaderTab.EXPLANATION),
            lastReadAt = "2026-08-01T10:00:01.000Z",
        )
        val row = lastReadRow("subsec-1-a-0", partId = 1, at = "2026-08-01T10:00:02.000Z")
        assertFalse(ProgressConfirmation.isConfirmed(remote, row))
    }

    @Test
    fun `last-read no confirmado si remoto apunta a otra subseccion parte o tab`() {
        val remote = ReadingProgress(
            lastSubsection = LastSubsection(partId = 1, subsectionId = "subsec-1-b-1", tab = ReaderTab.EXPLANATION),
            lastReadAt = "2026-08-01T10:00:03.000Z",
        )
        assertFalse(ProgressConfirmation.isConfirmed(remote, lastReadRow("subsec-1-a-0", 1, at = "2026-08-01T10:00:01.000Z")))
        assertFalse(
            ProgressConfirmation.isConfirmed(
                remote.copy(lastSubsection = LastSubsection(2, "subsec-1-b-1", ReaderTab.EXPLANATION)),
                lastReadRow("subsec-1-b-1", 1, at = "2026-08-01T10:00:01.000Z"),
            ),
        )
        assertFalse(
            ProgressConfirmation.isConfirmed(
                remote.copy(lastSubsection = LastSubsection(1, "subsec-1-b-1", ReaderTab.DIAGRAM)),
                lastReadRow("subsec-1-b-1", 1, tab = "repaso", at = "2026-08-01T10:00:01.000Z"),
            ),
        )
    }

    @Test
    fun `last-read no confirmado con timestamp remoto invalido o ausente`() {
        val row = lastReadRow("subsec-1-a-0", 1, at = "2026-08-01T10:00:01.000Z")
        val noTimestamp = ReadingProgress(
            lastSubsection = LastSubsection(1, "subsec-1-a-0", ReaderTab.EXPLANATION),
        )
        assertFalse(ProgressConfirmation.isConfirmed(noTimestamp, row))
        val invalidTimestamp = noTimestamp.copy(lastReadAt = "not-a-date")
        assertFalse(ProgressConfirmation.isConfirmed(invalidTimestamp, row))
    }
}

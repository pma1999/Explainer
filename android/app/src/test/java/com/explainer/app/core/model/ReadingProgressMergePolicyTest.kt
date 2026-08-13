package com.explainer.app.core.model

import com.explainer.app.data.remote.loadFixture
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.data.remote.dto.ProjectPayloadCodec
import com.explainer.app.data.remote.mapper.ProjectMapper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ReadingProgressMergePolicyTest {

    private val remoteBase = ReadingProgress(completedParts = setOf(1, 2), completedSubsections = setOf("a"))

    @Test
    fun `union de completadas entre remote local y pending`() {
        val local = ReadingProgress(completedParts = setOf(2, 3), completedSubsections = setOf("b"))
        val pending = PendingProgressOverlay(completedParts = setOf(4), completedSubsections = setOf("c"))
        val merged = ReadingProgressMergePolicy.merge(remoteBase, local, pending)
        assertEquals(setOf(1, 2, 3, 4), merged.completedParts)
        assertEquals(setOf("a", "b", "c"), merged.completedSubsections)
    }

    @Test
    fun `tombstone de seccion explicito gana`() {
        val pending = PendingProgressOverlay(uncompletedParts = setOf(2))
        val merged = ReadingProgressMergePolicy.merge(remoteBase, pending = pending)
        assertEquals(setOf(1), merged.completedParts)
    }

    @Test
    fun `tombstone de subseccion explicito gana`() {
        val pending = PendingProgressOverlay(uncompletedSubsections = setOf("a"))
        val merged = ReadingProgressMergePolicy.merge(remoteBase, pending = pending)
        assertEquals(setOf<String>(), merged.completedSubsections)
    }

    @Test
    fun `tombstone vence tambien a completadas locales`() {
        val local = ReadingProgress(completedParts = setOf(2, 3))
        val pending = PendingProgressOverlay(uncompletedParts = setOf(2))
        val merged = ReadingProgressMergePolicy.merge(remoteBase, local, pending)
        assertEquals(setOf(1, 3), merged.completedParts)
    }

    @Test
    fun `last subsection por last_read_at mas reciente`() {
        val remote = ReadingProgress(
            lastSubsection = LastSubsection(partId = 1, subsectionId = "s1", tab = ReaderTab.EXPLANATION),
            lastReadAt = "2026-01-01T10:00:00Z",
        )
        val local = ReadingProgress(
            lastSubsection = LastSubsection(partId = 2, subsectionId = "s2", tab = ReaderTab.WALKTHROUGH),
            lastReadAt = "2026-02-01T10:00:00Z",
        )
        val pending = PendingProgressOverlay(
            lastSubsection = LastSubsection(partId = 3, subsectionId = "s3", tab = ReaderTab.REVIEW),
            lastReadAt = "2026-03-01T10:00:00Z",
        )
        val merged = ReadingProgressMergePolicy.merge(remote, local, pending)
        assertEquals(LastSubsection(3, "s3", ReaderTab.REVIEW), merged.lastSubsection)
        assertEquals("2026-03-01T10:00:00Z", merged.lastReadAt)
    }

    @Test
    fun `empate de instante es deterministico y prioriza pending local remote`() {
        val remote = ReadingProgress(
            lastSubsection = LastSubsection(1, "r", ReaderTab.EXPLANATION),
            lastReadAt = "2026-01-01T10:00:00.000Z",
        )
        val local = ReadingProgress(
            lastSubsection = LastSubsection(2, "l", ReaderTab.WALKTHROUGH),
            lastReadAt = "2026-01-01T10:00:00Z",
        )
        val mergedLocal = ReadingProgressMergePolicy.merge(remote, local)
        assertEquals("el instante igual prioriza local", LastSubsection(2, "l", ReaderTab.WALKTHROUGH), mergedLocal.lastSubsection)

        val pending = PendingProgressOverlay(
            lastSubsection = LastSubsection(3, "p", ReaderTab.DIAGRAM),
            lastReadAt = "2026-01-01T10:00:00Z",
        )
        val mergedPending = ReadingProgressMergePolicy.merge(remote, local, pending)
        assertEquals("el instante igual prioriza pending", LastSubsection(3, "p", ReaderTab.DIAGRAM), mergedPending.lastSubsection)
    }

    @Test
    fun `instantes invalidos no crashean y pierden contra validos`() {
        val remote = ReadingProgress(
            lastSubsection = LastSubsection(1, "r", ReaderTab.EXPLANATION),
            lastReadAt = "no-es-una-fecha",
        )
        val pending = PendingProgressOverlay(
            lastSubsection = LastSubsection(2, "p", ReaderTab.WALKTHROUGH),
            lastReadAt = "2026-02-01T10:00:00Z",
        )
        val merged = ReadingProgressMergePolicy.merge(remote, pending = pending)
        assertEquals(LastSubsection(2, "p", ReaderTab.WALKTHROUGH), merged.lastSubsection)
        assertEquals("2026-02-01T10:00:00Z", merged.lastReadAt)
    }

    @Test
    fun `sin reloj se conserva el ultimo last subsection por prioridad`() {
        val remote = ReadingProgress(lastSubsection = LastSubsection(1, "r", ReaderTab.EXPLANATION))
        val local = ReadingProgress(lastSubsection = LastSubsection(2, "l", ReaderTab.WALKTHROUGH))
        val merged = ReadingProgressMergePolicy.merge(remote, local)
        assertEquals(LastSubsection(2, "l", ReaderTab.WALKTHROUGH), merged.lastSubsection)
        assertNull(merged.lastReadAt)
    }

    @Test
    fun `merge vacio es determinista y no crashea`() {
        val merged = ReadingProgressMergePolicy.merge(ReadingProgress())
        assertEquals(emptySet<Int>(), merged.completedParts)
        assertEquals(emptySet<String>(), merged.completedSubsections)
        assertNull(merged.lastSubsection)
        assertNull(merged.lastReadAt)
    }

    @Test
    fun `merge se aplica al snapshot descargado con progreso remoto real`() {
        val result = ProjectPayloadCodec.decodeProjectDetail(loadFixture("project_detail_full.json"))
        check(result is RemoteResult.Success)
        val remote = ProjectMapper.toDetailSummary(result.value).readingProgress
        val pending = PendingProgressOverlay(
            completedSubsections = setOf("subsec-1-0-0", "subsec-2-0-0"),
            lastSubsection = LastSubsection(2, "subsec-2-0-0", ReaderTab.EXPLANATION),
            lastReadAt = "2026-08-02T09:00:00Z",
        )
        val merged = ReadingProgressMergePolicy.merge(remote, pending = pending)
        assertEquals(setOf(1, 2), merged.completedParts)
        assertEquals(setOf("subsec-1-0-0", "subsec-1-0-1", "subsec-2-0-0"), merged.completedSubsections)
        assertEquals("2026-08-02T09:00:00Z", merged.lastReadAt)
    }
}

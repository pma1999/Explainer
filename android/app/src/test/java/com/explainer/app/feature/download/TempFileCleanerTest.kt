package com.explainer.app.feature.download

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * Limpieza verificable y SCOPED de temporales (R-T06-06): `File.delete()` es
 * best-effort, así que el borrado se verifica, se reintenta y, si el
 * filesystem se niega, el temporal queda registrado como orphan (nombre con
 * namespace `download-<owner>-<project>-<uuid>.json` bajo cacheDir) para un
 * sweep posterior. El sweep SOLO ve huérfanos del mismo owner/proyecto: el
 * temporal ACTIVO de otro proyecto/owner que comparte cacheDir nunca se toca.
 */
class TempFileCleanerTest {

    private lateinit var tempDir: File

    /** Otro proyecto válido (UUID) para los casos de namespace ajeno. */
    private val otherProjectId = "9f4c2a8d-7e3b-4f1a-8d5c-2b6e9a0f1c3d"

    @Before
    fun setUp() {
        tempDir = File.createTempFile("temp-cleaner", ".dir").apply {
            delete()
            mkdirs()
        }
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    private fun cleaner(deleteFile: (File) -> Boolean = File::delete): TempFileCleaner =
        TempFileCleaner({ tempDir }, deleteFile)

    private fun tempFile(name: String = "download-abc.json"): File =
        File(tempDir, name).apply { writeText("{}") }

    @Test
    fun `delete verified removes the temp file`() {
        val file = tempFile()
        assertTrue(cleaner().deleteVerified(file))
        assertFalse(file.exists())
        assertEquals(0, cleaner().orphansPending)
    }

    @Test
    fun `delete verified retries once before declaring success`() {
        val file = tempFile()
        var calls = 0
        // 1er intento falla (lock transitorio), 2º borra de verdad.
        val c = cleaner { calls++; if (calls >= 2) it.delete() else false }

        assertTrue(c.deleteVerified(file))
        assertFalse(file.exists())
        assertEquals(0, c.orphansPending)
        assertEquals(2, calls)
    }

    @Test
    fun `delete verified registers an orphan when the filesystem refuses`() {
        val file = tempFile()
        val c = cleaner { false }

        assertFalse(c.deleteVerified(file))
        assertTrue("el fichero queda en cache si el FS lo impide", file.exists())
        assertEquals(1, c.orphansPending)
    }

    @Test
    fun `delete verified on null is a no-op success`() {
        assertTrue(cleaner().deleteVerified(null))
    }

    // ------------------------------------------------------------------
    // R-T06-06 (ronda 2): sweep SCOPED por owner/proyecto
    // ------------------------------------------------------------------

    @Test
    fun `sweep deletes an orphaned temp of the same project`() {
        val orphan = tempFile(TempFileCleaner.prefixFor(TEST_OWNER_A, TEST_PROJECT_ID.value) + "dead-uuid.json")

        assertEquals(1, cleaner().sweepOrphans(TEST_OWNER_A, TEST_PROJECT_ID.value))
        assertFalse("el huérfano del mismo proyecto se borra", orphan.exists())
    }

    @Test
    fun `sweep does not delete an active temp of another project`() {
        // Temporal ACTIVO de otro proyecto (mismo owner): debe sobrevivir.
        val active = tempFile(TempFileCleaner.prefixFor(TEST_OWNER_A, otherProjectId) + "live-uuid.json")
        // Huérfano del MISMO proyecto: el sweep lo elimina.
        tempFile(TempFileCleaner.prefixFor(TEST_OWNER_A, TEST_PROJECT_ID.value) + "dead-uuid.json")

        assertEquals(1, cleaner().sweepOrphans(TEST_OWNER_A, TEST_PROJECT_ID.value))
        assertTrue("el temporal ACTIVO de otro proyecto no se borra", active.exists())
    }

    @Test
    fun `sweep does not touch temps of another owner`() {
        val foreign = tempFile(TempFileCleaner.prefixFor(TEST_OWNER_B, TEST_PROJECT_ID.value) + "live-uuid.json")

        assertEquals(0, cleaner().sweepOrphans(TEST_OWNER_A, TEST_PROJECT_ID.value))
        assertTrue("el temporal de otro owner no se borra", foreign.exists())
    }

    @Test
    fun `sweep removes leftover download temporals of the same project only`() {
        val prefix = TempFileCleaner.prefixFor(TEST_OWNER_A, TEST_PROJECT_ID.value)
        tempFile(prefix + "orphan-1.json")
        tempFile(prefix + "orphan-2.json")
        // Temporales de OTRO proyecto y de OTRO owner: intactos pese al sweep.
        tempFile(TempFileCleaner.prefixFor(TEST_OWNER_A, otherProjectId) + "live.json")
        tempFile(TempFileCleaner.prefixFor(TEST_OWNER_B, TEST_PROJECT_ID.value) + "live.json")
        File(tempDir, "keep.txt").writeText("x")
        File(tempDir, "download-other.tmp").writeText("x")

        assertEquals(2, cleaner().sweepOrphans(TEST_OWNER_A, TEST_PROJECT_ID.value))
        assertTrue(File(tempDir, "keep.txt").exists())
        assertTrue(File(tempDir, "download-other.tmp").exists())
        // Los temporales ajenos siguen en cacheDir (2 con el patrón download-*.json).
        assertEquals(2, tempDir.listFiles()?.count { it.name.startsWith("download-") && it.name.endsWith(".json") })
    }

    @Test
    fun `sweep on a missing directory is a no-op`() {
        val missing = File(tempDir, "nope")
        assertEquals(0, TempFileCleaner({ missing }).sweepOrphans(TEST_OWNER_A, TEST_PROJECT_ID.value))
    }
}

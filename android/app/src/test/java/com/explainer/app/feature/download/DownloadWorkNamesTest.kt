package com.explainer.app.feature.download

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class DownloadWorkNamesTest {

    @Test
    fun `unique name is stable and owner scoped`() {
        val nameA = DownloadWorkNames.forProject(TEST_OWNER_A, TEST_PROJECT_ID)
        val nameB = DownloadWorkNames.forProject(TEST_OWNER_B, TEST_PROJECT_ID)

        // Estable: repetir el cálculo da la misma key (KEEP no duplica).
        assertEquals(nameA, DownloadWorkNames.forProject(TEST_OWNER_A, TEST_PROJECT_ID))
        // Owner-scoped: el mismo proyecto de otro owner es otra key.
        assertNotEquals(nameA, nameB)
        assertEquals("download:$TEST_OWNER_A:${TEST_PROJECT_ID.value}", nameA)
    }

    @Test
    fun `tags are owner and project scoped`() {
        assertEquals("download:owner:$TEST_OWNER_A", DownloadWorkNames.ownerTag(TEST_OWNER_A))
        assertEquals("download:project:${TEST_PROJECT_ID.value}", DownloadWorkNames.projectTag(TEST_PROJECT_ID))
        assertNotEquals(DownloadWorkNames.ownerTag(TEST_OWNER_A), DownloadWorkNames.ownerTag(TEST_OWNER_B))
    }
}

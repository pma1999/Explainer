package com.explainer.app.ui.content

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Feedback accesible de enlaces rechazados (remediación R-T08-02): en
 * Markdown el callback de rechazo es obligatorio (no nullable) y se despacha
 * el resultado validado; en resources una URL no aprobada recibe feedback
 * accesible interno (semantics stateDescription con el string del contrato)
 * en lugar de omitirse silenciosamente.
 */
class LinkFeedbackContractTest {

    // ── Contrato de callback de MarkdownBody ──

    @Test
    fun `enlace aprobado se despacha a onLink con el Uri validado`() {
        val opened = mutableListOf<String>()
        val rejected = mutableListOf<String>()
        dispatchExternalLink(
            url = "https://example.com/guia.pdf",
            onLink = { opened += it },
            onRejectedLink = { rejected += it },
        )
        assertEquals(listOf("https://example.com/guia.pdf"), opened)
        assertEquals(emptyList<String>(), rejected)
    }

    @Test
    fun `enlace rechazado se despacha a onRejectedLink con el valor crudo`() {
        val opened = mutableListOf<String>()
        val rejected = mutableListOf<String>()
        dispatchExternalLink(
            url = "javascript:alert(1)",
            onLink = { opened += it },
            onRejectedLink = { rejected += it },
        )
        assertEquals(emptyList<String>(), opened)
        assertEquals(listOf("javascript:alert(1)"), rejected)
    }

    @Test
    fun `url sin autoridad se rechaza y notifica al callback obligatorio`() {
        val rejected = mutableListOf<String>()
        dispatchExternalLink(
            url = "http://",
            onLink = {},
            onRejectedLink = { rejected += it },
        )
        assertEquals(listOf("http://"), rejected)
    }

    // ── Contrato de semántica de resources (feedback interno) ──

    @Test
    fun `resources usa feedback accesible para urls rechazadas con el string del contrato`() {
        val source = contentSource("ResourcesContent.kt").readText()
        assertTrue("debe aplicar stateDescription accesible", source.contains("stateDescription"))
        assertTrue(
            "debe usar el string de rechazo del contrato",
            source.contains("content_link_rejected_message"),
        )
        assertTrue(
            "el affordance aprobado debe despachar el resultado validado",
            source.contains("SafeExternalUrlPolicy.safeExternalUriStringOrNull"),
        )
    }

    @Test
    fun `markdown obliga al callback de rechazo no nullable`() {
        val source = contentSource("MarkdownBody.kt").readText()
        assertTrue(
            "onRejectedLink debe ser obligatorio (no nullable)",
            source.contains("onRejectedLink: (String) -> Unit"),
        )
        assertFalse(
            "no debe admitir el tipo nullable",
            source.contains("onRejectedLink: ((String) -> Unit)?"),
        )
    }

    private fun contentSource(name: String): File =
        listOf(
            File(System.getProperty("user.dir") ?: "", "src/main/java/com/explainer/app/ui/content"),
            File("src/main/java/com/explainer/app/ui/content"),
            File("app/src/main/java/com/explainer/app/ui/content"),
        ).firstOrNull { it.isDirectory }
            ?.resolve(name)
            ?: error("fuente ui/content no encontrada")
}

package com.explainer.app.ui.content

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Política de URLs externas (T08): solo `http`/`https` absolutos salen de la
 * app mediante una app externa. Cualquier otro esquema (o ausencia de esquema)
 * se rechaza antes de tocar un UriHandler.
 */
class SafeExternalUrlPolicyTest {

    @Test
    fun `acepta https absoluto`() {
        assertTrue(SafeExternalUrlPolicy.isSafeExternal("https://example.com/guia.pdf"))
        assertTrue(SafeExternalUrlPolicy.isSafeExternal("https://example.com/a?b=1#c"))
        assertTrue(SafeExternalUrlPolicy.isSafeExternal("HTTPS://MAYUSCULAS.ORG/x"))
    }

    @Test
    fun `acepta http absoluto`() {
        assertTrue(SafeExternalUrlPolicy.isSafeExternal("http://example.com/recurso"))
    }

    @Test
    fun `rechaza esquemas peligrosos o no navegables`() {
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("javascript:alert(1)"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("data:text/html,<script>1</script>"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("file:///etc/passwd"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("content://com.example.provider/rows"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("ftp://example.com/x"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("tel:+34600000000"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("mailto:test@example.com"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("intent://example.com"))
    }

    @Test
    fun `rechaza urls sin esquema o relativas`() {
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("example.com/path"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("//protocol-relative.com/x"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("/relative/path"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("invalid"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http:sin-barras"))
    }

    @Test
    fun `rechaza nulos, vacios y espacios`() {
        assertFalse(SafeExternalUrlPolicy.isSafeExternal(null))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal(""))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("   "))
        // El trim permite URLs http/https con espacios laterales.
        assertTrue(SafeExternalUrlPolicy.isSafeExternal("  https://example.com  "))
    }

    @Test
    fun `un enlace markdown con prefijo peligroso camuflado se rechaza`() {
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("javascript:https://example.com"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("data:https://example.com"))
    }

    @Test
    fun `safeUriOrNull devuelve null fuera de la politica`() {
        assertNull(SafeExternalUrlPolicy.safeUriOrNull("javascript:alert(1)"))
        assertNull(SafeExternalUrlPolicy.safeUriOrNull("file:///x"))
        assertNull(SafeExternalUrlPolicy.safeUriOrNull(""))
        assertNull(SafeExternalUrlPolicy.safeUriOrNull(null))
    }

    // ── R-T08-03: autoridad/host obligatorios y entradas inválidas ──

    @Test
    fun `rechaza urls sin autoridad o con autoridad vacia`() {
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http://"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("https://"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http:///path"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http://?q=1"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http://#frag"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http://:8080/x"))
    }

    @Test
    fun `rechaza host invalido o con espacios`() {
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http://exa mple.com"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("https:// example.com/x"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http://."))
    }

    @Test
    fun `rechaza entradas con caracteres de control`() {
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("https://example.com/\u0000"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("http://exa\u0007mple.com"))
        // Control embebido en el medio (un \n final es whitespace de trim y se
        // acepta igual que los espacios laterales).
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("https://example.com/a\nb"))
        assertFalse(SafeExternalUrlPolicy.isSafeExternal("https://example.com/\tpath"))
    }

    @Test
    fun `acepta autoridad con puerto y conserva host y path validados`() {
        assertTrue(SafeExternalUrlPolicy.isSafeExternal("http://example.com:8080/x?y=1#z"))
        val validated = SafeExternalUrlPolicy.safeExternalUriStringOrNull("http://example.com:8080/x")
        assertEquals("http://example.com:8080/x", validated)
        val host = SafeExternalUrlPolicy.safeExternalUriStringOrNull("https://example.com/guia.pdf")
        assertEquals("https://example.com/guia.pdf", host)
    }

    @Test
    fun `la validacion es una sola pasada pura sin depender de android Uri`() {
        // El string validado se reutiliza para construir el Uri en el límite
        // (safeUriOrNull); nunca se revalida con un método distinto.
        assertNull(SafeExternalUrlPolicy.safeExternalUriStringOrNull("http://"))
        assertNull(SafeExternalUrlPolicy.safeExternalUriStringOrNull("javascript:alert(1)"))
        assertNull(SafeExternalUrlPolicy.safeExternalUriStringOrNull("  "))
        assertNull(SafeExternalUrlPolicy.safeExternalUriStringOrNull(null))
    }
}

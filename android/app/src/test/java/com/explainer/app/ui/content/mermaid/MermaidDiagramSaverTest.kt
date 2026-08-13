package com.explainer.app.ui.content.mermaid

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Base64

/**
 * Decode del data URL PNG (canal de chunks T-EXPORT): el núcleo puro de
 * [MermaidDiagramSaver.decodePngDataUrl] valida el prefijo y decodifica con
 * el decoder inyectado — JVM puro, sin `android.util.Base64` (stub en tests
 * locales). El prefijo correcto, el prefijo incorrecto y el base64 inválido.
 */
class MermaidDiagramSaverTest {

    private val jvmBase64 = Base64.getDecoder()

    @Test
    fun `decodifica un data url png valido`() {
        val payload = "diagrama de prueba".toByteArray(Charsets.UTF_8)
        val dataUrl = "data:image/png;base64," + Base64.getEncoder().encodeToString(payload)
        assertArrayEquals(
            payload,
            MermaidDiagramSaver.decodePngDataUrl(dataUrl, jvmBase64::decode),
        )
    }

    @Test
    fun `rechaza prefijos incorrectos`() {
        assertNull(
            "otro tipo de data URL no es un PNG",
            MermaidDiagramSaver.decodePngDataUrl("data:image/jpeg;base64,aG9sYQ==", jvmBase64::decode),
        )
        assertNull(
            "base64 sin prefijo no es un data URL",
            MermaidDiagramSaver.decodePngDataUrl("iVBORw0KGgo=", jvmBase64::decode),
        )
    }

    @Test
    fun `rechaza base64 invalido`() {
        assertNull(
            MermaidDiagramSaver.decodePngDataUrl("data:image/png;base64,!!!not-base64!!!", jvmBase64::decode),
        )
    }
}

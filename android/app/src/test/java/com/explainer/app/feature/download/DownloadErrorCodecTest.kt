package com.explainer.app.feature.download

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DownloadErrorCodecTest {

    @Test
    fun `plain categories round trip`() {
        val errors = listOf(
            DownloadError.Network,
            DownloadError.AuthRequired,
            DownloadError.NotFound,
            DownloadError.NotEnoughSpace,
        )
        for (error in errors) {
            val wire = DownloadErrorCodec.encode(error)
            assertEquals(error, DownloadErrorCodec.decode(wire))
        }
    }

    @Test
    fun `payload and permanent categories keep the short reason`() {
        assertEquals("invalid_payload:json", DownloadErrorCodec.encode(DownloadError.InvalidPayload("json")))
        assertEquals(
            DownloadError.InvalidPayload("json"),
            DownloadErrorCodec.decode("invalid_payload:json"),
        )
        assertEquals("permanent:http:400", DownloadErrorCodec.encode(DownloadError.Permanent("http:400")))
        assertEquals(
            DownloadError.Permanent("http:400"),
            DownloadErrorCodec.decode("permanent:http:400"),
        )
        assertEquals(
            DownloadError.Local("file"),
            DownloadErrorCodec.decode("local:file"),
        )
    }

    @Test
    fun `empty or missing wire decodes to null`() {
        assertNull(DownloadErrorCodec.decode(null))
        assertNull(DownloadErrorCodec.decode(""))
    }

    @Test
    fun `unknown category decodes safely as permanent`() {
        assertEquals(DownloadError.Permanent("unknown:future"), DownloadErrorCodec.decode("future:whatever"))
        assertEquals(DownloadError.Permanent("unknown:future"), DownloadErrorCodec.decode("future"))
    }
}

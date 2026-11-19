package app.regista

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.util.concurrent.CancellationException

class BackupRulesTest {
    @Test fun voiceNotesRingtonesAndVideosAreMediaRegardlessOfFolderOrMusicFlag() {
        assertEquals("audio", BackupRules.kind("audio/opus", "WhatsApp voice note"))
        assertEquals("audio", BackupRules.kind("application/octet-stream", "ringtone.M4A"))
        assertEquals("image", BackupRules.kind("application/octet-stream", "raw.NEF"))
        assertEquals("video", BackupRules.kind("video/mp4; codecs=hvc1", "recording"))
        assertEquals("video", BackupRules.kind("", "film.mkv"))
        assertNull(BackupRules.kind("application/pdf", "document.pdf"))
    }

    @Test fun hashingMeasuresUnknownSizesAndFindsContentDuplicates() {
        val bytes = "abc".toByteArray()
        val first = BackupRules.hash(ByteArrayInputStream(bytes)) { false }
        val second = BackupRules.hash(ByteArrayInputStream(bytes.copyOf())) { false }
        assertEquals(3, first.bytes.toInt())
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", first.sha256)
        assertEquals(first, second)
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", BackupRules.hash(ByteArrayInputStream(byteArrayOf())) { false }.sha256)
    }

    @Test fun cancellingHashingClosesTheSourceWithoutReturningADigest() {
        var closed = false
        val input = object : ByteArrayInputStream(ByteArray(600_000)) {
            override fun close() { closed = true; super.close() }
        }
        var checks = 0
        try {
            BackupRules.hash(input) { ++checks >= 2 }
            throw AssertionError("Cancelled hash returned a digest")
        } catch (_: CancellationException) { assertTrue(closed) }
    }

    @Test fun outgoingProgressCountsActualBytesAndDoesNotBufferTheFile() {
        var reported = 0L
        val bytes = ByteArray(800_000) { (it % 253).toByte() }
        val outgoing = BackupRules.Sending(ByteArrayInputStream(bytes), { false }) { reported = it }
        val copy = outgoing.use { it.readBytes() }
        assertTrue(bytes.contentEquals(copy))
        assertEquals(bytes.size.toLong(), reported)
    }

    @Test(expected = CancellationException::class) fun cancellationStopsTheNextOutgoingChunk() {
        val outgoing = BackupRules.Sending(ByteArrayInputStream(ByteArray(1_000)), { true }) {}
        outgoing.use { it.read(ByteArray(64)) }
    }
}

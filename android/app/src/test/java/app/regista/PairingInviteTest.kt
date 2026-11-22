package app.regista

import org.junit.Assert.*
import org.junit.Test

class PairingInviteTest {
    private val fingerprint = "ab".repeat(32)
    private val valid = "regista://pair?a=192.168.1.23,10.0.0.2&p=8443&s=invito_123&f=$fingerprint&n=PC+di+casa"

    @Test fun readsPcQrAndManualWhitespace() {
        val invite = readInvite("  $valid\n")!!
        assertEquals(listOf("192.168.1.23", "10.0.0.2"), invite.addresses)
        assertEquals(8443, invite.port)
        assertEquals("PC di casa", invite.computer)
        assertEquals(fingerprint, invite.fingerprint)
    }

    @Test fun rejectsOtherQrDestinations() {
        for (text in listOf("https://example.com", valid.replace("//pair?", "//other?"), valid.replace("//pair?", "//user@pair?"), valid.replace("pair?", "pair/path?"), "$valid#fragment", "regista:pair")) {
            assertNull(text, readInvite(text))
        }
    }

    @Test fun rejectsBrokenAndOversizedPayloadsWithoutThrowing() {
        for (text in listOf("", "not a link", "$valid&x=%ZZ", valid.replace("regista:", "regista%:"), "a".repeat(8193))) assertNull(readInvite(text))
    }

    @Test fun rejectsPublicAddressesAndDnsNames() {
        for (address in listOf("8.8.8.8", "example.com", "127.0.0.1", "192.168.1.256", "192.168.+1.2")) {
            assertNull(readInvite(valid.replace("192.168.1.23,10.0.0.2", address)))
        }
    }

    @Test fun keepsOnlyPrivateAddressesAndDeduplicates() {
        val invite = readInvite(valid.replace("192.168.1.23,10.0.0.2", "8.8.8.8,192.168.1.23,192.168.1.23"))!!
        assertEquals(listOf("192.168.1.23"), invite.addresses)
        assertTrue(isPrivate("172.16.0.1"))
        assertTrue(isPrivate("100.64.0.1"))
        assertFalse(isPrivate("172.32.0.1"))
    }

    @Test fun rejectsMissingOrAmbiguousParameters() {
        for (text in listOf(valid.replace("s=invito_123", "s="), "$valid&p=443", valid.replace("&p=8443", ""), valid.replace("s=invito_123", "s=%0A"))) assertNull(readInvite(text))
    }

    @Test fun validatesPortAndPinnedCertificate() {
        for (port in listOf("0", "-1", "65536", "hello")) assertNull(readInvite(valid.replace("p=8443", "p=$port")))
        assertNull(readInvite(valid.replace(fingerprint, "z".repeat(64))))
        assertNull(readInvite(valid.replace(fingerprint, "abc")))
        assertEquals(fingerprint, readInvite(valid.replace(fingerprint, fingerprint.uppercase()))!!.fingerprint)
    }

    @Test fun keepsComputerNameOnOneLine() {
        assertEquals("Il mio PC", readInvite(valid.replace("PC+di+casa", "Il+mio+PC%0A%0D%00"))!!.computer)
        assertEquals(40, readInvite(valid.replace("PC+di+casa", "x".repeat(80)))!!.computer.length)
    }
}

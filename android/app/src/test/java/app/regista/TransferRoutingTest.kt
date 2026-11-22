package app.regista

import org.junit.Assert.*
import org.junit.Test

class TransferRoutingTest {
    private val networks=listOf(ImportSubnet("wlan0","192.168.1.17",24),ImportSubnet("rndis0","192.168.42.1",24))
    @Test fun usbIsPreferredEvenIfWifiWorkedLast() {
        assertEquals(listOf("192.168.42.129","192.168.1.57"),TransferRouting.order(listOf("192.168.1.57","192.168.42.129"),networks))
    }
    @Test fun withoutUsbNetworkTheKnownWifiRemainsUsable() {
        assertEquals("wifi",TransferRouting.transport("192.168.1.57",networks.take(1)))
        assertEquals("local",TransferRouting.transport("192.168.42.129",networks.take(1)))
    }
    @Test fun publicOrNamedDestinationsAreNotDiscoveryCandidates() {
        assertEquals(listOf("192.168.1.57"),TransferRouting.order(listOf("8.8.8.8","example.com","192.168.1.57"),networks))
    }
    @Test fun subnetMatchingUsesTheActualPrefix() {
        val subnet=ImportSubnet("usb0","192.168.42.1",22)
        assertTrue(TransferRouting.contains(subnet,"192.168.43.50"))
        assertFalse(TransferRouting.contains(subnet,"192.168.44.50"))
    }
    @Test fun vpnAndChargingAreNotClaimedAsUsbNetwork() {
        assertFalse(TransferRouting.usb("tun0"))
        assertFalse(TransferRouting.usb("wlan0"))
        assertTrue(TransferRouting.usb("ncm0"))
    }
}

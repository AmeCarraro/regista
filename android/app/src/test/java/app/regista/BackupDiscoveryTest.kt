package app.regista

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class BackupDiscoveryTest {
    @Test fun usbTetheringAndLocalAdaptersAreDiscovered() {
        listOf("wlan0", "eth0", "rndis0", "rndis_data0", "usb0", "ncm0").forEach { assertTrue(BackupNetwork.localInterface(it)) }
    }
    @Test fun mobileAndVpnInterfacesAreNotScanned() {
        listOf("rmnet_data0", "ccmni0", "tun0", "lo", "unknown").forEach { assertFalse(BackupNetwork.localInterface(it)) }
    }
    @Test fun protectedAndroidTreesAreExcluded() {
        listOf("primary:Android/data", "primary:Android/data/com.example", "1A2B:Android/obb/game", "primary:ANDROID\\DATA\\app").forEach {
            assertTrue(BackupFolderPolicy.privateAndroidPath(it))
        }
        listOf("primary:Android/media/com.whatsapp", "primary:DCIM", "primary:Documents/Android/data-not-private").forEach {
            assertFalse(BackupFolderPolicy.privateAndroidPath(it))
        }
    }
    @Test fun providerNamesStaySingleReadablePathSegments() {
        assertEquals("cartella", BackupFolderPolicy.label(".."))
        assertEquals("vacanze_2026", BackupFolderPolicy.label("vacanze/2026"))
        assertEquals("Musica", BackupFolderPolicy.label("Mu\u0000sica"))
    }
}

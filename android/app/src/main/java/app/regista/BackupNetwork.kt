package app.regista

/** Local discovery excludes mobile/VPN interfaces; private-address and certificate checks still apply. */
object BackupNetwork {
    fun localInterface(name: String): Boolean = listOf("wlan", "eth", "usb", "rndis", "ncm")
        .any { name.startsWith(it) }
}

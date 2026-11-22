package app.regista

import java.net.URI
import java.net.URLDecoder

/** The PC's addresses, pinned certificate and short-lived invitation secret. */
class Invite(val addresses: List<String>, val port: Int, val secret: String, val fingerprint: String, val computer: String)

fun isPrivate(address: String): Boolean {
    val parts = address.split(".").map { part ->
        if (part.isEmpty() || part.any { it !in '0'..'9' }) return false
        part.toIntOrNull() ?: return false
    }
    if (parts.size != 4 || parts.any { it !in 0..255 }) return false
    val (first, second) = parts
    return first == 10 || (first == 172 && second in 16..31) || (first == 192 && second == 168) || (first == 100 && second in 64..127)
}

/** Shared by camera, pasted links and external deep links; malformed QR contents are ordinary misses. */
fun readInvite(text: String): Invite? {
    if (text.length > 8192) return null
    return try {
        val link = URI(text.trim())
        if (link.scheme != "regista" || link.rawAuthority != "pair" || !link.path.isNullOrEmpty() || link.rawFragment != null) return null
        val parameters = mutableMapOf<String, String>()
        for (part in (link.rawQuery ?: return null).split('&')) {
            val key = URLDecoder.decode(part.substringBefore('='), "UTF-8")
            val value = URLDecoder.decode(part.substringAfter('=', ""), "UTF-8")
            if (parameters.put(key, value) != null) return null
        }
        val addresses = parameters["a"]?.split(',')?.filter(::isPrivate)?.distinct() ?: return null
        val port = parameters["p"]?.toIntOrNull() ?: return null
        val secret = parameters["s"] ?: return null
        val fingerprint = parameters["f"] ?: return null
        if (addresses.isEmpty() || port !in 1..65535 || secret.isBlank() || secret.length > 512 || secret.any { it.isISOControl() }) return null
        if (!fingerprint.matches(Regex("[0-9a-fA-F]{64}"))) return null
        val computer = (parameters["n"] ?: "").filter { !it.isISOControl() }.trim().take(40)
        Invite(addresses, port, secret, fingerprint.lowercase(), computer)
    } catch (_: IllegalArgumentException) {
        null
    } catch (_: java.net.URISyntaxException) {
        null
    }
}

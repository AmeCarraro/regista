package app.regista

import android.content.Context
import android.net.Uri
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.net.SocketException
import java.net.URL
import java.security.GeneralSecurityException
import java.security.KeyStore
import java.security.ProviderException
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * What the link shown by the computer says: where the computer is, how to recognise it, and the
 * secret that lets this phone in. `addresses` holds only the ones inside a private network.
 */
class Invite(val addresses: List<String>, val port: Int, val secret: String, val fingerprint: String, val computer: String)

/**
 * Whether an address is inside a private network: the one at home, or a private link between
 * one's own devices. The user's computer is never out on the open internet, so a link that
 * points there is not the user's: it is someone who wants this phone's pictures.
 */
fun isPrivate(address: String): Boolean {
    val parts = address.split(".").map { it.toIntOrNull() ?: return false }
    if (parts.size != 4 || parts.any { it !in 0..255 }) return false
    val (first, second) = parts
    return first == 10 || (first == 172 && second in 16..31) || (first == 192 && second == 168) || (first == 100 && second in 64..127)
}

/** Reads a link like regista://pair?a=192.168.1.23&p=8443&s=...&f=... Anything else is not an invitation. */
fun readInvite(text: String): Invite? {
    val link = Uri.parse(text.trim())
    if (link.scheme != "regista" || link.host != "pair") return null
    val addresses = link.getQueryParameter("a")?.split(",")?.filter { it.isNotBlank() } ?: return null
    val port = link.getQueryParameter("p")?.toIntOrNull() ?: return null
    val secret = link.getQueryParameter("s") ?: return null
    val fingerprint = link.getQueryParameter("f") ?: return null
    if (addresses.isEmpty() || secret.isEmpty() || fingerprint.length != 64) return null
    // the name is shown to the user in the question that pairs: one line of it, so that it cannot pass for the rest of the question
    val computer = (link.getQueryParameter("n") ?: "").filter { !it.isISOControl() }.trim().take(40)
    return Invite(addresses.filter(::isPrivate), port, secret, fingerprint, computer)
}

/**
 * The other addresses of the network this phone is on by Wi-Fi or by cable, where the computer may be: the same
 * first three numbers as the phone's own, and the last from 1 to 254. None on the mobile network.
 */
fun neighbours(): List<String> = try {
    NetworkInterface.getNetworkInterfaces().toList()
        .filter { it.isUp && !it.isLoopback && (it.name.startsWith("wlan") || it.name.startsWith("eth")) }
        .flatMap { it.inetAddresses.toList() }
        .filterIsInstance<Inet4Address>()
        .mapNotNull { it.hostAddress }
        .filter(::isPrivate)
        .flatMap { own -> (1..254).map { "${own.substringBeforeLast('.')}.$it" }.filter { it != own } }
        .distinct()
} catch (problem: SocketException) {
    emptyList()
}

/** Which of these addresses take a connection at the port, within a moment: many are knocked at together. */
fun listening(addresses: List<String>, port: Int): List<String> {
    val pool = Executors.newFixedThreadPool(32)
    try {
        val knocks = addresses.map { address ->
            pool.submit(Callable {
                try {
                    Socket().use { it.connect(InetSocketAddress(address, port), 400) }
                    address
                } catch (closed: IOException) {
                    null
                }
            })
        }
        return knocks.mapNotNull { knock -> runCatching { knock.get() }.getOrNull() }
    } finally {
        pool.shutdownNow()
    }
}

fun fingerprintOf(certificate: X509Certificate): String =
    MessageDigest.getInstance("SHA-256").digest(certificate.encoded).joinToString("") { "%02x".format(it) }

/** The computer said no: the status says how, the message is the computer's own, for the user. */
class Refused(val status: Int, message: String) : IOException(message)

/**
 * The computer, as this phone reaches it. Every exchange is encrypted, and accepted only
 * if the computer shows the certificate whose fingerprint was in the link: no other
 * computer on the network can pass for it.
 */
class Computer(val address: String, private val port: Int, private val fingerprint: String, private val key: String) {
    private val sockets = SSLContext.getInstance("TLS").apply {
        init(null, arrayOf(object : X509TrustManager {
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                // the certificate is the computer's own, signed by nobody: what makes it good is its fingerprint
                if (!fingerprintOf(chain[0]).equals(fingerprint, ignoreCase = true)) {
                    throw CertificateException("this is not the computer this phone was paired with")
                }
            }

            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = throw CertificateException()
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }), null)
    }.socketFactory

    // the name in the certificate does not matter: the fingerprint has already said who it is
    private val anyName = HostnameVerifier { _, _ -> true }

    val home get() = "https://$address:$port/"

    /** What this phone shows to be let in, for the one request the app cannot make itself: the first load of the page. */
    fun proof(): Map<String, String> = mapOf("Authorization" to "Bearer $key")

    private fun open(method: String, path: String): HttpsURLConnection {
        val connection = URL("https://$address:$port$path").openConnection() as HttpsURLConnection
        connection.sslSocketFactory = sockets
        connection.hostnameVerifier = anyName
        connection.requestMethod = method
        connection.connectTimeout = 4000
        connection.readTimeout = 60000
        if (key.isNotEmpty()) connection.setRequestProperty("Authorization", "Bearer $key")
        // which Android this is: what the computer offers depends on it (a trash, from Android 11)
        connection.setRequestProperty("X-Regista-Android", Build.VERSION.SDK_INT.toString())
        return connection
    }

    private fun answer(connection: HttpsURLConnection): JSONObject {
        try {
            val status = connection.responseCode
            val text = (if (status < 400) connection.inputStream else connection.errorStream)?.bufferedReader()?.readText() ?: ""
            val said = runCatching { JSONObject(text) }.getOrDefault(JSONObject())
            if (status >= 400) throw Refused(status, said.optString("detail", "errore $status"))
            return said
        } finally {
            connection.disconnect()
        }
    }

    /** Asks the computer something, with a JSON body or none, and returns its JSON answer. */
    fun ask(method: String, path: String, body: JSONObject? = null): JSONObject {
        val connection = open(method, path)
        if (body != null) {
            val bytes = body.toString().toByteArray()
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setFixedLengthStreamingMode(bytes.size)
            connection.outputStream.use { it.write(bytes) }
        }
        return answer(connection)
    }

    /** Asks the computer something whose answer comes a line at a time, each a JSON object: each goes to `each` as it arrives. */
    fun lines(path: String, body: JSONObject, each: (JSONObject) -> Unit) {
        val connection = open("POST", path)
        try {
            val bytes = body.toString().toByteArray()
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setFixedLengthStreamingMode(bytes.size)
            connection.outputStream.use { it.write(bytes) }
            val status = connection.responseCode
            if (status >= 400) {
                val said = runCatching { JSONObject(connection.errorStream?.bufferedReader()?.readText() ?: "") }.getOrDefault(JSONObject())
                throw Refused(status, said.optString("detail", "errore $status"))
            }
            connection.inputStream.bufferedReader().useLines { lines -> lines.filter { it.isNotBlank() }.forEach { each(JSONObject(it)) } }
        } finally {
            connection.disconnect()
        }
    }

    /** Takes a file from the computer, with the fingerprint the computer gives of it, and hands both to `take`. */
    fun fetch(path: String, take: (InputStream, String) -> Boolean): Boolean {
        val connection = open("GET", path)
        connection.readTimeout = 180000
        try {
            val status = connection.responseCode
            if (status >= 400) {
                val said = runCatching { JSONObject(connection.errorStream?.bufferedReader()?.readText() ?: "") }.getOrDefault(JSONObject())
                throw Refused(status, said.optString("detail", "errore $status"))
            }
            val fingerprint = connection.getHeaderField("X-Regista-Sha256") ?: throw IOException("the computer did not say what the file is")
            return take(connection.inputStream, fingerprint)
        } finally {
            connection.disconnect()
        }
    }

    /** Sends a file as it is, without holding it all in memory, with the fingerprint the computer checks it against. */
    fun send(path: String, length: Long, source: InputStream, fingerprint: String): JSONObject {
        val connection = open("PUT", path)
        connection.doOutput = true
        connection.readTimeout = 180000
        connection.setRequestProperty("Content-Type", "application/octet-stream")
        connection.setRequestProperty("X-Regista-Sha256", fingerprint)
        if (length > 0) connection.setFixedLengthStreamingMode(length) else connection.setChunkedStreamingMode(64 * 1024)
        source.use { input -> connection.outputStream.use { output -> input.copyTo(output, 64 * 1024) } }
        return answer(connection)
    }
}

/**
 * What this phone remembers of the computer it was paired with. In the app's own storage, which no
 * other app can read; and the key that lets the phone into the computer is kept there locked, by a
 * lock that Android keeps in its own safe and never lets out of it (the Android Keystore): a copy of
 * the app's files does not carry a key anyone can use.
 */
class Memory(context: Context) {
    private val kept = context.getSharedPreferences("computer", Context.MODE_PRIVATE)

    init {
        // a key kept before it was locked is locked now, and the open one goes; on a phone whose safe does not work, it stays as it was
        kept.getString("key", null)?.let { open -> lock(open)?.let { locked -> kept.edit().putString("locked_key", locked).remove("key").commit() } }
    }

    val paired get() = kept.contains("locked_key") || kept.contains("key")

    /** The key that lets this phone into the computer; empty if there is none, or if it cannot be opened any more. */
    private val key get() = kept.getString("locked_key", null)?.let(::unlock) ?: kept.getString("key", null) ?: ""

    /** When the user last opened the computer's tab with the phone's own lock, in milliseconds. */
    val unlockedAt get() = kept.getLong("unlocked_at", 0)

    fun unlocked() {
        kept.edit().putLong("unlocked_at", System.currentTimeMillis()).apply()
    }
    val computer get() = kept.getString("computer", "") ?: ""
    val fingerprint get() = kept.getString("fingerprint", "") ?: ""

    /** The ways to reach the computer, the one that worked last time first. */
    private val addresses get() = (kept.getString("addresses", "") ?: "").split(",").filter { it.isNotBlank() }

    fun remember(invite: Invite, address: String, key: String, computer: String) {
        val ordered = listOf(address) + invite.addresses.filter { it != address }
        kept.edit()
            .putString("addresses", ordered.joinToString(","))
            .putInt("port", invite.port)
            .putString("fingerprint", invite.fingerprint)
            .apply {
                val locked = lock(key)
                if (locked != null) putString("locked_key", locked).remove("key") else putString("key", key).remove("locked_key")
            }
            .putString("computer", computer.ifBlank { invite.computer })
            .apply()
    }

    /** Forgets the computer. What the user asked of the phone itself stays: the models, if they were wanted. */
    fun forget() {
        val sight = wantsSight
        kept.edit().clear().putBoolean("sight", sight).apply()
    }

    /** Whether the new pictures of this phone go to the computer by themselves, on a Wi-Fi where it answers (CopyJob). */
    var autoCopy: Boolean
        get() = kept.getBoolean("auto", false)
        set(value) = kept.edit().putBoolean("auto", value).apply()

    /** The newest picture there was when they began to go by themselves, or the last one put in line since: the ones after it are new. */
    var autoAfter: Long
        get() = kept.getLong("auto_after", Long.MAX_VALUE)
        set(value) = kept.edit().putLong("auto_after", value).apply()

    /** When pictures last went to the computer by themselves, in milliseconds, and how many. */
    val copiedAt get() = kept.getLong("copied_at", 0)
    val copiedCount get() = kept.getInt("copied", 0)

    fun copied(count: Int) {
        kept.edit().putLong("copied_at", System.currentTimeMillis()).putInt("copied", count).apply()
    }

    /** Whether the user asked for the models with which the phone looks at pictures by itself: they come from the computer. */
    var wantsSight: Boolean
        get() = kept.getBoolean("sight", false)
        set(value) = kept.edit().putBoolean("sight", value).apply()

    /** The pictures the user chose on this phone to go to the computer, by the phone's numbers for them, until the computer takes them. */
    fun offers(): List<String> {
        val list = runCatching { JSONArray(kept.getString("offers", "[]")) }.getOrDefault(JSONArray())
        return (0 until list.length()).map { list.getString(it) }
    }

    // the app and the copying by themselves each have a Memory: the line of pictures is changed by one at a time
    fun offer(media: List<String>) = synchronized(LINE) {
        kept.edit().putString("offers", JSONArray((offers() + media).distinct()).toString()).commit()
    }

    fun offered(media: List<String>) = synchronized(LINE) {
        val sent = media.toSet()
        kept.edit().putString("offers", JSONArray(offers().filter { it !in sent }).toString()).commit()
    }


    /** The port of the computer's door for the phones. */
    val port get() = kept.getInt("port", 8443)

    /** The computer at each of its addresses, to be tried in turn; or at others, where it may be now. */
    fun ways(at: List<String> = addresses): List<Computer> {
        val key = key
        return at.map { Computer(it, port, fingerprint, key) }
    }

    fun worked(address: String) {
        kept.edit().putString("addresses", (listOf(address) + addresses.filter { it != address }).joinToString(",")).apply()
    }

    private companion object {
        val LINE = Any()

        /** The name of the lock in Android's safe. */
        const val SAFE = "regista"

        /** The lock, made the first time: AES in Android's safe, which uses it there and never gives it out. */
        fun safe(): SecretKey {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (store.getKey(SAFE, null) as? SecretKey)?.let { return it }
            val maker = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            maker.init(
                KeyGenParameterSpec.Builder(SAFE, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            return maker.generateKey()
        }

        /** A text locked: what Android's lock made of it, after the random start it was locked with. Null where the safe does not work. */
        fun lock(text: String): String? = try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, safe()) }
            Base64.encodeToString(cipher.iv + cipher.doFinal(text.toByteArray()), Base64.NO_WRAP)
        } catch (broken: GeneralSecurityException) {
            null
        } catch (broken: ProviderException) {
            null
        }

        fun unlock(text: String): String? = try {
            val bytes = Base64.decode(text, Base64.NO_WRAP)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, safe(), GCMParameterSpec(128, bytes, 0, 12)) }
            String(cipher.doFinal(bytes, 12, bytes.size - 12))
        } catch (broken: GeneralSecurityException) {
            null
        } catch (broken: IllegalArgumentException) {
            null
        } catch (broken: ProviderException) {
            null
        }
    }
}

package app.regista

import android.content.Context
import android.net.Uri
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** What the link shown by the computer says: where the computer is, how to recognise it, and the secret that lets this phone in. */
class Invite(val addresses: List<String>, val port: Int, val secret: String, val fingerprint: String, val computer: String)

/** Reads a link like regista://pair?a=192.168.1.23&p=8443&s=...&f=... Anything else is not an invitation. */
fun readInvite(text: String): Invite? {
    val link = Uri.parse(text.trim())
    if (link.scheme != "regista" || link.host != "pair") return null
    val addresses = link.getQueryParameter("a")?.split(",")?.filter { it.isNotBlank() } ?: return null
    val port = link.getQueryParameter("p")?.toIntOrNull() ?: return null
    val secret = link.getQueryParameter("s") ?: return null
    val fingerprint = link.getQueryParameter("f") ?: return null
    if (addresses.isEmpty() || secret.isEmpty() || fingerprint.length != 64) return null
    return Invite(addresses, port, secret, fingerprint, link.getQueryParameter("n") ?: "")
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

    /** Sends a file as it is, without holding it all in memory. */
    fun send(path: String, length: Long, source: InputStream): JSONObject {
        val connection = open("PUT", path)
        connection.doOutput = true
        connection.readTimeout = 180000
        connection.setRequestProperty("Content-Type", "application/octet-stream")
        if (length > 0) connection.setFixedLengthStreamingMode(length) else connection.setChunkedStreamingMode(64 * 1024)
        source.use { input -> connection.outputStream.use { output -> input.copyTo(output, 64 * 1024) } }
        return answer(connection)
    }
}

/** What this phone remembers of the computer it was paired with. In the app's own storage, which no other app can read. */
class Memory(context: Context) {
    private val kept = context.getSharedPreferences("computer", Context.MODE_PRIVATE)

    val paired get() = kept.contains("key")
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
            .putString("key", key)
            .putString("computer", computer.ifBlank { invite.computer })
            .apply()
    }

    fun forget() = kept.edit().clear().apply()

    /** The computer at each of its addresses, to be tried in turn. */
    fun ways(): List<Computer> = addresses.map { Computer(it, kept.getInt("port", 8443), fingerprint, kept.getString("key", "") ?: "") }

    fun worked(address: String) {
        kept.edit().putString("addresses", (listOf(address) + addresses.filter { it != address }).joinToString(",")).apply()
    }
}

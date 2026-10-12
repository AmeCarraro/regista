package app.regista

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.webkit.SslErrorHandler
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import org.json.JSONObject
import java.io.IOException
import javax.net.ssl.SSLException
import kotlin.concurrent.thread

/**
 * The whole app: a screen to pair the phone with the computer, and then the computer's own
 * page, shown here, with one line underneath that says what the phone is doing for it.
 */
class MainActivity : Activity() {
    private lateinit var memory: Memory
    private lateinit var gallery: Gallery
    private var link: Link? = null
    private var chatting = false

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        memory = Memory(this)
        gallery = Gallery(this)
        if (memory.paired) showChat() else showPairing("")
        intent?.dataString?.let(::readInvite)?.let(::offer)
    }

    /** The camera read the code while the app was already open. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.dataString?.let(::readInvite)?.let(::offer)
    }

    override fun onStart() {
        super.onStart()
        if (chatting) connect()
    }

    /** The phone works for the computer only while the app is in front. */
    override fun onStop() {
        super.onStop()
        link?.close()
        link = null
    }

    override fun onRequestPermissionsResult(request: Int, permissions: Array<String>, results: IntArray) {
        super.onRequestPermissionsResult(request, permissions, results)
        link?.refresh()
    }

    // ---- pairing

    private fun showPairing(message: String) {
        chatting = false
        link?.close()
        link = null
        setContentView(R.layout.pairing)
        findViewById<TextView>(R.id.message).text = message
        findViewById<Button>(R.id.pair).setOnClickListener {
            val invite = readInvite(findViewById<EditText>(R.id.link).text.toString())
            if (invite == null) {
                findViewById<TextView>(R.id.message).text = "Questo non è un collegamento di Regista. Copialo dalla pagina sul computer, alla voce «Telefono»."
            } else {
                offer(invite)
            }
        }
    }

    /**
     * Asks the user before pairing. A link can reach this app from anywhere, also from a page or
     * another app that wants this phone's pictures: so nothing is paired unless the user, who
     * sees which computer it is, says yes here. And never with a computer outside a private network.
     */
    private fun offer(invite: Invite) {
        if (invite.addresses.isEmpty()) {
            say("Questo codice porta a un computer fuori dalla tua rete. Non mi collego.")
            return
        }
        // what was said about an earlier link is no longer about this one
        if (!chatting) say("")
        val computer = invite.computer.ifBlank { "senza nome" }
        var question = "Computer: $computer\nIndirizzo: ${invite.addresses.first()}\n\n" +
            "Di' di sì solo se hai appena inquadrato il codice sul tuo computer: il computer collegato potrà vedere le foto di questo telefono."
        if (memory.paired) question += "\n\nQuesto telefono è già collegato a «${memory.computer}»: il nuovo collegamento prende il suo posto."
        AlertDialog.Builder(this)
            .setTitle("Collego questo telefono?")
            .setMessage(question)
            .setPositiveButton("Collega") { _, _ -> pair(invite) }
            .setNegativeButton("No", null)
            .show()
    }

    /** One line for the user, on whichever screen is showing. */
    private fun say(line: String) {
        findViewById<TextView>(if (chatting) R.id.status else R.id.message).text = line
    }

    /** Shows the computer the secret of the link. If it lets this phone in, the key it gives back is kept. */
    private fun pair(invite: Invite) {
        showPairing("Mi collego a ${invite.computer.ifBlank { "il computer" }}…")
        findViewById<Button>(R.id.pair).isEnabled = false
        thread {
            var problem = "Non trovo il computer. Controlla che sia acceso e sulla stessa rete di questo telefono."
            for (address in invite.addresses) {
                try {
                    val asked = JSONObject().put("secret", invite.secret).put("name", Build.MODEL)
                    val answer = Computer(address, invite.port, invite.fingerprint, "").ask("POST", "/phone/pair", asked)
                    memory.remember(invite, address, answer.getString("token"), answer.optString("computer"))
                    runOnUiThread { showChat() }
                    return@thread
                } catch (refused: Refused) {
                    problem = refused.message ?: problem
                    break
                } catch (other: SSLException) {
                    problem = "A quell'indirizzo risponde un altro computer, non quello del codice. Non mi collego."
                } catch (unreachable: IOException) {
                    // try the next address
                }
            }
            runOnUiThread {
                // a pairing that did not go through leaves the one there was, if there was one
                if (memory.paired) {
                    showChat()
                    say(problem)
                } else {
                    showPairing(problem)
                }
            }
        }
    }

    // ---- the computer's page, and the work done for it

    private fun showChat() {
        chatting = true
        setContentView(R.layout.chat)
        val status = findViewById<TextView>(R.id.status)
        status.text = "Cerco ${memory.computer.ifBlank { "il computer" }}…"
        status.setOnLongClickListener {
            AlertDialog.Builder(this)
                .setMessage("Scollego questo telefono dal computer? Per ricollegarlo servirà un nuovo codice.")
                .setPositiveButton("Scollega") { _, _ ->
                    memory.forget()
                    showPairing("Scollegato. Sul computer puoi toglierlo dall'elenco alla voce «Telefono».")
                }
                .setNegativeButton("No", null)
                .show()
            true
        }

        val page = findViewById<WebView>(R.id.page)
        page.setBackgroundColor(0xFF0B0910.toInt())
        page.settings.javaScriptEnabled = true
        page.settings.domStorageEnabled = true
        page.webViewClient = object : WebViewClient() {
            // the computer's certificate is its own, so Android does not know it: it is let through
            // only if it is the one whose fingerprint was in the code this phone was paired with
            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                val shown = error.certificate?.x509Certificate?.let(::fingerprintOf)
                if (shown != null && shown.equals(memory.fingerprint, ignoreCase = true)) handler.proceed() else handler.cancel()
            }

            // nothing but the computer's page opens in here
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                !view.url.orEmpty().startsWith("https://${request.url.host}:")
        }

        // to see the pictures and where each was taken: Android asks the user once for both
        gallery.missing().takeIf { it.isNotEmpty() }?.let { requestPermissions(it, 1) }
        connect()
    }

    private fun connect() {
        if (link != null) return
        val status = findViewById<TextView>(R.id.status)
        val page = findViewById<WebView>(R.id.page)
        link = Link(
            memory,
            gallery,
            found = { computer -> runOnUiThread { if (page.url == null) page.loadUrl(computer.home, computer.proof()) } },
            tell = { line -> runOnUiThread { status.text = line } },
            shutOut = {
                runOnUiThread {
                    memory.forget()
                    showPairing("Il computer non riconosce più questo telefono. Collegalo di nuovo con un codice nuovo.")
                }
            },
        ).also { it.start() }
    }
}

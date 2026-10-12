package app.regista

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.webkit.SslErrorHandler
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import org.json.JSONArray
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

    /** The question Android is showing: which pictures of which request of the computer may go to the trash. */
    private class Question(val transfer: String, val pictures: List<Pair<String, Long>>, val gone: List<String>)

    private var question: Question? = null

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

    // ---- taking pictures off this phone

    /**
     * Asks Android to move pictures to the phone's trash. Android shows them to the user and
     * moves them only after a yes: this app cannot do it by itself. They stay in the trash
     * for 30 days, and the computer already has a copy of each.
     */
    private fun clear(transfer: String, pictures: List<Pair<String, Long>>, gone: List<String>) = runOnUiThread {
        if (question != null || Build.VERSION.SDK_INT < 30) return@runOnUiThread
        try {
            val asking = MediaStore.createTrashRequest(contentResolver, pictures.map { gallery.named(it.second) }, true)
            question = Question(transfer, pictures, gone)
            startIntentSenderForResult(asking.intentSender, TRASH, null, 0, 0, 0)
        } catch (problem: Exception) {
            question = null
            say("Non riesco a chiedere ad Android di spostare le foto nel cestino: restano qui.")
        }
    }

    /** The user answered Android's question. The computer is told which pictures left, or that none did. */
    override fun onActivityResult(request: Int, result: Int, data: Intent?) {
        super.onActivityResult(request, result, data)
        if (request != TRASH) return
        val asked = question ?: return
        question = null
        val yes = result == RESULT_OK
        val left = asked.gone + if (yes) asked.pictures.map { it.first } else emptyList()
        if (chatting) say(if (yes) "Foto spostate nel cestino di questo telefono." else "Hai detto di no: le foto restano qui.")
        thread {
            val said = JSONObject().put("ids", JSONArray(left)).put("why", if (left.isEmpty()) "declined" else "")
            for (way in memory.ways()) {
                try {
                    way.ask("POST", "/phone/transfers/${asked.transfer}/trashed", said)
                    break
                } catch (unreachable: IOException) {
                    // if no way works the computer asks again, and finds the pictures gone or the answer the same
                }
            }
            // the gallery is not as the computer knows it any more
            runOnUiThread { link?.refresh() }
        }
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
            // a yes given through something another app drew on top of this question is not a yes
            .getButton(AlertDialog.BUTTON_POSITIVE).filterTouchesWhenObscured = true
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

            // nothing but the computer's page opens in here: the same computer, at the same door
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val here = Uri.parse(view.url.orEmpty())
                val there = request.url
                return !(there.scheme == "https" && here.scheme == "https" && there.host == here.host && there.port == here.port)
            }
        }
        // the page is the computer's and needs nothing of this phone's: not its files, not what other apps offer
        page.settings.allowFileAccess = false
        page.settings.allowContentAccess = false

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
            clear = ::clear,
        ).also { it.start() }
    }

    private companion object {
        /** The name of Android's question about the trash, to recognise its answer. */
        const val TRASH = 2
    }
}

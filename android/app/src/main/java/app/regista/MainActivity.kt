package app.regista

import android.app.Activity
import android.app.AlertDialog
import android.app.KeyguardManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.net.Uri
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.provider.MediaStore
import android.view.View
import android.webkit.CookieManager
import android.webkit.SslErrorHandler
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.IOException
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.SSLException
import kotlin.concurrent.thread

/**
 * The whole app, in two tabs. "Telefono" is the phone's own screen: it looks for the pictures of
 * this phone with no computer and no network. "Computer" is the computer's own page, shown here
 * once the phone is paired and the computer answers: from it pictures go both ways. One line at
 * the bottom says what the phone is doing for the computer.
 */
class MainActivity : Activity() {
    private lateinit var memory: Memory
    private lateinit var gallery: Gallery
    private lateinit var places: Places
    private lateinit var library: Library
    private lateinit var sight: Sight
    private lateinit var update: Update
    private lateinit var songs: Songs
    private var link: Link? = null

    /** The computer, when it answered last; null while it cannot be reached. */
    @Volatile var reached: Computer? = null
        private set

    /** The address whose page the "Computer" tab shows. */
    private var showing: String? = null

    /** The question Android is showing: which pictures of which request of the computer may go to the trash. */
    private class Question(val transfer: String, val pictures: List<Pair<String, Long>>, val gone: List<String>)

    private var question: Question? = null

    private val phonePage get() = findViewById<WebView>(R.id.phone_page)
    private val computerPage get() = findViewById<WebView>(R.id.page)
    private val pairing get() = findViewById<View>(R.id.pairing)

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        memory = Memory(this)
        gallery = Gallery(this)
        places = Places(this)
        sight = Sight(this)
        library = Library(this, gallery, places, sight)
        update = Update(this)
        songs = Songs(this)
        setContentView(R.layout.main)
        // the table of places takes a few seconds to read on an old phone: it is read now, in the background
        thread(name = "places") { places.ready() }
        setUpPhone()
        setUpComputer()
        setUpPairing()
        findViewById<TextView>(R.id.tab_phone).setOnClickListener { show(PHONE) }
        findViewById<TextView>(R.id.tab_music).setOnClickListener { show(MUSIC) }
        findViewById<TextView>(R.id.tab_computer).setOnClickListener { openComputer() }
        findViewById<TextView>(R.id.status).setOnLongClickListener {
            if (memory.paired) unpair()
            true
        }
        show(PHONE)
        say(if (memory.paired) "Cerco ${memory.computer.ifBlank { "il computer" }}…" else "Nessun computer collegato: puoi farlo dalla scheda «Computer».")
        // to see the pictures and where each was taken: Android asks the user once for both
        gallery.missing().takeIf { it.isNotEmpty() }?.let { requestPermissions(it, 1) }
        intent?.dataString?.let(::readInvite)?.let(::offer)
        // after an update the copying by themselves goes on as the user left it
        if (memory.paired && memory.autoCopy) CopyJob.plan(this, true)
    }

    /** The camera read the code while the app was already open. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.dataString?.let(::readInvite)?.let(::offer)
    }

    override fun onStart() {
        super.onStart()
        library.refresh()
        connect()
    }

    /** The phone works for the computer only while the app is in front. */
    override fun onStop() {
        super.onStop()
        link?.close()
        link = null
        reached = null
    }

    override fun onRequestPermissionsResult(request: Int, permissions: Array<String>, results: IntArray) {
        super.onRequestPermissionsResult(request, permissions, results)
        library.refresh()
        link?.refresh()
    }

    // ---- the three tabs

    private fun show(tab: String) {
        val paired = memory.paired
        // the pictures and the music are two views of the phone's own page
        phonePage.visibility = if (tab == PHONE || tab == MUSIC) View.VISIBLE else View.GONE
        if (tab != COMPUTER) phonePage.evaluateJavascript("window.registaView && window.registaView('$tab')", null)
        computerPage.visibility = if (tab == COMPUTER && paired) View.VISIBLE else View.GONE
        pairing.visibility = if (tab == COMPUTER && !paired) View.VISIBLE else View.GONE
        for ((id, name) in listOf(R.id.tab_phone to PHONE, R.id.tab_music to MUSIC, R.id.tab_computer to COMPUTER)) {
            val button = findViewById<TextView>(id)
            button.isSelected = name == tab
            button.setTextColor(getColor(if (name == tab) R.color.text else R.color.muted))
        }
    }

    /**
     * The computer's tab, behind the phone's own lock, at most once a day: whoever finds this phone
     * unlocked does not reach the computer's pictures. The search on the phone, and the copying by
     * themselves, never ask. Not paired, the tab is the one that pairs, and opens at once.
     */
    private fun openComputer() {
        if (!memory.paired || System.currentTimeMillis() - memory.unlockedAt < OPEN_FOR) return show(COMPUTER)
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (keyguard == null || !keyguard.isDeviceSecure) {
            say("Questo telefono non ha un blocco schermo: chi lo trova arriva alle foto del computer. Mettine uno nelle impostazioni.")
            return show(COMPUTER)
        }
        if (Build.VERSION.SDK_INT >= 30) try {
            BiometricPrompt.Builder(this)
                .setTitle("Apri il computer")
                .setSubtitle("Con l'impronta o il blocco schermo di questo telefono")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL)
                .build()
                .authenticate(
                    CancellationSignal(),
                    mainExecutor,
                    object : BiometricPrompt.AuthenticationCallback() {
                        override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = unlocked()

                        override fun onAuthenticationError(code: Int, message: CharSequence) = say(CLOSED)
                    },
                )
            return
        } catch (refused: SecurityException) {
            // the question about the fingerprint is not allowed here: the older one, about the phone's lock, is asked instead
        }
        @Suppress("DEPRECATION")
        val asking = keyguard.createConfirmDeviceCredentialIntent("Apri il computer", "Con il blocco schermo di questo telefono")
        if (asking == null) show(COMPUTER) else startActivityForResult(asking, UNLOCK)
    }

    private fun unlocked() {
        memory.unlocked()
        show(COMPUTER)
    }

    /** One line for the user, under both tabs. */
    private fun say(line: String) {
        findViewById<TextView>(R.id.status).text = line
    }

    /** What the phone's page shows of the computer: whether there is one, which, whether it answers now. */
    fun state(): JSONObject = JSONObject()
        .put("paired", memory.paired)
        .put("computer", memory.computer)
        .put("reachable", reached != null)
        .put("waiting", memory.offers().size)

    /** Tells the phone's page that the computer's answer to one of its requests is there, to take with Phone.answer. */
    fun answered(token: String) {
        runOnUiThread { phonePage.evaluateJavascript("window.registaAnswered && window.registaAnswered('$token')", null) }
    }

    /** Shows a picture in the phone's own viewer. */
    fun view(picture: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(picture, "image/*").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
        } catch (missing: ActivityNotFoundException) {
            say("Su questo telefono non c'è un'app per guardare le foto.")
        }
    }

    /** The user asked for the models on the phone's page: they come from the computer as soon as it answers. */
    fun sightWanted() {
        say(
            when {
                !memory.paired -> "Il modello arriva dal computer: collegalo dalla scheda «Computer»."
                reached != null -> "Prendo il modello dal computer…"
                else -> "Prendo il modello dal computer appena lo raggiungo."
            },
        )
        link?.refresh()
    }

    /** The user asked for the newer app on the phone's page: it comes from the computer as soon as it answers. */
    fun updateWanted() {
        say(if (reached != null) "Prendo dal computer l'app nuova…" else "Prendo l'app nuova appena raggiungo il computer.")
        link?.refresh()
    }

    /** The user wants to see the songs of this phone: Android asks once. */
    fun askForSongs() {
        if (!songs.allowed) requestPermissions(arrayOf(songs.permission), SONGS)
    }

    /** Pictures were put in line for the computer on the phone's page: they go as soon as it answers. */
    fun offered(count: Int) {
        say(if (reached != null) "Mando $count foto al computer…" else "$count foto in fila per il computer: le mando appena lo raggiungo.")
        link?.refresh()
    }

    private fun setUpPhone() {
        val page = phonePage
        page.setBackgroundColor(0xFF0B0910.toInt())
        page.settings.javaScriptEnabled = true
        page.settings.domStorageEnabled = true
        page.settings.allowFileAccess = false
        page.settings.allowContentAccess = false
        val phone = Phone(this, library, places, gallery, memory, sight, update, songs)
        // the page calls the app through this, and only this page can: it is the app's own, and nothing else opens in here
        page.addJavascriptInterface(phone, "Regista")
        page.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse = phone.answer(request)
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = true
        }
        page.loadUrl(Phone.START)
    }

    // ---- the computer's page, and the work done for it

    private fun setUpComputer() {
        val page = computerPage
        page.setBackgroundColor(0xFF0B0910.toInt())
        page.settings.javaScriptEnabled = true
        page.settings.domStorageEnabled = true
        // the page is the computer's and needs nothing of this phone's: not its files, not what other apps offer
        page.settings.allowFileAccess = false
        page.settings.allowContentAccess = false
        page.webViewClient = object : WebViewClient() {
            // the computer's certificate is its own, so Android does not know it: it is let through
            // only if it is the one whose fingerprint was in the code this phone was paired with
            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                val shown = certificateOf(error)?.let(::fingerprintOf)
                if (shown != null && shown.equals(memory.fingerprint, ignoreCase = true)) handler.proceed() else handler.cancel()
            }

            // nothing but the computer's page opens in here: the same computer, at the same door
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val here = Uri.parse(view.url.orEmpty())
                val there = request.url
                return !(there.scheme == "https" && here.scheme == "https" && there.host == here.host && there.port == here.port)
            }
        }
    }

    /** The certificate a page shows. Android 10 hands it over as it is; before, it is read out of what Android keeps of it. */
    private fun certificateOf(error: SslError): X509Certificate? {
        val shown = error.certificate ?: return null
        if (Build.VERSION.SDK_INT >= 29) return shown.x509Certificate
        val bytes = SslCertificate.saveState(shown).getByteArray("x509-certificate") ?: return null
        return try {
            CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(bytes)) as? X509Certificate
        } catch (wrong: CertificateException) {
            null
        }
    }

    /** Shows the computer's page, the first time it answers. */
    private fun open(computer: Computer) {
        if (showing == computer.home) return
        showing = computer.home
        computerPage.loadUrl(computer.home, computer.proof())
    }

    private fun connect() {
        if (link != null || !memory.paired) return
        link = Link(
            memory,
            gallery,
            sight,
            library,
            found = { computer ->
                reached = computer
                runOnUiThread { open(computer) }
            },
            lost = { reached = null },
            tell = { line -> runOnUiThread { say(line) } },
            shutOut = { runOnUiThread { forgotten("Il computer non riconosce più questo telefono. Collegalo di nuovo con un codice nuovo.") } },
            clear = ::clear,
            changed = { library.refresh() },
            update = update,
        ).also { it.start() }
    }

    // ---- pairing

    private fun setUpPairing() {
        findViewById<Button>(R.id.pair).setOnClickListener {
            val invite = readInvite(findViewById<EditText>(R.id.link).text.toString())
            if (invite == null) {
                pairingSays("Questo non è un collegamento di Regista. Copialo dalla pagina sul computer, alla voce «Telefono».")
            } else {
                offer(invite)
            }
        }
    }

    private fun pairingSays(line: String) {
        findViewById<TextView>(R.id.message).apply {
            text = line
            setTextColor(getColor(R.color.bad))
        }
        findViewById<TextView>(R.id.code).visibility = View.GONE
    }

    /** While the computer is asked to let this phone in: what to do there, and the number to find on its page. */
    private fun pairingShows(code: String) {
        findViewById<TextView>(R.id.message).apply {
            text = "Sul computer controlla che ci sia questo numero, e premi «Collega»:"
            setTextColor(getColor(R.color.text))
        }
        findViewById<TextView>(R.id.code).apply {
            text = "${code.take(3)} ${code.drop(3)}"
            visibility = View.VISIBLE
        }
    }

    /**
     * Asks the user before pairing. A link can reach this app from anywhere, also from a page or
     * another app that wants this phone's pictures: so nothing is paired unless the user, who
     * sees which computer it is, says yes here. And never with a computer outside a private network.
     */
    private fun offer(invite: Invite) {
        show(COMPUTER)
        if (invite.addresses.isEmpty()) {
            say("Questo codice porta a un computer fuori dalla tua rete. Non mi collego.")
            return
        }
        // what was said about an earlier link is no longer about this one
        pairingSays("")
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

    /**
     * Shows the computer the secret of the link, and asks to come in. The computer shows its user a
     * number, the same this phone shows: only with the user's yes there it lets this phone in, and
     * the key it gives then is kept.
     */
    private fun pair(invite: Invite) {
        pairingSays("Mi collego a ${invite.computer.ifBlank { "il computer" }}…")
        findViewById<Button>(R.id.pair).isEnabled = false
        thread {
            var problem = "Non trovo il computer. Controlla che sia acceso e sulla stessa rete di questo telefono."
            for (address in invite.addresses) {
                try {
                    val computer = Computer(address, invite.port, invite.fingerprint, "")
                    val asked = computer.ask("POST", "/phone/pair", JSONObject().put("secret", invite.secret).put("name", Build.MODEL))
                    val code = asked.getString("code")
                    runOnUiThread { pairingShows(code) }
                    val ticket = JSONObject().put("ticket", asked.getString("ticket"))
                    val until = System.currentTimeMillis() + asked.optLong("seconds", 120) * 1000
                    problem = "Sul computer nessuno ha risposto in tempo: rifai il collegamento."
                    while (System.currentTimeMillis() < until) {
                        Thread.sleep(2000)
                        val answer = computer.ask("POST", "/phone/pair/wait", ticket)
                        if (answer.optString("state") != "paired") continue
                        memory.remember(invite, address, answer.getString("token"), answer.optString("computer"))
                        // the user is at the computer, with this phone in hand: its tab opens without asking now
                        memory.unlocked()
                        runOnUiThread { paired() }
                        return@thread
                    }
                    break
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
                findViewById<Button>(R.id.pair).isEnabled = true
                // a pairing that did not go through leaves the one there was, if there was one
                if (memory.paired) say(problem) else pairingSays(problem)
            }
        }
    }

    /** A new computer: what the app kept of the one before goes, and the new one is looked for. */
    private fun paired() {
        link?.close()
        link = null
        reached = null
        showing = null
        // the key of the computer before lives on in the cookies of its page
        CookieManager.getInstance().removeAllCookies(null)
        computerPage.loadUrl("about:blank")
        findViewById<Button>(R.id.pair).isEnabled = true
        pairingSays("")
        show(COMPUTER)
        say("Cerco ${memory.computer.ifBlank { "il computer" }}…")
        connect()
    }

    private fun unpair() {
        AlertDialog.Builder(this)
            .setMessage("Scollego questo telefono dal computer? Per ricollegarlo servirà un nuovo codice.")
            .setPositiveButton("Scollega") { _, _ -> forgotten("Scollegato. Sul computer puoi toglierlo dall'elenco alla voce «Telefono».") }
            .setNegativeButton("No", null)
            .show()
    }

    /** This phone is no longer paired: by the user's choice, or because the computer forgot it. */
    private fun forgotten(why: String) {
        memory.forget()
        CopyJob.plan(this, false)
        link?.close()
        link = null
        reached = null
        showing = null
        CookieManager.getInstance().removeAllCookies(null)
        computerPage.loadUrl("about:blank")
        show(COMPUTER)
        pairingSays(why)
        say("Nessun computer collegato: la ricerca tra le foto di questo telefono funziona lo stesso.")
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
        if (request == UNLOCK) {
            if (result == RESULT_OK) unlocked() else say(CLOSED)
            return
        }
        if (request != TRASH) return
        val asked = question ?: return
        question = null
        val yes = result == RESULT_OK
        val left = asked.gone + if (yes) asked.pictures.map { it.first } else emptyList()
        say(if (yes) "Foto spostate nel cestino di questo telefono." else "Hai detto di no: le foto restano qui.")
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
            runOnUiThread {
                library.refresh()
                link?.refresh()
            }
        }
    }

    private companion object {
        const val PHONE = "phone"
        const val MUSIC = "music"
        const val COMPUTER = "computer"
        // the question about the songs, to tell its answer from the one about the pictures
        const val SONGS = 4

        /** The name of Android's question about the trash, to recognise its answer. */
        const val TRASH = 2

        /** The name of Android's question about the phone's own lock, before the computer's tab opens. */
        const val UNLOCK = 3

        /** How long the phone's own lock, once given, opens the computer's tab: a day. */
        const val OPEN_FOR = 24 * 60 * 60 * 1000L

        const val CLOSED = "Senza lo sblocco del telefono la scheda del computer resta chiusa."
    }
}

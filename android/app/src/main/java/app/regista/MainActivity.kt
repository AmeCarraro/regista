package app.regista

import android.app.Activity
import android.app.AlertDialog
import android.app.KeyguardManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.net.Uri
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.view.View
import android.view.WindowManager
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
    private lateinit var videos: Videos
    private lateinit var catalogCache: CatalogCache
    private lateinit var archiveCleanup: ArchiveCleanup
    private lateinit var remoteDocuments:RemoteDocuments
    private lateinit var mediaBackup: MediaBackup
    private lateinit var backupFolders: BackupFolders
    private lateinit var kinds: Kinds
    private lateinit var commands: CommandPreview
    private lateinit var speech: CommandSpeech
    private lateinit var tags: ManualTags
    private var link: Link? = null
    private var foreground = false
    private var documentFolder=false
    @Volatile private var documentRequestChecking=false
    private var lastDocumentRequest=0L
    private data class PendingImport(val request:String,val ids:List<String>?,val scope:String)
    private var waitingImport:PendingImport?=null
    private val importHandler = Handler(Looper.getMainLooper())
    private val importUi = object : Runnable {
        override fun run() {
            if (!foreground) return
            val state = PhotoImportStore(this@MainActivity).read()
            if (PhotoImportService.running || state.requested) {
                reached = PhotoImportService.reached
                reached?.let(::open)
                say(if (state.prepared) "Importazione: ${state.processed} / ${state.total} · ${state.copied} copiate · ${state.duplicates} già presenti · ${state.failed} errori. ${if (state.phase == "waiting") state.message else "Puoi spegnere lo schermo."}" else state.message)
            } else if (link == null) connect()
            if(!PhotoImportService.running) archiveCleanup.poll(reached)
            if(!PhotoImportService.running) pollDocumentRequest()
            importHandler.postDelayed(this, 1000)
        }
    }

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
        videos = Videos(this)
        catalogCache = CatalogCache(this, memory)
        archiveCleanup = ArchiveCleanup(this,memory) { line -> runOnUiThread { say(line) } }
        remoteDocuments=RemoteDocuments(this) { line -> runOnUiThread { say(line) } }
        archiveCleanup.recover(saved == null)
        backupFolders = BackupFolders(this)
        mediaBackup = MediaBackup(this, memory, { reached }, onStarting = {
            runOnUiThread { window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
            val previous = link
            previous?.close()
            previous?.join(2000)
            link = null
        }, onFinished = {
            runOnUiThread {
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                if (foreground) connect()
            }
        })
        kinds = Kinds(this, library)
        commands = CommandPreview(assets)
        tags = ManualTags(this, gallery)
        speech = CommandSpeech(this) {
            phonePage.evaluateJavascript("window.registaCommandSpeech && window.registaCommandSpeech()", null)
        }
        setContentView(R.layout.main)
        // the table of places takes a few seconds to read on an old phone: it is read now, in the background
        thread(name = "places") { places.ready() }
        setUpPhone()
        setUpComputer()
        setUpPairing()
        findViewById<TextView>(R.id.tab_phone).setOnClickListener { show(PHONE) }
        findViewById<TextView>(R.id.tab_music).setOnClickListener { show(MUSIC) }
        findViewById<TextView>(R.id.tab_video).setOnClickListener { show(VIDEO) }
        findViewById<TextView>(R.id.tab_computer).setOnClickListener { openComputer() }
        findViewById<TextView>(R.id.status).setOnLongClickListener {
            if (memory.paired) unpair()
            true
        }
        // the music widget opens the app on its tab
        show(if (intent?.getStringExtra(TAB) == MUSIC) MUSIC else PHONE)
        say(if (memory.paired) "Cerco ${memory.computer.ifBlank { "il computer" }}…" else "Nessun computer collegato: puoi farlo dalla scheda «Computer».")
        // to see the pictures and where each was taken: Android asks the user once for both
        gallery.missing().takeIf { it.isNotEmpty() }?.let { requestPermissions(it, 1) }
        intent?.dataString?.let(::readInvite)?.let(::offer)
        // after an update the copying by themselves goes on as the user left it
        memory.autoCopy=false
        CopyJob.plan(this, false)
    }

    /** The camera read the code while the app was already open. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.dataString?.let(::readInvite)?.let(::offer)
        if (intent.getStringExtra(TAB) == MUSIC) show(MUSIC)
    }

    override fun onStart() {
        super.onStart()
        foreground = true
        archiveCleanup.start()
        val pendingImport=PhotoImportStore(this).read()
        if (pendingImport.requested && !PhotoImportService.running) startPhotoImport(scope=pendingImport.scope)
        // The PC owns the photo catalog; Android only lists files when importing.
        connect()
        if (commands.available) speech.onStart()
        importHandler.post(importUi)
    }

    /** Closing this screen stops interactive work; the explicit photo-import service keeps its own lifetime. */
    override fun onStop() {
        super.onStop()
        foreground = false
        archiveCleanup.stop()
        importHandler.removeCallbacks(importUi)
        mediaBackup.cancel()
        speech.onStop()
        link?.close()
        link = null
        reached = null
    }

    override fun onDestroy() {
        mediaBackup.close()
        importHandler.removeCallbacks(importUi)
        commands.close()
        tags.close()
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(request: Int, permissions: Array<String>, results: IntArray) {
        super.onRequestPermissionsResult(request, permissions, results)
        if (request == CommandSpeech.PERMISSION) {
            speech.permissionResult(results.firstOrNull() == PackageManager.PERMISSION_GRANTED)
            return
        }
        if(request==BACKUP_PERMISSIONS) {
            waitingImport?.let { waiting ->
                waitingImport=null
                val kinds=if(waiting.scope=="all-media") setOf("image","video","audio") else setOf("image","video")
                if(MediaFiles(this,kinds).missingPermissions().isEmpty()) {
                    if(foreground) startPhotoImport(waiting.request,waiting.ids,waiting.scope)
                    else PhotoImportStore(this).begin(memory.fingerprint,waiting.request,waiting.ids,waiting.scope)
                } else {
                    PhotoImportStore(this).pause("Permessi incompleti. Concedi l’accesso ai file, poi premi Riprendi.")
                    say("Accesso incompleto: l’importazione resta in pausa.")
                }
            }
        }
        // The PC owns the photo catalog; Android only lists files when importing.
        link?.refresh()
    }

    // ---- the three tabs

    /** The tab shown: the phone's page asks for it when it opens, as it may open after the tab was chosen. */
    @Volatile var tab = PHONE
        private set

    private fun show(tab: String) {
        this.tab = tab
        if (tab != PHONE) speech.cancel()
        val paired = memory.paired
        // the pictures and the music are two views of the phone's own page
        phonePage.visibility = if (tab == PHONE || tab == MUSIC || tab == VIDEO) View.VISIBLE else View.GONE
        if (tab != COMPUTER) phonePage.evaluateJavascript("window.registaView && window.registaView('$tab')", null)
        computerPage.visibility = if (tab == COMPUTER && paired) View.VISIBLE else View.GONE
        pairing.visibility = if (tab == COMPUTER && !paired) View.VISIBLE else View.GONE
        for ((id, name) in listOf(R.id.tab_phone to PHONE, R.id.tab_music to MUSIC, R.id.tab_video to VIDEO, R.id.tab_computer to COMPUTER)) {
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
            startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(picture, contentResolver.getType(picture) ?: "image/*").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
        } catch (missing: ActivityNotFoundException) {
            say("Su questo telefono non c'è un'app per guardare le foto.")
        }
    }

    /** Legacy callback: local model experiments remain on standby. */
    fun sightWanted() {
        say("L’analisi delle foto viene eseguita sul PC. Sul telefono arrivano il catalogo e i tag.")
    }

    /** The user asked for the newer app on the phone's page: it comes from the computer as soon as it answers. */
    fun updateWanted() {
        say(if (reached != null) "Prendo dal computer l'app nuova…" else "Prendo l'app nuova appena raggiungo il computer.")
        link?.refresh()
    }

    /** This app's page in the phone's settings: the user changes there what the phone lets it do. */
    fun openSettings() {
        try {
            startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
        } catch (missing: ActivityNotFoundException) {
            say("Apri tu le impostazioni del telefono, alla voce delle app, e cerca Regista.")
        }
    }

    /** The user wants to see the songs of this phone: Android asks once. */
    fun askForSongs() {
        if (!songs.allowed) requestPermissions(arrayOf(songs.permission), SONGS)
    }

    /**
     * The user wants songs that are elsewhere on the phone, as the ones received on WhatsApp: Android's
     * own window lets them choose, opened where WhatsApp keeps them when it can. The app sees only
     * the files chosen there.
     */
    fun addSongs() {
        val choose = Intent(Intent.ACTION_OPEN_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType("*/*")
            .putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("audio/*", "application/ogg"))
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        if (Build.VERSION.SDK_INT >= 26) {
            // since Android 11 WhatsApp keeps its files in Android/media; a folder that is not there is left for the usual one
            val folder = if (Build.VERSION.SDK_INT >= 30) "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Audio" else "WhatsApp/Media/WhatsApp Audio"
            choose.putExtra(DocumentsContract.EXTRA_INITIAL_URI, DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", "primary:$folder"))
        }
        try {
            startActivityForResult(choose, ADD_SONGS)
        } catch (missing: ActivityNotFoundException) {
            say("Questo telefono non ha la finestra per scegliere i file: metti le canzoni nella cartella Music.")
        }
    }

    fun addVideos() {
        try {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType("video/*").putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true).putExtra(Intent.EXTRA_LOCAL_ONLY, true), ADD_VIDEOS)
        } catch (_: ActivityNotFoundException) { say("Non riesco ad aprire la selezione dei video su questo telefono.") }
    }

    fun requestMediaBackup() {
        if (mediaBackup.busy) return
        if (reached == null) { say("Collega il PC prima di avviare il backup completo."); return }
        AlertDialog.Builder(this).setTitle("Avviare il backup completo?")
            .setMessage("Verranno cercati foto, audio, video e documenti nelle raccolte e nelle cartelle autorizzate. WhatsApp e Telegram sono separati; ogni blocco completo ha copie normali e uno ZIP verificato. Gli originali sul telefono restano intatti. La copia continua anche a schermo spento.")
            .setPositiveButton("Avvia backup") { _, _ ->
                startPhotoImport(scope="all-media")
            }.setNegativeButton("Annulla", null).show()
    }

    fun chooseBackupFolder() {
        if (mediaBackup.busy || PhotoImportService.running) return
        try {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                .putExtra(Intent.EXTRA_LOCAL_ONLY, true)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION), BACKUP_FOLDER)
        } catch (_: ActivityNotFoundException) { say("La selezione delle cartelle non è disponibile su questo telefono.") }
    }

    fun requestDocumentImport() {
        if(!foreground) return
        if(PhotoImportService.running) { say("Attendi la fine dell’importazione in corso."); return }
        if(reached==null) { say("Collega il PC prima di importare i documenti."); return }
        AlertDialog.Builder(this).setTitle("Importa e indicizza documenti")
            .setItems(arrayOf("Importa dalle cartelle autorizzate","Scegli file…","Aggiungi una cartella, poi importa…")) { _,which ->
                when(which) {
                    0 -> startPhotoImport(scope="documents")
                    1 -> try {
                        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true).putExtra(Intent.EXTRA_LOCAL_ONLY,true)
                            .putExtra(Intent.EXTRA_MIME_TYPES,arrayOf("application/pdf","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.ms-excel",
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/msword","text/csv","text/plain"))
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION),ADD_DOCUMENTS)
                    } catch(_:ActivityNotFoundException) { say("Il selettore documenti non è disponibile.") }
                    2 -> { documentFolder=true; chooseBackupFolder() }
                }
            }.setNegativeButton("Annulla",null).show()
    }

    private fun pollDocumentRequest() {
        val computer=reached ?: return
        if(documentRequestChecking || System.currentTimeMillis()-lastDocumentRequest<10000) return
        documentRequestChecking=true; lastDocumentRequest=System.currentTimeMillis()
        thread(name="document import request") {
            try {
                val request=computer.ask("GET","/phone/documents/import-request").optString("request_id")
                val preferences=getSharedPreferences("document-requests",MODE_PRIVATE)
                if(request.isNotEmpty() && preferences.getString("offered","")!=request) runOnUiThread {
                    if(foreground && !PhotoImportService.running) {
                        preferences.edit().putString("offered",request).apply()
                        requestDocumentImport()
                        thread { runCatching { computer.ask("POST","/phone/documents/import-request/seen",JSONObject()) } }
                    }
                }
            } catch(_:Exception) { } finally { documentRequestChecking=false }
        }
    }

    /** Pictures were put in line for the computer on the phone's page: they go as soon as it answers. */
    fun offered(count: Int) {
        say(if (reached != null) "Mando $count foto al computer…" else "$count foto in fila per il computer: le mando appena lo raggiungo.")
        link?.refresh()
    }

    fun startPhotoImport(request: String = "", ids: List<String>? = null,scope:String="photos-videos") {
        if (!foreground) return
        val sources=MediaFiles(this,when(scope) { "documents" -> setOf("document"); "all-media" -> setOf("image","video","audio"); else -> setOf("image","video") })
        if(sources.missingPermissions().isNotEmpty()) {
            waitingImport=PendingImport(request,ids,scope)
            requestPermissions(sources.permissionRequest(),BACKUP_PERMISSIONS)
            say("Concedi l’accesso ai file: poi inizierà l’importazione richiesta.")
            return
        }
        try {
            PhotoImportService.start(this, request, ids,scope)
            link?.close()
            link = null
            say("Importazione avviata. Puoi spegnere lo schermo; l’avanzamento è nella notifica.")
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                val preferences = getSharedPreferences("photo-import", MODE_PRIVATE)
                if (!preferences.getBoolean("notification-asked", false)) {
                    preferences.edit().putBoolean("notification-asked", true).apply()
                    requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), IMPORT_NOTIFICATIONS)
                }
            }
        } catch (problem: Exception) { say(problem.message ?: "Non riesco ad avviare l’importazione.") }
    }

    private fun setUpPhone() {
        val page = phonePage
        page.setBackgroundColor(0xFF0B0910.toInt())
        page.settings.javaScriptEnabled = true
        page.settings.domStorageEnabled = true
        page.settings.allowFileAccess = false
        page.settings.allowContentAccess = false
        val phone = Phone(this, library, places, gallery, memory, sight, update, songs, kinds, commands, speech, tags, catalogCache, videos, mediaBackup, backupFolders)
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
        page.addJavascriptInterface(object {
            @android.webkit.JavascriptInterface fun openDocument(sha:String,download:Boolean) {
                if(sha.matches(Regex("[a-f0-9]{64}"))) reached?.let { remoteDocuments.take(it,sha,download) }
            }
        },"RegistaPc")
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
                if(there.scheme=="https" && there.host==here.host && there.port==here.port && Regex("/api/documents/[a-f0-9]{64}/file").matches(there.path.orEmpty())) {
                    reached?.let { remoteDocuments.take(it,there.pathSegments[2],there.getQueryParameter("download")=="true") }
                    return true
                }
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
        if (link != null || !memory.paired || mediaBackup.busy || PhotoImportService.running || PhotoImportStore(this).read().requested) return
        link = Link(
            memory,
            gallery,
            sight,
            library,
            found = { computer ->
                reached = computer
                catalogCache.sync(computer)
                runOnUiThread { open(computer) }
            },
            lost = { reached = null },
            tell = { line -> runOnUiThread { say(line) } },
            shutOut = { runOnUiThread { forgotten("Il computer non riconosce più questo telefono. Collegalo di nuovo con un codice nuovo.") } },
            clear = ::clear,
            changed = { library.refresh() },
            update = update,
            kinds = kinds,
            requestImport = { request -> runOnUiThread {
                if (foreground) {
                    val store = PhotoImportStore(this)
                    val allowed = if (request.isEmpty()) store.read().work.isEmpty() else store.remoteAllowed(request, memory.fingerprint)
                    if (allowed && request.isNotEmpty()) startPhotoImport(request)
                }
            } },
        ).also { it.start() }
    }

    // ---- pairing

    private fun setUpPairing() {
        findViewById<Button>(R.id.scan_qr).setOnClickListener {
            startActivityForResult(Intent(this, PairingScanner::class.java), SCAN_QR)
        }
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

    /** A new connection; downloaded catalogs and originals stay available. */
    private fun paired() {
        if (PhotoImportService.running || PhotoImportStore(this).read().requested) PhotoImportService.cancel(this)
        mediaBackup.cancel()
        catalogCache.disconnected()
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
            .setMessage("Scollego questo telefono dal computer? Foto, video, tag e backup restano conservati. Per ricollegarlo servirà un nuovo codice.")
            .setPositiveButton("Scollega") { _, _ -> forgotten("Scollegato. Sul computer puoi toglierlo dall'elenco alla voce «Telefono».") }
            .setNegativeButton("No", null)
            .show()
    }

    /** This phone is no longer paired: by the user's choice, or because the computer forgot it. */
    private fun forgotten(why: String) {
        PhotoImportService.cancel(this)
        mediaBackup.cancel()
        catalogCache.disconnected()
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
        say("Nessun computer collegato. Musica e video del telefono restano disponibili.")
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
        if(request==RemoteDocuments.SAVE) { remoteDocuments.saved(result,data?.data); return }
        if(request==ArchiveCleanup.REQUEST) { archiveCleanup.answered(result); return }
        if(request==ArchiveCleanup.WRITE_REQUEST) { archiveCleanup.folderAnswered(result, data); return }
        if (request == SCAN_QR) {
            if (result == RESULT_OK) {
                val invite = data?.getStringExtra(PairingScanner.INVITE)?.let(::readInvite)
                if (invite != null) offer(invite) else pairingSays("QR non valido. Inquadra il codice di Regista sul PC.")
            }
            return
        }
        if (request == BACKUP_FOLDER) {
            if (result == RESULT_OK && data?.data != null) {
                try { backupFolders.add(data.data!!); if(documentFolder) {
                    if(foreground) startPhotoImport(scope="documents") else PhotoImportStore(this).begin(memory.fingerprint,scope="documents")
                } }
                catch (_: Exception) { say("Non riesco ad accedere a questa cartella. Scegli una cartella consentita da Android.") }
            }
            documentFolder=false
            return
        }
        if(request==ADD_DOCUMENTS) {
            if(result==RESULT_OK && data!=null) {
                val uris=data.clipData?.let { clip -> (0 until clip.itemCount).map { clip.getItemAt(it).uri } } ?: listOfNotNull(data.data)
                try {
                    val ids=SelectedDocuments(this).add(uris)
                    if(ids.isNotEmpty()) {
                        if(foreground) startPhotoImport(ids=ids,scope="documents") else PhotoImportStore(this).begin(memory.fingerprint,ids=ids,scope="documents")
                    } else say("Seleziona PDF, Excel, Word, CSV o TXT.")
                } catch(error:Exception) { say(error.message ?: "Non riesco a leggere i documenti scelti.") }
            }
            return
        }
        if (request == ADD_VIDEOS) {
            if (result == RESULT_OK && data != null) {
                val chosen = data.clipData?.let { clip -> (0 until clip.itemCount).map { clip.getItemAt(it).uri } } ?: listOfNotNull(data.data)
                videos.selected(chosen)
            }
            return
        }
        if (request == ADD_SONGS) {
            if (result != RESULT_OK || data == null) return
            val chosen = data.clipData?.let { clip -> (0 until clip.itemCount).map { clip.getItemAt(it).uri } } ?: listOfNotNull(data.data)
            songs.add(chosen)
            return
        }
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
                // The PC owns the photo catalog; Android only lists files when importing.
                link?.refresh()
            }
        }
    }

    // the tabs and the extra that names one are for the music widget too, which opens the app on its tab
    companion object {
        const val PHONE = "phone"
        const val MUSIC = "music"
        const val VIDEO = "video"
        const val COMPUTER = "computer"
        // the question about the songs, to tell its answer from the one about the pictures
        const val SONGS = 4
        // Android's window where the user chooses songs to add
        const val ADD_SONGS = 5
        const val ADD_VIDEOS = 6
        const val BACKUP_PERMISSIONS = 7
        const val BACKUP_FOLDER = 8
        const val SCAN_QR = 9
        const val IMPORT_NOTIFICATIONS = 42
        const val ADD_DOCUMENTS=44
        // the tab the app is opened on, when it is not the first one
        const val TAB = "app.regista.TAB"

        /** The name of Android's question about the trash, to recognise its answer. */
        const val TRASH = 2

        /** The name of Android's question about the phone's own lock, before the computer's tab opens. */
        const val UNLOCK = 3

        /** How long the phone's own lock, once given, opens the computer's tab: a day. */
        const val OPEN_FOR = 24 * 60 * 60 * 1000L

        const val CLOSED = "Senza lo sblocco del telefono la scheda del computer resta chiusa."
    }
}

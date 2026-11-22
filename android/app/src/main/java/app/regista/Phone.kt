package app.regista

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import kotlin.concurrent.thread

/**
 * The phone's own screen: a page that travels inside the app (built from web/src/telefono into
 * the app's files), shown from those files as if from a site, with no server and no network,
 * and the few calls that page may make to the app. It works with no computer.
 */
class Phone(
    private val app: MainActivity,
    private val library: Library,
    private val places: Places,
    private val gallery: Gallery,
    private val memory: Memory,
    private val sight: Sight,
    private val update: Update,
    private val songs: Songs,
    private val kinds: Kinds,
    private val commands: CommandPreview,
    private val speech: CommandSpeech,
    private val tags: ManualTags,
    private val catalogCache: CatalogCache,
    private val videos: Videos,
    private val mediaBackup: MediaBackup,
    private val backupFolders: BackupFolders,
) {
    @JavascriptInterface
    fun mediaBackupState(): String {
        val checkpoint=PhotoImportStore(app).read()
        val status=if(checkpoint.scope=="all-media" && checkpoint.work.isNotEmpty()) JSONObject(PhotoImportStore(app).json())
            .put("scanned",checkpoint.processed).put("complete",checkpoint.phase=="done")
            .put("current",checkpoint.message).put("error",if(checkpoint.phase=="paused") checkpoint.message else "")
            .put("errors",JSONArray()).put("warnings",JSONArray()).put("bytes",0).put("current_size",0)
        else JSONObject(mediaBackup.state()).put("busy",PhotoImportService.running)
        return status.put("folders", backupFolders.state().getJSONArray("folders"))
        .put("paired", memory.paired).put("reachable", app.reached != null).put("address", app.reached?.address.orEmpty())
        .put("missing_permissions", JSONArray(mediaBackup.missingPermissions().toList())).toString()
    }

    @JavascriptInterface
    fun startMediaBackup() = app.runOnUiThread { app.requestMediaBackup() }

    @JavascriptInterface
    fun cancelMediaBackup() { PhotoImportService.cancel(app); mediaBackup.cancel() }

    @JavascriptInterface
    fun chooseBackupFolder() = app.runOnUiThread { app.chooseBackupFolder() }

    @JavascriptInterface
    fun importDocuments()=app.runOnUiThread { app.requestDocumentImport() }

    @JavascriptInterface
    fun removeBackupFolder(id: String) { if (!mediaBackup.busy && !PhotoImportService.running) backupFolders.remove(id) }

    @JavascriptInterface
    fun openBackupNetworkSettings() = app.runOnUiThread {
        try { app.startActivity(Intent(android.provider.Settings.ACTION_WIRELESS_SETTINGS)) }
        catch (_: android.content.ActivityNotFoundException) { app.openSettings() }
    }
    /** The pictures of this phone by kind (Kinds.sorted); null until the computer said what the kinds are. */
    @JavascriptInterface
    fun kinds(): String = kinds.sorted()

    @JavascriptInterface
    fun commandPreviewAvailable(): Boolean = commands.available

    @JavascriptInterface
    fun previewCommand(text: String): String = commands.preview(text)

    @JavascriptInterface
    fun commandSpeechAvailable(): Boolean = speech.available

    @JavascriptInterface
    fun listenCommand() = app.runOnUiThread { if (app.tab == MainActivity.PHONE) speech.listen() }

    @JavascriptInterface
    fun cancelCommandSpeech() = app.runOnUiThread { speech.cancel() }

    @JavascriptInterface
    fun commandSpeech(): String = speech.json()

    @JavascriptInterface
    fun applyCommandTags(action: String, tag: String, idsJson: String): String = commandTags { apply(action, tag, idsJson) }

    @JavascriptInterface
    fun findCommandTagged(tag: String): String = commandTags { find(tag) }

    private fun commandTags(operation: ManualTags.() -> String): String = if (commands.available) {
        tags.operation()
    } else {
        JSONObject().put("error", "La prova comandi non è disponibile in questa versione.").toString()
    }

    // what the computer said about requests typed here, until the page takes it
    private val heard = ConcurrentHashMap<String, ConcurrentLinkedQueue<JSONObject>>()

    // the songs of the computer as it listed them last, and when; null before it ever did
    @Volatile private var computerSongs: JSONArray? = null
    @Volatile private var listedAt = 0L
    @Volatile private var listing = false

    /** The songs of this phone, and whether the app may see them: {"allowed", "songs"}. */
    @JavascriptInterface
    fun songs(): String = JSONObject().put("allowed", songs.allowed).put("songs", songs.json()).toString()

    /** The user wants the songs shown: Android asks once. */
    @JavascriptInterface
    fun allowSongs() = app.runOnUiThread { app.askForSongs() }

    /** Opens Android's window to choose songs elsewhere on the phone, WhatsApp's say: the chosen ones are copied into Music/Regista. */
    @JavascriptInterface
    fun addSongs() = app.runOnUiThread { app.addSongs() }

    /** How the songs chosen last are being added (Songs.adding). */
    @JavascriptInterface
    fun added(): String = songs.adding()

    @JavascriptInterface
    fun musicSyncState(): String = app.musicSync.state()

    @JavascriptInterface
    fun syncMusic() = app.runOnUiThread { app.syncMusic() }

    @JavascriptInterface
    fun musicCollections(): String = app.musicCollections.state()

    @JavascriptInterface
    fun labelSong(id: String, tags: String): String = app.musicCollections.tags(id, tags)

    @JavascriptInterface
    fun saveMusicPlaylist(name: String, query: String, tag: String): String = app.musicCollections.playlist(name, query, tag)

    @JavascriptInterface
    fun videos(): String = videos.state()

    @JavascriptInterface
    fun addVideos() = app.runOnUiThread { app.addVideos() }

    @JavascriptInterface
    fun playVideo(id: String) {
        if (videos.named(id) == null) return
        app.runOnUiThread { app.startActivity(Intent(app, VideoActivity::class.java).putExtra("id", id)) }
    }

    @JavascriptInterface
    fun removeVideo(id: String) = videos.remove(id)

    /** The songs of the computer, while it answers: {"reachable", "songs"}, asked of it again every half minute. */
    @JavascriptInterface
    fun computerSongs(): String {
        val computer = app.reached
        if (computer != null && !listing && System.currentTimeMillis() - listedAt > 30_000) {
            listing = true
            thread(name = "songs") {
                try {
                    computerSongs = computer.ask("GET", "/phone/music").optJSONArray("songs")
                    listedAt = System.currentTimeMillis()
                } catch (unreachable: IOException) {
                } finally {
                    listing = false
                }
            }
        }
        return JSONObject().put("reachable", computer != null).put("songs", computerSongs ?: JSONObject.NULL).toString()
    }

    /** Plays a line of songs, [{"where", "id", "title", "artist"}], from the one at `index`. */
    @JavascriptInterface
    fun play(queue: String, index: Int) {
        Player.computer = app.reached ?: Player.computer
        Player.ask(app, Player.PLAY) {
            putExtra("queue", queue)
            putExtra("index", index)
        }
    }

    /** "pause", "resume", "next", "previous" or "stop". */
    @JavascriptInterface
    fun control(what: String) {
        val action = mapOf("pause" to Player.PAUSE, "resume" to Player.RESUME, "next" to Player.NEXT, "previous" to Player.PREVIOUS, "stop" to Player.STOP)[what] ?: return
        Player.computer = app.reached ?: Player.computer
        Player.ask(app, action)
    }

    /** Jumps to a point of the song playing, in milliseconds. */
    @JavascriptInterface
    fun seek(position: Double) = Player.ask(app, Player.SEEK) { putExtra("position", position.toLong()) }

    /** The tab of the app that shows this page: "phone" or "music". */
    @JavascriptInterface
    fun tab(): String = app.tab

    /** Who made this phone, in small letters ("xiaomi"): some makers stop the apps that are closed, unless the user lets them be. */
    @JavascriptInterface
    fun maker(): String = Build.MANUFACTURER.lowercase()

    /** Opens this app's page in the phone's settings, where the user allows the battery and the starting by itself. */
    @JavascriptInterface
    fun openSettings() = app.runOnUiThread { app.openSettings() }

    /** Whether Android can put the music widget on the home screen when asked: from Android 8, and if the home screen lets it. */
    @JavascriptInterface
    fun canPinWidget(): Boolean =
        Build.VERSION.SDK_INT >= 26 && app.getSystemService(AppWidgetManager::class.java)?.isRequestPinAppWidgetSupported == true

    /** Asks Android to put the music widget on the home screen: Android asks the user first. */
    @JavascriptInterface
    fun pinWidget() {
        if (!canPinWidget()) return
        app.runOnUiThread { app.getSystemService(AppWidgetManager::class.java)?.requestPinAppWidget(ComponentName(app, MusicWidget::class.java), null, null) }
    }

    /** What plays now, and how far it is (Player.state). */
    @JavascriptInterface
    fun player(): String = Player.state().toString()

    // the songs being copied, and how each copy ended, by "phone:<id>" or "computer:<id>": "copying", "done" or "failed"
    private val copies = ConcurrentHashMap<String, String>()

    @JavascriptInterface
    fun copies(): String = JSONObject(copies.toMap()).toString()

    /** Copies a song of the computer onto this phone, into Music/Regista: from then on it plays away from home too. */
    @JavascriptInterface
    fun copyHere(id: String, name: String) {
        val computer = app.reached ?: return
        val key = "computer:$id"
        if (copies.put(key, "copying") == "copying") return
        thread(name = "copy song") {
            copies[key] = try {
                if (computer.fetch("/phone/music/${Uri.encode(id)}") { stream, fingerprint -> songs.keep(name, stream, fingerprint) }) "done" else "failed"
            } catch (unreachable: IOException) {
                "failed"
            }
        }
    }

    /** Sends a song of this phone to the computer, into "Dal telefono" in its music folder. The phone keeps its own. */
    @JavascriptInterface
    fun copyThere(id: String) {
        val computer = app.reached ?: return
        val key = "phone:$id"
        if (copies.put(key, "copying") == "copying") return
        thread(name = "send song") {
            copies[key] = try {
                val song = songs.described(id.toLong()) ?: throw IOException("the song is gone")
                computer.send("/phone/music/received?name=${Uri.encode(song.name)}", song.size, songs.open(id.toLong()), song.fingerprint)
                "done"
            } catch (unreachable: IOException) {
                "failed"
            } catch (wrong: NumberFormatException) {
                "failed"
            }
        }
    }

    private val catalogAnswers = ConcurrentHashMap<String, String>()

    @JavascriptInterface
    fun cachedCatalog(): String {
        catalogCache.sync(app.reached)
        return catalogCache.state().toString()
    }

    @JavascriptInterface
    fun syncCatalog() = catalogCache.sync(app.reached, force = true)

    @JavascriptInterface
    fun searchCachedCatalog(query: String, offset: Int, token: String) {
        cachedSearch(query,offset,JSONObject(),token)
    }

    @JavascriptInterface
    fun searchCachedCatalogWithFilters(query:String,offset:Int,filters:String,token:String) {
        val options=runCatching { JSONObject(filters) }.getOrDefault(JSONObject())
        cachedSearch(query,offset,options,token)
    }

    private fun cachedSearch(query:String,offset:Int,filters:JSONObject,token:String) {
        if (!TOKEN.matches(token) || catalogAnswers.size >= 32) return
        catalogAnswers[token] = ""
        thread(name = "local catalog search") {
            val result = try { catalogCache.search(query, offset,filters) }
                catch (problem: Exception) { JSONObject().put("error", problem.message ?: "Catalogo non disponibile.") }
            catalogAnswers.replace(token, result.toString())
        }
    }

    @JavascriptInterface
    fun openCachedMedia(id:String):String {
        val source=runCatching { catalogCache.localMedia(id,gallery) }.getOrNull()
            ?: return JSONObject().put("error","Originale non presente sul telefono. Aprilo dal catalogo del PC quando è collegato.").toString()
        app.runOnUiThread { app.view(source.first) }
        return JSONObject().put("opened",true).toString()
    }

    /** Catalog reads and the configured PC model control; pairing keys stay native. */
    @JavascriptInterface
    fun catalogRequest(path: String, body: String, token: String) {
        if (!TOKEN.matches(token) || catalogAnswers.size >= 32) return
        if (path !in setOf("/api/catalog/status", "/api/catalog/search", "/api/catalog/plan", "/api/catalog/albums", "/api/model-runtime")) return
        catalogAnswers[token] = ""
        thread(name = "catalog") {
            val result = try {
                val computer = app.reached ?: throw IOException("Computer non raggiungibile: accendilo e collegalo.")
                val payload = if (body.isBlank()) null else JSONObject(body)
                computer.ask(if (payload == null) "GET" else "POST", path, payload)
            } catch (problem: Exception) {
                JSONObject().put("error", problem.message ?: "Computer non raggiungibile")
            }
            catalogAnswers.replace(token, result.toString())
        }
    }

    @JavascriptInterface
    fun catalogResponse(token: String): String {
        val result = catalogAnswers[token] ?: return ""
        if (result.isNotEmpty()) catalogAnswers.remove(token)
        return result
    }

    @JavascriptInterface
    fun cancelCatalog(token: String) { catalogAnswers.remove(token) }

    @JavascriptInterface
    fun importAll(): String {
        val previous=PhotoImportStore(app).read()
        val scope=if(previous.phase=="paused") previous.scope else "photos-videos"
        val permissions=MediaFiles(app,if(scope=="all-media") setOf("image","video","audio") else if(scope=="documents") setOf("document") else setOf("image","video")).missingPermissions().isNotEmpty()
        app.runOnUiThread { app.startPhotoImport(scope=scope) }
        return JSONObject().put("background",true).put("queued",PhotoImportStore(app).read().remaining.size)
            .put("message",if(permissions) "Completa le autorizzazioni Android: poi inizierà l’importazione." else "Importazione richiesta. Puoi seguirla nella notifica e spegnere lo schermo.").toString()
    }

    @JavascriptInterface
    fun photoImportState():String=PhotoImportStore(app).json()

    @JavascriptInterface
    fun cancelPhotoImport() { PhotoImportService.cancel(app) }

    @JavascriptInterface
    fun newImportBlock()=app.runOnUiThread {
        try { val scope=PhotoImportStore(app).newBlock(memory.fingerprint); app.startPhotoImport(scope=scope) }
        catch(_:Exception) { /* Keep the previous committed checkpoint while it is still running. */ }
    }

    @JavascriptInterface
    fun pictures(): String = library.json()

    @JavascriptInterface
    fun reading(): String = JSONObject().put("allowed", gallery.allowed).put("done", library.done).put("total", library.total).toString()

    @JavascriptInterface
    fun state(): String = app.state().toString()

    /** Whether the phone can see what pictures show: its models, how much of them has arrived, how many pictures it has looked at. */
    @JavascriptInterface
    fun sight(): String = JSONObject()
        .put("ready", false)
        .put("wanted", false)
        .put("got", sight.got)
        .put("size", sight.size)
        .put("seen", library.seen)
        .put("unseen", library.unseen)
        .toString()

    /** The user wants the models: they come from the computer, as soon as it answers. */
    @JavascriptInterface
    fun wantSight() {
        // Experiment on standby. No download, activation or deletion of old weights.
    }

    /** Whether the computer has a newer app for this phone, and how much of it has arrived while it is taken. */
    @JavascriptInterface
    fun update(): String = JSONObject()
        .put("newer", update.newer > 0)
        .put("taking", update.size > 0)
        .put("got", update.got)
        .put("size", update.size)
        .toString()

    /** The user wants the newer app: it comes from the computer, and Android asks before installing it. */
    @JavascriptInterface
    fun takeUpdate() {
        if (update.newer == 0L) return
        update.wanted = true
        app.runOnUiThread { app.updateWanted() }
    }

    /** How close each picture is to a sentence, {"id": score}; null while the phone has no models. */
    @JavascriptInterface
    fun scores(sentence: String): String {
        if (!sight.ready || sentence.isBlank()) return "null"
        return library.scores(sight.sentence(sentence.take(500)))
    }

    /**
     * Asks the computer about a request typed here, if it answers: its director understands more
     * than the phone can by itself. What it finds comes a little at a time: each time the page is
     * told, by `token`, and takes it (answer). Last comes the answer, null when the computer has none.
     */
    @JavascriptInterface
    fun ask(text: String, token: String) {
        if (!TOKEN.matches(token)) return
        val computer = app.reached
        val said = ConcurrentLinkedQueue<JSONObject>()
        heard[token] = said
        thread(name = "ask") {
            var answered = false
            try {
                computer?.lines("/phone/ask/stream", JSONObject().put("text", text.take(500))) { event ->
                    val kind = event.optString("type")
                    if (kind !in SAID) return@lines
                    answered = answered || kind == "answer"
                    said.add(event)
                    app.answered(token)
                }
            } catch (unreachable: IOException) {
            } catch (garbled: JSONException) {
            }
            // the computer could not be asked, or stopped before the end: the page waits no more
            if (!answered) {
                said.add(JSONObject().put("type", "answer").put("answer", JSONObject.NULL))
                app.answered(token)
            }
        }
    }

    /** What the computer said about a request since the page last took it, as a JSON list; the last of all is the answer. */
    @JavascriptInterface
    fun answer(token: String): String {
        val said = heard[token] ?: return "[]"
        val taken = JSONArray()
        while (true) {
            val event = said.poll() ?: break
            taken.put(event)
            if (event.optString("type") == "answer") heard.remove(token)
        }
        return taken.toString()
    }

    /** Whether the new pictures go to the computer by themselves, and when they last did: {"on", "at", "count"}. */
    @JavascriptInterface
    fun autoCopy(): String = JSONObject().put("on", memory.autoCopy).put("at", memory.copiedAt).put("count", memory.copiedCount).toString()

    /**
     * Starts or stops the copying of the new pictures by themselves. They are the ones added from now
     * on: the pictures already on the phone stay where they are.
     */
    @JavascriptInterface
    fun setAutoCopy(on: Boolean) {
        memory.autoCopy = false
        CopyJob.plan(app, false)
    }

    @JavascriptInterface
    fun country(name: String): String = places.country(name)?.toString() ?: "null"

    @JavascriptInterface
    fun city(written: String): String = places.city(written)?.toString() ?: "null"

    @JavascriptInterface
    fun open(id: String) {
        id.toLongOrNull()?.let { picture -> app.runOnUiThread { app.view(gallery.named(picture)) } }
    }

    /** Puts pictures in line for the computer. They go when the computer can be reached, now or later. */
    @JavascriptInterface
    fun send(ids: String): String {
        val chosen = try {
            JSONArray(ids).let { list -> (0 until list.length()).map { list.getString(it) }.filter { it.toLongOrNull() != null } }
        } catch (wrong: org.json.JSONException) {
            emptyList()
        }
        if (chosen.isNotEmpty()) {
            memory.offer(chosen)
            app.runOnUiThread { app.offered(chosen.size) }
        }
        return JSONObject().put("queued", chosen.size).toString()
    }

    /** What the page asks for: its own files, and the small copies of the pictures. Nothing else is answered, and nothing goes out. */
    fun answer(request: WebResourceRequest): WebResourceResponse {
        val address = request.url
        val path = address.path.orEmpty()
        if (address.scheme != "https" || address.host != HOST) return refused()
        if (Regex("/catalog-media/[a-f0-9]{64}/(thumb|full)").matches(path)) {
            val id = path.split('/')[2]
            val local = runCatching { catalogCache.localMedia(id, gallery) }.getOrNull()
            if (local != null) {
                try {
                    if (path.endsWith("/thumb") && Build.VERSION.SDK_INT>=29) {
                        val bitmap=app.contentResolver.loadThumbnail(local.first,android.util.Size(384,384),null)
                        val buffer=java.io.ByteArrayOutputStream()
                        bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,85,buffer)
                        bitmap.recycle()
                        return WebResourceResponse("image/jpeg",null,ByteArrayInputStream(buffer.toByteArray()))
                    }
                    if (path.endsWith("/full")) app.contentResolver.openInputStream(local.first)?.let {
                        return WebResourceResponse(app.contentResolver.getType(local.first) ?: if(local.second=="video") "video/mp4" else "image/jpeg", null, it)
                    }
                } catch (_: Exception) { /* The PC copy may still be available. */ }
            }
            val computer = app.reached ?: return refused(503)
            val remote = path.removePrefix("/catalog-media/")
            return try {
                var data = ByteArray(0)
                val valid = computer.fetch("/api/catalog/photos/$remote") { input, expected ->
                    val bytes = java.io.ByteArrayOutputStream()
                    val digest = java.security.MessageDigest.getInstance("SHA-256")
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        if (bytes.size() + read > 64 * 1024 * 1024) throw IOException("Immagine troppo grande")
                        digest.update(buffer, 0, read)
                        bytes.write(buffer, 0, read)
                    }
                    data = bytes.toByteArray()
                    digest.digest().joinToString("") { "%02x".format(it) }.equals(expected, ignoreCase = true)
                }
                if (!valid) return refused(502)
                val stream = ByteArrayInputStream(data)
                val type = java.net.URLConnection.guessContentTypeFromStream(stream) ?: "image/jpeg"
                WebResourceResponse(type, null, 200, "OK", mapOf("Cache-Control" to "no-store"), stream)
            } catch (problem: IOException) { refused(503) }
        }
        if (path.startsWith("/thumb/")) {
            val small = path.removePrefix("/thumb/").toLongOrNull()?.let(gallery::small) ?: return refused(404)
            return WebResourceResponse("image/jpeg", null, 200, "OK", mapOf("Cache-Control" to "max-age=86400"), ByteArrayInputStream(small))
        }
        val file = path.removePrefix("/").takeIf { it.startsWith("telefono/") && ".." !in it } ?: return refused(404)
        return try {
            WebResourceResponse(kindOf(file), if (kindOf(file).startsWith("text/")) "utf-8" else null, app.assets.open(file))
        } catch (missing: IOException) {
            refused(404)
        }
    }

    private fun refused(status: Int = 403) = WebResourceResponse("text/plain", "utf-8", status, if (status == 404) "Not Found" else "Forbidden", emptyMap(), ByteArrayInputStream(ByteArray(0)))

    private fun kindOf(file: String) = when (file.substringAfterLast('.').lowercase()) {
        "html" -> "text/html"
        "js" -> "text/javascript"
        "css" -> "text/css"
        "svg" -> "image/svg+xml"
        "woff2" -> "font/woff2"
        "png" -> "image/png"
        else -> "application/octet-stream"
    }

    companion object {
        // what the page names an answer it waits for by: a few letters and figures, nothing that could be code
        private val TOKEN = Regex("[a-z0-9]{1,24}")

        // what the page knows of what the computer says: the pictures it finds, how far it is, and the answer
        private val SAID = setOf("photo", "looked", "answer")

        // a name reserved for pages that an app shows from its own files: no site in the world answers to it
        const val HOST = "appassets.androidplatform.net"
        const val START = "https://$HOST/telefono/telefono.html"
    }
}

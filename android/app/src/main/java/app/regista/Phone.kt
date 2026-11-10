package app.regista

import android.appwidget.AppWidgetManager
import android.content.ComponentName
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
) {
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

    @JavascriptInterface
    fun pictures(): String = library.json()

    @JavascriptInterface
    fun reading(): String = JSONObject().put("allowed", gallery.allowed).put("done", library.done).put("total", library.total).toString()

    @JavascriptInterface
    fun state(): String = app.state().toString()

    /** Whether the phone can see what pictures show: its models, how much of them has arrived, how many pictures it has looked at. */
    @JavascriptInterface
    fun sight(): String = JSONObject()
        .put("ready", sight.ready)
        .put("wanted", memory.wantsSight)
        .put("got", sight.got)
        .put("size", sight.size)
        .put("seen", library.seen)
        .put("unseen", library.unseen)
        .toString()

    /** The user wants the models: they come from the computer, as soon as it answers. */
    @JavascriptInterface
    fun wantSight() {
        memory.wantsSight = true
        app.runOnUiThread { app.sightWanted() }
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
        if (on && !memory.paired) return
        if (on && !memory.autoCopy) memory.autoAfter = gallery.newest()
        memory.autoCopy = on
        CopyJob.plan(app, on)
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

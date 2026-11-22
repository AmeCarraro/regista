package app.regista

import android.net.Uri
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** Reconciles the music on this phone with its paired PC. Completed copies survive a retry. */
class MusicSync(private val songs: Songs, private val memory: Memory) {
    private data class Status(
        val state: String = "idle",
        val id: String = "",
        val sent: Int = 0,
        val received: Int = 0,
        val toPc: Int = 0,
        val toPhone: Int = 0,
        val error: String = "",
    ) {
        fun json() = JSONObject()
            .put("state", state).put("id", id).put("sent", sent).put("received", received)
            .put("to_pc", toPc).put("to_phone", toPhone).put("error", error)
    }

    @Volatile private var status = Status()
    private val working = AtomicBoolean()
    private val checking = AtomicBoolean()
    private var lastCheck = -10_000L

    fun state(): String = status.json().toString()

    fun problem(reason: String) {
        if (!working.get()) status = Status(state = "error", error = reason)
    }

    fun poll(computer: Computer?) {
        val now = SystemClock.elapsedRealtime()
        if (computer == null || working.get() || now - lastCheck < 8000 || !checking.compareAndSet(false, true)) return
        lastCheck = now
        thread(name = "music sync request") {
            try {
                val request = computer.ask("GET", "/phone/music-sync/pending").optString("request")
                if (request.isNotEmpty()) {
                    if (songs.missingForSync().isEmpty()) start(computer, request)
                    else problem("Premi Sincronizza sul telefono e consenti l'accesso alla musica.")
                }
            } catch (_: IOException) {
                // Offline, or a previous version of Regista on the PC.
            } finally {
                checking.set(false)
            }
        }
    }

    fun start(computer: Computer, request: String = "") {
        if (!working.compareAndSet(false, true)) return
        val pairedWith = memory.fingerprint
        status = Status(state = "scanning")
        thread(name = "music sync") {
            try {
                reconcile(computer, pairedWith, request)
            } catch (problem: Refused) {
                val reason = if (problem.status == 404 && status.id.isEmpty()) "Aggiorna Regista sul PC e riprova."
                else problem.message ?: "Il PC ha interrotto la sincronizzazione."
                fail(computer, reason)
            } catch (_: SecurityException) {
                fail(computer, "Consenti l'accesso alla musica del telefono e riprova.")
            } catch (problem: IOException) {
                fail(computer, (problem as? CopyProblem)?.message ?: "Copia interrotta. Premi Sincronizza per riprendere.")
            } catch (_: JSONException) {
                fail(computer, "Il PC ha restituito una risposta incompleta. Premi Sincronizza per riprendere.")
            } finally {
                working.set(false)
            }
        }
    }

    private class CopyProblem(message: String) : IOException(message)

    private fun reconcile(computer: Computer, pairedWith: String, request: String) {
        fun checkPairing() {
            if (!memory.paired || memory.fingerprint != pairedWith) throw CopyProblem("Collegamento cambiato. Premi Sincronizza per riprendere.")
        }
        checkPairing()
        val job = computer.ask("POST", "/phone/music-sync/start", JSONObject().put("request", request)).getString("id")
        status = status.copy(id = job)
        var lastSignal = SystemClock.elapsedRealtime()
        fun heartbeat() {
            val now = SystemClock.elapsedRealtime()
            if (now - lastSignal >= 5000) {
                report(computer)
                lastSignal = now
            }
        }

        val local = linkedMapOf<String, Songs.Source>()
        var unreadable = 0
        for (song in songs.sources()) {
            checkPairing()
            val hash = try { songs.fingerprint(song.id) } catch (_: IOException) { null }
            if (hash == null) unreadable++ else local.putIfAbsent(hash, song)
            heartbeat()
        }
        val plan = computer.ask(
            "POST", "/phone/music-sync/plan",
            JSONObject().put("job", job).put("hashes", JSONArray(local.keys)),
        )
        val wanted = plan.getJSONArray("wanted")
        val download = plan.getJSONArray("download")
        status = status.copy(state = "copying", toPc = wanted.length(), toPhone = download.length())
        var tooLarge = 0
        for (index in 0 until wanted.length()) {
            checkPairing()
            val sha = wanted.getString(index)
            val song = local.getValue(sha)
            if (song.size > 400L * 1024 * 1024) {
                tooLarge++
                continue
            }
            val result = songs.open(song.id).use { source ->
                computer.send("/phone/music/received?name=${Uri.encode(song.name)}&sync=$job", song.size, source, sha)
            }
            if (!result.optBoolean("duplicate")) status = status.copy(sent = status.sent + 1)
            heartbeat()
        }
        for (index in 0 until download.length()) {
            checkPairing()
            val track = download.getJSONObject(index)
            val name = track.getString("name")
            val copied = computer.fetch("/phone/music/${Uri.encode(track.getString("id"))}") { source, sha ->
                source.use {
                    if (sha != track.getString("sha256")) throw CopyProblem("Il brano «$name» è cambiato sul PC. Riprova.")
                    songs.keepFromSync(name, track.getLong("size"), source, sha)
                }
            }
            if (copied) status = status.copy(received = status.received + 1)
            heartbeat()
        }
        if (unreadable > 0 || tooLarge > 0) {
            val reasons = listOfNotNull(
                if (unreadable > 0) "$unreadable file illeggibili sul telefono" else null,
                if (tooLarge > 0) "$tooLarge file oltre il limite di 400 MiB verso il PC" else null,
            )
            throw CopyProblem(reasons.joinToString(" e ") + ". Gli altri brani sono stati sincronizzati.")
        }
        status = status.copy(state = "ready")
        report(computer)
    }

    private fun fail(computer: Computer, reason: String) {
        status = status.copy(state = "error", error = reason.take(400))
        if (status.id.isNotEmpty()) runCatching { report(computer) }
    }

    private fun report(computer: Computer) {
        val body = status.json()
        body.put("job", body.getString("id"))
        computer.ask("POST", "/phone/music-sync/progress", body)
    }
}

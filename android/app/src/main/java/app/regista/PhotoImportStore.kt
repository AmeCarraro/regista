package app.regista

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.UUID

/** Private checkpoints are committed before the service moves on to another photo. */
class PhotoImportStore(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences("photo-import", Context.MODE_PRIVATE)

    fun read(): ImportCheckpoint = synchronized(LOCK) {
        val raw = preferences.getString("checkpoint", "{}") ?: "{}"
        cached?.let { (saved, state) -> if (saved == raw) return@synchronized state }
        try {
            val value = JSONObject(raw)
            val ids = value.optJSONArray("remaining") ?: JSONArray()
            val errors = value.optJSONArray("failed_media") ?: JSONArray()
            ImportCheckpoint(work=value.optString("work"), peer=value.optString("peer"), request=value.optString("request"),
                requested=value.optBoolean("requested"), prepared=value.optBoolean("prepared"),
                remaining=(0 until ids.length()).map { ids.getString(it) }, total=value.optInt("total"), copied=value.optInt("copied"),
                duplicates=value.optInt("duplicates"), failed=value.optInt("failed"), phase=value.optString("phase", "idle"), message=value.optString("message"),
                scope=value.optString("scope","photos-videos"),batch=value.optString("batch"),transport=value.optString("transport"),
                failedMedia=(0 until errors.length()).map { errors.getString(it) },
                groups=(value.optJSONObject("groups") ?: JSONObject()).let { map -> map.keys().asSequence().associateWith { map.getInt(it) } },
                members=(value.optJSONObject("members") ?: JSONObject()).let { map -> map.keys().asSequence().associateWith { map.getString(it) } },
                batches=(value.optJSONObject("batches") ?: JSONObject()).let { map -> map.keys().asSequence().associateWith { map.getString(it) } },
                finishedGroups=(value.optJSONArray("finished_groups") ?: JSONArray()).let { list -> (0 until list.length()).map { list.getString(it) }.toSet() })
                .also { cached = raw to it }
        } catch (_: Exception) {
            ImportCheckpoint(phase = "paused", message = "Avanzamento non leggibile. Premi Importa per ricontrollare i file già salvati sul PC.")
        }
    }

    private fun write(value: ImportCheckpoint): ImportCheckpoint {
        val json = JSONObject().put("work", value.work).put("peer", value.peer).put("request", value.request)
            .put("requested", value.requested).put("prepared", value.prepared).put("remaining", JSONArray(value.remaining))
            .put("total", value.total).put("copied", value.copied).put("duplicates", value.duplicates)
            .put("failed", value.failed).put("phase", value.phase).put("message", value.message)
            .put("scope",value.scope).put("batch",value.batch).put("transport",value.transport).put("failed_media",JSONArray(value.failedMedia))
            .put("groups",JSONObject(value.groups)).put("members",JSONObject(value.members)).put("batches",JSONObject(value.batches)).put("finished_groups",JSONArray(value.finishedGroups.toList()))
        val raw = json.toString()
        if (!preferences.edit().putString("checkpoint", raw).commit()) throw IOException("Non riesco a salvare l’avanzamento sul telefono.")
        cached = raw to value
        return value
    }

    fun begin(peer: String, request: String = "", ids: List<String>? = null,scope:String="photos-videos"): ImportCheckpoint = synchronized(LOCK) {
        val old = read()
        if (old.requested && old.peer == peer) return old
        val next = if (old.scope==scope && old.canResume(peer, "")) old.copy(request=if(request.isEmpty()) old.request else request,
            requested = true, phase = "waiting", message = "Riprendo i file rimasti.")
        else ImportCheckpoint(work = UUID.randomUUID().toString(), peer = peer, request = request, requested = true,
            phase = "starting", message = "Preparo l’importazione.",scope=scope)
        write(if (ids != null && !next.prepared) next.prepare(ids) else next)
    }

    fun newBlock(peer:String):String = synchronized(LOCK) {
        val previous=read()
        check(!previous.requested && !PhotoImportService.running) { "Metti prima in pausa l’importazione." }
        if(previous.work.isNotEmpty()) preferences.edit().putString("history-"+previous.work,preferences.getString("checkpoint","{}")).commit()
        write(ImportCheckpoint(peer=peer))
        previous.scope
    }

    fun update(work: String, change: (ImportCheckpoint) -> ImportCheckpoint): ImportCheckpoint = synchronized(LOCK) {
        val before = read()
        if (before.work != work || !before.requested) return before
        val after = change(before)
        if (after == before) before else write(after)
    }

    fun pause(message: String, dismissRequest: Boolean = true) = synchronized(LOCK) {
        val old = read()
        if (dismissRequest && old.request.isNotEmpty()) preferences.edit().putString("dismissed", old.request).commit()
        write(old.copy(requested = false, phase = "paused", message = message))
    }

    fun remoteAllowed(request: String, peer: String): Boolean = synchronized(LOCK) {
        if (request.isEmpty() || request == preferences.getString("dismissed", "")) return false
        val old = read()
        !(old.peer == peer && old.request == request && (old.requested || old.phase == "done"))
    }

    fun json(): String {
        val value = read()
        return JSONObject().put("active", value.requested).put("phase", value.phase).put("total", value.total)
            .put("processed", value.processed).put("copied", value.copied).put("duplicates", value.duplicates)
            .put("failed", value.failed).put("remaining", value.remaining.size).put("message", value.message)
            .put("scope",value.scope).put("batch",value.batch).put("transport",value.transport)
            .put("blocks",value.groups.size).put("blocks_ready",value.finishedGroups.size)
            .put("busy",PhotoImportService.running || value.requested).toString()
    }

    companion object {
        private val LOCK = Any()
        private var cached: Pair<String, ImportCheckpoint>? = null
    }
}

/** Adapts an import pass to its persisted scope; retried acknowledgements cannot inflate counters. */
class PhotoImportSession(private val store: PhotoImportStore, val work: String) {
    val state get() = store.read()
    val active get() = state.let { it.work == work && it.requested }
    fun attachRequest(request: String) {
        if (request.isNotEmpty()) store.update(work) { if (it.request.isEmpty()) it.copy(request = request) else it }
    }
    fun select(all: List<Photo>): List<Photo> {
        val value = store.update(work) { it.prepare(all.map { photo -> photo.id.toString() }) }
        val known = all.associateBy { it.id.toString() }
        for (id in value.remaining) if (id !in known) failed(id.toLong(), "Una foto non è più accessibile sul telefono.")
        return state.remaining.mapNotNull(known::get)
    }
    fun confirmed(id: Long, duplicate: Boolean) {
        store.update(work) { it.confirmed(id.toString(), if (duplicate) ImportOutcome.DUPLICATE else ImportOutcome.COPIED) }
    }
    fun failed(id: Long, reason: String) {
        store.update(work) { it.confirmed(id.toString(), ImportOutcome.FAILED).copy(message = reason) }
    }
    fun uploading(name: String) { store.update(work) { it.copy(phase = "uploading", message = name) } }
    fun finished() { store.update(work) { check(it.complete); it.copy(requested = false, phase = "done",
        message = if (it.failed == 0) "Importazione completata. I tag si avviano dal PC." else "Importazione terminata: ${it.failed} foto da riprovare.") } }
}

package app.regista

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** References to user-selected local videos. Files stay in their original folders. */
class Videos(private val context: Context) {
    private val saved = context.getSharedPreferences("videos", Context.MODE_PRIVATE)
    private val adding = AtomicBoolean(false)
    @Volatile private var problem = ""
    private fun entries() = runCatching { JSONArray(saved.getString("items", "[]")) }.getOrDefault(JSONArray())

    fun state(): String {
        val result = JSONArray()
        val entries = entries()
        for (index in 0 until entries.length()) {
            val item = entries.getJSONObject(index)
            result.put(JSONObject().put("id", item.getString("id")).put("title", item.getString("title")))
        }
        return JSONObject().put("videos", result).put("adding", adding.get()).put("error", problem).toString()
    }

    fun selected(uris: List<Uri>) {
        if (!adding.compareAndSet(false, true)) return
        thread(name = "selected videos") {
            try {
                val entries = entries()
                val known = (0 until entries.length()).map { entries.getJSONObject(it).getString("id") }.toMutableSet()
                var failures = 0
                for (uri in uris.distinct()) {
                    try {
                        require(uri.scheme == "content" && uri.toString().length <= 4000)
                        require(context.contentResolver.getType(uri)?.startsWith("video/") == true)
                        val id = MessageDigest.getInstance("SHA-256").digest(uri.toString().toByteArray())
                            .joinToString("") { "%02x".format(it) }
                        if (id in known) continue
                        require(known.size < 1000) { "La raccolta contiene già 1000 video." }
                        context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        val title = context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                            ?.use { if (it.moveToFirst()) it.getString(0) else null } ?: "Video"
                        entries.put(JSONObject().put("id", id).put("title", title).put("uri", uri.toString()))
                        known.add(id)
                    } catch (_: Exception) { failures++ }
                }
                saved.edit().putString("items", entries.toString()).commit()
                problem = if (failures == 0) "" else "$failures video non aggiunti: scegli file video accessibili sul telefono."
            } catch (_: Exception) {
                problem = "Non riesco a salvare la selezione dei video."
            } finally { adding.set(false) }
        }
    }

    fun named(id: String): JSONObject? {
        val entries = entries()
        return (0 until entries.length()).map { entries.getJSONObject(it) }.firstOrNull { it.getString("id") == id }
    }

    fun remove(id: String) {
        if (!adding.compareAndSet(false, true)) return
        try {
            val entries = entries()
            val keep = JSONArray()
            for (index in 0 until entries.length()) {
                val item = entries.getJSONObject(index)
                if (item.getString("id") == id) {
                    runCatching { context.contentResolver.releasePersistableUriPermission(Uri.parse(item.getString("uri")), Intent.FLAG_GRANT_READ_URI_PERMISSION) }
                } else keep.put(item)
            }
            saved.edit().putString("items", keep.toString()).commit()
        } finally {
            adding.set(false)
        }
    }
}

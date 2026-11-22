package app.regista

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/** Personal tags and playlists for the phone's music, stored apart from audio files. */
class MusicCollections(context: Context) {
    private val prefs = context.getSharedPreferences("music_library", Context.MODE_PRIVATE)

    @Synchronized
    fun state(): String = JSONObject().put("tags", read("tags")).put("playlists", read("playlists")).toString()

    @Synchronized
    fun tags(id: String, text: String): String {
        if (id.toLongOrNull() == null) return state()
        val tags = read("tags")
        val chosen = text.take(1200).split(',').map(String::trim).filter(String::isNotEmpty)
            .distinctBy { it.lowercase(Locale.ROOT) }.take(30)
        if (chosen.isEmpty()) tags.remove(id) else tags.put(id, JSONArray(chosen))
        write("tags", tags)
        return state()
    }

    @Synchronized
    fun playlist(name: String, query: String, tag: String): String {
        val title = name.trim().take(80)
        if (title.isEmpty() || (query.isBlank() && tag.isBlank())) return state()
        val playlists = read("playlists")
        playlists.put(
            title.lowercase(Locale.ROOT),
            JSONObject().put("name", title).put("query", query.trim().take(200)).put("tag", tag.trim().take(1200)),
        )
        write("playlists", playlists)
        return state()
    }

    private fun read(key: String) = JSONObject(prefs.getString(key, "{}") ?: "{}")

    private fun write(key: String, value: JSONObject) {
        prefs.edit().putString(key, value.toString()).apply()
    }
}

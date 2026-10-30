package app.regista

import android.content.Context
import android.util.Base64
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * The pictures of this phone by kind, as the computer sorts its own (kinds.py): what each kind comes
 * to in numbers is taken once from the computer and kept here, and then the phone sorts its pictures
 * by itself, also away from home. Only the pictures whose numbers it has, its own or the computer's,
 * can be sorted. Nothing is moved: it is a way of looking at the gallery.
 */
class Kinds(context: Context, private val library: Library) {
    private val kept = File(context.filesDir, "kinds.json")

    // what was worked out last, and for which kinds and pictures: the page asks every two seconds, and it is
    // worked out again only when the kinds arrived or the pictures changed
    @Volatile private var made: Pair<List<Long>, String>? = null

    /** Keeps what the computer said of the kinds, for the next time too. */
    fun keep(said: JSONObject) {
        val partial = File(kept.parentFile, "${kept.name}.part")
        partial.writeText(said.toString())
        partial.renameTo(kept)
    }

    /**
     * {"kinds": [{"kind", "label", "sure": [ids], "maybe": [ids]}], "unsorted": how many pictures have no numbers yet};
     * null while the computer never said what the kinds are.
     */
    fun sorted(): String {
        val key = listOf(kept.lastModified(), library.seen.toLong(), library.unseen.toLong(), library.total.toLong())
        made?.let { (before, sorted) -> if (before == key) return sorted }
        return work().also { made = key to it }
    }

    private fun work(): String {
        val said = try {
            JSONObject(kept.takeIf { it.exists() }?.readText() ?: return "null")
        } catch (garbled: JSONException) {
            return "null"
        }
        val listed = said.getJSONArray("kinds")
        val margin = said.optDouble("margin", 0.01).toFloat()
        val vectors = (0 until listed.length()).map { at ->
            val bytes = Base64.decode(listed.getJSONObject(at).getString("vector"), Base64.DEFAULT)
            FloatArray(Sight.SIZE).also { ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(it) }
        }
        val sure = List(vectors.size) { JSONArray() }
        val maybe = List(vectors.size) { JSONArray() }
        val screenshots = JSONArray()
        library.looked { id, name, vector ->
            if (SCREENSHOT.containsMatchIn(name)) {
                screenshots.put(id.toString())
                return@looked
            }
            var first = -1
            var best = -Float.MAX_VALUE
            var next = -Float.MAX_VALUE
            for ((at, kind) in vectors.withIndex()) {
                var score = 0f
                for (index in 0 until Sight.SIZE) score += vector.get(index) * kind[index]
                if (score > best) {
                    next = best
                    best = score
                    first = at
                } else if (score > next) {
                    next = score
                }
            }
            (if (best - next >= margin) sure else maybe)[first].put(id.toString())
        }
        val kinds = JSONArray()
        for (at in 0 until listed.length()) {
            val kind = listed.getJSONObject(at)
            kinds.put(JSONObject().put("kind", kind.getString("kind")).put("label", kind.getString("label")).put("sure", sure[at]).put("maybe", maybe[at]))
        }
        kinds.put(JSONObject().put("kind", "schermate").put("label", "Schermate").put("sure", screenshots).put("maybe", JSONArray()))
        return JSONObject().put("kinds", kinds).put("unsorted", library.unseen).toString()
    }

    companion object {
        // a screenshot as phones name it: by its name, not by what it shows (kinds.py)
        private val SCREENSHOT = Regex("screen\\s*shot|schermat[ae]|bildschirmfoto|captura", RegexOption.IGNORE_CASE)
    }
}

package app.regista

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import android.database.sqlite.SQLiteOpenHelper
import android.icu.lang.UCharacter
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.text.Normalizer

/** Manual tags created from an explicitly confirmed selection in the command preview. */
class ManualTags(context: Context, private val gallery: Gallery) : SQLiteOpenHelper(context, "command-tags.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE photo_tag (
                tag TEXT NOT NULL,
                media_id INTEGER NOT NULL,
                identity TEXT NOT NULL,
                PRIMARY KEY (tag, media_id, identity)
            )
        """.trimIndent())
    }

    override fun onUpgrade(db: SQLiteDatabase, before: Int, now: Int) = Unit

    @Synchronized
    fun apply(action: String, tag: String, idsJson: String): String = reply {
        require(action == "add_tag" || action == "remove_tag") { "Questa azione non modifica i tag." }
        val key = key(tag)
        val ids = selection(idsJson)
        val current = gallery.identities(ids)
        require(current.size == ids.size) { "Almeno una foto selezionata non è più disponibile. Aggiorna la selezione." }

        val db = writableDatabase
        var changed = 0
        db.beginTransaction()
        try {
            for ((id, identity) in current) {
                if (action == "add_tag") {
                    val values = ContentValues().apply {
                        put("tag", key)
                        put("media_id", id)
                        put("identity", identity)
                    }
                    if (db.insertWithOnConflict("photo_tag", null, values, SQLiteDatabase.CONFLICT_IGNORE) != -1L) changed += 1
                } else {
                    changed += db.delete("photo_tag", "tag = ? AND media_id = ? AND identity = ?", arrayOf(key, id.toString(), identity))
                }
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        JSONObject().put("changed", changed)
    }

    @Synchronized
    fun find(tag: String): String = reply {
        val candidates = mutableListOf<Pair<Long, String>>()
        readableDatabase.query("photo_tag", arrayOf("media_id", "identity"), "tag = ?", arrayOf(key(tag)), null, null, "media_id").use { rows ->
            while (rows.moveToNext()) candidates += rows.getLong(0) to rows.getString(1)
        }
        val current = gallery.identities(candidates.map { it.first }.distinct())
        val found = JSONArray()
        for ((id, identity) in candidates) {
            if (current[id] == identity) found.put(id.toString())
        }
        JSONObject().put("ids", found)
    }

    private fun key(tag: String): String {
        require(tag.length <= 500) { "Scrivi un tag di al massimo 500 caratteri." }
        val display = SPACE.replace(tag, " ").trim(' ')
        require(display.isNotEmpty()) { "Il tag non può essere vuoto." }
        val normalized = Normalizer.normalize(display, Normalizer.Form.NFKC)
        return Normalizer.normalize(UCharacter.foldCase(normalized, true), Normalizer.Form.NFKC)
    }

    private fun selection(json: String): Set<Long> {
        // A positive decimal Long encoded as JSON uses at most 22 characters including separators.
        require(json.length <= 3_000) { "Seleziona al massimo 120 foto." }
        val raw = JSONArray(json)
        require(raw.length() in 1..120) { "Seleziona da 1 a 120 foto." }
        val ids = LinkedHashSet<Long>()
        for (index in 0 until raw.length()) {
            val text = raw.opt(index) as? String
            val id = text?.toLongOrNull()
            require(id != null && id > 0 && id.toString() == text && ids.add(id)) { "La selezione delle foto non è valida." }
        }
        return ids
    }

    private fun reply(work: () -> JSONObject): String = try {
        if (!gallery.allowed) throw SecurityException()
        work().toString()
    } catch (problem: SecurityException) {
        failure("Consenti l’accesso alle foto per usare i tag.")
    } catch (problem: IllegalArgumentException) {
        failure(problem.message ?: "La richiesta per i tag non è valida.")
    } catch (problem: JSONException) {
        failure("La selezione delle foto non è valida.")
    } catch (problem: IOException) {
        failure("Non riesco a leggere le foto adesso. Riprova.")
    } catch (problem: SQLiteException) {
        failure("Non riesco ad aprire il catalogo dei tag. Riprova.")
    }

    private fun failure(message: String) = JSONObject().put("error", message).toString()

    private companion object {
        val SPACE = Regex("""[\p{Z}\u0009-\u000d\u001c-\u001f\u0085]+""")
    }
}

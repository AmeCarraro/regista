package app.regista

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.os.SystemClock
import android.system.Os
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** Read-only PC annotations, indexed on the phone. No vision, embeddings or model runtime. */
class CatalogCache(private val context: Context, private val memory: Memory) {
    private val file = File(context.filesDir, "pc-catalog.sqlite")
    private val settings = context.getSharedPreferences("pc-catalog", Context.MODE_PRIVATE)
    private val lock = Any()
    private val syncing = AtomicBoolean(false)
    @Volatile private var attempted = 0L
    @Volatile private var problem = ""
    private var epoch = 0L

    private fun active() = memory.paired && memory.fingerprint.isNotBlank() &&
        settings.getString("source", "") == memory.fingerprint && file.isFile

    private fun <T> read(block: (SQLiteDatabase) -> T): T = synchronized(lock) {
        if (!active()) throw IOException("Sincronizza il catalogo dal PC quando è collegato.")
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use(block)
    }

    private fun meta(db: SQLiteDatabase, key: String): String = db.rawQuery(
        "SELECT value FROM meta WHERE key=?", arrayOf(key)).use { if (it.moveToFirst()) it.getString(0) else "null" }

    fun state(): JSONObject {
        val state = JSONObject().put("ready", false).put("syncing", syncing.get()).put("count", 0)
            .put("at", 0L).put("error", problem)
        try {
            read { db -> state.put("ready", true).put("count", meta(db, "count").toLong())
                .put("at", meta(db, "created_ms").toLong()) }
        } catch (_: Exception) { /* No partial or foreign catalog is shown. */ }
        return state
    }

    /** A failed download leaves the last verified snapshot available for offline searches. */
    fun sync(computer: Computer?, force: Boolean = false) {
        if (computer == null || !memory.paired) return
        val now = SystemClock.elapsedRealtime()
        if (!force && attempted != 0L && now - attempted < 5 * 60_000) return
        if (!syncing.compareAndSet(false, true)) return
        attempted = now
        val source = memory.fingerprint
        val generation = synchronized(lock) { epoch }
        thread(name = "catalog sync") {
            var candidate: File? = null
            try {
                val temporary = File.createTempFile("catalog-", ".sqlite", context.filesDir)
                candidate = temporary
                val verified = computer.fetch("/phone/catalog/snapshot") { input, expected ->
                    val digest = MessageDigest.getInstance("SHA-256")
                    var size = 0L
                    FileOutputStream(temporary).use { output ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            val length = input.read(buffer)
                            if (length < 0) break
                            size += length
                            if (size > 128L * 1024 * 1024) throw IOException("Catalogo oltre il limite tecnico di 128 MB.")
                            digest.update(buffer, 0, length)
                            output.write(buffer, 0, length)
                        }
                        output.fd.sync()
                    }
                    digest.digest().joinToString("") { "%02x".format(it) }.equals(expected, ignoreCase = true)
                }
                if (!verified) throw IOException("Il catalogo non è arrivato integro. La copia precedente resta disponibile.")
                SQLiteDatabase.openDatabase(temporary.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                    if (db.version != 1 || meta(db, "version") != "1") throw IOException("Aggiorna Regista su telefono e PC.")
                    db.rawQuery("PRAGMA quick_check", null).use {
                        if (!it.moveToFirst() || it.getString(0) != "ok") throw IOException("Catalogo danneggiato.")
                    }
                    val count = db.rawQuery("SELECT count(*) FROM photos", null).use { it.moveToFirst(); it.getLong(0) }
                    if (count != meta(db, "count").toLong()) throw IOException("Catalogo incompleto.")
                    db.rawQuery("SELECT body FROM search_text LIMIT 1", null).use { it.moveToFirst() }
                    JSONArray(meta(db, "synonyms"))
                    JSONObject(meta(db, "counts"))
                }
                synchronized(lock) {
                    if (epoch != generation || !memory.paired || memory.fingerprint != source) return@synchronized
                    Os.rename(temporary.path, file.path)
                    settings.edit().putString("source", source).commit()
                    problem = ""
                }
            } catch (error: Exception) {
                if (memory.fingerprint == source) problem = error.message ?: "Sincronizzazione non riuscita."
            } finally {
                candidate?.delete()
                syncing.set(false)
            }
        }
    }

    /** Only this app's downloaded metadata is removed; originals and old experiment weights stay intact. */
    fun clear() = synchronized(lock) {
        epoch++
        settings.edit().clear().commit()
        file.delete()
        attempted = 0L
        problem = ""
    }

    fun search(query: String, offset: Int): JSONObject = read { db ->
        if (query.length > 1000 || offset !in 0..1_000_000) throw IOException("Ricerca troppo lunga o pagina non valida.")
        val counts = JSONObject(meta(db, "counts"))
        val groups = JSONArray(meta(db, "synonyms"))
        val countMap = counts.keys().asSequence().associateWith { counts.getString(it) }
        val synonyms = (0 until groups.length()).map { index -> groups.getJSONArray(index).let { group ->
            (0 until group.length()).map { group.getString(it) } } }
        val expressions = CatalogQuery.expressions(query, countMap, synonyms)
        val where = if (expressions.isEmpty()) "" else " WHERE " + expressions.joinToString(" AND ") {
            "rowid IN (SELECT docid FROM search_text WHERE search_text MATCH ?)"
        }
        val args = expressions.toTypedArray()
        val total = db.rawQuery("SELECT count(*) FROM photos$where", args).use { it.moveToFirst(); it.getLong(0) }
        val photos = JSONArray()
        db.rawQuery("SELECT id,name,description,metadata,tags,day,stage FROM photos$where ORDER BY day DESC,id LIMIT 60 OFFSET ?",
            (expressions + offset.toString()).toTypedArray()).use { rows ->
            while (rows.moveToNext()) photos.put(JSONObject().put("id", rows.getString(0)).put("name", rows.getString(1))
                .put("description", rows.getString(2)).put("metadata", JSONObject(rows.getString(3)))
                .put("tags", JSONArray(rows.getString(4))).put("stage", rows.getString(6)))
        }
        JSONObject().put("photos", photos).put("total", total).put("offset", offset).put("limit", 60)
    }

    /** Match strong MediaStore identities before reusing the phone's original or thumbnail. */
    fun local(id: String, gallery: Gallery): Long? = read { db ->
        db.rawQuery("SELECT media,stamp FROM phone_media WHERE asset_id=?", arrayOf(id)).use { rows ->
            while (rows.moveToNext()) {
                val media = rows.getString(0).toLongOrNull() ?: continue
                try {
                    if (gallery.identities(listOf(media))[media] == rows.getString(1)) return@read media
                } catch (_: Exception) { /* Removed file or revoked permission: use the PC copy. */ }
            }
        }
        null
    }

}

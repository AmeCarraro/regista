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

    private fun active() = file.isFile

    private fun <T> read(block: (SQLiteDatabase) -> T): T = synchronized(lock) {
        if (!active()) throw IOException("Sincronizza il catalogo dal PC quando è collegato.")
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use(block)
    }

    private fun meta(db: SQLiteDatabase, key: String): String = db.rawQuery(
        "SELECT value FROM meta WHERE key=?", arrayOf(key)).use { if (it.moveToFirst()) it.getString(0) else "null" }
    private fun table(db:SQLiteDatabase,name:String)=db.rawQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",arrayOf(name)).use { it.moveToFirst() }
    private fun hasKind(db:SQLiteDatabase)=db.rawQuery("PRAGMA table_info(photos)",null).use { rows -> var found=false
        while(rows.moveToNext()) if(rows.getString(1)=="kind") found=true; found }

    fun state(): JSONObject {
        val state = JSONObject().put("ready", false).put("syncing", syncing.get()).put("count", 0)
            .put("at", 0L).put("error", problem)
        try {
            read { db -> state.put("ready", true).put("count", meta(db, "count").toLong())
                .put("at", meta(db, "created_ms").toLong())
                val albums=JSONArray()
                if(table(db,"albums")) db.rawQuery("SELECT id,name,hidden FROM albums ORDER BY name",null).use { rows ->
                    while(rows.moveToNext()) albums.put(JSONObject().put("id",rows.getString(0)).put("name",rows.getString(1)).put("hidden",rows.getInt(2)==1)) }
                state.put("albums",albums)
            }
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
                    // Keep the previous verified catalog when changing PCs or when an export has fewer entries.
                    if(file.isFile) {
                        val oldCount=SQLiteDatabase.openDatabase(file.path,null,SQLiteDatabase.OPEN_READONLY).use { meta(it,"count").toLong() }
                        val newCount=SQLiteDatabase.openDatabase(temporary.path,null,SQLiteDatabase.OPEN_READONLY).use { meta(it,"count").toLong() }
                        if(settings.getString("source","")!=source || newCount<oldCount) archive()
                    }
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

    private fun archive() {
        if(!file.isFile) return
        val digest=file.inputStream().use { stream -> val md=MessageDigest.getInstance("SHA-256"); val buffer=ByteArray(65536)
            while(true) { val size=stream.read(buffer); if(size<0) break; md.update(buffer,0,size) }; md.digest().joinToString(""){"%02x".format(it)} }
        val directory=File(context.filesDir,"saved-catalogs").apply { mkdirs() }
        val destination=File(directory,"$digest.sqlite")
        if(!destination.exists()) file.copyTo(destination)
    }

    /** Disconnect only revokes network access. The last metadata remains searchable offline. */
    fun disconnected() = synchronized(lock) {
        epoch++
        archive()
        attempted = 0L
        problem = ""
    }

    fun search(query: String, offset: Int,filters:JSONObject=JSONObject()): JSONObject = read { db ->
        if (query.length > 1000 || offset !in 0..1_000_000) throw IOException("Ricerca troppo lunga o pagina non valida.")
        val counts = JSONObject(meta(db, "counts"))
        val groups = JSONArray(meta(db, "synonyms"))
        val countMap = counts.keys().asSequence().associateWith { counts.getString(it) }
        val synonyms = (0 until groups.length()).map { index -> groups.getJSONArray(index).let { group ->
            (0 until group.length()).map { group.getString(it) } } }
        val expressions = CatalogQuery.expressions(query, countMap, synonyms)
        val conditions=expressions.map {
            "rowid IN (SELECT docid FROM search_text WHERE search_text MATCH ?)"
        }.toMutableList()
        val values=expressions.toMutableList()
        val kind=filters.optString("kind","all")
        if(hasKind(db) && kind in setOf("image","video")) { conditions+="kind=?"; values+=kind }
        for(key in listOf("since","until")) if(filters.optString(key).matches(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}"))) {
            conditions+="day${if(key=="since") ">=" else "<="}?"; values+=filters.getString(key) }
        val album=filters.optString("album")
        if(album.isNotEmpty() && table(db,"album_items")) { conditions+="id IN (SELECT asset_id FROM album_items WHERE album_id=?)"; values+=album }
        if(!filters.optBoolean("include_hidden") && album.isEmpty() && table(db,"albums")) {
            conditions+="id NOT IN (SELECT asset_id FROM hidden_media)"
            conditions+="id NOT IN (SELECT i.asset_id FROM album_items i JOIN albums a ON a.id=i.album_id WHERE a.hidden=1)"
        }
        val where=if(conditions.isEmpty()) "" else " WHERE "+conditions.joinToString(" AND ")
        val args = values.toTypedArray()
        val total = db.rawQuery("SELECT count(*) FROM photos$where", args).use { it.moveToFirst(); it.getLong(0) }
        val photos = JSONArray()
        val kindColumn=if(hasKind(db)) "kind" else "'image'"
        db.rawQuery("SELECT id,name,description,metadata,tags,day,stage,$kindColumn FROM photos$where ORDER BY day DESC,id LIMIT 60 OFFSET ?",
            (values + offset.toString()).toTypedArray()).use { rows ->
            while (rows.moveToNext()) photos.put(JSONObject().put("id", rows.getString(0)).put("name", rows.getString(1))
                .put("description", rows.getString(2)).put("metadata", JSONObject(rows.getString(3)))
                .put("tags", JSONArray(rows.getString(4))).put("stage", rows.getString(6)).put("kind",rows.getString(7)))
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

    fun localMedia(id:String,gallery:Gallery):Pair<android.net.Uri,String>? = read { db ->
        val scanner=MediaFiles(context,setOf("image","video"))
        db.rawQuery("SELECT media,stamp FROM phone_media WHERE asset_id=?",arrayOf(id)).use { rows ->
            while(rows.moveToNext()) {
                val media=rows.getString(0)
                try {
                    if(media.startsWith("tree:")) BackupFolders(context).resolve(media,rows.getString(1))?.let { return@read it }
                    scanner.resolve(media,rows.getString(1))?.let { return@read it }
                    val legacy=media.toLongOrNull()
                    if(legacy!=null && gallery.identities(listOf(legacy))[legacy]==rows.getString(1)) return@read Pair(gallery.named(legacy),"image")
                } catch(_:Exception) { }
            }
        }
        null
    }

}

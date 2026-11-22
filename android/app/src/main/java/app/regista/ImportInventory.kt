package app.regista

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray

/** The current selection and its scan cursors are checkpointed a page at a time. */
internal class ImportInventory private constructor(context: Context) :
    SQLiteOpenHelper(context.applicationContext, "import-inventory.sqlite", null, 1) {
    data class Source(val media: String, val stamp: String, val day: String, val group: String) {
        constructor(file: BackupMedia) : this(file.media, file.stamp, file.day, ImportGroups.key(file.folder, file.kind, file.name))
    }

    data class CollectionPosition(val version: String, val lastId: Long = -1, val done: Boolean = false)
    data class Folder(val key: String, val tree: String, val document: String, val relative: String, val grant: String,
                      val position: Int = -1, val anchor: String = "")
    data class FolderFile(val source: Source, val record: String)

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execSQL("""CREATE TABLE selected (
            media TEXT PRIMARY KEY, stamp TEXT NOT NULL, day TEXT NOT NULL, block TEXT NOT NULL, source TEXT NOT NULL
        )""")
        db.execSQL("CREATE INDEX selected_source ON selected(source)")
        db.execSQL("""CREATE TABLE folders (
            key TEXT PRIMARY KEY, tree TEXT NOT NULL, document TEXT NOT NULL, relative TEXT NOT NULL,
            grant_id TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT -1,
            anchor TEXT NOT NULL DEFAULT ''
        )""")
        db.execSQL("CREATE TABLE folder_files (media TEXT PRIMARY KEY, record TEXT NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    private fun transaction(change: (SQLiteDatabase) -> Unit) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            change(db)
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }

    private fun state(db: SQLiteDatabase, key: String): String? =
        db.rawQuery("SELECT value FROM state WHERE key=?", arrayOf(key)).use { if (it.moveToFirst()) it.getString(0) else null }

    private fun saveState(db: SQLiteDatabase, key: String, value: String) {
        db.execSQL("INSERT OR REPLACE INTO state(key, value) VALUES (?, ?)", arrayOf(key, value))
    }

    fun begin(work: String) {
        if (state(readableDatabase, "work") == work) return
        transaction { db ->
            db.execSQL("DELETE FROM selected")
            db.execSQL("DELETE FROM folders")
            db.execSQL("DELETE FROM state")
            saveState(db, "work", work)
        }
    }

    private fun saveSources(db: SQLiteDatabase, origin: String, items: List<Source>) {
        db.compileStatement("INSERT OR IGNORE INTO selected(media, stamp, day, block, source) VALUES (?,?,?,?,?)").use { insert ->
            for (file in items) {
                insert.bindString(1, file.media)
                insert.bindString(2, file.stamp)
                insert.bindString(3, file.day)
                insert.bindString(4, file.group)
                insert.bindString(5, origin)
                insert.executeInsert()
            }
        }
    }

    fun collectionPosition(key: String, version: String): CollectionPosition {
        val old = state(readableDatabase, key)?.let(::JSONArray) ?: return CollectionPosition(version)
        if (old.getString(0) == version) return CollectionPosition(version, old.getLong(1), old.getBoolean(2))
        // A MediaStore rebuild can reuse IDs. Restart only the affected collection during selection.
        transaction { db ->
            db.execSQL("DELETE FROM selected WHERE source=?", arrayOf(key))
            db.execSQL("DELETE FROM state WHERE key=?", arrayOf(key))
        }
        return CollectionPosition(version)
    }

    fun saveCollection(key: String, position: CollectionPosition, items: List<Source>) = transaction { db ->
        saveSources(db, key, items)
        saveState(db, key, JSONArray().put(position.version).put(position.lastId).put(position.done).toString())
    }

    private fun addFolders(db: SQLiteDatabase, folders: List<Folder>) {
        for (folder in folders) {
            db.execSQL("INSERT OR IGNORE INTO folders(key, tree, document, relative, grant_id) VALUES (?,?,?,?,?)",
                arrayOf(folder.key, folder.tree, folder.document, folder.relative, folder.grant))
        }
    }

    fun needsFolderRoots() = state(readableDatabase, "folder-roots") == null

    fun saveFolderRoots(roots: List<Folder>) = transaction { db ->
        addFolders(db, roots)
        saveState(db, "folder-roots", "1")
    }

    fun nextFolder(): Folder? = readableDatabase.rawQuery(
        "SELECT key, tree, document, relative, grant_id, position, anchor FROM folders WHERE done=0 ORDER BY rowid LIMIT 1", null,
    ).use { if (it.moveToFirst()) Folder(it.getString(0), it.getString(1), it.getString(2), it.getString(3), it.getString(4),
        it.getInt(5), it.getString(6)) else null }

    fun savedIn(folder: Folder): Set<String> = readableDatabase.rawQuery(
        "SELECT media FROM selected WHERE source=?", arrayOf(folder.key),
    ).use { rows -> buildSet { while (rows.moveToNext()) add(rows.getString(0)) } }

    fun saveFolder(folder: Folder, files: List<FolderFile>, children: List<Folder>, done: Boolean) = transaction { db ->
        saveSources(db, folder.key, files.map { it.source })
        for (file in files) db.execSQL("INSERT OR REPLACE INTO folder_files(media, record) VALUES (?,?)", arrayOf(file.source.media, file.record))
        addFolders(db, children)
        db.execSQL("UPDATE folders SET done=?, position=?, anchor=? WHERE key=?",
            arrayOf(if (done) 1 else 0, folder.position, folder.anchor, folder.key))
    }

    fun folderRecord(media: String): String? = readableDatabase.rawQuery(
        "SELECT record FROM folder_files WHERE media=?", arrayOf(media),
    ).use { if (it.moveToFirst()) it.getString(0) else null }

    fun selectedDocumentsRecorded() = state(readableDatabase, "documents") != null

    fun saveDocuments(files: List<Source>) = transaction { db ->
        saveSources(db, "documents", files)
        saveState(db, "documents", "1")
    }

    fun selection(): List<Source> = readableDatabase.rawQuery(
        "SELECT media, stamp, day, block FROM selected ORDER BY day, media", null,
    ).use { rows -> buildList { while (rows.moveToNext()) add(Source(rows.getString(0), rows.getString(1), rows.getString(2), rows.getString(3))) } }

    fun stamps(media: List<String>): Map<String, String> {
        if (media.isEmpty()) return emptyMap()
        val values = media.joinToString(",") { "?" }
        return readableDatabase.rawQuery("SELECT media, stamp FROM selected WHERE media IN ($values)", media.toTypedArray())
            .use { rows -> buildMap { while (rows.moveToNext()) put(rows.getString(0), rows.getString(1)) } }
    }

    fun size(): Int = readableDatabase.rawQuery("SELECT count(*) FROM selected", null).use { it.moveToFirst(); it.getInt(0) }

    companion object {
        const val PAGE_SIZE = 256
        private var shared: ImportInventory? = null

        @Synchronized fun open(context: Context): ImportInventory =
            shared ?: ImportInventory(context).also { shared = it }
    }
}

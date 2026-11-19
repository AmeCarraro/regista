package app.regista

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.security.MessageDigest
import java.util.ArrayDeque

/** Extra explicitly-authorized directory trees, including media not indexed because of .nomedia. */
class BackupFolders(private val context: Context) {
    private val settings = context.getSharedPreferences("backup-folders", Context.MODE_PRIVATE)
    private fun roots(): JSONArray = runCatching { JSONArray(settings.getString("roots", "[]")) }.getOrDefault(JSONArray())

    fun state(): JSONObject {
        val shown = JSONArray()
        val roots = roots()
        for (index in 0 until roots.length()) {
            val root = roots.optJSONObject(index) ?: continue
            shown.put(JSONObject().put("id", root.optString("id")).put("name", root.optString("name")))
        }
        return JSONObject().put("folders", shown)
    }

    /** Called only for a tree the user selected in Android's directory picker. */
    @Synchronized fun add(uri: Uri) {
        require(uri.scheme == "content" && DocumentsContract.isTreeUri(uri)) { "Scegli una cartella con il selettore Android." }
        require(uri.toString().length <= 4000) { "Identificativo della cartella troppo lungo." }
        val documentId = DocumentsContract.getTreeDocumentId(uri)
        require(allowed(uri, documentId)) { "Android/data e Android/obb non sono cartelle accessibili per questo backup." }
        val document = DocumentsContract.buildDocumentUriUsingTree(uri, documentId)
        val info = described(document) ?: throw IOException("La cartella non è leggibile.")
        require(info.directory) { "Seleziona una cartella, non un file." }
        context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        val roots = roots()
        val id = hash(uri.toString())
        if ((0 until roots.length()).any { roots.optJSONObject(it)?.optString("id") == id }) return
        roots.put(JSONObject().put("id", id).put("uri", uri.toString()).put("name", BackupFolderPolicy.label(info.name)))
        if (!settings.edit().putString("roots", roots.toString()).commit()) {
            runCatching { context.contentResolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            throw IOException("Non riesco a memorizzare la cartella scelta.")
        }
    }

    @Synchronized fun remove(id: String) {
        val roots = roots()
        val keep = JSONArray()
        val release = mutableListOf<Uri>()
        for (index in 0 until roots.length()) {
            val root = roots.optJSONObject(index) ?: continue
            if (root.optString("id") == id) release += Uri.parse(root.getString("uri")) else keep.put(root)
        }
        if (!settings.edit().putString("roots", keep.toString()).commit()) throw IOException("Non riesco ad aggiornare le cartelle del backup.")
        release.forEach { runCatching { context.contentResolver.releasePersistableUriPermission(it, Intent.FLAG_GRANT_READ_URI_PERMISSION) } }
    }

    private data class Entry(val id: String, val name: String, val mime: String, val size: Long, val modified: Long, val flags: Int) {
        val directory get() = mime == DocumentsContract.Document.MIME_TYPE_DIR
        val virtual get() = flags and DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT != 0
        fun stamp() = hash("$id\u0000$name\u0000$mime\u0000$size\u0000$modified\u0000$flags")
    }

    private fun described(uri: Uri): Entry? = context.contentResolver.query(uri, COLUMNS, null, null, null)?.use { rows ->
        if (!rows.moveToFirst()) return@use null
        Entry(rows.getString(0).orEmpty(), rows.getString(1).orEmpty(), rows.getString(2).orEmpty(),
            if (rows.isNull(3)) -1 else rows.getLong(3), if (rows.isNull(4)) 0 else rows.getLong(4),
            if (rows.isNull(5)) 0 else rows.getInt(5))
    }

    fun scan(cancelled: () -> Boolean, onProblem: (String) -> Unit): List<BackupMedia> {
        val files = mutableListOf<BackupMedia>()
        val visited = HashSet<String>()
        val roots = roots()
        for (index in 0 until roots.length()) {
            if (cancelled()) break
            val root = roots.optJSONObject(index) ?: continue
            val tree = Uri.parse(root.optString("uri"))
            val rootName = root.optString("name", "cartella")
            try {
                val rootId = DocumentsContract.getTreeDocumentId(tree)
                if (!allowed(tree, rootId)) throw IOException("Cartella protetta da Android.")
                val pending = ArrayDeque<Pair<String, String>>()
                // External-storage document IDs retain volume and original ancestor folders.
                // They are metadata only, never paths written on the PC.
                val rootPath = if (tree.authority == "com.android.externalstorage.documents") rootId else rootName
                pending.add(rootId to rootPath)
                while (pending.isNotEmpty() && !cancelled()) {
                    val (directory, relative) = pending.removeFirst()
                    if (!visited.add("${tree.authority}\u0000$directory")) continue
                    try {
                        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, directory)
                        val cursor = context.contentResolver.query(children, COLUMNS, null, null, null)
                            ?: throw IOException("Elenco della cartella non disponibile.")
                        cursor.use { rows ->
                            while (!cancelled() && rows.moveToNext()) {
                                val entry = Entry(rows.getString(0).orEmpty(), rows.getString(1).orEmpty(), rows.getString(2).orEmpty(),
                                    if (rows.isNull(3)) -1 else rows.getLong(3), if (rows.isNull(4)) 0 else rows.getLong(4),
                                    if (rows.isNull(5)) 0 else rows.getInt(5))
                                if (entry.id.isEmpty() || !allowed(tree, entry.id)) continue
                                if (entry.directory) {
                                    pending.add(entry.id to "$relative/${BackupFolderPolicy.label(entry.name)}")
                                    continue
                                }
                                val kind = MediaFiles.kind(entry.mime, entry.name) ?: continue
                                if (!visited.add("${tree.authority}\u0000${entry.id}")) continue
                                if (entry.virtual) {
                                    onProblem("${entry.name}: documento virtuale, originale non disponibile.")
                                    continue
                                }
                                val document = DocumentsContract.buildDocumentUriUsingTree(tree, entry.id)
                                val version = entry.stamp()
                                val rootKey = root.optString("id")
                                files += BackupMedia(media = "tree:" + hash("${tree.authority}\u0000${entry.id}"),
                                    name = entry.name.ifBlank { "file" }.take(500), folder = relative.take(2000), kind = kind,
                                    size = entry.size, mime = entry.mime.ifBlank { "application/octet-stream" }, stamp = version,
                                    current = {
                                        runCatching {
                                            val selected = this@BackupFolders.roots()
                                            (0 until selected.length()).any { selected.optJSONObject(it)?.optString("id") == rootKey } &&
                                                described(document)?.stamp() == version
                                        }.getOrDefault(false)
                                    },
                                    open = { MediaFiles.openOriginal(context, document, kind) })
                            }
                        }
                    } catch (error: Exception) {
                        if (!cancelled()) onProblem("$relative: ${error.message ?: "cartella non leggibile"}")
                    }
                }
            } catch (error: Exception) {
                if (!cancelled()) onProblem("$rootName: ${error.message ?: "cartella non più autorizzata"}")
            }
        }
        return files
    }

    companion object {
        private val COLUMNS = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_SIZE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_FLAGS)
        private fun hash(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray())
            .joinToString("") { "%02x".format(it) }
        private fun allowed(tree: Uri, id: String) = tree.authority != "com.android.externalstorage.documents" ||
            !BackupFolderPolicy.privateAndroidPath(id)
    }
}

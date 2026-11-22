package app.regista

import android.content.Context
import android.content.Intent
import android.database.Cursor
import android.net.Uri
import android.provider.DocumentsContract
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.security.MessageDigest
import java.util.ArrayDeque
import java.util.concurrent.CancellationException

/** Extra explicitly-authorized directory trees, including media not indexed because of .nomedia. */
class BackupFolders(private val context: Context) {
    private val settings = context.getSharedPreferences("backup-folders", Context.MODE_PRIVATE)
    private val known = context.getSharedPreferences("folder-media",Context.MODE_PRIVATE)
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

    private fun entry(rows: Cursor) = Entry(rows.getString(0).orEmpty(), rows.getString(1).orEmpty(), rows.getString(2).orEmpty(),
        if (rows.isNull(3)) -1 else rows.getLong(3), if (rows.isNull(4)) 0 else rows.getLong(4),
        if (rows.isNull(5)) 0 else rows.getInt(5))

    private fun described(uri: Uri): Entry? = context.contentResolver.query(uri, COLUMNS, null, null, null)?.use { rows ->
        if (rows.moveToFirst()) entry(rows) else null
    }

    private fun item(media: String, entry: Entry, folder: String, kind: String, document: Uri, rootKey: String,
                     version: String = entry.stamp()): BackupMedia {
        val modified = MediaFiles.day(entry.modified)
        return BackupMedia(media, entry.name.ifBlank { "file" }.take(500), folder.take(2000), kind,
            entry.size, entry.mime.ifBlank { "application/octet-stream" }, version,
            current = { stillSelected(rootKey) && described(document)?.stamp() == version },
            open = {
                if (document.authority == EXTERNAL) {
                    context.contentResolver.openInputStream(document) ?: throw IOException("Originale nella cartella non leggibile.")
                } else MediaFiles.openOriginal(context, document, kind)
            }, day = modified, uri = document,
            modifiedDay = modified, phonePath = if (document.authority == EXTERNAL) entry.id else "")
    }

    private fun stillSelected(rootKey: String): Boolean {
        val selected = roots()
        return (0 until selected.length()).any { selected.optJSONObject(it)?.optString("id") == rootKey }
    }

    fun scan(cancelled: () -> Boolean, onProblem: (String) -> Unit, kinds: Set<String>? = null): List<BackupMedia> {
        val files = mutableListOf<BackupMedia>()
        val visited = HashSet<String>()
        val roots = roots()
        val remembered=known.edit()
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
                                val entry = entry(rows)
                                if (entry.id.isEmpty() || !allowed(tree, entry.id)) continue
                                if (entry.directory) {
                                    pending.add(entry.id to "$relative/${BackupFolderPolicy.label(entry.name)}")
                                    continue
                                }
                                val kind = MediaFiles.kind(entry.mime, entry.name) ?: continue
                                if (kinds != null && kind !in kinds) continue
                                if (!visited.add("${tree.authority}\u0000${entry.id}")) continue
                                if (entry.virtual) {
                                    onProblem("${entry.name}: documento virtuale, originale non disponibile.")
                                    continue
                                }
                                val document = DocumentsContract.buildDocumentUriUsingTree(tree, entry.id)
                                val version = entry.stamp()
                                val rootKey = root.optString("id")
                                val media="tree:" + hash("${tree.authority}\u0000${entry.id}")
                                remembered.putString(media, JSONObject().put("uri", document.toString()).put("root", rootKey)
                                    .put("stamp", version).put("kind", kind).put("folder", relative).toString())
                                files += item(media, entry, relative, kind, document, rootKey, version)
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
        remembered.apply()
        return files
    }

    internal fun scanResumable(inventory: ImportInventory, kinds: Set<String>, cancelled: () -> Boolean, onFound: (Int) -> Unit) {
        fun folder(tree: Uri, id: String, path: String, grant: String) =
            ImportInventory.Folder("${tree.authority}:$id", tree.toString(), id, path, grant)

        if (inventory.needsFolderRoots()) {
            val selected = roots()
            val initial = (0 until selected.length()).mapNotNull { index ->
                val root = selected.optJSONObject(index) ?: return@mapNotNull null
                val tree = Uri.parse(root.getString("uri"))
                val id = DocumentsContract.getTreeDocumentId(tree)
                val path = if (tree.authority == EXTERNAL) id else root.optString("name", "cartella")
                folder(tree, id, path, root.getString("id"))
            }
            inventory.saveFolderRoots(initial)
        }
        while (true) {
            if (cancelled()) throw CancellationException()
            val directory = inventory.nextFolder() ?: return
            val tree = Uri.parse(directory.tree)
            if (!stillSelected(directory.grant) || !allowed(tree, directory.document)) {
                throw ImportNeedsUser("Cartella non più autorizzata: ${directory.relative}.")
            }
            val seen = inventory.savedIn(directory)
            val files = ArrayList<ImportInventory.FolderFile>(ImportInventory.PAGE_SIZE)
            val children = mutableListOf<ImportInventory.Folder>()
            val uri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, directory.document)
            val cursor = context.contentResolver.query(uri, COLUMNS, null, null, null)
                ?: throw ImportNeedsUser("Cartella non leggibile: ${directory.relative}.")
            cursor.use { rows ->
                var checkpoint = directory
                if (directory.position >= 0 && (!rows.moveToPosition(directory.position) || rows.getString(0) != directory.anchor)) {
                    // The provider reordered the directory. Re-read only its listing, keeping the entries already saved.
                    rows.moveToPosition(-1)
                    checkpoint = directory.copy(position = -1, anchor = "")
                }
                var inPage = 0
                while (rows.moveToNext()) {
                    if (cancelled()) throw CancellationException()
                    val entry = entry(rows)
                    if (entry.id.isNotEmpty() && allowed(tree, entry.id)) {
                        if (entry.directory) {
                            children += folder(tree, entry.id, "${directory.relative}/${BackupFolderPolicy.label(entry.name)}", directory.grant)
                        } else {
                            val kind = MediaFiles.kind(entry.mime, entry.name)
                            if (kind in kinds) {
                                val media = "tree:" + hash("${tree.authority}\u0000${entry.id}")
                                if (media !in seen) {
                                    if (entry.virtual) throw ImportNeedsUser("${entry.name}: originale non disponibile.")
                                    val document = DocumentsContract.buildDocumentUriUsingTree(tree, entry.id)
                                    val file = item(media, entry, directory.relative, checkNotNull(kind), document, directory.grant)
                                    val record = JSONObject().put("uri", document.toString()).put("root", directory.grant)
                                        .put("stamp", file.stamp).put("kind", kind).put("folder", directory.relative).toString()
                                    files += ImportInventory.FolderFile(ImportInventory.Source(file), record)
                                }
                            }
                        }
                    }
                    inPage++
                    if (inPage == ImportInventory.PAGE_SIZE) {
                        checkpoint = directory.copy(position = rows.position, anchor = entry.id)
                        inventory.saveFolder(checkpoint, files, children, false)
                        files.clear()
                        children.clear()
                        inPage = 0
                        onFound(inventory.size())
                    }
                }
                if (cancelled()) throw CancellationException()
                inventory.saveFolder(checkpoint, files, children, true)
                onFound(inventory.size())
            }
        }
    }

    private fun record(media: String, stamp: String? = null): JSONObject? {
        val indexed = ImportInventory.open(context).folderRecord(media)?.let(::JSONObject)
        if (indexed != null && (stamp == null || indexed.optString("stamp") == stamp)) return indexed
        return known.getString(media, null)?.let(::JSONObject)?.takeIf { stamp == null || it.optString("stamp") == stamp }
    }

    fun importItem(media: String, expected: String? = null): BackupMedia? {
        val record = record(media, expected) ?: return null
        val stamp = expected ?: record.getString("stamp")
        val root = record.getString("root")
        if (record.optString("stamp") != stamp || !stillSelected(root)) return null
        val uri = Uri.parse(record.getString("uri"))
        val entry = described(uri) ?: return null
        if (entry.directory || entry.virtual || entry.stamp() != stamp) return null
        val folder = record.optString("folder", entry.id.substringBeforeLast('/', ""))
        return item(media, entry, folder, record.getString("kind"), uri, root, stamp)
    }

    fun resolve(media:String,stamp:String):Pair<Uri,String>? {
        val record=record(media, stamp) ?: return null
        if(record.optString("stamp")!=stamp) return null
        val roots=roots()
        if(!(0 until roots.length()).any { roots.getJSONObject(it).optString("id")==record.optString("root") }) return null
        val uri=Uri.parse(record.getString("uri"))
        return if(described(uri)?.stamp()==stamp) Pair(uri,record.getString("kind")) else null
    }

    /** Only originals on local storage can enter the phone removal flow. */
    fun cleanupItem(media: String, stamp: String): BackupMedia? {
        val record = record(media, stamp) ?: return null
        val root = record.getString("root")
        if (record.optString("stamp") != stamp || !stillSelected(root)) return null
        val uri = Uri.parse(record.getString("uri"))
        if (uri.authority != EXTERNAL) return null
        val entry = described(uri) ?: return null
        if (entry.directory || entry.virtual || entry.stamp() != stamp || !supportsDelete(entry)) return null
        val folder = record.optString("folder", entry.id.substringBeforeLast('/', ""))
        return item(media, entry, folder, record.getString("kind"), uri, root)
    }

    private fun supportsDelete(entry: Entry): Boolean = entry.flags and DocumentsContract.Document.FLAG_SUPPORTS_DELETE != 0

    /** Rebind the exact same document to the tree the user just authorized for writing. */
    fun writableDocument(document: Uri, selectedTree: Uri): Uri? {
        if (document.authority != EXTERNAL || selectedTree.authority != EXTERNAL || !DocumentsContract.isTreeUri(selectedTree)) return null
        val oldRoot = DocumentsContract.getTreeDocumentId(document)
        val newRoot = DocumentsContract.getTreeDocumentId(selectedTree)
        val file = DocumentsContract.getDocumentId(document)
        if (!under(newRoot, oldRoot) || !under(file, newRoot) || file == newRoot || !allowed(selectedTree, file)) return null
        val target = DocumentsContract.buildDocumentUriUsingTree(selectedTree, file)
        val entry = described(target) ?: return null
        return if (!entry.directory && !entry.virtual && supportsDelete(entry)) target else null
    }

    companion object {
        private const val EXTERNAL = "com.android.externalstorage.documents"
        private fun under(file: String, folder: String): Boolean = file == folder || file.startsWith(folder.trimEnd('/') + "/")
        private val COLUMNS = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_SIZE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_FLAGS)
        private fun hash(value: String) = BackupRules.hex(MessageDigest.getInstance("SHA-256").digest(value.toByteArray()))
        private fun allowed(tree: Uri, id: String) = tree.authority != "com.android.externalstorage.documents" ||
            !BackupFolderPolicy.privateAndroidPath(id)
    }
}

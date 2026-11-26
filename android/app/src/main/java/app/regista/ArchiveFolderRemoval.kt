package app.regista

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Process
import android.provider.DocumentsContract
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import javax.net.ssl.HttpsURLConnection

internal data class CleanupReview(val job: String, val number: Int) {
    fun report() = JSONObject().put("job_id", job).put("review", number)
    fun pending(peer: String) = JSONObject().put("job", job).put("review", number).put("peer", peer)
    fun owns(record: JSONObject, peer: String) =
        record.optString("job") == job && record.optInt("review", -1) == number && record.optString("peer") == peer

    companion object {
        fun current(job: JSONObject) = CleanupReview(job.getString("id"), job.optInt("review"))
    }
}

/** Durable consent and results for a single PC selection in Android's document provider. */
internal class ArchiveFolderRemoval(private val context: Context, private val originals: ArchiveOriginals) {
    private val settings = context.getSharedPreferences("archive-cleanup", Context.MODE_PRIVATE)
    private val resolver get() = context.contentResolver
    private fun saved(key: String) = settings.getString(key, null)?.let(::JSONObject)
    private fun save(key: String, value: JSONObject) {
        if (!settings.edit().putString(key, value.toString()).commit()) throw IOException("Impossibile salvare la ripresa della rimozione.")
    }

    private fun approval(review: CleanupReview, peer: String) = saved(APPROVAL)?.takeIf { review.owns(it, peer) }
    fun confirmed(review: CleanupReview, peer: String) = approval(review, peer)?.optBoolean("confirmed") == true
    fun hasJournal() = settings.contains(JOURNAL)

    fun discardOtherApproval(review: CleanupReview?, peer: String) {
        val previous = saved(APPROVAL) ?: return
        if (review?.owns(previous, peer) != true) discardApproval()
    }

    fun discardApproval() {
        val previous = saved(APPROVAL) ?: return
        if (!settings.edit().remove(APPROVAL).commit()) return
        val grants = previous.optJSONArray("grants") ?: return
        for (index in 0 until grants.length()) {
            val grant = grants.getJSONObject(index)
            if (grant.optBoolean("owned")) runCatching {
                resolver.releasePersistableUriPermission(Uri.parse(grant.getString("tree")), WRITE)
            }
        }
    }

    fun rememberTree(review: CleanupReview, peer: String, tree: Uri) {
        discardOtherApproval(review, peer)
        val record = approval(review, peer) ?: review.pending(peer)
        val grants = record.optJSONArray("grants") ?: JSONArray()
        val stored = (0 until grants.length()).map(grants::getJSONObject).firstOrNull { it.getString("tree") == tree.toString() }
        if (stored != null && resolver.persistedUriPermissions.any { it.uri == tree && it.isWritePermission }) return
        val held = resolver.persistedUriPermissions.any { it.uri == tree && it.isWritePermission }
        // Providers can grant access only for the current task. Keep that usable and
        // remember the user's explicit consent even if Android later asks for the tree again.
        val added = !held && runCatching { resolver.takePersistableUriPermission(tree, WRITE) }.isSuccess
        val entry = stored ?: JSONObject().put("tree", tree.toString()).also { grants.put(it) }
        entry.put("owned", added || entry.optBoolean("owned"))
        try {
            save(APPROVAL, record.put("grants", grants))
        } catch (error: IOException) {
            if (added) runCatching { resolver.releasePersistableUriPermission(tree, WRITE) }
            throw error
        }
    }

    fun confirm(review: CleanupReview, peer: String) {
        val record = approval(review, peer) ?: throw IOException("Autorizza prima la cartella originale.")
        save(APPROVAL, record.put("confirmed", true))
    }

    fun writable(original: Uri, tree: Uri): Uri? {
        val uri = originals.folders.writableDocument(original, tree) ?: return null
        return uri.takeIf { context.checkUriPermission(it, Process.myPid(), Process.myUid(), WRITE) == PackageManager.PERMISSION_GRANTED }
    }

    private fun writable(review: CleanupReview, peer: String, original: Uri): Uri? {
        val grants = approval(review, peer)?.optJSONArray("grants") ?: return null
        for (index in 0 until grants.length()) {
            val uri = runCatching { writable(original, Uri.parse(grants.getJSONObject(index).getString("tree"))) }.getOrNull()
            if (uri != null) return uri
        }
        return null
    }

    fun canWrite(review: CleanupReview, peer: String, original: Uri) = writable(review, peer, original) != null

    private data class Original(val file: BackupMedia, val receipt: JSONObject, val writable: Uri)

    /** Returns false when Android needs the Activity to ask for a different folder grant. */
    fun removePage(computer: Computer, job: JSONObject, peer: String, stopped: () -> Boolean,
                   changed: (HttpsURLConnection?) -> Unit = {}): Boolean {
        val review = CleanupReview.current(job)
        if (!confirmed(review, peer) || stopped()) return false
        val group = job.getJSONArray("files")
        val checked = mutableListOf<Original>()
        try {
            for (index in 0 until group.length()) {
                if (stopped()) return false
                val receipt = group.getJSONObject(index)
                if (receipt.getString("method") != "folder") break
                val file = originals.locate(receipt) ?: throw IOException("Un originale è cambiato. Ricrea l’anteprima dal PC.")
                val uri = writable(review, peer, checkNotNull(file.uri)) ?: break
                val date = originals.day(file)
                if (date.date != receipt.optString("day") || date.source != receipt.optString("date_source") ||
                    !originals.unchanged(file, receipt, stopped)) throw IOException("Un originale è cambiato. Ricrea l’anteprima dal PC.")
                checked.add(Original(file, receipt, uri))
            }
        } catch (error: Exception) {
            if (!stopped()) {
                save(JOURNAL, review.pending(peer).put("cancelled", true).put("error", error.message.orEmpty().take(1000)))
            }
            return hasJournal()
        }
        if (checked.isEmpty() || stopped()) return false
        val ids = JSONArray(checked.map { it.file.media })
        val authorized = try {
            computer.ask("POST", "/phone/import-cleanup/authorize", review.report().put("media", ids), changed)
        } catch (error: Refused) {
            if (error.status != 409) throw error
            val current = computer.ask("GET", "/phone/import-cleanup?protocol=3", connectionChanged = changed)
                .optJSONObject("job")
            if (current?.optString("state") == "approved" && CleanupReview.current(current) == review) {
                save(JOURNAL, review.pending(peer).put("cancelled", true).put("error", error.message.orEmpty().take(1000)))
            }
            return hasJournal()
        }
        if (!authorized.optBoolean("authorized") || !authorized.optBoolean("requires_android_confirmation")) return false
        val removed = JSONArray()
        val progress = review.pending(peer).put("media", removed)
        save(JOURNAL, progress)
        try {
            for (item in checked) {
                if (stopped() || !confirmed(review, peer)) break
                if (!originals.unchanged(item.file, item.receipt, stopped) || !item.file.current()) {
                    if (stopped()) break
                    throw IOException("Un originale è cambiato. Ricrea l’anteprima dal PC.")
                }
                progress.put("attempt", JSONObject().put("media", item.file.media).put("uri", item.file.uri.toString()))
                save(JOURNAL, progress)
                if (stopped() || !confirmed(review, peer) || !item.file.current()) break
                if (!DocumentsContract.deleteDocument(resolver, item.writable)) throw IOException("Android ha interrotto la rimozione del file.")
                removed.put(item.file.media)
                progress.remove("attempt")
                save(JOURNAL, progress)
            }
        } catch (error: Exception) {
            if (!stopped()) save(JOURNAL, progress.put("cancelled", true).put("error", error.message.orEmpty().take(1000)))
        }
        return true
    }

    fun report(computer: Computer, peer: String, changed: (HttpsURLConnection?) -> Unit = {}) {
        val progress = saved(JOURNAL) ?: return
        if (progress.optString("peer") != peer) {
            settings.edit().remove(JOURNAL).commit()
            return
        }
        val review = CleanupReview(progress.getString("job"), progress.getInt("review"))
        val removed = progress.optJSONArray("media") ?: JSONArray()
        progress.optJSONObject("attempt")?.let { attempt ->
            // A shutdown may have happened between deleteDocument and saving its result.
            if (!present(Uri.parse(attempt.getString("uri")))) removed.put(attempt.getString("media"))
        }
        val result = computer.ask("POST", "/phone/import-cleanup/result", review.report().put("media", removed)
            .put("cancelled", progress.optBoolean("cancelled")).put("error", progress.optString("error")), changed)
        if (progress.optBoolean("cancelled") || (result.optInt("review", -1) == review.number &&
                    result.optString("state") in setOf("reviewed", "finished", "cancelled"))) discardApproval()
        settings.edit().remove(JOURNAL).commit()
    }

    private fun present(document: Uri): Boolean {
        val id = DocumentsContract.getDocumentId(document)
        val parent = id.substringBeforeLast('/', id.substringBefore(':') + ":")
        val folder = DocumentsContract.buildDocumentUriUsingTree(document, parent)
        val mime = DocumentsContract.Document.COLUMN_MIME_TYPE
        val isDirectory = resolver.query(folder, arrayOf(mime), null, null, null)?.use { rows ->
            rows.moveToFirst() && rows.getString(0) == DocumentsContract.Document.MIME_TYPE_DIR
        } ?: false
        if (!isDirectory) throw IOException("Attendo la cartella originale per verificare l’ultimo file.")
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(document, parent)
        val column = DocumentsContract.Document.COLUMN_DOCUMENT_ID
        return resolver.query(children, arrayOf(column), null, null, null)?.use { rows ->
            while (rows.moveToNext()) if (rows.getString(0) == id) return@use true
            false
        } ?: throw IOException("Impossibile verificare l’ultimo file rimosso.")
    }

    private companion object {
        const val APPROVAL = "folder-approval"
        const val JOURNAL = "folder-removal-journal"
        const val WRITE = Intent.FLAG_GRANT_WRITE_URI_PERMISSION
    }
}

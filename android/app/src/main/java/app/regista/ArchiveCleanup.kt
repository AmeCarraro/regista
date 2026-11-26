package app.regista

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.provider.DocumentsContract
import android.provider.MediaStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** Review the exact imported phone copies, then require a local confirmation for each removal method. */
class ArchiveCleanup(private val app: MainActivity, private val memory: Memory, private val tell: (String) -> Unit) {
    private val settings = app.getSharedPreferences("archive-cleanup", Context.MODE_PRIVATE)
    private val busy = AtomicBoolean(false)
    private val originals = ArchiveOriginals(app)
    @Volatile private var enabled = false
    @Volatile private var last = 0L
    @Volatile private var inDialog = false
    @Volatile private var writeRequest: WriteRequest? = null
    @Volatile private var writeAccess: Pair<Review, Uri>? = null
    @Volatile private var folderConsent: Review? = null
    private data class Review(val job: String, val number: Int) {
        fun report() = JSONObject().put("job_id", job).put("review", number)
        fun pending(peer: String) = JSONObject().put("job", job).put("review", number).put("peer", peer)
    }
    private data class WriteRequest(val review: Review, val peer: String, val original: Uri)
    private data class Checked(val file: BackupMedia, val receipt: JSONObject)

    private fun stopped(peer: String) = !enabled || !memory.paired || memory.fingerprint != peer || PhotoImportService.running
    fun start() { enabled = true }
    fun stop() { enabled = false; folderConsent = null }

    fun poll(computer: Computer?) {
        if (computer == null || !enabled || PhotoImportService.running || inDialog || writeRequest != null) return
        if (System.currentTimeMillis() - last < 3000 || !busy.compareAndSet(false, true)) return
        last = System.currentTimeMillis()
        val peer = memory.fingerprint
        thread(name = "phone originals review") {
            try {
                val pending = settings.getString("pending", null)?.let(::JSONObject)
                if (pending != null) {
                    if (pending.optString("peer") != peer) settings.edit().remove("pending").commit()
                    else if (pending.optString("phase") == "result") report(computer, pending)
                    return@thread
                }
                val response = computer.ask("GET", "/phone/import-cleanup?protocol=3")
                val checkpoint = !response.optBoolean("upgrade_required")
                val job = (if (checkpoint) response else computer.ask("GET", "/phone/import-cleanup?protocol=2")).optJSONObject("job")
                if (job == null) {
                    writeAccess = null
                    folderConsent = null
                    return@thread
                }
                if (stopped(peer)) return@thread
                when (job.getString("state")) {
                    "finding" -> {
                        if (!checkpoint || !ArchiveReviewService.start(app, job.getString("id"), peer)) {
                            app.runOnUiThread { app.window.decorView.keepScreenOn = enabled }
                            originals.scan(computer, job, checkpoint, { stopped(peer) }, { scanned, total, complete ->
                                tell(if (complete) "Lotto pronto sul PC. Controllati $scanned originali."
                                    else "Controllo originali sul Redmi: $scanned${if (total > 0) " su $total" else ""}.")
                            })
                        }
                    }
                    "approved" -> applyApproved(computer, job, peer)
                }
            } catch (error: Exception) {
                if (error is Refused && error.status in setOf(404, 409) && settings.getString("pending", null)
                        ?.let { JSONObject(it).optString("phase") == "result" } == true) {
                    settings.edit().remove("pending").commit()
                }
                if (!stopped(peer) && !(error is Refused && error.status == 409)) tell("Verifica originali: ${error.message.orEmpty()}")
            } finally {
                app.runOnUiThread { app.window.decorView.keepScreenOn = false }
                busy.set(false)
            }
        }
    }

    private fun applyApproved(computer: Computer, job: JSONObject, peer: String) {
        val review = Review(job.getString("id"), job.optInt("review"))
        val files = job.getJSONArray("files")
        if (files.length() == 0) return
        val method = files.getJSONObject(0).getString("method")
        val group = (0 until files.length()).map(files::getJSONObject).takeWhile { it.getString("method") == method }
        try {
            if (method == "folder") {
                val first = originals.locate(group.first())?.uri ?: throw IOException("Un originale è cambiato. Ricrea l’anteprima dal PC.")
                val grant = writeAccess?.takeIf { it.first == review }?.second
                if (grant == null || folderUri(first, grant) == null) {
                    askForFolder(WriteRequest(review, peer, first))
                    return
                }
                if (folderConsent != review) {
                    askForDeletion(review, peer, job.getInt("folder_remaining"))
                    return
                }
                // Other folders, if selected, need their own grant and confirmation.
                val checked = checked(group, peer).takeWhile { folderUri(it.file.uri!!, grant) != null }
                if (checked.isEmpty()) throw IOException("Il telefono non concede la rimozione in questa cartella.")
                authorize(computer, review, checked)
                removeFromFolder(review, peer, checked, grant)
            } else {
                val checked = checked(group, peer)
                authorize(computer, review, checked)
                if (checked.any { !it.file.current() }) throw IOException("Un file è cambiato durante la verifica.")
                askForTrash(review, peer, checked)
            }
        } catch (error: Exception) {
            if (!stopped(peer)) {
                recordResult(review, peer, JSONArray(), true, error.message.orEmpty())
                tell("Pulizia interrotta. ${error.message.orEmpty()}")
            }
        }
    }

    private fun checked(group: List<JSONObject>, peer: String): List<Checked> = group.map { receipt ->
        val item = originals.locate(receipt) ?: throw IOException("Un originale è cambiato. Ricrea l’anteprima dal PC.")
        val currentDay = originals.day(item)
        if (currentDay.date != receipt.optString("day") || currentDay.source != receipt.optString("date_source") ||
            !originals.unchanged(item, receipt) { stopped(peer) }) throw IOException("${item.name} è cambiato. Ricrea l’anteprima dal PC.")
        Checked(item, receipt)
    }

    private fun authorize(computer: Computer, review: Review, checked: List<Checked>) {
        val ids = JSONArray(checked.map { it.file.media })
        val approval = computer.ask("POST", "/phone/import-cleanup/authorize", review.report().put("media", ids))
        if (!approval.optBoolean("authorized") || !approval.optBoolean("requires_android_confirmation"))
            throw IOException("Manca la nuova verifica sul PC.")
    }

    private fun folderUri(original: Uri, grant: Uri): Uri? {
        val uri = originals.folders.writableDocument(original, grant) ?: return null
        return uri.takeIf { app.checkUriPermission(uri, Process.myPid(), Process.myUid(), Intent.FLAG_GRANT_WRITE_URI_PERMISSION) == PackageManager.PERMISSION_GRANTED }
    }

    private fun askForFolder(request: WriteRequest) = app.runOnUiThread {
        if (stopped(request.peer) || inDialog) return@runOnUiThread
        inDialog = true
        folderConsent = null
        AlertDialog.Builder(app).setTitle("Autorizza la cartella di questa selezione")
            .setMessage("Alcuni file sono nelle cartelle lette direttamente. Apri il selettore Android e autorizza la cartella originale per questa pulizia.")
            .setPositiveButton("Scegli la cartella") { _, _ ->
                writeRequest = request
                try {
                    app.startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                        .putExtra(Intent.EXTRA_LOCAL_ONLY, true)
                        .putExtra(DocumentsContract.EXTRA_INITIAL_URI, request.original), WRITE_REQUEST)
                } catch (_: Exception) {
                    writeRequest = null
                    recordResult(request.review, request.peer, JSONArray(), true, "Selettore delle cartelle non disponibile.")
                }
            }
            .setNegativeButton("Annulla") { _, _ -> recordResult(request.review, request.peer, JSONArray(), true) }
            .setOnCancelListener { recordResult(request.review, request.peer, JSONArray(), true) }
            .setOnDismissListener { inDialog = false }.show()
    }

    fun folderAnswered(result: Int, data: Intent?) {
        val request = writeRequest ?: return
        writeRequest = null
        val tree = data?.data
        if (result != Activity.RESULT_OK || tree == null || runCatching { folderUri(request.original, tree) }.getOrNull() == null) {
            recordResult(request.review, request.peer, JSONArray(), true, "Il Redmi non ha concesso accesso in scrittura alla cartella selezionata.")
            tell("Autorizza la stessa cartella usata per l’importazione e ricrea l’anteprima.")
            return
        }
        // This write grant is transient. The ordinary backup keeps only the read permission.
        writeAccess = request.review to tree
        last = 0
    }

    private fun askForDeletion(review: Review, peer: String, count: Int) = app.runOnUiThread {
        if (stopped(peer) || inDialog) return@runOnUiThread
        inDialog = true
        AlertDialog.Builder(app).setTitle("Conferma rimozione dal Redmi")
            .setMessage("Rimuovere i file selezionati nelle cartelle autorizzate? Restano $count file di questo tipo. Android li elimina direttamente dalla cartella. Per recuperarli usa le copie e gli ZIP verificati sul PC.")
            .setPositiveButton("Elimina dal Redmi") { _, _ -> if (!stopped(peer)) { folderConsent = review; last = 0 } }
            .setNegativeButton("Conserva") { _, _ -> recordResult(review, peer, JSONArray(), true) }
            .setOnCancelListener { recordResult(review, peer, JSONArray(), true) }
            .setOnDismissListener { inDialog = false }.show()
    }

    private fun removeFromFolder(review: Review, peer: String, checked: List<Checked>, grant: Uri) {
        val removed = JSONArray()
        // A restart records the partial result and requires a fresh review for any further removal.
        val progress = review.pending(peer).put("phase", "removing").put("media", removed)
        savePending(progress)
        var error = ""
        try {
            for (item in checked) {
                if (folderConsent != review || !originals.unchanged(item.file, item.receipt) { stopped(peer) })
                    throw IOException("La conferma o l’identità del file non è più valida.")
                val uri = folderUri(item.file.uri!!, grant) ?: throw IOException("Il permesso di rimozione è cambiato.")
                if (stopped(peer) || folderConsent != review || !item.file.current()) throw IOException("Pulizia interrotta sul telefono.")
                if (!DocumentsContract.deleteDocument(app.contentResolver, uri)) throw IOException("Android non ha rimosso ${item.file.name}.")
                removed.put(item.file.media)
                savePending(progress)
            }
        } catch (failure: Exception) { error = failure.message.orEmpty().ifBlank { "Pulizia interrotta." } }
        recordResult(review, peer, removed, error.isNotEmpty(), error)
        tell("Rimossi dal Redmi ${removed.length()} file. Copie e ZIP conservati sul PC.")
    }

    private fun askForTrash(review: Review, peer: String, checked: List<Checked>) = app.runOnUiThread {
        if (stopped(peer) || settings.contains("pending") || Build.VERSION.SDK_INT < 30) return@runOnUiThread
        try {
            val uris = checked.map { checkNotNull(it.file.uri) }
            val question = MediaStore.createTrashRequest(app.contentResolver, uris, true)
            val files = JSONArray(checked.map { JSONObject().put("media", it.file.media).put("uri", it.file.uri.toString()) })
            savePending(review.pending(peer).put("phase", "question").put("files", files))
            app.startIntentSenderForResult(question.intentSender, REQUEST, null, 0, 0, 0)
        } catch (error: Exception) {
            recordResult(review, peer, JSONArray(), true, error.message.orEmpty())
        }
    }

    fun answered(result: Int) {
        val pending = settings.getString("pending", null)?.let(::JSONObject) ?: return
        savePending(pending.put("phase", "result").put("yes", result == Activity.RESULT_OK))
        last = 0
    }

    fun recover(discardedQuestion: Boolean) {
        val pending = settings.getString("pending", null)?.let(::JSONObject) ?: return
        when (pending.optString("phase")) {
            "question" -> if (discardedQuestion) savePending(pending.put("phase", "result").put("yes", false))
            "removing" -> savePending(pending.put("phase", "result").put("cancelled", true).put("error", "Ripresa dopo l’interruzione del telefono."))
        }
    }

    private fun savePending(value: JSONObject) {
        check(settings.edit().putString("pending", value.toString()).commit()) { "Impossibile salvare il risultato della pulizia." }
    }

    private fun recordResult(review: Review, peer: String, removed: JSONArray, cancelled: Boolean, error: String = "") {
        savePending(review.pending(peer).put("phase", "result")
            .put("media", removed).put("cancelled", cancelled).put("error", error.take(1000)))
        if (cancelled) { folderConsent = null; writeAccess = null }
        last = 0
    }

    private fun report(computer: Computer, pending: JSONObject) {
        val removed = pending.optJSONArray("media") ?: JSONArray()
        val files = pending.optJSONArray("files")
        var cancelled = pending.optBoolean("cancelled")
        var error = pending.optString("error")
        if (files != null && Build.VERSION.SDK_INT >= 30) {
            val options = Bundle().apply { putInt(MediaStore.QUERY_ARG_MATCH_TRASHED, MediaStore.MATCH_INCLUDE) }
            for (index in 0 until files.length()) {
                val file = files.getJSONObject(index)
                val uri = Uri.parse(file.getString("uri"))
                val gone = app.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.IS_TRASHED), options, null)?.use { rows ->
                    rows.moveToFirst() && rows.getInt(0) == 1
                } ?: false
                if (gone) removed.put(file.getString("media"))
            }
            cancelled = !pending.optBoolean("yes") || removed.length() != files.length()
            if (pending.optBoolean("yes") && cancelled) error = "Alcuni file non risultano nel cestino Android."
        }
        val review = Review(pending.getString("job"), pending.optInt("review"))
        computer.ask("POST", "/phone/import-cleanup/result", review.report()
            .put("media", removed).put("cancelled", cancelled).put("error", error))
        settings.edit().remove("pending").commit()
    }

    companion object {
        const val REQUEST = 43
        const val WRITE_REQUEST = 46
    }
}

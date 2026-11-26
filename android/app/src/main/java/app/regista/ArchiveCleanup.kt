package app.regista

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
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
    private val folderRemoval = ArchiveFolderRemoval(app, originals)
    @Volatile private var enabled = false
    @Volatile private var last = 0L
    @Volatile private var inDialog = false
    @Volatile private var writeRequest: WriteRequest? = null
    private data class WriteRequest(val review: CleanupReview, val peer: String, val original: Uri)
    private data class Checked(val file: BackupMedia, val receipt: JSONObject)

    private fun stopped(peer: String) = !enabled || !memory.paired || memory.fingerprint != peer || PhotoImportService.running
    fun start() { enabled = true }
    fun stop() { enabled = false }

    fun poll(computer: Computer?) {
        if (computer == null || !enabled || ArchiveReviewService.running || PhotoImportService.running || inDialog || writeRequest != null) return
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
                if (folderRemoval.hasJournal()) {
                    folderRemoval.report(computer, peer)
                    return@thread
                }
                val response = computer.ask("GET", "/phone/import-cleanup?protocol=3")
                val checkpoint = !response.optBoolean("upgrade_required")
                val job = (if (checkpoint) response else computer.ask("GET", "/phone/import-cleanup?protocol=2")).optJSONObject("job")
                folderRemoval.discardOtherApproval(job?.takeIf { it.optString("state") == "approved" }?.let { CleanupReview.current(it) }, peer)
                if (job == null) return@thread
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
        val review = CleanupReview.current(job)
        val files = job.getJSONArray("files")
        if (files.length() == 0) return
        val method = files.getJSONObject(0).getString("method")
        val group = (0 until files.length()).map(files::getJSONObject).takeWhile { it.getString("method") == method }
        if (method == "folder") {
            val first = originals.locate(group.first())?.uri
            if (first == null) {
                if (!stopped(peer)) recordResult(review, peer, JSONArray(), true, "Un originale è cambiato. Ricrea l’anteprima dal PC.")
                return
            }
            if (!folderRemoval.canWrite(review, peer, first)) {
                askForFolder(WriteRequest(review, peer, first))
            } else if (!folderRemoval.confirmed(review, peer)) {
                askForDeletion(review, peer, job.getInt("folder_remaining"))
            } else if (!ArchiveReviewService.start(app, review.job, peer, removing = true)) {
                app.runOnUiThread { app.window.decorView.keepScreenOn = enabled }
                try {
                    if (folderRemoval.removePage(computer, job, peer, { stopped(peer) })) folderRemoval.report(computer, peer)
                } catch (error: Refused) {
                    if (!stopped(peer) && error.status == 409) recordResult(review, peer, JSONArray(), true, error.message.orEmpty())
                    else throw error
                }
            }
            return
        }
        try {
            val checked = checked(group, peer)
            authorize(computer, review, checked)
            if (checked.any { !it.file.current() }) throw IOException("Un file è cambiato durante la verifica.")
            askForTrash(review, peer, checked)
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

    private fun authorize(computer: Computer, review: CleanupReview, checked: List<Checked>) {
        val ids = JSONArray(checked.map { it.file.media })
        val approval = computer.ask("POST", "/phone/import-cleanup/authorize", review.report().put("media", ids))
        if (!approval.optBoolean("authorized") || !approval.optBoolean("requires_android_confirmation"))
            throw IOException("Manca la nuova verifica sul PC.")
    }

    private fun askForFolder(request: WriteRequest) = app.runOnUiThread {
        if (stopped(request.peer) || inDialog) return@runOnUiThread
        inDialog = true
        AlertDialog.Builder(app).setTitle("Autorizza la cartella di questa selezione")
            .setMessage("Alcuni file sono nelle cartelle lette direttamente. Apri il selettore Android e autorizza la cartella originale per questa pulizia.")
            .setPositiveButton("Scegli la cartella") { _, _ ->
                writeRequest = request
                try {
                    app.startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                            Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
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
        if (result != Activity.RESULT_OK || tree == null || runCatching { folderRemoval.writable(request.original, tree) }.getOrNull() == null) {
            recordResult(request.review, request.peer, JSONArray(), true, "Il Redmi non ha concesso accesso in scrittura alla cartella selezionata.")
            tell("Autorizza la stessa cartella usata per l’importazione e ricrea l’anteprima.")
            return
        }
        runCatching { folderRemoval.rememberTree(request.review, request.peer, tree) }
            .onSuccess { last = 0 }.onFailure { tell(it.message.orEmpty()) }
    }

    private fun askForDeletion(review: CleanupReview, peer: String, count: Int) = app.runOnUiThread {
        if (stopped(peer) || inDialog) return@runOnUiThread
        inDialog = true
        AlertDialog.Builder(app).setTitle("Conferma rimozione dal Redmi")
            .setMessage("Rimuovere i file selezionati nelle cartelle autorizzate? Restano $count file di questo tipo. Android li elimina direttamente dalla cartella. Per recuperarli usa le copie e gli ZIP verificati sul PC.")
            .setPositiveButton("Elimina dal Redmi") { _, _ ->
                if (!stopped(peer)) runCatching { folderRemoval.confirm(review, peer) }.onSuccess {
                    last = 0
                    ArchiveReviewService.start(app, review.job, peer, removing = true)
                }.onFailure { tell(it.message.orEmpty()) }
            }
            .setNegativeButton("Conserva") { _, _ -> recordResult(review, peer, JSONArray(), true) }
            .setOnCancelListener { recordResult(review, peer, JSONArray(), true) }
            .setOnDismissListener { inDialog = false }.show()
    }

    private fun askForTrash(review: CleanupReview, peer: String, checked: List<Checked>) = app.runOnUiThread {
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

    private fun recordResult(review: CleanupReview, peer: String, removed: JSONArray, cancelled: Boolean, error: String = "") {
        savePending(review.pending(peer).put("phase", "result")
            .put("media", removed).put("cancelled", cancelled).put("error", error.take(1000)))
        if (cancelled) folderRemoval.discardApproval()
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
        val review = CleanupReview(pending.getString("job"), pending.optInt("review"))
        computer.ask("POST", "/phone/import-cleanup/result", review.report()
            .put("media", removed).put("cancelled", cancelled).put("error", error))
        settings.edit().remove("pending").commit()
    }

    companion object {
        const val REQUEST = 43
        const val WRITE_REQUEST = 46
    }
}

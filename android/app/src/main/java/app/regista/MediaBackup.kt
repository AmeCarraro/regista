package app.regista

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.HttpsURLConnection
import kotlin.concurrent.thread

/** An explicit foreground-only backup. Nothing here deletes media or runs photo inference. */
class MediaBackup(
    context: Context,
    private val memory: Memory,
    private val computerProvider: () -> Computer?,
    private val onStarting: () -> Unit = {},
    private val onFinished: () -> Unit = {},
) {
    private val appContext = context.applicationContext
    private val files = MediaFiles(context.applicationContext)
    private val folders = BackupFolders(context.applicationContext)
    val busy get() = ACTIVE.get()

    fun missingPermissions(): Array<String> = files.missingPermissions()
    fun permissionRequest(): Array<String> = files.permissionRequest()

    fun state(): String {
        val value = status
        return JSONObject().put("busy", busy).put("phase", if (busy && CANCELLED.get()) "cancelling" else value.phase)
            .put("total", value.total).put("scanned", value.scanned).put("copied", value.copied)
            .put("duplicates", value.duplicates).put("failed", value.failed).put("current", value.current)
            .put("bytes", value.bytes).put("current_bytes", value.bytes).put("current_size", value.currentSize)
            .put("uploaded_bytes", value.uploadedBytes).put("total_bytes", value.totalBytes)
            .put("run_id", value.run).put("error", value.error).put("errors", JSONArray(value.errors))
            .put("warnings", JSONArray(value.warnings)).put("complete", !busy && value.phase == "done" && value.failed == 0 && value.warnings.isEmpty())
            .toString()
    }

    fun start(): String {
        if (PhotoImportService.running || PhotoImportStore(appContext).read().requested) return JSONObject().put("error", "Termina o interrompi l’importazione delle foto prima del backup completo.").toString()
        if (busy) return JSONObject().put("error", "Un backup è già in corso o si sta chiudendo.").toString()
        if (!memory.paired) return JSONObject().put("error", "Collega prima il telefono al PC.").toString()
        if (missingPermissions().isNotEmpty()) return JSONObject().put("error", "Per il backup completo servono i permessi per tutte le foto, video, audio e metadati originali.").toString()
        val computer = computerProvider() ?: return JSONObject().put("error", "Il PC deve essere acceso e collegato.").toString()
        if (!ACTIVE.compareAndSet(false, true)) return JSONObject().put("error", "Un backup è già in corso.").toString()
        CANCELLED.set(false)
        status = Status(phase = "scanning")
        val source = memory.fingerprint
        scanner = files
        task = thread(name = "complete media backup") {
            run(computer, source)
        }
        return JSONObject().put("started", true).toString()
    }

    fun cancel() {
        if (!busy || !CANCELLED.compareAndSet(false, true)) return
        scanner?.cancel()
        task?.interrupt()
        thread(name = "cancel media backup") {
            // disconnect() before connection establishment can be a no-op. Keep checking
            // until the worker leaves the current operation; final status writes are bounded.
            while (ACTIVE.get() && CANCELLED.get() && status.phase !in setOf("cancelled", "error")) {
                runCatching { connection?.disconnect() }
                try { Thread.sleep(100) } catch (_: InterruptedException) { break }
            }
        }
    }

    fun close() = cancel()

    private fun cancelled(source: String): Boolean = CANCELLED.get() || !memory.paired || memory.fingerprint != source
    private fun check(source: String) { if (cancelled(source)) throw CancellationException() }

    private fun connectionChanged(value: HttpsURLConnection?) {
        connection = value
        if (value != null && CANCELLED.get()) throw CancellationException()
    }

    private fun ask(computer: Computer, path: String, body: JSONObject): JSONObject =
        computer.ask("POST", "/phone/media-backup/$path", body, connectionChanged = ::connectionChanged)

    private fun fail(item: BackupMedia, error: Exception, count: Int = 1) {
        val detail = "${item.name}: ${error.message ?: "file non leggibile"}".take(500)
        status = status.copy(failed = status.failed + count, errors = (status.errors + detail).take(20))
    }

    private fun progress(computer: Computer, done: Boolean, cancelled: Boolean = false, finalReport: Boolean = false) {
        val value = status
        val details = (listOf(value.error).filter { it.isNotBlank() } + value.errors + value.warnings).joinToString("; ").take(1000)
        val callback: (HttpsURLConnection?) -> Unit = if (finalReport) { connection -> Companion.connection = connection } else ::connectionChanged
        computer.ask("POST", "/phone/media-backup/progress", JSONObject().put("run_id", value.run).put("total", value.total)
            .put("scanned", value.scanned).put("failed", value.failed).put("done", done)
            .put("cancelled", cancelled).put("error", details), connectionChanged = callback)
    }

    private data class Hashed(val item: BackupMedia, val digest: BackupRules.Digest)

    private fun run(computer: Computer, source: String) {
        var completed = false
        try {
            onStarting()
            check(source)
            val started = ask(computer, "start", JSONObject())
            if (started.optInt("protocol") != 1) throw IOException("Aggiorna Regista sul PC: il protocollo di backup non è compatibile.")
            status = status.copy(run = started.getString("run_id"))
            val maximum = started.optLong("max_file_bytes", 64L * 1024 * 1024 * 1024)
            fun problem(message: String) { status = status.copy(warnings = (status.warnings + message.take(500)).take(20)) }
            val found = files.scan({ cancelled(source) }, ::problem) { total -> status = status.copy(total = total) }
            check(source)
            val extra = folders.scan({ cancelled(source) }, ::problem)
            val all = (found + extra).distinctBy { it.media }
            status = status.copy(total = all.size, totalBytes = all.sumOf { maxOf(0, it.size) })
            progress(computer, done = false)
            for (batch in all.chunked(100)) {
                check(source)
                val hashed = mutableListOf<Hashed>()
                for (item in batch) {
                    check(source)
                    status = status.copy(phase = "hashing", current = item.name, currentSize = item.size, bytes = 0)
                    try {
                        if (item.media.length > 300 || item.stamp.length > 1000 || item.name.length > 500 || item.folder.length > 2000 || item.mime.length > 200) {
                            throw IOException("Nome o percorso oltre i limiti del manifesto: questo file resta da verificare.")
                        }
                        if (!item.current()) throw IOException("File cambiato o non più accessibile: riprova il backup.")
                        val digest = BackupRules.hash(item.open()) { cancelled(source) }
                        if (!item.current() || (item.size >= 0 && digest.bytes != item.size)) throw IOException("Il file è cambiato durante il controllo.")
                        if (digest.bytes > maximum) throw IOException("File oltre il limite configurato sul PC (${maximum / (1024 * 1024)} MB).")
                        hashed += Hashed(item, digest)
                        if (item.size < 0) status = status.copy(totalBytes = status.totalBytes + digest.bytes)
                    } catch (error: Exception) {
                        if (cancelled(source) || error is CancellationException) throw CancellationException()
                        fail(item, error)
                    }
                    status = status.copy(scanned = status.scanned + 1)
                }
                if (hashed.isEmpty()) { progress(computer, done = false); continue }
                check(source)
                val manifest = JSONArray()
                for ((item, digest) in hashed) manifest.put(JSONObject().put("media", item.media).put("stamp", item.stamp)
                    .put("sha256", digest.sha256).put("name", item.name).put("folder", item.folder)
                    .put("kind", item.kind).put("size", digest.bytes).put("mime", item.mime))
                val answer = ask(computer, "manifest", JSONObject().put("run_id", status.run).put("files", manifest)).getJSONArray("wanted")
                val wanted = (0 until answer.length()).map { answer.getString(it) }.toSet()
                if (!wanted.all { media -> hashed.any { it.item.media == media } }) throw IOException("Il PC ha richiesto un file assente dal manifesto.")
                for (group in hashed.groupBy { it.digest.sha256 }.values) {
                    check(source)
                    val selected = group.firstOrNull { it.item.media in wanted }
                    if (selected == null) {
                        for (entry in group) {
                            check(source)
                            if (runCatching { entry.item.current() }.getOrDefault(false)) status = status.copy(duplicates = status.duplicates + 1)
                            else fail(entry.item, IOException("File cambiato durante la verifica dei doppioni: riprova."))
                        }
                        continue
                    }
                    val (item, digest) = selected
                    status = status.copy(phase = "uploading", current = item.name, currentSize = digest.bytes, bytes = 0)
                    try {
                        if (!item.current()) throw IOException("File cambiato dopo il controllo: riprova.")
                        val already = status.uploadedBytes
                        val input = BackupRules.Sending(item.open(), { cancelled(source) }) { bytes ->
                            status = status.copy(bytes = bytes, uploadedBytes = already + bytes)
                        }
                        val result = input.use { stream ->
                            computer.send("/phone/media-backup/upload?run_id=${Uri.encode(status.run)}&media=${Uri.encode(item.media)}&stamp=${Uri.encode(item.stamp)}",
                                digest.bytes, stream, digest.sha256, connectionChanged = ::connectionChanged)
                        }
                        check(source)
                        if (!result.optBoolean("kept") || result.optString("id") != digest.sha256) throw IOException("Il PC non ha confermato lo ZIP verificato.")
                        if (!item.current()) throw IOException("Il file è cambiato durante l'invio: esegui un nuovo backup.")
                        val duplicate = result.optBoolean("duplicate")
                        var valid = 1
                        for (entry in group) if (entry !== selected) {
                            check(source)
                            if (runCatching { entry.item.current() }.getOrDefault(false)) valid++
                            else fail(entry.item, IOException("File cambiato durante l'invio del doppione: riprova."))
                        }
                        status = status.copy(copied = status.copied + if (duplicate) 0 else 1,
                            duplicates = status.duplicates + valid - if (duplicate) 0 else 1)
                    } catch (error: Exception) {
                        if (cancelled(source) || error is CancellationException) throw CancellationException()
                        if (error is Refused && error.status == 401) throw error
                        fail(item, error, group.size)
                    }
                }
                progress(computer, done = false)
            }
            check(source)
            status = status.copy(phase = "done", current = "", bytes = 0, currentSize = 0)
            progress(computer, done = true)
            completed = true
        } catch (error: Exception) {
            val stopped = cancelled(source) || error is CancellationException
            status = status.copy(phase = if (stopped) "cancelled" else "error", current = "",
                error = if (stopped) "Backup interrotto. I file già confermati restano sul PC; ripeti per continuare." else error.message ?: "Backup non riuscito.")
        } finally {
            if (!completed && status.run.isNotEmpty() && memory.paired && memory.fingerprint == source) {
                Thread.interrupted()
                try { progress(computer, done = true, cancelled = status.phase == "cancelled", finalReport = true) } catch (_: Exception) { /* Next run deduplicates confirmed ZIPs. */ }
            }
            connection = null
            scanner = null
            task = null
            ACTIVE.set(false)
            try { onFinished() } catch (_: Exception) { /* UI may already be closed. */ }
        }
    }

    private data class Status(val phase: String = "idle", val run: String = "", val total: Int = 0,
        val scanned: Int = 0, val copied: Int = 0, val duplicates: Int = 0, val failed: Int = 0,
        val current: String = "", val bytes: Long = 0, val currentSize: Long = 0, val uploadedBytes: Long = 0,
        val totalBytes: Long = 0, val error: String = "", val errors: List<String> = emptyList(), val warnings: List<String> = emptyList())

    companion object {
        val running get() = ACTIVE.get()
        private val ACTIVE = AtomicBoolean(false)
        private val CANCELLED = AtomicBoolean(false)
        @Volatile private var status = Status()
        @Volatile private var task: Thread? = null
        @Volatile private var scanner: MediaFiles? = null
        @Volatile private var connection: HttpsURLConnection? = null
    }
}

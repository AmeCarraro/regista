package app.regista

import android.content.Context
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import javax.net.ssl.HttpsURLConnection

internal class ArchiveOriginals(context: Context) {
    val folders = BackupFolders(context)
    private val media = MediaFiles(context, setOf("image", "video"))

    fun locate(receipt: JSONObject): BackupMedia? {
        val id = receipt.getString("media")
        val stamp = receipt.getString("stamp")
        val item = if (id.startsWith("tree:")) folders.cleanupItem(id, stamp)
            else if (Build.VERSION.SDK_INT >= 30) media.lookup(id, stamp) else null
        return item?.takeIf {
            it.uri != null && it.name == receipt.getString("name") && it.folder == receipt.getString("folder") &&
                it.kind == receipt.getString("kind") && (it.size < 0 || it.size == receipt.getLong("size"))
        }
    }

    fun day(file: BackupMedia) = CleanupDates.forFile(
        ImportGroups.source(file.folder) == "whatsapp", file.name, file.modifiedDay, file.day)

    fun unchanged(item: BackupMedia, receipt: JSONObject, stopped: () -> Boolean): Boolean {
        if (stopped() || !item.current()) return false
        val digest = BackupRules.hash(item.open(), stopped)
        return !stopped() && item.current() && digest.bytes == receipt.getLong("size") &&
            digest.sha256 == receipt.getString("sha256")
    }

    fun scan(computer: Computer, job: JSONObject, checkpoint: Boolean, stopped: () -> Boolean,
             progress: (Int, Int, Boolean) -> Unit, changed: (HttpsURLConnection?) -> Unit = {}) {
        val id = job.getString("id")
        val policy = job.getJSONObject("policy")
        val since = policy.optString("since").takeUnless { it == "null" }.orEmpty()
        val until = policy.optString("until").takeUnless { it == "null" }.orEmpty()
        val seenPaths = mutableSetOf<String>()
        var offset = job.optInt("scanned")
        val total = job.optInt("scan_total")
        val digest = MessageDigest.getInstance("SHA-256")
        val protocol = if (checkpoint) 3 else 2
        do {
            if (stopped()) return
            val candidates = computer.ask("GET", "/phone/import-cleanup/candidates?job_id=$id&offset=$offset&protocol=$protocol",
                connectionChanged = changed).getJSONArray("files")
            val found = JSONArray()
            for (index in 0 until candidates.length()) {
                if (stopped()) return
                val receipt = candidates.getJSONObject(index)
                val item = runCatching { locate(receipt) }.getOrNull() ?: continue
                val physical = item.phonePath.ifEmpty { item.media }
                if (physical in seenPaths) continue
                val date = day(item)
                if (!CleanupDates.includes(date, since, until)) continue
                if (!runCatching { unchanged(item, receipt, stopped) }.getOrDefault(false)) continue
                seenPaths.add(physical)
                val method = if (item.media.startsWith("tree:")) "folder" else "trash"
                receipt.put("day", date.date.takeIf { it.isNotEmpty() } ?: JSONObject.NULL)
                    .put("date_source", date.source).put("method", method)
                if (checkpoint) receipt.put("original", digest.digest(physical.toByteArray()).joinToString("") { "%02x".format(it) })
                found.put(receipt)
            }
            if (stopped()) return
            val end = candidates.length() < PAGE
            val report = JSONObject().put("job_id", id).put("files", found).put("finished", end)
            if (checkpoint) report.put("offset", offset).put("review", job.getInt("review")).put("checked", candidates.length())
            val accepted = computer.ask("POST", "/phone/import-cleanup/matched", report, changed)
            offset = if (checkpoint) accepted.getInt("scanned") else offset + candidates.length()
            val complete = if (checkpoint) accepted.getBoolean("finished") else end
            progress(offset, total, complete)
        } while (!complete)
    }

    private companion object {
        const val PAGE = 200
    }
}

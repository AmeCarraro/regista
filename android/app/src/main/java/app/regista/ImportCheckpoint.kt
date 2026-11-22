package app.regista

/** Durable scope of one user-requested import. Reopening the app never adds new photos to it. */
data class ImportCheckpoint(
    val work: String = "", val peer: String = "", val request: String = "",
    val requested: Boolean = false, val prepared: Boolean = false,
    val remaining: List<String> = emptyList(), val total: Int = 0,
    val copied: Int = 0, val duplicates: Int = 0, val failed: Int = 0,
    val phase: String = "idle", val message: String = "",
    val scope: String = "photos-videos", val batch: String = "", val transport: String = "",
    val failedMedia: List<String> = emptyList(),
    val groups:Map<String,Int> = emptyMap(),val members:Map<String,String> = emptyMap(),
    val batches:Map<String,String> = emptyMap(),val finishedGroups:Set<String> = emptySet(),
) {
    val processed get() = copied + duplicates
    val complete get() = prepared && remaining.isEmpty()
    fun prepare(ids: List<String>): ImportCheckpoint = if (prepared) this else {
        val unique = ids.distinct()
        copy(prepared = true, remaining = unique, total = unique.size)
    }
    fun confirmed(media: String, outcome: ImportOutcome): ImportCheckpoint {
        if (media !in remaining) return this
        if (outcome == ImportOutcome.FAILED) return if (media in failedMedia) this else copy(failed = failed+1,failedMedia=failedMedia+media)
        return copy(remaining = remaining.filter { it != media },
            copied = copied + if (outcome == ImportOutcome.COPIED) 1 else 0,
            duplicates = duplicates + if (outcome == ImportOutcome.DUPLICATE) 1 else 0,
            failed = failed - if (media in failedMedia) 1 else 0, failedMedia = failedMedia.filter { it != media })
    }
    fun canResume(fingerprint: String, remoteRequest: String) =
        work.isNotEmpty() && peer == fingerprint && prepared && (remaining.isNotEmpty() || ((batch.isNotEmpty() || batches.isNotEmpty()) && phase != "done")) &&
            (remoteRequest.isEmpty() || request == remoteRequest)
}

enum class ImportOutcome { COPIED, DUPLICATE, FAILED }

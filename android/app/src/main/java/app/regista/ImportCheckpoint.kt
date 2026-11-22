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
    fun confirmed(media: String, outcome: ImportOutcome): ImportCheckpoint = confirmed(mapOf(media to outcome))

    fun confirmed(outcomes: Map<String, ImportOutcome>): ImportCheckpoint {
        if (outcomes.isEmpty()) return this
        val errors = failedMedia.toMutableSet()
        val completed = mutableSetOf<String>()
        var newCopies = 0
        var existingCopies = 0
        for (media in remaining) {
            when (outcomes[media]) {
                ImportOutcome.FAILED -> errors.add(media)
                ImportOutcome.COPIED -> { completed.add(media); newCopies++ }
                ImportOutcome.DUPLICATE -> { completed.add(media); existingCopies++ }
                null -> continue
            }
        }
        if (completed.isEmpty() && errors.size == failedMedia.size) return this
        errors.removeAll(completed)
        return copy(
            remaining = remaining.filterNot { it in completed },
            members = members.filterKeys { it !in completed },
            copied = copied + newCopies,
            duplicates = duplicates + existingCopies,
            failed = failed + errors.size - failedMedia.size,
            failedMedia = errors.toList(),
        )
    }
    fun canResume(fingerprint: String, remoteRequest: String) =
        work.isNotEmpty() && peer == fingerprint && phase != "done" &&
            (!prepared || remaining.isNotEmpty() || batch.isNotEmpty() || batches.isNotEmpty()) &&
            (remoteRequest.isEmpty() || request == remoteRequest)
}

enum class ImportOutcome { COPIED, DUPLICATE, FAILED }

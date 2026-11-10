package app.regista

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.res.AssetManager
import android.icu.lang.UCharacter
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.nio.LongBuffer
import java.security.MessageDigest

/** Local interpretation of a command, for the read-only preview. */
class CommandPreview(private val assets: AssetManager) {
    private val environment by lazy { OrtEnvironment.getEnvironment() }
    private var model: Model? = null
    private var closed = false

    val available: Boolean by lazy {
        try {
            val files = assets.list("commands").orEmpty()
            "commands.json" in files && "commands.onnx" in files
        } catch (problem: IOException) {
            false
        }
    }

    @Synchronized
    fun preview(text: String): String {
        if (closed || !available) return failure("Il modello dei comandi non è incluso in questa versione.")
        if (text.length > 500) return failure("Scrivi un comando di al massimo 500 caratteri.")
        val words = WORDS.findAll(text).take(LIMIT + 1).toList()
        if (words.isEmpty() || words.size > LIMIT) return clarify().toString()

        return try {
            val loaded = model ?: load().also { model = it }
            val tokens = LongArray(LIMIT)
            for ((index, word) in words.withIndex()) {
                tokens[index] = loaded.vocabulary.optLong(fold(word.value), 1)
            }
            OnnxTensor.createTensor(environment, LongBuffer.wrap(tokens), longArrayOf(1, LIMIT.toLong())).use { input ->
                loaded.runtime.run(mapOf("tokens" to input)).use { output ->
                    @Suppress("UNCHECKED_CAST")
                    val intents = output.get("intent_logits").get().value as Array<FloatArray>
                    @Suppress("UNCHECKED_CAST")
                    val scores = output.get("slot_logits").get().value as Array<Array<FloatArray>>
                    val intent = INTENTS[argmax(intents.single())]
                    val tags = if (loaded.boundaries) boundaries(scores.single(), intent) else scores.single().map(::argmax).toIntArray()
                    decode(text, words, intent, tags).toString()
                }
            }
        } catch (problem: Exception) {
            Log.w("Regista", "Impossibile eseguire il modello dei comandi", problem)
            failure("Non riesco a eseguire il modello dei comandi.")
        }
    }

    @Synchronized
    fun close() {
        closed = true
        model?.runtime?.close()
        model = null
    }

    private class Model(val runtime: OrtSession, val vocabulary: JSONObject, val boundaries: Boolean)

    private fun load(): Model {
        val metadata = assets.open("commands/commands.json").bufferedReader().use { JSONObject(it.readText()) }
        val payload = assets.open("commands/commands.onnx").use { it.readBytes() }
        val hash = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        require(hash == metadata.getString("model_sha256"))
        val input = metadata.getJSONObject("input")
        val tokenizer = metadata.getJSONObject("tokenizer")
        val encoding = metadata.getString("slot_encoding")
        require(metadata.getInt("format_version") == 1 && input.getString("name") == "tokens" &&
            input.getString("type") == "int64" && input.getInt("length") == LIMIT &&
            metadata.getJSONArray("intents").strings() == INTENTS && metadata.getJSONArray("labels").strings() == LABELS &&
            metadata.getJSONArray("outputs").strings() == listOf("intent_logits", "slot_logits") &&
            tokenizer.getString("pattern") == """\w+|[^\w\s]""" && tokenizer.getString("normalization") == "casefold" &&
            tokenizer.getInt("padding_id") == 0 && tokenizer.getInt("unknown_id") == 1 &&
            encoding in setOf("per_token", "boundaries"))
        val vocabulary = tokenizer.getJSONObject("vocabulary")
        return OrtSession.SessionOptions().use { options ->
            options.setIntraOpNumThreads(2)
            Model(environment.createSession(payload, options), vocabulary, encoding == "boundaries")
        }
    }

    private fun JSONArray.strings() = List(length()) { getString(it) }

    private fun argmax(scores: FloatArray): Int = scores.indices.maxByOrNull { scores[it] } ?: error("empty model output")

    private fun boundaries(scores: Array<FloatArray>, intent: String): IntArray {
        // The exported axes are [position][edge]; each slot has a start and end edge.
        val edges = IntArray(2 * (LABELS.size - 1)) { edge -> argmax(FloatArray(scores.size) { scores[it][edge] }) }
        val tags = IntArray(LIMIT)
        for (slot in relevant(intent)) {
            val start = edges[2 * (slot - 1)]
            val end = edges[2 * (slot - 1) + 1]
            if (start == LIMIT && end == LIMIT) continue
            if (start > end || end >= LIMIT || (start..end).any { tags[it] != 0 }) return IntArray(LIMIT)
            for (index in start..end) tags[index] = slot
        }
        return tags
    }

    private fun decode(text: String, words: List<MatchResult>, intent: String, tags: IntArray): JSONObject {
        val allowed = relevant(intent)
        if (allowed.isEmpty()) return clarify()
        val slots = JSONObject()
        for (slot in allowed) {
            val indexes = words.indices.filter { tags[it] == slot }
            if (indexes.isEmpty()) continue
            val first = indexes.first()
            var last = indexes.last()
            if (indexes.size != last - first + 1) return clarify()
            if (slot == 2 && first < last && last + 1 < words.size && tags[last + 1] == 3 &&
                fold(words[last].value) in TITLE_SEPARATORS) last -= 1
            slots.put(LABELS[slot], text.substring(words[first].range.first, words[last].range.last + 1))
        }
        if (!slots.has(LABELS[allowed.first()])) return clarify()
        return JSONObject().put("intent", intent).put("slots", slots)
    }

    private fun relevant(intent: String) = when (intent) {
        "clarify" -> emptyList()
        "play_song" -> listOf(2, 3)
        else -> listOf(1)
    }

    private fun clarify() = JSONObject().put("intent", "clarify").put("slots", JSONObject())

    private fun failure(message: String) = JSONObject().put("error", message).toString()

    private fun fold(word: String) = UCharacter.foldCase(word, true)

    private companion object {
        const val LIMIT = 64
        val INTENTS = listOf("search_photos", "add_tag", "remove_tag", "play_song", "clarify")
        val LABELS = listOf("O", "tag", "title", "artist")
        val TITLE_SEPARATORS = setOf("di", "del", "della", "dei", "degli", "delle")
        // Python's Unicode word class means letters, numbers and underscore. Its spaces include U+001C–U+001F.
        val WORDS = Regex("""[\p{L}\p{N}_]+|[^\p{L}\p{N}_\p{Z}\u0009-\u000d\u001c-\u001f\u0085]""")
    }
}

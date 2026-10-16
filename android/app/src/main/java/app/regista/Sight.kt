package app.regista

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.LongBuffer
import java.security.MessageDigest
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * The phone's own eyes: two small models that turn a picture, and a sentence in Italian (or in
 * many other languages), into 512 numbers, so that a picture and a sentence that describes it
 * get similar numbers. The picture model is CLIP ViT-B/32, the one the computer uses too; the
 * sentence model was taught to answer as CLIP does, in many languages
 * (sentence-transformers/clip-ViT-B-32-multilingual-v1). They come from the computer once
 * (Link), into the app's own files, and from then on work with no computer and no network.
 */
class Sight(context: Context) {
    private val folder = File(context.filesDir, "models")

    /** While the models arrive from the computer: how many bytes have arrived, of how many. */
    @Volatile var got = 0L

    @Volatile var size = 0L

    val ready get() = FILES.all { File(folder, it).isFile }

    private var environment: OrtEnvironment? = null
    private var sentences: OrtSession? = null
    private var pictures: OrtSession? = null
    private var pieces: WordPieces? = null

    // the last layer of the sentence model: 512 rows of 768
    private var dense = FloatArray(0)

    @Synchronized
    private fun load() {
        if (sentences != null) return
        val made = OrtEnvironment.getEnvironment()
        val options = OrtSession.SessionOptions().apply { setIntraOpNumThreads(2) }
        sentences = made.createSession(File(folder, "text.onnx").path, options)
        pictures = made.createSession(File(folder, "vision.onnx").path, options)
        pieces = WordPieces(File(folder, "vocab.txt"))
        dense = readDense(File(folder, "dense.safetensors"))
        environment = made
    }

    /** What a sentence says, as 512 numbers of length 1. */
    @Synchronized
    fun sentence(text: String): FloatArray {
        load()
        val made = environment!!
        val ids = pieces!!.encode(text)
        val shape = longArrayOf(1, ids.size.toLong())
        OnnxTensor.createTensor(made, LongBuffer.wrap(ids), shape).use { words ->
            OnnxTensor.createTensor(made, LongBuffer.wrap(LongArray(ids.size) { 1 }), shape).use { mask ->
                sentences!!.run(mapOf("input_ids" to words, "attention_mask" to mask)).use { result ->
                    @Suppress("UNCHECKED_CAST")
                    val hidden = (result[0].value as Array<Array<FloatArray>>)[0]
                    // the mean of what the model says of each piece, then its last layer
                    val pooled = FloatArray(WIDTH)
                    for (piece in hidden) for (index in 0 until WIDTH) pooled[index] += piece[index] / hidden.size
                    val out = FloatArray(SIZE) { row ->
                        var sum = 0f
                        val start = row * WIDTH
                        for (index in 0 until WIDTH) sum += dense[start + index] * pooled[index]
                        sum
                    }
                    return unit(out)
                }
            }
        }
    }

    /** What a picture shows, as 512 numbers of length 1, from a small copy of it as a JPEG. Null if it cannot be read. */
    @Synchronized
    fun picture(jpeg: ByteArray): FloatArray? {
        val source = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: return null
        load()
        // the shortest side to 224, then the middle 224 by 224: as the model was taught
        val scale = SIDE.toFloat() / min(source.width, source.height)
        val width = max(SIDE, (source.width * scale).roundToInt())
        val height = max(SIDE, (source.height * scale).roundToInt())
        val scaled = Bitmap.createScaledBitmap(source, width, height, true)
        val pixels = IntArray(SIDE * SIDE)
        scaled.getPixels(pixels, 0, SIDE, (width - SIDE) / 2, (height - SIDE) / 2, SIDE, SIDE)
        val values = FloatArray(3 * SIDE * SIDE)
        val plane = SIDE * SIDE
        for (index in pixels.indices) {
            val pixel = pixels[index]
            values[index] = ((pixel shr 16 and 0xFF) / 255f - MEAN[0]) / STD[0]
            values[plane + index] = ((pixel shr 8 and 0xFF) / 255f - MEAN[1]) / STD[1]
            values[2 * plane + index] = ((pixel and 0xFF) / 255f - MEAN[2]) / STD[2]
        }
        OnnxTensor.createTensor(environment!!, FloatBuffer.wrap(values), longArrayOf(1, 3, SIDE.toLong(), SIDE.toLong())).use { batch ->
            pictures!!.run(mapOf("pixel_values" to batch)).use { result ->
                @Suppress("UNCHECKED_CAST")
                return unit((result[0].value as Array<FloatArray>)[0])
            }
        }
    }

    /** Whether one of the models is here, whole: as large as the computer said. */
    fun has(name: String, bytes: Long) = File(folder, name).let { it.isFile && it.length() == bytes }

    /**
     * Keeps a model that arrives from the computer. Written under another name until all of it is
     * here and is what the computer said it is: a model cut short never looks like one. Says whether it was kept.
     */
    fun keep(name: String, source: InputStream, expected: String, arrived: (Long) -> Unit): Boolean {
        folder.mkdirs()
        val partial = File(folder, "$name.part")
        val digest = MessageDigest.getInstance("SHA-256")
        try {
            partial.outputStream().use { out ->
                source.use { input ->
                    val buffer = ByteArray(256 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        digest.update(buffer, 0, read)
                        out.write(buffer, 0, read)
                        arrived(read.toLong())
                    }
                }
            }
        } catch (problem: IOException) {
            partial.delete()
            throw problem
        }
        if (!digest.digest().joinToString("") { "%02x".format(it) }.equals(expected, ignoreCase = true)) {
            partial.delete()
            return false
        }
        return partial.renameTo(File(folder, name))
    }

    private fun unit(vector: FloatArray): FloatArray {
        val length = sqrt(vector.fold(0f) { sum, value -> sum + value * value })
        return FloatArray(vector.size) { vector[it] / length }
    }

    /** The weights of the last layer, from its safetensors file: a header that says where they are, then the numbers. */
    private fun readDense(file: File): FloatArray {
        val bytes = file.readBytes()
        val size = ByteBuffer.wrap(bytes, 0, 8).order(ByteOrder.LITTLE_ENDIAN).long.toInt()
        val header = JSONObject(String(bytes, 8, size, Charsets.UTF_8)).getJSONObject("linear.weight")
        val offsets = header.getJSONArray("data_offsets")
        val start = 8 + size + offsets.getLong(0).toInt()
        val values = FloatArray(((offsets.getLong(1) - offsets.getLong(0)) / 4).toInt())
        ByteBuffer.wrap(bytes, start, values.size * 4).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(values)
        return values
    }

    companion object {
        val FILES = listOf("text.onnx", "vision.onnx", "vocab.txt", "dense.safetensors")
        const val SIZE = 512
        private const val WIDTH = 768
        private const val SIDE = 224
        private val MEAN = floatArrayOf(0.48145466f, 0.4578275f, 0.40821073f)
        private val STD = floatArrayOf(0.26862954f, 0.26130258f, 0.27577711f)
    }
}

/**
 * Words into the numbers the sentence model reads, as BERT cuts them, for a model that keeps
 * capitals and accents: spaces and punctuation split words, and each word is cut into the
 * longest pieces its vocabulary has. The same as tools on the computer do, written out here.
 */
class WordPieces(vocab: File) {
    private val ids = HashMap<String, Long>(130_000)

    init {
        vocab.useLines { lines -> lines.forEachIndexed { index, line -> ids[line] = index.toLong() } }
    }

    private val unknown = ids.getValue("[UNK]")

    fun encode(text: String): LongArray {
        val found = ArrayList<Long>()
        found += ids.getValue("[CLS]")
        for (word in words(text)) found += pieces(word)
        val kept = found.take(MAX - 1) + ids.getValue("[SEP]")
        return kept.toLongArray()
    }

    private fun words(text: String): List<String> {
        val cleaned = StringBuilder()
        text.codePoints().forEach { code ->
            val kind = Character.getType(code)
            when {
                code == 0 || code == 0xFFFD -> {}
                code == '\t'.code || code == '\n'.code || code == '\r'.code || code == ' '.code || kind == Character.SPACE_SEPARATOR.toInt() -> cleaned.append(' ')
                kind in CONTROLS -> {}
                chinese(code) -> cleaned.append(' ').appendCodePoint(code).append(' ')
                else -> cleaned.appendCodePoint(code)
            }
        }
        val words = ArrayList<String>()
        for (word in cleaned.split(' ')) {
            if (word.isEmpty()) continue
            val piece = StringBuilder()
            word.codePoints().forEach { code ->
                if (punctuation(code)) {
                    if (piece.isNotEmpty()) words += piece.toString()
                    piece.setLength(0)
                    words += String(Character.toChars(code))
                } else {
                    piece.appendCodePoint(code)
                }
            }
            if (piece.isNotEmpty()) words += piece.toString()
        }
        return words
    }

    private fun pieces(word: String): List<Long> {
        if (word.codePointCount(0, word.length) > 100) return listOf(unknown)
        val found = ArrayList<Long>()
        var start = 0
        while (start < word.length) {
            var end = word.length
            var match: Long? = null
            while (start < end) {
                match = ids[(if (start > 0) "##" else "") + word.substring(start, end)]
                if (match != null) break
                end -= 1
            }
            if (match == null) return listOf(unknown)
            found += match
            start = end
        }
        return found
    }

    private fun punctuation(code: Int): Boolean {
        if (code in 33..47 || code in 58..64 || code in 91..96 || code in 123..126) return true
        return Character.getType(code) in PUNCTUATION
    }

    private fun chinese(code: Int) = code in 0x4E00..0x9FFF || code in 0x3400..0x4DBF || code in 0x20000..0x2A6DF || code in 0x2A700..0x2B73F ||
        code in 0x2B740..0x2B81F || code in 0x2B820..0x2CEAF || code in 0xF900..0xFAFF || code in 0x2F800..0x2FA1F

    private companion object {
        const val MAX = 128
        val CONTROLS = setOf(Character.CONTROL, Character.FORMAT, Character.SURROGATE, Character.PRIVATE_USE, Character.UNASSIGNED).map { it.toInt() }.toSet()
        val PUNCTUATION = setOf(
            Character.CONNECTOR_PUNCTUATION, Character.DASH_PUNCTUATION, Character.START_PUNCTUATION, Character.END_PUNCTUATION,
            Character.INITIAL_QUOTE_PUNCTUATION, Character.FINAL_QUOTE_PUNCTUATION, Character.OTHER_PUNCTUATION,
        ).map { it.toInt() }.toSet()
    }
}

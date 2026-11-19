package app.regista

import java.io.FilterInputStream
import java.io.InputStream
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.CancellationException

/** Pure policies shared by MediaStore/SAF sources and JVM tests. */
object BackupRules {
    private val images = setOf("jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "avif", "heic", "heif", "dng", "nef", "cr2", "cr3", "arw", "raf", "rw2", "orf", "pef", "srw")
    private val audios = setOf("mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "amr", "wma", "aiff", "aif", "alac", "ac3", "mka", "mid", "midi", "ape", "oga", "spx")
    private val videos = setOf("mp4", "m4v", "mov", "mkv", "webm", "3gp", "3g2", "avi", "wmv", "mpg", "mpeg", "mts", "m2ts", "ts", "vob", "ogv", "flv", "divx")

    fun kind(mime: String, name: String): String? {
        val type = mime.lowercase(Locale.ROOT).substringBefore(';').trim()
        for (kind in listOf("image", "audio", "video")) if (type.startsWith("$kind/")) return kind
        return when (name.substringAfterLast('.', "").lowercase(Locale.ROOT)) {
            in images -> "image"
            in audios -> "audio"
            in videos -> "video"
            else -> null
        }
    }

    data class Digest(val sha256: String, val bytes: Long)

    fun hash(input: InputStream, cancelled: () -> Boolean): Digest = input.use { source ->
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(256 * 1024)
        var bytes = 0L
        while (true) {
            if (cancelled()) throw CancellationException()
            val count = source.read(buffer)
            if (count < 0) break
            bytes += count
            digest.update(buffer, 0, count)
        }
        if (cancelled()) throw CancellationException()
        Digest(digest.digest().joinToString("") { "%02x".format(it) }, bytes)
    }

    class Sending(input: InputStream, private val cancelled: () -> Boolean, private val progress: (Long) -> Unit) : FilterInputStream(input) {
        private var bytes = 0L
        override fun read(): Int {
            if (cancelled()) throw CancellationException()
            val result = `in`.read()
            if (result >= 0) { bytes++; progress(bytes) }
            return result
        }
        override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
            if (cancelled()) throw CancellationException()
            val count = `in`.read(buffer, offset, length)
            if (count > 0) { bytes += count; progress(bytes) }
            return count
        }
    }
}

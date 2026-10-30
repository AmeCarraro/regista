package app.regista

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.BaseColumns
import android.provider.MediaStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

/**
 * The songs on this phone, as Android lists them: music only, not ringtones, alarms or voice notes.
 * Android reads their title, artist and album from the files itself. Nothing here changes a song.
 */
class Songs(private val context: Context) {
    /** The permission to see the songs: its name changed with Android 13, as for the pictures. */
    val permission: String
        get() = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_AUDIO else Manifest.permission.READ_EXTERNAL_STORAGE

    val allowed get() = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    /** All of them, by title: their number in Android's list, title, artist, album and length in milliseconds. */
    fun json(): JSONArray {
        val songs = JSONArray()
        if (!allowed) return songs
        val columns = arrayOf(
            BaseColumns._ID,
            MediaStore.MediaColumns.TITLE,
            MediaStore.Audio.AudioColumns.ARTIST,
            MediaStore.Audio.AudioColumns.ALBUM,
            MediaStore.Audio.AudioColumns.DURATION,
        )
        val music = "${MediaStore.Audio.AudioColumns.IS_MUSIC} != 0"
        context.contentResolver.query(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, columns, music, null, "${MediaStore.MediaColumns.TITLE} COLLATE NOCASE")?.use { rows ->
            while (rows.moveToNext()) {
                songs.put(
                    JSONObject()
                        .put("id", rows.getLong(0).toString())
                        .put("title", rows.getString(1).orEmpty())
                        .put("artist", known(rows.getString(2)))
                        .put("album", known(rows.getString(3)))
                        .put("duration", rows.getLong(4)),
                )
            }
        }
        return songs
    }

    // what Android says when a file does not say
    private fun known(said: String?) = if (said == null || said == MediaStore.UNKNOWN_STRING) "" else said

    /** A song of this phone, to send it: its file name, its size and its fingerprint (SHA-256). */
    class Described(val name: String, val size: Long, val fingerprint: String)

    fun described(id: Long): Described? {
        val columns = arrayOf(MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE)
        val (name, size) = context.contentResolver.query(uri(id), columns, null, null, null)?.use { rows ->
            if (rows.moveToFirst()) rows.getString(0).orEmpty() to rows.getLong(1) else null
        } ?: return null
        val fingerprint = open(id).use { input -> written(input, null) }
        return Described(name, size, fingerprint)
    }

    /** The bytes of a song of this phone. */
    fun open(id: Long): InputStream = context.contentResolver.openInputStream(uri(id)) ?: throw IOException("the song is gone")

    /**
     * Keeps a song that arrives from the computer, in Music/Regista: a song of this phone from now
     * on. Android keeps it hidden until all of it is there and it is what the computer said it is;
     * if it is not, it is not kept. Says whether it was.
     */
    fun keep(name: String, source: InputStream, expected: String): Boolean {
        val safe = name.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), " ").trim().ifEmpty { "canzone.mp3" }
        if (Build.VERSION.SDK_INT < 29) return keepBefore10(safe, source, expected)
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, safe)
            put(MediaStore.MediaColumns.MIME_TYPE, kindOf(safe))
            put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_MUSIC}/Regista")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val made = resolver.insert(MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values) ?: return false
        try {
            val out = resolver.openOutputStream(made) ?: throw IOException("no place to write")
            if (!written(source, out).equals(expected, ignoreCase = true)) throw IOException("not what the computer sent")
            resolver.update(made, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
            return true
        } catch (problem: IOException) {
            // what did not arrive whole is not a song: the app's own unfinished file does not stay
            resolver.delete(made, null, null)
            return false
        }
    }

    /** Before Android 10 a song is a file in the folder of music, which Android is then told to look at. */
    @Suppress("DEPRECATION")
    private fun keepBefore10(name: String, source: InputStream, expected: String): Boolean {
        val directory = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC), "Regista")
        if (!directory.isDirectory && !directory.mkdirs()) return false
        // never over a song that is there: "Volare (2).mp3"
        var target = File(directory, name)
        var number = 2
        while (target.exists()) target = File(directory, "${name.substringBeforeLast('.')} ($number).${name.substringAfterLast('.', "mp3")}").also { number += 1 }
        val partial = File(directory, ".${target.name}.part")
        val arrived = try {
            written(source, partial.outputStream())
        } catch (problem: IOException) {
            null
        }
        if (arrived == null || !arrived.equals(expected, ignoreCase = true) || !partial.renameTo(target)) {
            partial.delete()
            return false
        }
        MediaScannerConnection.scanFile(context, arrayOf(target.path), arrayOf(kindOf(target.name)), null)
        return true
    }

    /** Reads all of `source`, into `target` when there is one, and says its SHA-256. Both are closed after. */
    private fun written(source: InputStream, target: OutputStream?): String {
        val digest = MessageDigest.getInstance("SHA-256")
        try {
            source.use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                    target?.write(buffer, 0, read)
                }
            }
        } finally {
            target?.close()
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun kindOf(name: String) = when (name.substringAfterLast('.').lowercase()) {
        "m4a" -> "audio/mp4"
        "aac" -> "audio/aac"
        "flac" -> "audio/flac"
        "ogg", "oga", "opus" -> "audio/ogg"
        "wav" -> "audio/x-wav"
        else -> "audio/mpeg"
    }

    companion object {
        /** Where Android keeps a song, to play it. */
        fun uri(id: Long): Uri = ContentUris.withAppendedId(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, id)
    }
}

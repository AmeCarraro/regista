package app.regista

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Size
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * A picture of the phone: the phone's own number for it, its file name, a stamp that changes
 * when the picture does, and the day Android believes it was taken (see Gallery.notes for the real one).
 */
class Photo(val id: Long, val name: String, val stamp: String, val day: String)

/** What a picture says about itself: the day it was taken and, if known, where, in degrees. */
class Notes(val day: String, val latitude: Double?, val longitude: Double?)

/**
 * The pictures of this phone, read through Android's own list of them. Nothing here changes a
 * picture that is there: it can add new ones, the ones the computer sends, and moving some to
 * the phone's trash is asked of Android, which asks the user (MainActivity).
 */
class Gallery(private val context: Context) {
    private val pictures: Uri = MediaStore.Images.Media.EXTERNAL_CONTENT_URI

    private companion object {
        // the long side of a small copy, in pixels
        const val SMALL = 384
    }

    /** The permission Android asks the user for before an app can see the pictures. Its name changed with Android 13. */
    val permission = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE

    val allowed get() = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    /** The number of the newest picture of the gallery; 0 when there is none. The ones added later have larger numbers. */
    fun newest(): Long = all().maxOfOrNull { it.id } ?: 0L

    fun all(): List<Photo> {
        val columns = arrayOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.DATE_MODIFIED,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Images.Media.SIZE,
        )
        val found = mutableListOf<Photo>()
        context.contentResolver.query(pictures, columns, null, null, "${MediaStore.Images.Media.DATE_MODIFIED} DESC")?.use { rows ->
            while (rows.moveToNext()) {
                val modified = rows.getLong(2)
                // some pictures have no date of their own: the date of the file, which is in seconds, stands in
                val taken = rows.getLong(3).takeIf { it > 0 } ?: (modified * 1000)
                found += Photo(
                    id = rows.getLong(0),
                    name = rows.getString(1) ?: "foto.jpg",
                    stamp = "$modified-${rows.getLong(4)}",
                    // the day as this phone's clock and calendar say it, like "2024-08-15": the computer could not know where the phone was
                    day = SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).format(Date(taken)),
                )
            }
        }
        return found
    }

    private fun address(id: Long): Uri = ContentUris.withAppendedId(pictures, id)

    /** The permissions the app still lacks: to see the pictures, and to see where each was taken. Android asks the user for both at once. */
    fun missing(): Array<String> {
        val wanted = if (Build.VERSION.SDK_INT >= 29) {
            listOf(permission, Manifest.permission.ACCESS_MEDIA_LOCATION)
        } else {
            // before Android 10 the place is in the picture for whoever may read it, and the pictures that
            // arrive from the computer are written as files: Android asks once for both
            listOf(permission, Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
        return wanted.filter { context.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }.toTypedArray()
    }

    /**
     * What a picture says about itself: the day it was taken and, if its camera knew, where.
     *
     * The camera writes the day as the clock said where the picture was taken: that is the day
     * the user remembers. Android's own list often has no date for pictures that came from
     * another phone or from a backup, and then it would be the day they were copied. So the
     * picture itself is asked first. The place Android takes out of a picture before handing
     * it to an app, unless the user allowed the app to see it: the picture is asked for whole
     * first, and if that is refused, as Android gives it.
     */
    fun notes(photo: Photo): Notes {
        for (whole in listOf(true, false)) {
            try {
                val picture = if (whole && Build.VERSION.SDK_INT >= 29) MediaStore.setRequireOriginal(address(photo.id)) else address(photo.id)
                context.contentResolver.openInputStream(picture)?.use { stream ->
                    val written = ExifInterface(stream)
                    val moment = written.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL) ?: written.getAttribute(ExifInterface.TAG_DATETIME)
                    val day = moment?.take(10)?.replace(':', '-')?.takeIf { Regex("[12]\\d{3}-\\d{2}-\\d{2}").matches(it) } ?: photo.day
                    val place = FloatArray(2)
                    return if (written.getLatLong(place)) Notes(day, place[0].toDouble(), place[1].toDouble()) else Notes(day, null, null)
                }
            } catch (problem: IOException) {
                // not readable this way: the next
            } catch (problem: SecurityException) {
                // the place is not for this app to see: the picture without it
            } catch (problem: UnsupportedOperationException) {
                // the same, as some versions of Android say it
            }
        }
        return Notes(photo.day, null, null)
    }

    /** A small copy of a picture, as a JPEG: what the computer, and the phone's own model, need to know what the picture shows. */
    fun small(id: Long): ByteArray? = try {
        val bitmap = if (Build.VERSION.SDK_INT >= 29) context.contentResolver.loadThumbnail(address(id), Size(SMALL, SMALL), null) else smallBefore10(id)
        bitmap?.let { ByteArrayOutputStream().also { out -> it.compress(Bitmap.CompressFormat.JPEG, 80, out) }.toByteArray() }
    } catch (problem: IOException) {
        null
    } catch (problem: SecurityException) {
        null
    }

    /** Before Android 10 there is no call for a small copy: the picture is read at a fraction of its size, and turned as its camera says. */
    private fun smallBefore10(id: Long): Bitmap? {
        val resolver = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(address(id))?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= SMALL) sample *= 2
        val decoded = resolver.openInputStream(address(id))?.use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample }) } ?: return null
        val scale = SMALL.toFloat() / max(decoded.width, decoded.height)
        val sized = if (scale < 1) Bitmap.createScaledBitmap(decoded, (decoded.width * scale).roundToInt(), (decoded.height * scale).roundToInt(), true) else decoded
        val turn = resolver.openInputStream(address(id))?.use { ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL) }
        val degrees = when (turn) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
        return if (degrees == 0f) sized else Bitmap.createBitmap(sized, 0, 0, sized.width, sized.height, Matrix().apply { postRotate(degrees) }, true)
    }

    /**
     * How to read a picture from start to end. As its camera wrote it, if Android allows: that
     * is the picture, place included. Otherwise as Android hands it to an app, with the place
     * taken out; but not when `whole` is asked for, as for a picture that is about to leave the
     * phone: a copy with something missing is not the copy to keep.
     */
    fun source(id: Long, whole: Boolean): Uri? {
        // before Android 10 a picture is handed over as it is, place included
        if (Build.VERSION.SDK_INT < 29) return address(id).takeIf { readable(it) }
        val written = MediaStore.setRequireOriginal(address(id))
        if (readable(written)) return written
        return address(id).takeIf { !whole && readable(it) }
    }

    private fun readable(picture: Uri): Boolean = try {
        context.contentResolver.openInputStream(picture)?.use { it.read() >= 0 } ?: false
    } catch (problem: IOException) {
        false
    } catch (problem: SecurityException) {
        false
    } catch (problem: UnsupportedOperationException) {
        false
    }

    fun open(source: Uri): InputStream? = try {
        context.contentResolver.openInputStream(source)
    } catch (problem: IOException) {
        null
    } catch (problem: SecurityException) {
        null
    }

    /** What tells these bytes from any others: the computer checks it against what arrives. */
    fun fingerprint(source: Uri): String? {
        val digest = MessageDigest.getInstance("SHA-256")
        val stream = open(source) ?: return null
        return try {
            stream.use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            digest.digest().joinToString("") { "%02x".format(it) }
        } catch (problem: IOException) {
            null
        }
    }

    /**
     * Keeps a picture that arrives from the computer, in the album Pictures/Regista/<album>: a new
     * picture of this phone. Android keeps it hidden until all of it is there and it is what the
     * computer said it is; if it is not, it is not kept. Says whether it was.
     */
    fun save(name: String, album: String, source: InputStream, expected: String): Boolean {
        val folder = album.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), " ").trim().ifEmpty { "Dal computer" }
        if (Build.VERSION.SDK_INT < 29) return saveBefore10(name, folder, source, expected)
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, name)
            put(MediaStore.Images.Media.MIME_TYPE, kindOf(name))
            put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/Regista/$folder")
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val made = resolver.insert(pictures, values) ?: return false
        try {
            val digest = MessageDigest.getInstance("SHA-256")
            val out = resolver.openOutputStream(made) ?: throw IOException("no place to write")
            out.use { target ->
                source.use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        digest.update(buffer, 0, read)
                        target.write(buffer, 0, read)
                    }
                }
            }
            if (!digest.digest().joinToString("") { "%02x".format(it) }.equals(expected, ignoreCase = true)) throw IOException("not what the computer sent")
            resolver.update(made, ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) }, null, null)
            return true
        } catch (problem: IOException) {
            // what did not arrive whole is not a picture: the app's own unfinished file does not stay
            resolver.delete(made, null, null)
            return false
        }
    }

    /** Before Android 10 a picture is a file in the folder of pictures, which Android is then told to look at. */
    @Suppress("DEPRECATION")
    private fun saveBefore10(name: String, folder: String, source: InputStream, expected: String): Boolean {
        val directory = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "Regista/$folder")
        if (!directory.isDirectory && !directory.mkdirs()) return false
        val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), " ").trim().ifEmpty { "foto.jpg" }
        // never over a picture that is there: "rosa (2).jpg"
        var target = File(directory, safe)
        var number = 2
        while (target.exists()) target = File(directory, "${safe.substringBeforeLast('.')} ($number).${safe.substringAfterLast('.', "jpg")}").also { number += 1 }
        val partial = File(directory, ".${target.name}.part")
        val digest = MessageDigest.getInstance("SHA-256")
        try {
            partial.outputStream().use { out ->
                source.use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        digest.update(buffer, 0, read)
                        out.write(buffer, 0, read)
                    }
                }
            }
        } catch (problem: IOException) {
            partial.delete()
            return false
        }
        if (!digest.digest().joinToString("") { "%02x".format(it) }.equals(expected, ignoreCase = true) || !partial.renameTo(target)) {
            partial.delete()
            return false
        }
        MediaScannerConnection.scanFile(context, arrayOf(target.path), arrayOf(kindOf(target.name)), null)
        return true
    }

    private fun kindOf(name: String) = when (name.substringAfterLast('.').lowercase()) {
        "png" -> "image/png"
        "webp" -> "image/webp"
        "gif" -> "image/gif"
        "heic", "heif" -> "image/heic"
        else -> "image/jpeg"
    }

    /** The name Android knows a picture by, for the question that moves it to the trash. */
    fun named(id: Long): Uri = address(id)

    /** Which of some pictures are still in the gallery: one moved to the trash, or deleted, is not. */
    fun present(ids: List<Long>): Set<Long> {
        if (ids.isEmpty()) return emptySet()
        val there = mutableSetOf<Long>()
        val among = "${MediaStore.Images.Media._ID} IN (${ids.joinToString(",")})"
        context.contentResolver.query(pictures, arrayOf(MediaStore.Images.Media._ID), among, null, null)?.use { rows ->
            while (rows.moveToNext()) there += rows.getLong(0)
        }
        return there
    }
}

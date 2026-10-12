package app.regista

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.media.ExifInterface
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.Size
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.time.Instant
import java.time.ZoneId

/**
 * A picture of the phone: the phone's own number for it, its file name, a stamp that changes
 * when the picture does, and the day Android believes it was taken (see Gallery.notes for the real one).
 */
class Photo(val id: Long, val name: String, val stamp: String, val day: String)

/** What a picture says about itself: the day it was taken and, if known, where, in degrees. */
class Notes(val day: String, val latitude: Double?, val longitude: Double?)

/** The pictures of this phone, read through Android's own list of them. Nothing here changes a picture. */
class Gallery(private val context: Context) {
    private val pictures: Uri = MediaStore.Images.Media.EXTERNAL_CONTENT_URI

    /** The permission Android asks the user for before an app can see the pictures. Its name changed with Android 13. */
    val permission = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE

    val allowed get() = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

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
                    day = Instant.ofEpochMilli(taken).atZone(ZoneId.systemDefault()).toLocalDate().toString(),
                )
            }
        }
        return found
    }

    private fun address(id: Long): Uri = ContentUris.withAppendedId(pictures, id)

    /** The permissions the app still lacks: to see the pictures, and to see where each was taken. Android asks the user for both at once. */
    fun missing(): Array<String> =
        arrayOf(permission, Manifest.permission.ACCESS_MEDIA_LOCATION).filter { context.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }.toTypedArray()

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
                val picture = if (whole) MediaStore.setRequireOriginal(address(photo.id)) else address(photo.id)
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

    /** A small copy of a picture, as a JPEG: what the computer needs to know what the picture shows. */
    fun small(id: Long): ByteArray? = try {
        val bitmap = context.contentResolver.loadThumbnail(address(id), Size(384, 384), null)
        ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG, 80, it) }.toByteArray()
    } catch (problem: IOException) {
        null
    }

    /** The picture itself, to be read from start to end. */
    fun open(id: Long): InputStream? = try {
        context.contentResolver.openInputStream(address(id))
    } catch (problem: IOException) {
        null
    } catch (problem: SecurityException) {
        null
    }
}

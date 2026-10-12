package app.regista

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.Size
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream

/** A picture of the phone: the phone's own number for it, its file name, and a stamp that changes when the picture does. */
class Photo(val id: Long, val name: String, val stamp: String, val taken: Long, val size: Long)

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
                val size = rows.getLong(4)
                found += Photo(
                    id = rows.getLong(0),
                    name = rows.getString(1) ?: "foto.jpg",
                    stamp = "$modified-$size",
                    // some pictures have no date of their own: the date of the file, which is in seconds, stands in
                    taken = rows.getLong(3).takeIf { it > 0 } ?: (modified * 1000),
                    size = size,
                )
            }
        }
        return found
    }

    private fun address(id: Long): Uri = ContentUris.withAppendedId(pictures, id)

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

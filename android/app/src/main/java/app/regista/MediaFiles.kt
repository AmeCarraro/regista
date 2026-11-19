package app.regista

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.provider.DocumentsContract
import android.provider.MediaStore
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.CancellationException

/** One read-only source, either a MediaStore row or a granted SAF document. */
data class BackupMedia(
    val media: String, val name: String, val folder: String, val kind: String,
    val size: Long, val mime: String, val stamp: String,
    val current: () -> Boolean, val open: () -> InputStream,
    val cacheable: Boolean = false,
)

/** All granted image, audio and video collections, across mounted volumes; no album or music-only filter. */
class MediaFiles(private val context: Context) {
    @Volatile private var querying: CancellationSignal? = null

    fun missingPermissions(): Array<String> {
        val permissions = if (Build.VERSION.SDK_INT >= 33) mutableListOf(
            Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO, Manifest.permission.READ_MEDIA_AUDIO,
        ) else mutableListOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        if (Build.VERSION.SDK_INT >= 29) permissions += Manifest.permission.ACCESS_MEDIA_LOCATION
        return permissions.filter { context.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }.toTypedArray()
    }

    fun permissionRequest(): Array<String> {
        val missing = missingPermissions().toMutableList()
        if (Build.VERSION.SDK_INT >= 34 && (Manifest.permission.READ_MEDIA_IMAGES in missing || Manifest.permission.READ_MEDIA_VIDEO in missing)) {
            missing += Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED
        }
        return missing.distinct().toTypedArray()
    }

    fun cancel() { querying?.cancel() }

    private fun version(volume: String): String = if (Build.VERSION.SDK_INT >= 29) {
        MediaStore.getVersion(context, volume).orEmpty()
    } else MediaStore.getVersion(context).orEmpty()

    private fun columns(): Array<String> = (listOf(
        MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE,
        MediaStore.MediaColumns.DATE_MODIFIED, MediaStore.MediaColumns.MIME_TYPE,
        if (Build.VERSION.SDK_INT >= 29) MediaStore.MediaColumns.RELATIVE_PATH else MediaStore.MediaColumns.DATA,
    ) + if (Build.VERSION.SDK_INT >= 30) listOf(MediaStore.MediaColumns.GENERATION_ADDED, MediaStore.MediaColumns.GENERATION_MODIFIED) else emptyList()).toTypedArray()

    private fun stamp(rows: Cursor, volume: String, version: String): String =
        "$volume:$version:${rows.getLong(0)}:${rows.getLong(2)}:${rows.getLong(3)}:" +
            if (Build.VERSION.SDK_INT >= 30) "${rows.getLong(6)}:${rows.getLong(7)}" else "legacy"

    private fun current(uri: Uri, volume: String, expected: String): Boolean {
        val before = version(volume)
        if (before.isEmpty()) return false
        val found = context.contentResolver.query(uri, columns(), null, null, null)?.use { rows ->
            rows.moveToFirst() && stamp(rows, volume, before) == expected
        } ?: false
        return found && version(volume) == before
    }

    fun scan(cancelled: () -> Boolean, onProblem: (String) -> Unit, onFound: (Int) -> Unit = {}): List<BackupMedia> {
        val results = mutableListOf<BackupMedia>()
        val volumes = if (Build.VERSION.SDK_INT >= 29) MediaStore.getExternalVolumeNames(context).sorted() else listOf("external")
        if (volumes.isEmpty()) onProblem("Nessuna memoria multimediale disponibile: controlla la memoria del telefono e le schede SD.")
        for (volume in volumes) for (type in listOf("image", "audio", "video")) {
            if (cancelled()) throw CancellationException()
            val signal = CancellationSignal()
            querying = signal
            try {
                val before = version(volume)
                if (before.isEmpty()) throw IOException("Memoria non disponibile")
                val collection = when (type) {
                    "image" -> MediaStore.Images.Media.getContentUri(volume)
                    "audio" -> MediaStore.Audio.Media.getContentUri(volume)
                    else -> MediaStore.Video.Media.getContentUri(volume)
                }
                val cursor = context.contentResolver.query(collection, columns(), null, null,
                    "${MediaStore.MediaColumns._ID} ASC", signal) ?: throw IOException("Elenco non leggibile")
                cursor.use { rows ->
                    while (rows.moveToNext()) {
                        if (cancelled()) throw CancellationException()
                        val id = rows.getLong(0)
                        val uri = ContentUris.withAppendedId(collection, id)
                        val identity = stamp(rows, volume, before)
                        val name = rows.getString(1).orEmpty().ifBlank { "media-$id" }
                        val path = rows.getString(5).orEmpty()
                        val folder = if (Build.VERSION.SDK_INT >= 29) path.trim('/') else
                            path.substringBeforeLast('/', "").removePrefix("/storage/").substringAfter('/', "").trim('/')
                        results += BackupMedia("$type:$volume:$id", name, folder, type, if (rows.isNull(2)) -1 else rows.getLong(2),
                            rows.getString(4).orEmpty().ifBlank { "$type/*" }, identity,
                            current = { current(uri, volume, identity) },
                            open = { openOriginal(context, uri, type) }, cacheable = Build.VERSION.SDK_INT >= 30)
                        onFound(results.size)
                    }
                }
                if (version(volume) != before) throw IOException("La memoria è cambiata durante la scansione: riprova")
            } catch (error: Exception) {
                if (cancelled()) throw CancellationException()
                onProblem("$type · $volume: ${error.message ?: "lettura non riuscita"}")
            } finally { querying = null }
        }
        return results
    }

    companion object {
        fun kind(mime: String, name: String): String? = BackupRules.kind(mime, name)

        /** No fallback to redacted or transcoded copies when the original was requested. */
        fun openOriginal(context: Context, uri: Uri, kind: String): InputStream {
            val convertible = uri.authority in setOf("com.android.providers.media.documents", "com.android.externalstorage.documents")
            val mediaUri = if (Build.VERSION.SDK_INT >= 29 && convertible && DocumentsContract.isDocumentUri(context, uri)) {
                MediaStore.getMediaUri(context, uri) ?: uri
            } else uri
            val original = if (Build.VERSION.SDK_INT >= 29 && kind in setOf("image", "video") && mediaUri.authority == MediaStore.AUTHORITY) {
                MediaStore.setRequireOriginal(mediaUri)
            } else mediaUri
            if (Build.VERSION.SDK_INT >= 31) {
                val extras = Bundle().apply { putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true) }
                val descriptor = context.contentResolver.openTypedAssetFileDescriptor(original, "*/*", extras)
                    ?: throw IOException("Originale non leggibile")
                try { return descriptor.createInputStream() } catch (error: Exception) { descriptor.close(); throw error }
            }
            return context.contentResolver.openInputStream(original) ?: throw IOException("Originale non leggibile")
        }
    }
}

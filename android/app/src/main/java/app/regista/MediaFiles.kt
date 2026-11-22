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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** One read-only source, either a MediaStore row or a granted SAF document. */
data class BackupMedia(
    val media: String, val name: String, val folder: String, val kind: String,
    val size: Long, val mime: String, val stamp: String,
    val current: () -> Boolean, val open: () -> InputStream,
    val cacheable: Boolean = false,
    val day: String = "", val uri: Uri? = null,
)

/** All granted image, audio and video collections, across mounted volumes; no album or music-only filter. */
class MediaFiles(private val context: Context,private val kinds:Set<String> = setOf("image","video","audio")) {
    @Volatile private var querying: CancellationSignal? = null

    fun missingPermissions(): Array<String> {
        val permissions = if (Build.VERSION.SDK_INT >= 33) mutableListOf<String>().apply {
            if ("image" in kinds) add(Manifest.permission.READ_MEDIA_IMAGES)
            if ("video" in kinds) add(Manifest.permission.READ_MEDIA_VIDEO)
            if ("audio" in kinds) add(Manifest.permission.READ_MEDIA_AUDIO)
        } else if(kinds.any { it in setOf("image","video","audio") }) mutableListOf(Manifest.permission.READ_EXTERNAL_STORAGE) else mutableListOf()
        if (Build.VERSION.SDK_INT >= 29 && kinds.any { it in setOf("image","video") }) permissions += Manifest.permission.ACCESS_MEDIA_LOCATION
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

    /** Resolve a portable catalog receipt directly, preserving volume and generation checks. */
    fun resolve(media:String,expected:String):Pair<Uri,String>? {
        val parts=media.split(':')
        if(parts.size!=3 || parts[0] !in setOf("image","video") || parts[2].toLongOrNull()==null) return null
        val volume=parts[1]
        if(Build.VERSION.SDK_INT>=29 && volume !in MediaStore.getExternalVolumeNames(context)) return null
        val base=if(parts[0]=="image") MediaStore.Images.Media.getContentUri(volume) else MediaStore.Video.Media.getContentUri(volume)
        val uri=ContentUris.withAppendedId(base,parts[2].toLong())
        return if(current(uri,volume,expected,parts[0])) Pair(uri,parts[0]) else null
    }

    private fun version(volume: String): String = if (Build.VERSION.SDK_INT >= 29) {
        MediaStore.getVersion(context, volume).orEmpty()
    } else "legacy"

    private fun columns(kind:String): Array<String> = (listOf(
        MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE,
        MediaStore.MediaColumns.DATE_MODIFIED, MediaStore.MediaColumns.MIME_TYPE,
        if (Build.VERSION.SDK_INT >= 29) MediaStore.MediaColumns.RELATIVE_PATH else MediaStore.MediaColumns.DATA,
    ) + (if (Build.VERSION.SDK_INT >= 30) listOf(MediaStore.MediaColumns.GENERATION_ADDED, MediaStore.MediaColumns.GENERATION_MODIFIED) else emptyList()) +
        if (kind in setOf("image","video")) listOf(MediaStore.Images.ImageColumns.DATE_TAKEN) else emptyList()).toTypedArray()

    private fun stamp(rows: Cursor, volume: String, version: String): String =
        "$volume:$version:${rows.getLong(0)}:${rows.getLong(2)}:${rows.getLong(3)}:" +
            if (Build.VERSION.SDK_INT >= 30) "${rows.getLong(6)}:${rows.getLong(7)}" else "legacy"

    private fun current(uri: Uri, volume: String, expected: String,kind:String): Boolean {
        val before = version(volume)
        if (before.isEmpty()) return false
        val found = context.contentResolver.query(uri, columns(kind), null, null, null)?.use { rows ->
            rows.moveToFirst() && stamp(rows, volume, before) == expected
        } ?: false
        return found && version(volume) == before
    }

    fun scan(cancelled: () -> Boolean, onProblem: (String) -> Unit, onFound: (Int) -> Unit = {}): List<BackupMedia> {
        val results = mutableListOf<BackupMedia>()
        val volumes = if (Build.VERSION.SDK_INT >= 29) MediaStore.getExternalVolumeNames(context).sorted() else listOf("external")
        if (volumes.isEmpty()) onProblem("Nessuna memoria multimediale disponibile: controlla la memoria del telefono e le schede SD.")
        for (volume in volumes) for (type in listOf("image", "audio", "video").filter { it in kinds }) {
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
                val cursor = context.contentResolver.query(collection, columns(type), null, null,
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
                        val dateColumn=rows.getColumnIndex(MediaStore.Images.ImageColumns.DATE_TAKEN)
                        val taken=if (dateColumn>=0 && !rows.isNull(dateColumn)) rows.getLong(dateColumn) else 0L
                        val day=SimpleDateFormat("yyyy-MM-dd",Locale.ROOT).format(Date(if (taken>0) taken else rows.getLong(3)*1000))
                        results += BackupMedia("$type:$volume:$id", name, folder, type, if (rows.isNull(2)) -1 else rows.getLong(2),
                            rows.getString(4).orEmpty().ifBlank { "$type/*" }, identity,
                            current = { current(uri, volume, identity,type) },
                            open = { openOriginal(context, uri, type) }, cacheable = Build.VERSION.SDK_INT >= 30,day=day,uri=uri)
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

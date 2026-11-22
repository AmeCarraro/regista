package app.regista

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import java.io.File

/** Temporary read access to one downloaded original, granted only to the viewer the user opens. */
class DocumentProvider:ContentProvider() {
    override fun onCreate()=true
    private fun file(uri:Uri):File {
        val parts=uri.pathSegments
        require(parts.size==2 && parts[0].matches(Regex("[a-f0-9]{64}")))
        val root=File(context!!.cacheDir,"received-documents").canonicalFile
        val file=File(File(root,parts[0]),parts[1]).canonicalFile
        require(file.parentFile?.parentFile==root && file.parentFile?.name==parts[0] && file.isFile)
        return file
    }
    override fun getType(uri:Uri):String=MimeTypeMap.getSingleton().getMimeTypeFromExtension(file(uri).extension.lowercase()) ?: "application/octet-stream"
    override fun query(uri:Uri,projection:Array<out String>?,selection:String?,args:Array<out String>?,sort:String?):Cursor {
        val file=file(uri)
        val columns=projection ?: arrayOf(OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE)
        return MatrixCursor(columns).apply { addRow(columns.map { when(it) { OpenableColumns.DISPLAY_NAME -> file.name; OpenableColumns.SIZE -> file.length(); else -> null } }) }
    }
    override fun openFile(uri:Uri,mode:String):ParcelFileDescriptor {
        require(mode=="r")
        return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.MODE_READ_ONLY)
    }
    override fun insert(uri:Uri,values:ContentValues?):Uri?=throw UnsupportedOperationException()
    override fun delete(uri:Uri,selection:String?,args:Array<out String>?):Int=throw UnsupportedOperationException()
    override fun update(uri:Uri,values:ContentValues?,selection:String?,args:Array<out String>?):Int=throw UnsupportedOperationException()
}

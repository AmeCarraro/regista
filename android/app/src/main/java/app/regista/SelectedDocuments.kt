package app.regista

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import org.json.JSONObject
import java.security.MessageDigest

/** Individually selected documents, with persistable read grants and stable provider identities. */
class SelectedDocuments(private val context:Context) {
    private val settings=context.getSharedPreferences("selected-documents",Context.MODE_PRIVATE)
    private fun hash(value:String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString(""){"%02x".format(it)}
    private fun info(uri:Uri):JSONObject? =context.contentResolver.query(uri,arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME,
        DocumentsContract.Document.COLUMN_SIZE,DocumentsContract.Document.COLUMN_LAST_MODIFIED),null,null,null)?.use { rows ->
        if(!rows.moveToFirst()) null else JSONObject().put("name",rows.getString(0).orEmpty()).put("size",if(rows.isNull(1)) -1L else rows.getLong(1))
            .put("modified",if(rows.isNull(2)) 0L else rows.getLong(2)) }
    fun add(uris:List<Uri>):List<String> {
        val ids=mutableListOf<String>()
        val edit=settings.edit()
        for(uri in uris) {
            require(uri.scheme=="content")
            val item=info(uri) ?: continue
            if(BackupRules.kind(context.contentResolver.getType(uri).orEmpty(),item.getString("name"))!="document") continue
            context.contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION)
            val id="document:"+hash(uri.toString())
            edit.putString(id,uri.toString()); ids+=id
        }
        check(edit.commit()) { "Non riesco a salvare la selezione." }
        return ids
    }
    fun scan(onProblem:(String)->Unit):List<BackupMedia> =settings.all.mapNotNull { (id,value) ->
        try {
            val uri=Uri.parse(value as String)
            val row=info(uri) ?: throw java.io.IOException("Documento non leggibile")
            val stamp=hash(row.toString())
            val folder=runCatching { DocumentsContract.getDocumentId(uri).substringBeforeLast('/',"") }.getOrDefault("")
            val modified=row.getLong("modified")
            BackupMedia(id,row.getString("name"),folder,"document",row.getLong("size"),context.contentResolver.getType(uri).orEmpty(),stamp,
                current={runCatching { info(uri)?.let { hash(it.toString()) }==stamp }.getOrDefault(false)},
                open={context.contentResolver.openInputStream(uri) ?: throw java.io.IOException("Originale non leggibile")},
                day=if(modified>0) java.text.SimpleDateFormat("yyyy-MM-dd",java.util.Locale.ROOT).format(java.util.Date(modified)) else "",uri=uri)
        } catch(error:Exception) { onProblem("Documento selezionato: ${error.message.orEmpty()}"); null }
    }
}

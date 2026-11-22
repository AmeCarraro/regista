package app.regista

import android.app.Activity
import android.content.Intent
import android.net.Uri
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class RemoteDocuments(private val app:MainActivity,private val tell:(String)->Unit) {
    private val busy=AtomicBoolean(false)
    private val settings=app.getSharedPreferences("document-download",Activity.MODE_PRIVATE)
    fun take(computer:Computer,sha:String,download:Boolean) {
        if(!sha.matches(Regex("[a-f0-9]{64}")) || !busy.compareAndSet(false,true)) return
        thread(name="original document") {
            var temporary:File?=null
            try {
                tell("Scarico e verifico il documento originale dal PC…")
                val info=computer.ask("GET","/api/documents/$sha")
                val name=info.getString("name").replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"),"_").trim('.',' ').take(180).ifBlank { "documento" }
                val directory=File(app.cacheDir,"received-documents/$sha").apply { mkdirs() }
                val target=File(directory,name)
                val temp=File.createTempFile("download-",".part",directory); temporary=temp
                val expectedSize=info.getLong("size")
                val verified=computer.fetch("/api/documents/$sha/file") { input,expected ->
                    if(expected!=sha) throw IOException("Identità del documento non corrispondente.")
                    val digest=MessageDigest.getInstance("SHA-256")
                    var size=0L
                    FileOutputStream(temp).use { output ->
                        val buffer=ByteArray(256*1024)
                        while(true) {
                            val count=input.read(buffer); if(count<0) break
                            size+=count; if(size>expectedSize) throw IOException("Documento più grande del previsto.")
                            digest.update(buffer,0,count); output.write(buffer,0,count)
                        }
                        output.fd.sync()
                    }
                    size==expectedSize && digest.digest().joinToString(""){"%02x".format(it)}==sha
                }
                if(!verified) throw IOException("Documento incompleto o SHA diverso. Riprova il download.")
                android.system.Os.rename(temp.path,target.path)
                app.runOnUiThread {
                    try {
                        val uri=Uri.Builder().scheme("content").authority(app.packageName+".documents").appendPath(sha).appendPath(name).build()
                        val mime=app.contentResolver.getType(uri) ?: "application/octet-stream"
                        if(download) {
                            settings.edit().putString("source",target.path).putString("sha",sha).commit()
                            app.startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                                .setType(mime).putExtra(Intent.EXTRA_TITLE,name),SAVE)
                        } else app.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri,mime).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
                    } catch(error:Exception) { tell("Originale verificato. Usa Scarica se non hai un’app per aprirlo: ${error.message.orEmpty()}") }
                }
            } catch(error:Exception) { tell("Documento non scaricato: ${error.message.orEmpty()}") }
            finally { temporary?.delete(); busy.set(false) }
        }
    }
    fun saved(result:Int,uri:Uri?) {
        val source=settings.getString("source",null) ?: return
        val sha=settings.getString("sha",null) ?: return
        settings.edit().clear().commit()
        if(result!=Activity.RESULT_OK || uri==null) return
        thread(name="save original document") {
            try {
                val file=File(source).canonicalFile
                val root=File(app.cacheDir,"received-documents").canonicalFile
                require(file.parentFile?.parentFile==root && file.parentFile?.name==sha)
                val digest=MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input -> app.contentResolver.openOutputStream(uri,"w")?.use { output ->
                    val buffer=ByteArray(65536)
                    while(true) { val size=input.read(buffer); if(size<0) break; digest.update(buffer,0,size); output.write(buffer,0,size) }
                } ?: throw IOException("Destinazione non scrivibile.") }
                check(digest.digest().joinToString(""){"%02x".format(it)}==sha)
                tell("Documento originale salvato nella posizione scelta.")
            } catch(error:Exception) { tell("Salvataggio non completato: ${error.message.orEmpty()}") }
        }
    }
    companion object { const val SAVE=45 }
}

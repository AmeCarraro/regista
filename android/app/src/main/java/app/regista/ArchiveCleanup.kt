package app.regista

import android.app.Activity
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** A PC ZIP proposal can only reach Android's system trash dialog after fresh SHA checks on both sides. */
class ArchiveCleanup(private val app:MainActivity,private val memory:Memory,private val tell:(String)->Unit) {
    private val settings=app.getSharedPreferences("archive-cleanup",Context.MODE_PRIVATE)
    private val busy=AtomicBoolean(false)
    @Volatile private var scanning:MediaFiles?=null
    @Volatile private var enabled=false
    @Volatile private var last=0L
    private fun stopped(peer:String)=!enabled || !memory.paired || memory.fingerprint!=peer
    fun start() { enabled=true }
    fun stop() { enabled=false; scanning?.cancel() }

    fun poll(computer:Computer?) {
        if(computer==null || !enabled || PhotoImportService.running || Build.VERSION.SDK_INT<30) return
        if(System.currentTimeMillis()-last<4000 || !busy.compareAndSet(false,true)) return
        last=System.currentTimeMillis()
        val peer=memory.fingerprint
        thread(name="ZIP originals check") {
            try {
                val pending=settings.getString("pending",null)?.let(::JSONObject)
                if(pending!=null) {
                    if(pending.optString("peer")!=peer) return@thread
                    if(pending.optString("phase")=="result") report(computer,pending)
                    // A launched Android question must receive its own activity result, never an automatic yes.
                    return@thread
                }
                val job=computer.ask("GET","/phone/import-cleanup").optJSONObject("job") ?: return@thread
                if(stopped(peer)) return@thread
                when(job.getString("state")) {
                    "finding" -> match(computer,job,peer)
                    "approved" -> authorize(computer,job,peer)
                }
            } catch(error:Exception) {
                if(error is Refused && error.status in setOf(404,409) && settings.getString("pending",null)?.let { JSONObject(it).optString("phase")=="result" }==true)
                    settings.edit().remove("pending").commit()
                if(!stopped(peer)) tell("Verifica originali: ${error.message.orEmpty()}")
            } finally { scanning=null; busy.set(false) }
        }
    }

    private fun sources(peer:String):List<BackupMedia> {
        val scanner=MediaFiles(app,setOf("image","video"))
        scanning=scanner
        if(scanner.missingPermissions().isNotEmpty()) throw IOException("Concedi l’accesso completo a foto e video per verificare gli originali.")
        val warnings=mutableListOf<String>()
        val files=scanner.scan({stopped(peer)},{warnings+=it})
        if(warnings.isNotEmpty()) throw IOException(warnings.first())
        return files
    }

    private fun digest(item:BackupMedia,peer:String):String? {
        if(stopped(peer) || item.uri==null || !item.current()) return null
        val hashed=BackupRules.hash(item.open(),{stopped(peer)})
        return if(!stopped(peer) && item.current() && (item.size<0 || hashed.bytes==item.size)) hashed.sha256 else null
    }

    private fun match(computer:Computer,job:JSONObject,peer:String) {
        val allowed=job.getJSONArray("allowed").let { values -> (0 until values.length()).map { values.getString(it) }.toSet() }
        val found=JSONArray()
        val files=sources(peer)
        for((index,item) in files.withIndex()) {
            if(stopped(peer)) return
            if(index%20==0) tell("Controllo originali dello ZIP: ${index+1} / ${files.size}. Nessun file viene eliminato.")
            val sha=try { digest(item,peer) } catch(_:IOException) { null }
            if(sha!=null && sha in allowed) found.put(JSONObject().put("media",item.media).put("stamp",item.stamp)
                .put("sha256",sha).put("name",item.name).put("folder",item.folder).put("kind",item.kind))
        }
        if(stopped(peer)) return
        computer.ask("POST","/phone/import-cleanup/matched",JSONObject().put("job_id",job.getString("id")).put("files",found))
        tell("Trovati ${found.length()} originali dello ZIP. Controlla l’anteprima e conferma sul PC.")
    }

    private fun authorize(computer:Computer,job:JSONObject,peer:String) {
        val expected=job.getJSONArray("files")
        if(expected.length()==0) {
            computer.ask("POST","/phone/import-cleanup/result",JSONObject().put("job_id",job.getString("id")).put("media",JSONArray()).put("done",true))
            return
        }
        val current=sources(peer).associateBy { it.media }
        val files=JSONArray()
        val uris=mutableListOf<Uri>()
        for(index in 0 until minOf(200,expected.length())) {
            val original=expected.getJSONObject(index)
            val item=current[original.getString("media")] ?: throw IOException("Un originale non è più disponibile. Annulla sul PC e ricontrolla il blocco.")
            if(item.stamp!=original.getString("stamp") || digest(item,peer)!=original.getString("sha256"))
                throw IOException("${item.name} è cambiato. Nessuna eliminazione autorizzata per questo gruppo.")
            files.put(original.put("uri",item.uri.toString()))
            uris+=item.uri!!
        }
        if(stopped(peer)) return
        val ids=JSONArray((0 until files.length()).map { files.getJSONObject(it).getString("media") })
        val approval=computer.ask("POST","/phone/import-cleanup/authorize",JSONObject().put("job_id",job.getString("id")).put("media",ids))
        if(!approval.optBoolean("authorized") || !approval.optBoolean("requires_android_confirmation")) throw IOException("Manca la conferma del PC.")
        // Check identity again after the potentially long PC ZIP verification.
        if(files.let { (0 until it.length()).any { i -> current[it.getJSONObject(i).getString("media")]?.current()!=true } })
            throw IOException("Un originale è cambiato durante la verifica del PC.")
        val pending=JSONObject().put("job",job.getString("id")).put("peer",peer).put("files",files)
            .put("phase","question").put("last",files.length()==expected.length())
        app.runOnUiThread {
            if(stopped(peer) || settings.contains("pending")) return@runOnUiThread
            try {
                val question=MediaStore.createTrashRequest(app.contentResolver,uris,true)
                settings.edit().putString("pending",pending.toString()).commit()
                app.startIntentSenderForResult(question.intentSender,REQUEST,null,0,0,0)
            } catch(error:Exception) {
                settings.edit().remove("pending").commit()
                tell("Gli originali restano sul telefono: ${error.message.orEmpty()}")
            }
        }
    }

    fun answered(result:Int) {
        val pending=settings.getString("pending",null)?.let(::JSONObject) ?: return
        pending.put("phase","result").put("yes",result==Activity.RESULT_OK)
        settings.edit().putString("pending",pending.toString()).commit()
        last=0
        tell(if(result==Activity.RESULT_OK) "Android ha confermato il cestino. Verifico il risultato." else "Hai annullato: gli originali restano sul telefono.")
    }

    /** Restore safely after activity/process recreation: inspect the result; never relaunch a saved approval. */
    fun recover() {
        val pending=settings.getString("pending",null)?.let(::JSONObject) ?: return
        if(pending.optString("phase")=="question") {
            pending.put("phase","result").put("yes",false)
            settings.edit().putString("pending",pending.toString()).commit()
        }
    }

    private fun report(computer:Computer,pending:JSONObject) {
        val files=pending.getJSONArray("files")
        val trashed=JSONArray()
        for(index in 0 until files.length()) {
            val file=files.getJSONObject(index)
            val uri=Uri.parse(file.getString("uri"))
            val options=Bundle().apply { putInt(MediaStore.QUERY_ARG_MATCH_TRASHED,MediaStore.MATCH_INCLUDE) }
            val gone=app.contentResolver.query(uri,arrayOf(MediaStore.MediaColumns.IS_TRASHED),options,null)?.use { rows ->
                rows.moveToFirst() && rows.getInt(0)==1
            } ?: false
            if(gone) trashed.put(file.getString("media"))
        }
        val yes=pending.optBoolean("yes")
        computer.ask("POST","/phone/import-cleanup/result",JSONObject().put("job_id",pending.getString("job"))
            .put("media",trashed).put("cancelled",!yes || trashed.length()!=files.length())
            .put("done",yes && pending.optBoolean("last") && trashed.length()==files.length())
            .put("error",if(yes && trashed.length()!=files.length()) "Alcuni file non risultano nel cestino. Le copie sul PC restano conservate." else ""))
        settings.edit().remove("pending").commit()
        tell("${trashed.length()} originali verificati nel cestino Android. Copie normali, catalogo e ZIP restano sul PC.")
    }

    companion object { const val REQUEST=43 }
}

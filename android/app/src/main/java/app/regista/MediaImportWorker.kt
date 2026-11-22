package app.regista

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.CancellationException
import javax.net.ssl.HttpsURLConnection
import kotlin.concurrent.thread

class ImportNeedsUser(message:String):Exception(message)

/** Streams originals; the PC publishes one final ZIP only after every selected media item is confirmed. */
class MediaImportWorker(private val context:Context,private val memory:Memory,private val store:PhotoImportStore,
    private val work:String,private val found:(Computer?)->Unit) {
    @Volatile private var stopped=false
    @Volatile private var connection:HttpsURLConnection?=null
    private val peer=store.read().peer
    private var scanner:MediaFiles?=null
    private val routes=ImportConnections(memory,::changed,::cancelled)
    private fun value()=store.read()
    private fun cancelled()=stopped || !memory.paired || peer!=memory.fingerprint
    private fun check() { if (cancelled()) throw CancellationException() }
    fun cancel() {
        stopped=true
        scanner?.cancel()
        val active=connection
        if (active!=null) thread(name="disconnect media import") { active.disconnect() }
    }
    private fun changed(next:HttpsURLConnection?) {
        connection=next
        if (next!=null && cancelled()) { next.disconnect(); throw CancellationException() }
    }
    private fun phase(phase:String,message:String) { store.update(work) { it.copy(phase=phase,message=message) } }
    private fun failed(media:String,message:String) { store.update(work) { it.confirmed(media,ImportOutcome.FAILED).copy(message=message) } }
    private fun confirm(media:String,outcome:String) {
        store.update(work) { it.confirmed(media,if(outcome=="copied") ImportOutcome.COPIED else ImportOutcome.DUPLICATE) }
    }
    private data class Hashed(val item:BackupMedia,val digest:BackupRules.Digest)

    fun once():Boolean {
        check()
        phase("waiting","Cerco il PC: provo prima la rete USB disponibile.")
        var selected=routes.choose() ?: return false
        found(selected.computer)
        store.update(work) { it.copy(transport=selected.transport) }
        val kinds=when(value().scope) { "documents" -> setOf("document"); "all-media" -> setOf("image","video","audio","document"); else -> setOf("image","video") }
        val scan=MediaFiles(context,kinds)
        scanner=scan
        val needSources=!value().prepared || value().remaining.isNotEmpty()
        val all=if(needSources) {
            if(scan.missingPermissions().isNotEmpty()) throw ImportNeedsUser("Concedi l’accesso a foto e video nelle impostazioni, poi premi Riprendi importazione.")
            phase("scanning","Leggo le raccolte e le cartelle autorizzate.")
            val warnings=mutableListOf<String>()
            val listed=if(kinds.any { it in setOf("image","video","audio") }) scan.scan(::cancelled,{ warnings+=it }) else emptyList()
            val extra=BackupFolders(context).scan(::cancelled,{ warnings+=it }).filter { it.kind in kinds }
            val documents=if("document" in kinds) SelectedDocuments(context).scan { warnings+=it } else emptyList()
            if(warnings.isNotEmpty()) throw ImportNeedsUser(warnings.take(3).joinToString("; "))
            (listed+extra+documents).distinctBy { it.media }.sortedWith(compareBy<BackupMedia> { it.day }.thenBy { it.media })
        } else emptyList()
        check()
        store.update(work) { it.prepare(all.map { item->item.media }) }
        val byId=all.associateBy { it.media }
        for(id in value().remaining) if(id !in byId) failed(id,"Un file del blocco non è più accessibile: $id")
        if(value().groups.isEmpty() && value().remaining.isNotEmpty()) {
            if(value().remaining.any { it !in byId }) throw ImportNeedsUser("Alcuni file selezionati non sono più accessibili. Controlla cartelle e permessi, poi riprendi.")
            store.update(work) { state ->
                val members=state.remaining.associateWith { id -> byId.getValue(id).let { ImportGroups.key(it.folder,it.kind,it.name) } }
                state.copy(members=members,groups=members.values.groupingBy { it }.eachCount())
            }
        }
        if(value().request.isEmpty() && value().scope!="documents") {
            val pendingRequest=selected.computer.ask("GET","/phone/catalog/import-request",connectionChanged=::changed).optString("request_id")
            if(pendingRequest.isNotEmpty()) store.update(work) { it.copy(request=pendingRequest) }
        }
        for(group in value().groups.keys.sorted()) {
            if(group in value().finishedGroups) continue
            phase("starting","Preparo ${ImportGroups.label(group)}.")
            selected=importGroup(selected,group,byId)
            progress(selected.computer,false)
        }
        check()
        if(value().remaining.isNotEmpty()) throw ImportNeedsUser("Restano file da verificare. Le copie già confermate rimangono salvate; premi Riprendi.")
        progress(selected.computer,true)
        store.update(work) { it.copy(requested=false,phase="done",failed=0,failedMedia=emptyList(),
            message="Importazione completata. ${it.finishedGroups.size} blocchi verificati. Gli eventuali nuovi ZIP sono sul PC.") }
        return true
    }

    private fun progress(computer:Computer,done:Boolean) {
        val state=value()
        if(state.request.isEmpty() || state.scope=="documents") return
        computer.ask("POST","/phone/catalog/progress",JSONObject().put("request_id",state.request).put("total",state.total)
            .put("copied",state.copied).put("duplicates",state.duplicates).put("done",done),connectionChanged=::changed)
    }

    private fun importGroup(initial:ImportConnection,group:String,byId:Map<String,BackupMedia>):ImportConnection {
        var selected=initial
        val starting=value()
        val scope=if(group.contains("-documents-")) "documents" else if(starting.scope=="all-media") "all-media" else "photos-videos"
        val started=selected.computer.ask("POST","/phone/imports/start",JSONObject().put("work_id",work)
            .put("work_id",work+"-"+group).put("source",group.substringBefore('-'))
            .put("document_type",if(scope=="documents") group.substringAfter("-documents-") else "")
            .put("request_id",starting.request).put("scope",scope).put("total",starting.groups.getValue(group)).put("transport",selected.transport),connectionChanged=::changed)
        if(started.optInt("protocol")!=2) throw ImportNeedsUser("Il PC non supporta i nuovi archivi per blocco.")
        val batch=started.getString("id")
        store.update(work) { it.copy(batch=batch,batches=it.batches+(group to batch)) }
        if(started.optBoolean("zip_ready")) {
            if(value().remaining.any { value().members[it]==group }) throw ImportNeedsUser("Il blocco risulta chiuso sul PC ma mancano conferme sul telefono. Controlla lo stato prima di continuare.")
            finishGroup(group); return selected
        }
        val pending=value().remaining.filter { value().members[it]==group }
        for(ids in pending.chunked(100)) {
            check()
            routes.choose(usbOnly=true)?.let { selected=it; found(it.computer); store.update(work) { state->state.copy(transport=it.transport) } }
            val hashed=mutableListOf<Hashed>()
            for(id in ids) {
                check()
                val item=byId[id] ?: continue
                phase("hashing",item.name)
                try {
                    if(!item.current()) throw ImportNeedsUser("${item.name} è cambiato: riprova la selezione.")
                    val digest=BackupRules.hash(item.open(),::cancelled)
                    if(!item.current() || (item.size>=0 && item.size!=digest.bytes)) throw ImportNeedsUser("${item.name} è cambiato durante la lettura.")
                    hashed+=Hashed(item,digest)
                } catch(error:Exception) {
                    if(cancelled() || error is CancellationException) throw CancellationException()
                    failed(id,"${item.name}: ${error.message.orEmpty()}")
                }
            }
            if(hashed.isEmpty()) continue
            val manifest=JSONArray()
            for((item,digest) in hashed) manifest.put(JSONObject().put("media",item.media).put("stamp",item.stamp)
                .put("sha256",digest.sha256).put("name",item.name).put("folder",item.folder).put("kind",item.kind)
                .put("size",digest.bytes).put("mime",item.mime).put("day",item.day))
            val answer=selected.computer.ask("POST","/phone/imports/manifest",JSONObject().put("batch_id",batch).put("files",manifest).put("transport",selected.transport),connectionChanged=::changed)
            val wantedJson=answer.getJSONArray("wanted")
            val wanted=(0 until wantedJson.length()).map { wantedJson.getString(it) }.toSet()
            if(!wanted.all { id->hashed.any { it.item.media==id } }) throw ImportNeedsUser("Il PC ha richiesto file fuori dalla selezione.")
            val confirmed=answer.getJSONObject("confirmed")
            for(entry in hashed) if(confirmed.has(entry.item.media)) {
                if(entry.item.current()) confirm(entry.item.media,confirmed.getString(entry.item.media))
                else failed(entry.item.media,"Un file è cambiato dopo la verifica.")
            }
            for(group in hashed.filter { it.item.media in wanted }.groupBy { it.digest.sha256 }.values) {
                check()
                val selectedFile=group.first()
                val item=selectedFile.item
                if(!item.current()) { failed(item.media,"${item.name} è cambiato prima dell’invio."); continue }
                phase("uploading",item.name)
                val input=BackupRules.Sending(item.open(),::cancelled,{})
                val result=input.use { selected.computer.send("/phone/imports/upload?batch_id=${Uri.encode(batch)}&media=${Uri.encode(item.media)}",
                    selectedFile.digest.bytes,it,selectedFile.digest.sha256,connectionChanged=::changed) }
                if(!result.optBoolean("kept") || result.optString("id")!=selectedFile.digest.sha256) throw IOException("Il PC non ha confermato il file.")
                val outcomes=result.getJSONObject("confirmed")
                for(entry in group) {
                    if(!entry.item.current()) { failed(entry.item.media,"${entry.item.name} è cambiato durante l’invio."); continue }
                    if(!outcomes.has(entry.item.media)) throw IOException("Conferma incompleta del PC.")
                    confirm(entry.item.media,outcomes.getString(entry.item.media))
                }
            }
        }
        check()
        if(value().remaining.any { value().members[it]==group }) throw ImportNeedsUser("Restano file da verificare in ${ImportGroups.label(group)}. Le copie confermate restano salvate; premi Riprendi per riprovare.")
        phase("finalizing","Il PC sta creando e verificando lo ZIP: ${ImportGroups.label(group)}. Puoi tenere spento lo schermo.")
        var status=selected.computer.ask("POST","/phone/imports/finalize",JSONObject().put("batch_id",batch),connectionChanged=::changed)
        while(!status.optBoolean("zip_ready")) {
            check()
            if(status.optString("state")=="error") throw ImportNeedsUser(status.optString("error","ZIP non verificato."))
            Thread.sleep(2000)
            status=selected.computer.ask("GET","/phone/imports/status?batch_id=${Uri.encode(batch)}",connectionChanged=::changed)
        }
        finishGroup(group)
        return selected
    }
    private fun finishGroup(group:String) { store.update(work) { it.copy(finishedGroups=it.finishedGroups+group) } }
}

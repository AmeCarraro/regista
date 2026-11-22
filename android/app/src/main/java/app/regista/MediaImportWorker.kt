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
    private val kinds = when (store.read().scope) {
        "documents" -> setOf("document")
        "all-media" -> setOf("image", "video", "audio", "document")
        else -> setOf("image", "video")
    }
    private val scanner = MediaFiles(context, kinds)
    private val folders = BackupFolders(context)
    private val documents = SelectedDocuments(context)
    private val inventory = ImportInventory.open(context)
    private val routes=ImportConnections(memory,::changed,::cancelled)
    private fun value()=store.read()
    private fun cancelled()=stopped || !memory.paired || peer!=memory.fingerprint
    private fun check() { if (cancelled()) throw CancellationException() }
    fun cancel() {
        stopped=true
        scanner.cancel()
        val active=connection
        if (active!=null) thread(name="disconnect media import") { active.disconnect() }
    }
    private fun changed(next:HttpsURLConnection?) {
        connection=next
        if (next!=null && cancelled()) { next.disconnect(); throw CancellationException() }
    }
    private fun phase(phase:String,message:String) { store.update(work) { it.copy(phase=phase,message=message) } }
    private data class Hashed(val item:BackupMedia,val digest:BackupRules.Digest)

    fun once():Boolean {
        check()
        phase("waiting","Cerco il PC: provo prima la rete USB disponibile.")
        var selected=routes.choose() ?: return false
        found(selected.computer)
        store.update(work) { it.copy(transport=selected.transport) }
        if (scanner.missingPermissions().isNotEmpty()) {
            throw ImportNeedsUser("Concedi l’accesso ai file nelle impostazioni, poi premi Riprendi importazione.")
        }
        inventory.begin(work)
        prepareSelection()
        check()
        if(value().request.isEmpty() && value().scope!="documents") {
            val pendingRequest=selected.computer.ask("GET","/phone/catalog/import-request",connectionChanged=::changed).optString("request_id")
            if(pendingRequest.isNotEmpty()) store.update(work) { it.copy(request=pendingRequest) }
        }
        for(group in value().groups.keys.sorted()) {
            if(group in value().finishedGroups) continue
            phase("starting","Preparo ${ImportGroups.label(group)}.")
            selected=importGroup(selected,group)
            progress(selected.computer,false)
        }
        check()
        if(value().remaining.isNotEmpty()) throw ImportNeedsUser("Restano file da verificare. Le copie già confermate rimangono salvate; premi Riprendi.")
        progress(selected.computer,true)
        store.update(work) { it.copy(requested=false,phase="done",failed=0,failedMedia=emptyList(),
            message="Importazione completata. ${it.finishedGroups.size} blocchi verificati. Gli eventuali nuovi ZIP sono sul PC.") }
        return true
    }

    private fun prepareSelection() {
        val initial = value()
        if (initial.prepared && (initial.groups.isNotEmpty() || initial.remaining.isEmpty())) {
            // Older versions saved the fixed selection before keeping a durable folder inventory.
            if (initial.remaining.any { it.startsWith("tree:") } && (inventory.needsFolderRoots() || inventory.nextFolder() != null)) {
                phase("scanning", "Recupero i riferimenti alle cartelle del blocco esistente.")
                folders.scanResumable(inventory, kinds, ::cancelled) { count ->
                    phase("scanning", "$count riferimenti alle cartelle salvati per riprendere la copia.")
                }
            }
            return
        }
        val individual = initial.prepared && initial.scope == "documents" && initial.remaining.all { it.startsWith("document:") }
        fun found(count: Int) = phase("scanning", "$count file trovati nelle raccolte e nelle cartelle autorizzate.")
        found(inventory.size())
        val warnings = mutableListOf<String>()
        if (!individual) {
            if (kinds.any { it in setOf("image", "video", "audio") }) scanner.scan(::cancelled, { warnings += it }, inventory, ::found)
            if (warnings.isNotEmpty()) throw ImportNeedsUser(warnings.take(3).joinToString("\n"))
            folders.scanResumable(inventory, kinds, ::cancelled, ::found)
        }
        if ("document" in kinds && !inventory.selectedDocumentsRecorded()) {
            val chosen = if (individual) initial.remaining.map { id ->
                documents.lookup(id) ?: throw ImportNeedsUser("Un documento selezionato non è più accessibile.")
            } else documents.scan { warnings += it }
            if (warnings.isNotEmpty()) throw ImportNeedsUser(warnings.take(3).joinToString("\n"))
            check()
            inventory.saveDocuments(chosen.map { ImportInventory.Source(it) })
        }
        check()
        val listed = inventory.selection()
        val members = if (initial.prepared) {
            val byId = listed.associateBy { it.media }
            initial.remaining.associateWith { id ->
                byId[id]?.group ?: throw ImportNeedsUser("Un file della selezione non è più accessibile.")
            }
        } else listed.associate { it.media to it.group }
        store.update(work) {
            it.prepare(members.keys.toList()).copy(members = members, groups = members.values.groupingBy { group -> group }.eachCount())
        }
    }

    private fun progress(computer:Computer,done:Boolean) {
        val state=value()
        if(state.request.isEmpty() || state.scope=="documents") return
        computer.ask("POST","/phone/catalog/progress",JSONObject().put("request_id",state.request).put("total",state.total)
            .put("copied",state.copied).put("duplicates",state.duplicates).put("done",done),connectionChanged=::changed)
    }

    private fun importGroup(initial:ImportConnection,group:String):ImportConnection {
        var selected=initial
        val starting=value()
        val scope=if(group.contains("-documents-")) "documents" else if(starting.scope=="all-media") "all-media" else "photos-videos"
        val started=selected.computer.ask("POST","/phone/imports/start",JSONObject()
            .put("work_id",work+"-"+group).put("source",group.substringBefore('-'))
            .put("document_type",if(scope=="documents") group.substringAfter("-documents-") else "")
            .put("request_id",starting.request).put("scope",scope).put("total",starting.groups.getValue(group)).put("transport",selected.transport),connectionChanged=::changed)
        if(started.optInt("protocol")!=2) throw ImportNeedsUser("Il PC non supporta i nuovi archivi per blocco.")
        val batch=started.getString("id")
        store.update(work) { it.copy(batch=batch,batches=it.batches+(group to batch)) }
        val pending = starting.remaining.filter { starting.members[it] == group }
        if(started.optBoolean("zip_ready")) {
            if(pending.isNotEmpty()) throw ImportNeedsUser("Il blocco risulta chiuso sul PC ma mancano conferme sul telefono. Controlla lo stato prima di continuare.")
            finishGroup(group); return selected
        }
        for(ids in pending.chunked(100)) {
            check()
            routes.choose(usbOnly=true)?.let { selected=it; found(it.computer); store.update(work) { state->state.copy(transport=it.transport) } }
            transferChunk(selected, batch, ids)
        }
        check()
        val checkpoint = value()
        if(checkpoint.remaining.any { checkpoint.members[it]==group }) throw ImportNeedsUser("Restano file da verificare in ${ImportGroups.label(group)}. Le copie confermate restano salvate; premi Riprendi per riprovare.")
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

    private fun transferChunk(selected: ImportConnection, batch: String, ids: List<String>) {
        val recorded = mutableMapOf<String, ImportOutcome>()
        val stamps = inventory.stamps(ids)
        var warning = ""
        fun failed(media: String, message: String) {
            recorded[media] = ImportOutcome.FAILED
            warning = message
        }
        fun confirm(media: String, outcome: String) {
            recorded[media] = if (outcome == "copied") ImportOutcome.COPIED else ImportOutcome.DUPLICATE
        }
        try {
            phase("hashing", "Verifico i contenuti di ${ids.size} file.")
            val hashed=mutableListOf<Hashed>()
            for(id in ids) {
                check()
                try {
                    val expected = stamps[id]
                    val item = when {
                        id.startsWith("tree:") -> folders.importItem(id, expected)
                        id.startsWith("document:") -> documents.lookup(id, expected)
                        else -> scanner.lookup(id, expected)
                    }
                    if (item == null) throw ImportNeedsUser("Un file della selezione è cambiato o non è più accessibile.")
                    if(!item.current()) throw ImportNeedsUser("${item.name} è cambiato: riprova la selezione.")
                    val digest=BackupRules.hash(item.open(),::cancelled)
                    if(!item.current() || (item.size>=0 && item.size!=digest.bytes)) throw ImportNeedsUser("${item.name} è cambiato durante la lettura.")
                    hashed+=Hashed(item,digest)
                } catch(error:Exception) {
                    if(cancelled() || error is CancellationException) throw CancellationException()
                    failed(id, error.message ?: "Un file della selezione non è leggibile.")
                }
            }
            if (hashed.isEmpty()) throw ImportNeedsUser(warning.ifBlank { "I file del gruppo non sono leggibili." })
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
            if (wanted.isNotEmpty()) phase("uploading", "Copio i file che mancano sul PC.")
            for(group in hashed.filter { it.item.media in wanted }.groupBy { it.digest.sha256 }.values) {
                check()
                val selectedFile=group.first()
                val item=selectedFile.item
                if(!item.current()) { failed(item.media,"${item.name} è cambiato prima dell’invio."); continue }
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
        } finally {
            // The PC keeps each verified receipt. On retry it confirms any file committed since the last phone checkpoint.
            if (recorded.isNotEmpty()) store.update(work) {
                val next = it.confirmed(recorded)
                if (warning.isEmpty()) next else next.copy(message = warning)
            }
        }
    }
    private fun finishGroup(group:String) { store.update(work) { it.copy(finishedGroups=it.finishedGroups+group) } }
}

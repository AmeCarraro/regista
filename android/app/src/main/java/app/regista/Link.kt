package app.regista

import android.os.Build
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock

/**
 * Keeps the phone and the computer in step while the app is open. It finds the computer,
 * tells it which pictures the phone has and sends a small copy of the ones it does not
 * know, and takes back what the computer read in them; then it waits for requests, and
 * sends the originals the user asked for.
 *
 * Nothing here changes or deletes a picture. When the user asked to take pictures off the
 * phone, and the computer says their copies are safely there, the question goes to Android,
 * which asks the user and moves them to the phone's trash itself.
 */
class Link(
    private val memory: Memory,
    private val gallery: Gallery,
    private val sight: Sight,
    private val library: Library,
    /** The computer answered: its page can be shown. */
    private val found: (Computer) -> Unit,
    /** The computer no longer answers. */
    private val lost: () -> Unit,
    /** One line for the user about what is going on. */
    private val tell: (String) -> Unit,
    /** The computer no longer knows this phone. */
    private val shutOut: () -> Unit,
    /**
     * Pictures whose copies are on the computer may go to this phone's trash: the user is to be
     * asked. A request of the computer, its pictures as (the computer's name, the phone's number),
     * and the names of the ones that have gone already.
     */
    private val clear: (transfer: String, pictures: List<Pair<String, Long>>, gone: List<String>) -> Unit,
    /** The gallery of this phone changed: pictures arrived from the computer. */
    private val changed: () -> Unit,
) : Thread("link") {
    companion object {
        /** Only one round of work with the computer at a time: the app's own, or the copying by themselves. */
        private val ROUNDS = ReentrantLock()
    }

    @Volatile private var open = true

    /** Set when the pictures may have changed: the computer is told again what the phone has. */
    @Volatile private var again = true

    /** How many originals went to the computer in this round. */
    @Volatile private var sentNow = 0

    fun close() {
        open = false
        interrupt()
    }

    fun refresh() {
        again = true
        interrupt()
    }

    override fun run() {
        var computer: Computer? = null
        var told = 0L
        while (open) {
            try {
                val reached = computer ?: reach()?.also { computer = it; found(it) }
                if (reached == null) {
                    tell("Non trovo il computer. È acceso, e sulla stessa rete di questo telefono?")
                    pause(5000)
                    continue
                }
                // the copying by themselves may be at work, with the app closed: one at a time
                if (!turn()) {
                    tell("Sto già mandando le foto nuove al computer…")
                    pause(3000)
                    continue
                }
                val idle = try {
                    // once at the start, when asked, and every ten minutes: pictures are taken all the time
                    if (again || System.currentTimeMillis() - told > 10 * 60_000) {
                        again = false
                        if (describe(reached)) {
                            told = System.currentTimeMillis()
                            borrow(reached)
                        }
                    }
                    // once the computer knows the pictures, the ones the user chose on the phone can go
                    askToTake(reached)
                    if (memory.wantsSight && !sight.ready) takeSight(reached)
                    !send(reached)
                } finally {
                    ROUNDS.unlock()
                }
                if (idle) pause(3000)
            } catch (refused: Refused) {
                if (refused.status == 401) {
                    shutOut()
                    return
                }
                tell("Il computer ha risposto: ${refused.message}")
                pause(5000)
            } catch (problem: IOException) {
                // off, asleep, or out of reach: a phone keeps trying, and once back it says again what it has,
                // so that this line does not stay on the screen
                computer = null
                again = true
                lost()
                tell("Non raggiungo il computer: riprovo tra poco.")
                pause(5000)
            }
        }
    }

    /** The right to work with the computer now, or false when the copying by themselves has it: a moment's wait, unless woken. */
    private fun turn(): Boolean = try {
        ROUNDS.tryLock(1, TimeUnit.SECONDS)
    } catch (woken: InterruptedException) {
        false
    }

    /**
     * One round of work with the computer, with no screen: for the copying of the new pictures while the
     * app is closed (CopyJob). Tells the computer what the phone has, puts the new pictures in line, and
     * sends what the computer waits for. Says how many pictures went; nothing when the app is at it already.
     */
    fun once(): Int {
        if (!ROUNDS.tryLock()) return 0
        try {
            val reached = reach() ?: return 0
            if (!describe(reached)) return 0
            askToTake(reached)
            // a few times, as the computer asks for what was just put in line
            for (round in 1..20) {
                if (!open || !send(reached)) break
            }
            return sentNow
        } finally {
            ROUNDS.unlock()
        }
    }

    private fun pause(milliseconds: Long) {
        try {
            sleep(milliseconds)
        } catch (woken: InterruptedException) {
            // closed, or asked to look again: either way the wait is over
        }
    }

    /** The computer at the first of its addresses that answers; when none does, looked for on this phone's network. */
    private fun reach(): Computer? = first(memory.ways()) ?: search()

    private fun first(ways: List<Computer>): Computer? {
        for (way in ways) {
            try {
                way.ask("GET", "/phone/hello")
                memory.worked(way.address)
                return way
            } catch (refused: Refused) {
                throw refused
            } catch (unreachable: IOException) {
                // off, or another machine: one that does not show the certificate of the pairing gets nothing
                continue
            }
        }
        return null
    }

    /** When the computer was last looked for on the network: at most once a minute, as it takes a few seconds. */
    @Volatile private var searched = 0L

    /**
     * The home router may give the computer another address, and then none of the ones it had answers. So it
     * is looked for at every address of the network this phone is on, at its port. Only the computer that
     * shows the certificate of the pairing passes for it (Computer), and only to it does the phone show its
     * key; found, its new address is the first one tried from then on.
     */
    private fun search(): Computer? {
        val now = System.currentTimeMillis()
        if (now - searched < 60_000) return null
        searched = now
        val known = memory.ways().map { it.address }.toSet()
        val near = neighbours().filter { it !in known }
        if (near.isEmpty()) return null
        tell("Cerco il computer sulla rete di casa…")
        return first(memory.ways(listening(near, memory.port)))
    }

    /** Tells the computer which pictures the phone has, and sends the small copies it asks for. */
    private fun describe(computer: Computer): Boolean {
        if (!gallery.allowed) {
            tell("Non ho il permesso di vedere le foto: senza, il computer non sa cosa c'è in questo telefono.")
            return false
        }
        val photos = gallery.all()
        val listing = JSONArray()
        photos.forEach { listing.put(JSONObject().put("id", it.id.toString()).put("stamp", it.stamp)) }
        val answer = computer.ask("POST", "/phone/library", JSONObject().put("photos", listing)).getJSONArray("wanted")
        val wanted = (0 until answer.length()).map { answer.getString(it) }
        val known = photos.associateBy { it.id.toString() }

        var sent = 0
        for (batch in wanted.chunked(16)) {
            if (!open) return false
            val copies = JSONArray()
            for (id in batch) {
                val photo = known[id] ?: continue
                val small = gallery.small(photo.id) ?: continue
                val notes = gallery.notes(photo)
                val copy = JSONObject().put("id", id).put("stamp", photo.stamp).put("name", photo.name).put("day", notes.day)
                    .put("jpeg", Base64.encodeToString(small, Base64.NO_WRAP))
                if (notes.latitude != null && notes.longitude != null) copy.put("lat", notes.latitude).put("lon", notes.longitude)
                copies.put(copy)
            }
            if (copies.length() > 0) computer.ask("POST", "/phone/photos", JSONObject().put("photos", copies))
            sent += batch.size
            tell("Faccio conoscere le foto al computer: $sent di ${wanted.size}")
        }
        queueNew(photos)
        computer.ask("POST", "/phone/library/done", JSONObject())
        tell(if (photos.isEmpty()) "Su questo telefono non trovo foto." else "Il computer conosce le ${photos.size} foto di questo telefono.")
        return true
    }

    /**
     * Takes what the computer read in the pictures this phone has not looked at yet: it read their
     * small copies with the same model the phone has, and an old phone takes a second for each.
     */
    private fun borrow(computer: Computer) {
        var kept = 0
        for (batch in library.notLookedAt().chunked(500)) {
            if (!open) return
            val asked = JSONArray()
            batch.forEach { (id, stamp) -> asked.put(JSONObject().put("id", id.toString()).put("stamp", stamp)) }
            val vectors = computer.ask("POST", "/phone/vectors", JSONObject().put("photos", asked)).optJSONObject("vectors") ?: return
            kept += library.keep(vectors, batch.toMap())
        }
        if (kept > 0) tell("Il computer mi ha detto cosa mostrano $kept foto: non devo guardarle una a una.")
    }

    /** Takes from the computer the two models with which this phone looks at pictures by itself. Each file is checked as it arrives. */
    private fun takeSight(computer: Computer) {
        val listed = computer.ask("GET", "/phone/models").getJSONArray("models")
        if (listed.length() == 0) {
            memory.wantsSight = false
            tell("Il computer non ha il modello da darmi: va scaricato prima sul computer.")
            return
        }
        val files = (0 until listed.length()).map { listed.getJSONObject(it) }
        sight.size = files.sumOf { it.getLong("size") }
        sight.got = files.filter { sight.has(it.getString("name"), it.getLong("size")) }.sumOf { it.getLong("size") }
        var told = 0L
        for (file in files) {
            val name = file.getString("name")
            if (sight.has(name, file.getLong("size"))) continue
            val kept = computer.fetch("/phone/models/$name") { stream, fingerprint ->
                sight.keep(name, stream, fingerprint) { read ->
                    sight.got += read
                    if (sight.got - told > 4_000_000) {
                        told = sight.got
                        tell("Prendo dal computer il modello per guardare le foto: ${sight.got / 1_000_000} di ${sight.size / 1_000_000} MB")
                    }
                }
            }
            if (!kept) {
                tell("Il modello non è arrivato intero: riprovo.")
                return
            }
        }
        if (sight.ready) {
            tell("Il modello è sul telefono: ora guardo le foto, una alla volta.")
            changed()
        }
    }

    /** Puts in line for the computer the pictures added to the gallery since the user asked for the new ones to go by themselves. */
    private fun queueNew(photos: List<Photo>) {
        if (!memory.autoCopy) return
        val after = memory.autoAfter
        val fresh = photos.filter { it.id > after }
        if (fresh.isEmpty()) return
        memory.offer(fresh.map { it.id.toString() })
        memory.autoAfter = fresh.maxOf { it.id }
    }

    /** Asks the computer to take the pictures the user chose on this phone. Those it does not know yet wait for the next round. */
    private fun askToTake(computer: Computer) {
        val media = memory.offers()
        if (media.isEmpty()) return
        for (part in media.chunked(500)) {
            try {
                val answer = computer.ask("POST", "/phone/offer", JSONObject().put("media", JSONArray(part)))
                memory.offered(part)
                tell("Il computer prende ${answer.optInt("count")} foto, nella cartella «${answer.optString("folder")}».")
            } catch (refused: Refused) {
                if (refused.status == 401) throw refused
                // the computer does not know them yet: it will, once it has had their small copies
                if (refused.status != 409 || "conosce" !in refused.message.orEmpty()) memory.offered(part)
                tell("Il computer ha risposto: ${refused.message}")
            }
        }
    }

    /** Does what the computer asks: sends the originals it is waiting for, takes the pictures it prepared. Says whether there was anything. */
    private fun send(computer: Computer): Boolean {
        val work = computer.ask("GET", "/phone/work")
        val took = take(computer, work.optJSONArray("incoming") ?: JSONArray())
        val transfers = work.getJSONArray("transfers")
        val total = (0 until transfers.length()).sumOf { transfers.getJSONObject(it).getJSONArray("photos").length() }

        var sent = 0
        var settled = false
        for (index in 0 until transfers.length()) {
            val transfer = transfers.getJSONObject(index)
            val asked = transfer.getJSONArray("photos")
            // a picture that is to leave the phone is sent whole, or not at all
            val whole = transfer.optString("then") == "trash"
            val missing = JSONArray()
            for (position in 0 until asked.length()) {
                if (!open) return true
                val photo = asked.getJSONObject(position)
                val source = photo.getString("media").toLongOrNull()?.let { gallery.source(it, whole) }
                val fingerprint = source?.let { gallery.fingerprint(it) }
                val stream = if (source != null && fingerprint != null) gallery.open(source) else null
                if (stream == null || fingerprint == null) {
                    // deleted from the phone since the computer saw it, or not readable as it must be
                    missing.put(photo.getString("id"))
                    continue
                }
                computer.send("/phone/transfers/${transfer.getString("id")}/photos/${photo.getString("id")}", -1, stream, fingerprint)
                sent += 1
                sentNow += 1
                tell("Mando le foto al computer: $sent di $total")
            }
            if (missing.length() > 0) {
                computer.ask("POST", "/phone/transfers/${transfer.getString("id")}/missing", JSONObject().put("ids", missing))
            }
            if (offer(computer, transfer)) settled = true
        }
        if (total > 0) tell(if (sent == total) "Fatto: $sent foto mandate al computer." else "Mandate $sent foto su $total: le altre non le ho potute mandare.")
        return total > 0 || settled || took
    }

    /** Takes into this phone's gallery the pictures the computer prepared for it, each checked. Says whether there were any. */
    private fun take(computer: Computer, sendings: JSONArray): Boolean {
        val total = (0 until sendings.length()).sumOf { sendings.getJSONObject(it).getJSONArray("photos").length() }
        if (total == 0) return false
        var taken = 0
        var album = ""
        for (index in 0 until sendings.length()) {
            val sending = sendings.getJSONObject(index)
            val id = sending.getString("id")
            album = sending.optString("folder")
            val photos = sending.getJSONArray("photos")
            val received = JSONArray()
            val missing = JSONArray()
            for (position in 0 until photos.length()) {
                if (!open) return true
                val photo = photos.getJSONObject(position)
                val picture = photo.getString("id")
                val kept = try {
                    computer.fetch("/phone/incoming/$id/photos/$picture") { stream, fingerprint -> gallery.save(photo.getString("name"), album, stream, fingerprint) }
                } catch (refused: Refused) {
                    // no longer on the computer, or no longer for this phone
                    if (refused.status == 401) throw refused
                    false
                }
                if (kept) {
                    received.put(picture)
                    taken += 1
                    tell("Prendo le foto dal computer: $taken di $total")
                } else {
                    missing.put(picture)
                }
            }
            computer.ask("POST", "/phone/incoming/$id/received", JSONObject().put("ids", received).put("missing", missing))
        }
        if (taken > 0) {
            tell("Fatto: $taken foto dal computer, nell'album «Regista/$album».")
            // the gallery changed: the computer will be told, and the phone's own search will know them
            again = true
            changed()
        }
        return true
    }

    /**
     * The pictures of a request that the computer has safely, and that the user asked to take
     * off this phone: Android is asked to move them to its trash, and asks the user. Says
     * whether the request was closed here, without a question.
     */
    private fun offer(computer: Computer, transfer: JSONObject): Boolean {
        val named = transfer.optJSONArray("trash") ?: return false
        val pictures = (0 until named.length()).map { named.getJSONObject(it) }.mapNotNull { one ->
            one.getString("media").toLongOrNull()?.let { one.getString("id") to it }
        }
        if (pictures.isEmpty()) return false
        val answer = "/phone/transfers/${transfer.getString("id")}/trashed"
        if (Build.VERSION.SDK_INT < 30) {
            // before Android 11 a phone has no trash an app can ask for: the pictures stay
            computer.ask("POST", answer, JSONObject().put("ids", JSONArray()).put("why", "old"))
            tell("Questo telefono non ha un cestino che io possa usare: le foto restano qui, e una copia è sul computer.")
            return true
        }
        // one that is no longer in the gallery has gone already: by a yes whose news did not reach the computer
        val there = gallery.present(pictures.map { it.second })
        val gone = pictures.filter { it.second !in there }.map { it.first }
        val left = pictures.filter { it.second in there }
        if (left.isEmpty()) {
            computer.ask("POST", answer, JSONObject().put("ids", JSONArray(gone)))
            return true
        }
        tell("Le copie sono sul computer: rispondi alla domanda per spostare le foto nel cestino.")
        clear(transfer.getString("id"), left, gone)
        return false
    }
}

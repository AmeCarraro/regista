package app.regista

import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

/**
 * Keeps the phone and the computer in step while the app is open. It finds the computer,
 * tells it which pictures the phone has and sends a small copy of the ones it does not
 * know; then it waits for requests, and sends the originals the user asked for.
 *
 * Nothing here changes or deletes a picture: the phone only reads its own.
 */
class Link(
    private val memory: Memory,
    private val gallery: Gallery,
    /** The computer answered: its page can be shown. */
    private val found: (Computer) -> Unit,
    /** One line for the user about what is going on. */
    private val tell: (String) -> Unit,
    /** The computer no longer knows this phone. */
    private val shutOut: () -> Unit,
) : Thread("link") {
    @Volatile private var open = true

    /** Set when the pictures may have changed: the computer is told again what the phone has. */
    @Volatile private var again = true

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
                // once at the start, when asked, and every ten minutes: pictures are taken all the time
                if (again || System.currentTimeMillis() - told > 10 * 60_000) {
                    again = false
                    if (describe(reached)) told = System.currentTimeMillis()
                }
                if (!send(reached)) pause(3000)
            } catch (refused: Refused) {
                if (refused.status == 401) {
                    shutOut()
                    return
                }
                tell("Il computer ha risposto: ${refused.message}")
                pause(5000)
            } catch (problem: IOException) {
                // off, asleep, or out of reach: a phone keeps trying
                computer = null
                tell("Non raggiungo il computer: riprovo tra poco.")
                pause(5000)
            }
        }
    }

    private fun pause(milliseconds: Long) {
        try {
            sleep(milliseconds)
        } catch (woken: InterruptedException) {
            // closed, or asked to look again: either way the wait is over
        }
    }

    /** The computer at the first of its addresses that answers. */
    private fun reach(): Computer? {
        for (way in memory.ways()) {
            try {
                way.ask("GET", "/phone/hello")
                memory.worked(way.address)
                return way
            } catch (refused: Refused) {
                throw refused
            } catch (unreachable: IOException) {
                continue
            }
        }
        return null
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
                copies.put(
                    JSONObject().put("id", id).put("stamp", photo.stamp).put("name", photo.name).put("day", gallery.day(photo))
                        .put("jpeg", Base64.encodeToString(small, Base64.NO_WRAP))
                )
            }
            if (copies.length() > 0) computer.ask("POST", "/phone/photos", JSONObject().put("photos", copies))
            sent += batch.size
            tell("Faccio conoscere le foto al computer: $sent di ${wanted.size}")
        }
        computer.ask("POST", "/phone/library/done", JSONObject())
        tell(if (photos.isEmpty()) "Su questo telefono non trovo foto." else "Il computer conosce le ${photos.size} foto di questo telefono.")
        return true
    }

    /** Sends the originals the computer is waiting for. Says whether there was anything to send. */
    private fun send(computer: Computer): Boolean {
        val transfers = computer.ask("GET", "/phone/work").getJSONArray("transfers")
        val total = (0 until transfers.length()).sumOf { transfers.getJSONObject(it).getJSONArray("photos").length() }
        if (total == 0) return false

        var sent = 0
        for (index in 0 until transfers.length()) {
            val transfer = transfers.getJSONObject(index)
            val asked = transfer.getJSONArray("photos")
            val missing = JSONArray()
            for (position in 0 until asked.length()) {
                if (!open) return true
                val photo = asked.getJSONObject(position)
                val source = photo.getString("media").toLongOrNull()?.let { gallery.open(it) }
                if (source == null) {
                    // deleted from the phone since the computer saw it
                    missing.put(photo.getString("id"))
                    continue
                }
                computer.send("/phone/transfers/${transfer.getString("id")}/photos/${photo.getString("id")}", -1, source)
                sent += 1
                tell("Mando le foto al computer: $sent di $total")
            }
            if (missing.length() > 0) {
                computer.ask("POST", "/phone/transfers/${transfer.getString("id")}/missing", JSONObject().put("ids", missing))
            }
        }
        tell(if (sent == total) "Fatto: $sent foto mandate al computer." else "Mandate $sent foto su $total: le altre non sono più su questo telefono.")
        return true
    }
}

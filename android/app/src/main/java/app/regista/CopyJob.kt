package app.regista

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import kotlin.concurrent.thread

/**
 * Copies the new pictures of this phone to the computer by themselves, also with the app closed,
 * when the user asked for it. Android runs this now and then, only on a network that costs nothing
 * (a Wi-Fi), and it does what the app does when it is open (Link), with no screen: tells the computer
 * what the phone has, puts the new pictures in line and sends them, each checked. At home the computer
 * answers; anywhere else it does not, and nothing happens until the next time.
 */
class CopyJob : JobService() {
    @Volatile private var link: Link? = null

    override fun onStartJob(params: JobParameters): Boolean {
        val memory = Memory(this)
        if (!memory.paired || !memory.autoCopy) return false
        thread(name = "copy") {
            val gallery = Gallery(this)
            val worker = Link(
                memory, gallery, Sight(this), Library(this, gallery, Places(this), Sight(this)),
                found = {}, lost = {}, tell = {}, shutOut = {}, clear = { _, _, _ -> }, changed = {},
            )
            link = worker
            val sent = try {
                worker.once()
            } catch (problem: Exception) {
                // out of reach, refused, or anything else: the next time will try again
                0
            }
            if (sent > 0) memory.copied(sent)
            jobFinished(params, false)
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        // Android wants it to stop, the Wi-Fi went away perhaps: what is half sent is sent again next time
        link?.close()
        return true
    }

    companion object {
        private const val ID = 1

        /** Starts or stops the copying by themselves, as the user chose. Starting it again changes nothing. */
        fun plan(context: Context, on: Boolean) {
            val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
            if (!on) {
                scheduler.cancel(ID)
                return
            }
            if (scheduler.getPendingJob(ID) != null) return
            scheduler.schedule(
                JobInfo.Builder(ID, ComponentName(context, CopyJob::class.java))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
                    // as often as Android allows: every quarter of an hour at most, when the phone is not asleep
                    .setPeriodic(15 * 60_000L)
                    // and again after the phone is switched off and on
                    .setPersisted(true)
                    .build(),
            )
        }
    }
}

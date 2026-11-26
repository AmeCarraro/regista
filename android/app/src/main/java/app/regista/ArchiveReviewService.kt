package app.regista

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import java.io.IOException
import java.util.concurrent.CancellationException
import javax.net.ssl.HttpsURLConnection
import kotlin.concurrent.thread

/** A comparison or explicitly confirmed folder removal can continue without an Activity. */
class ArchiveReviewService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var worker: Thread? = null
    private var wake: PowerManager.WakeLock? = null
    private var wifi: WifiManager.WifiLock? = null
    private var removing = false
    @Volatile private var stopping = false
    @Volatile private var connection: HttpsURLConnection? = null
    private val refreshWake = object : Runnable {
        override fun run() {
            if (stopping) return
            wake?.acquire(15 * 60_000L)
            handler.postDelayed(this, 5 * 60_000L)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= 26) getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Verifica e rimozione degli originali", NotificationManager.IMPORTANCE_LOW))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val memory = Memory(this)
        val job = intent?.getStringExtra("job").orEmpty()
        val peer = intent?.getStringExtra("peer").orEmpty()
        if (job.isEmpty() || !memory.paired || peer != memory.fingerprint) {
            stopSelf()
            return START_NOT_STICKY
        }
        removing = intent?.getBooleanExtra("removing", false) == true
        val notice = notification("Cerco Regista sul PC.")
        if (Build.VERSION.SDK_INT >= 29) startForeground(SHOWN, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(SHOWN, notice)
        if (worker?.isAlive == true) return START_NOT_STICKY
        wake = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Regista:review").apply {
            setReferenceCounted(false)
        }
        wifi = runCatching {
            (applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager)
                ?.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "Regista:review")?.apply {
                    setReferenceCounted(false)
                    acquire()
                }
        }.getOrNull()
        handler.post(refreshWake)
        worker = thread(name = "review phone originals") { runLot(job, peer, memory) }
        return START_NOT_STICKY
    }

    private fun runLot(jobId: String, peer: String, memory: Memory) {
        fun cancelled() = stopping || !memory.paired || memory.fingerprint != peer || PhotoImportService.running || MediaBackup.running
        val routes = ImportConnections(memory, ::changed, ::cancelled)
        val originals = ArchiveOriginals(this)
        val folderRemoval = ArchiveFolderRemoval(this, originals)
        try {
            while (!cancelled()) {
                try {
                    val computer = routes.choose()?.computer
                    if (computer != null) {
                        if (removing && folderRemoval.hasJournal()) folderRemoval.report(computer, peer, ::changed)
                        val job = computer.ask("GET", "/phone/import-cleanup?protocol=3", connectionChanged = ::changed)
                            .optJSONObject("job")
                        if (removing) {
                            val current = job?.takeIf { it.optString("id") == jobId && it.optString("state") == "approved" }
                            folderRemoval.discardOtherApproval(current?.let { CleanupReview.current(it) }, peer)
                            if (current == null) return
                            announce("Restano ${current.optInt("remaining")} file autorizzati.")
                            if (!folderRemoval.removePage(computer, current, peer, ::cancelled, ::changed)) return
                            continue
                        }
                        if (job == null || job.optString("id") != jobId || job.optString("state") != "finding") return
                        originals.scan(computer, job, true, ::cancelled, { scanned, total, complete ->
                            val text = if (complete) "Lotto pronto sul PC." else "Controllati $scanned su $total originali."
                            announce(text, scanned, total)
                        }, ::changed)
                        return
                    }
                } catch (error: Refused) {
                    if (error.status in 400..499 && error.status !in setOf(408, 429)) return
                } catch (_: IOException) {
                    // The PC retains its last accepted page, including pages with no matches.
                }
                if (!cancelled()) {
                    announce("Attendo il PC. Riprenderò dal punto salvato.")
                    Thread.sleep(5000)
                }
            }
        } catch (_: InterruptedException) {
        } catch (_: CancellationException) {
        } finally {
            stopSelf()
        }
    }

    private fun changed(next: HttpsURLConnection?) {
        connection = next
        if (stopping && next != null) {
            next.disconnect()
            throw CancellationException()
        }
    }

    private fun announce(text: String, checked: Int = 0, total: Int = 0) {
        if (!stopping) getSystemService(NotificationManager::class.java).notify(SHOWN, notification(text, checked, total))
    }

    private fun notification(text: String, checked: Int = 0, total: Int = 0): Notification {
        val open = PendingIntent.getActivity(this, SHOWN, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else Notification.Builder(this)
        return builder.setSmallIcon(R.drawable.spark)
            .setContentTitle(if (removing) "Rimozione confermata di Regista" else "Verifica originali di Regista")
            .setContentText(text).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .setVisibility(Notification.VISIBILITY_PRIVATE).setProgress(total, checked, total == 0).build()
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        stopSelf()
    }

    override fun onDestroy() {
        stopping = true
        handler.removeCallbacks(refreshWake)
        worker?.interrupt()
        val active = connection
        if (active != null) thread(name = "disconnect phone review") { active.disconnect() }
        wake?.let { if (it.isHeld) it.release() }
        wifi?.let { if (it.isHeld) it.release() }
        started = false
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "archive-review"
        private const val SHOWN = 33
        @Volatile private var started = false
        val running get() = started

        /** The Activity calls this only after the paired PC has requested a comparison. */
        @Synchronized fun start(context: Context, job: String, peer: String, removing: Boolean = false): Boolean {
            if (started) return true
            if (MediaBackup.running || PhotoImportService.running) return false
            val intent = Intent(context, ArchiveReviewService::class.java).putExtra("job", job).putExtra("peer", peer)
                .putExtra("removing", removing)
            return try {
                started = true
                if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
                true
            } catch (_: RuntimeException) {
                started = false
                false
            }
        }
    }
}

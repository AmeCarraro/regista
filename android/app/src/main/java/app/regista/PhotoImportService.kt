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
import android.os.SystemClock
import java.io.IOException
import kotlin.concurrent.thread

/** One explicit import keeps running without an Activity, until completion or the user's stop. */
class PhotoImportService : Service() {
    private lateinit var store: PhotoImportStore
    private lateinit var memory: Memory
    private val handler = Handler(Looper.getMainLooper())
    private var worker: Thread? = null
    private var transfer: MediaImportWorker? = null
    private var wake: PowerManager.WakeLock? = null
    private var wifi: WifiManager.WifiLock? = null
    private var renewed = 0L
    @Volatile private var stopping = false
    @Volatile private var terminal = false
    private val tick = object : Runnable {
        override fun run() {
            if (stopping) return
            if (SystemClock.elapsedRealtime() - renewed > 5 * 60_000L) {
                wake?.acquire(15 * 60_000L)
                renewed = SystemClock.elapsedRealtime()
            }
            getSystemService(NotificationManager::class.java).notify(SHOWN, notification())
            handler.postDelayed(this, 1000)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        store = PhotoImportStore(this)
        memory = Memory(this)
        current = this
        if (Build.VERSION.SDK_INT >= 26) getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Importazione foto", NotificationManager.IMPORTANCE_LOW))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val initial = store.read()
        // A system redelivery resumes only a persisted user request, never a new gallery scan.
        if (!initial.requested || initial.peer != memory.fingerprint || !memory.paired) {
            stopSelf()
            return START_NOT_STICKY
        }
        val notice = notification()
        if (Build.VERSION.SDK_INT >= 29) startForeground(SHOWN, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(SHOWN, notice)
        if (worker?.isAlive == true) return START_REDELIVER_INTENT
        stopping = false
        terminal = false
        try {
            wake = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Regista:photo-import").apply {
                setReferenceCounted(false)
                acquire(15 * 60_000L)
            }
            renewed = SystemClock.elapsedRealtime()
            wifi = (applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager)
                ?.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "Regista:photo-import")?.apply {
                    setReferenceCounted(false)
                    acquire()
                }
        } catch (error: RuntimeException) {
            pause("Non riesco a mantenere attiva la copia: ${error.message.orEmpty()}")
            return START_NOT_STICKY
        }
        handler.removeCallbacks(tick)
        handler.post(tick)
        worker = thread(name = "user photo import") { runImport(initial.work) }
        return START_REDELIVER_INTENT
    }

    private fun runImport(work: String) {
        val importer=MediaImportWorker(this,memory,store,work) { reached=it }
        transfer=importer
        fun active()=store.read().let { it.work==work && it.requested }
        try {
            while (!stopping && active()) {
                if (!memory.paired || memory.fingerprint != store.read().peer) {
                    pause("Il collegamento al PC è cambiato. Scegli nuovamente quando importare.")
                    break
                }
                try {
                    if (!importer.once() && active()) {
                        store.update(work) { it.copy(phase = "waiting", message = "Attendo il PC. Riprendo appena torna raggiungibile.") }
                    }
                } catch (needsUser:ImportNeedsUser) {
                    pause(needsUser.message ?: "Controlla i file del blocco e riprendi l’importazione.")
                    break
                } catch (refused: Refused) {
                    if (refused.status in 400..499 && refused.status !in setOf(408,429)) {
                        pause(refused.message ?: "Il PC ha rifiutato l’importazione.")
                        break
                    }
                    reached = null
                    store.update(work) { it.copy(phase = "waiting", message = "Il PC è occupato. Riprovo tra poco.") }
                } catch (unreachable: IOException) {
                    reached = null
                    if (!stopping && active()) store.update(work) {
                        it.copy(phase = "waiting", message = "Collegamento interrotto. I file confermati restano salvati; riprovo.")
                    }
                }
                if (!stopping && active()) Thread.sleep(5000)
            }
            terminal = !store.read().requested
            if (store.read().phase == "done" && store.read().copied > 0) memory.copied(store.read().copied)
        } catch (_: InterruptedException) {
            // Cancellation or Android stopping the service: the committed queue remains available.
        } catch (error: Exception) {
            runCatching { pause(error.message ?: "Importazione interrotta. Premi Riprendi per continuare.") }
        } finally {
            importer.cancel()
            handler.post { if (current === this) finishService() }
        }
    }

    private fun pause(message: String) {
        terminal = true
        stopping = true
        runCatching { store.pause(message) }
        transfer?.cancel()
        worker?.interrupt()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun finishService() {
        handler.removeCallbacks(tick)
        val value = store.read()
        stopForeground(STOP_FOREGROUND_REMOVE)
        if (terminal && value.phase == "done") getSystemService(NotificationManager::class.java).notify(SHOWN, notification())
        stopSelf()
    }

    /** Android 15 gives data-sync services a bounded background budget. Stop promptly, keeping the queue. */
    override fun onTimeout(startId: Int, fgsType: Int) {
        pause("Android ha sospeso la copia prolungata. Apri Regista e premi Riprendi importazione.")
    }

    override fun onDestroy() {
        stopping = true
        handler.removeCallbacks(tick)
        transfer?.cancel()
        worker?.interrupt()
        wake?.let { if (it.isHeld) it.release() }
        wifi?.let { if (it.isHeld) it.release() }
        if (current === this) { current = null; reached = null }
        super.onDestroy()
    }

    private fun notification(): Notification {
        val value = store.read()
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        val open = PendingIntent.getActivity(this, 20, Intent(this, MainActivity::class.java), flags)
        val stop = PendingIntent.getBroadcast(this, 21, Intent(this, StopPhotoImport::class.java), flags)
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else Notification.Builder(this)
        val text = if (!value.prepared) value.message else
            "${value.processed} / ${value.total} · ${value.copied} copiate · ${value.duplicates} già presenti · ${value.failed} errori"
        builder.setSmallIcon(R.drawable.spark).setContentTitle(if (value.phase == "done") "Importazione terminata" else if(value.scope=="all-media") "Backup completo" else "Importazione foto e video")
            .setContentText(text).setStyle(Notification.BigTextStyle().bigText("$text\n${value.message}"))
            .setContentIntent(open).setOnlyAlertOnce(true).setOngoing(value.requested)
            .setVisibility(Notification.VISIBILITY_PRIVATE).setCategory(Notification.CATEGORY_PROGRESS)
        if (value.requested) builder.setProgress(value.total.coerceAtLeast(1), value.processed, !value.prepared)
            .addAction(Notification.Action.Builder(android.R.drawable.ic_media_pause, "Interrompi", stop).build())
        return builder.build()
    }

    companion object {
        private const val CHANNEL = "photo-import"
        private const val SHOWN = 32
        @Volatile private var current: PhotoImportService? = null
        val running get() = current != null
        @Volatile var reached: Computer? = null
            private set

        /** Called only from a visible Activity, after a click or an explicit request from the paired PC. */
        fun start(context: Context, request: String = "", ids: List<String>? = null,scope:String="photos-videos") {
            val memory = Memory(context)
            if (!memory.paired) throw IllegalStateException("Collega prima il PC dalla scheda Computer.")
            if (MediaBackup.running) throw IllegalStateException("Termina prima il backup completo in corso.")
            val store = PhotoImportStore(context)
            if (running && !store.read().requested) throw IllegalStateException("Attendi la chiusura della copia precedente.")
            store.begin(memory.fingerprint, request, ids,scope)
            try {
                val intent = Intent(context, PhotoImportService::class.java)
                if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
            } catch (error: RuntimeException) {
                store.pause("Apri Regista e premi Riprendi importazione: Android non ha avviato la copia.")
                throw error
            }
        }

        fun cancel(context: Context) {
            PhotoImportStore(context).pause("Importazione interrotta. Premi Riprendi per continuare dai file rimasti.")
            current?.pause("Importazione interrotta. I file già confermati sono al sicuro sul PC.")
        }
    }
}

/** The notification's explicit stop action; never starts another import. */
class StopPhotoImport : android.content.BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) { PhotoImportService.cancel(context) }
}

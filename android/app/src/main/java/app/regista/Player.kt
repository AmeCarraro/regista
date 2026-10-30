package app.regista

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaDataSource
import android.media.MediaMetadata
import android.media.MediaPlayer
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.MessageDigest
import kotlin.concurrent.thread

/** A song in line to be played: on this phone (its number in Android's list) or on the computer (its name there, and its size). */
class Song(val where: String, val id: String, val title: String, val artist: String, val size: Long = 0) {
    fun json(): JSONObject = JSONObject().put("where", where).put("id", id).put("title", title).put("artist", artist)
}

/**
 * A song still arriving from the computer, played from what has arrived: Android waits where the rest
 * is not there yet. An M4A whose words come at its end starts once it is whole, as Android reads the end first.
 */
private class Arriving(private val file: File, private val size: Long) : MediaDataSource() {
    @Volatile var got = 0L
    // null while it arrives; true once whole and checked, false when it broke off or is not what the computer sent
    @Volatile var whole: Boolean? = null
    @Volatile private var closed = false
    private var reader: RandomAccessFile? = null

    override fun getSize() = size

    override fun readAt(position: Long, buffer: ByteArray, offset: Int, length: Int): Int {
        if (position >= size) return -1
        val wanted = minOf(size, position + length)
        while (got < wanted && whole == null && !closed) Thread.sleep(40)
        if (closed || whole == false) throw IOException("the song did not arrive whole")
        val ready = (minOf(got, wanted) - position).toInt()
        if (ready <= 0) return -1
        synchronized(this) {
            val open = reader ?: RandomAccessFile(file, "r").also { reader = it }
            open.seek(position)
            return open.read(buffer, offset, ready)
        }
    }

    override fun close() {
        closed = true
        synchronized(this) {
            reader?.close()
            reader = null
        }
    }
}

/**
 * Plays a line of songs, one after the other, also with the screen off and the app closed: Android
 * keeps running a player that shows a notification, puts its controls on the lock screen and gives
 * it the buttons of headphones. A song of the computer is taken from it into the app's own cache and
 * plays while it arrives; checked once whole, it stops if it is not what the computer sent. Only the
 * one playing is kept.
 */
class Player : Service() {
    private var player: MediaPlayer? = null
    private lateinit var session: MediaSession
    private lateinit var audio: AudioManager
    private var focus: AudioFocusRequest? = null
    private val main = Handler(Looper.getMainLooper())
    // which song was asked for last: a song still arriving for an older request is left behind
    private var asked = 0
    // paused because another app took the sound for a moment: it plays again when the sound comes back
    private var interrupted = false
    private var listening = false
    private var foreground = false

    private val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build()

    // the headphones came out: the song does not go on out loud
    private val noisy = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) = pause()
    }

    private val changed = AudioManager.OnAudioFocusChangeListener { change ->
        when (change) {
            AudioManager.AUDIOFOCUS_LOSS -> pause()
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> if (playing) {
                pause()
                interrupted = true
            }
            AudioManager.AUDIOFOCUS_GAIN -> if (interrupted) resume()
        }
    }

    // how far the song is, for the page and the lock screen
    private val tick = object : Runnable {
        override fun run() {
            player?.takeIf { playing }?.let { position = it.currentPosition.toLong() }
            main.postDelayed(this, 500)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        audio = getSystemService(AudioManager::class.java)
        session = MediaSession(this, "Regista")
        session.setCallback(object : MediaSession.Callback() {
            override fun onPlay() = resume()
            override fun onPause() = pause()
            override fun onSkipToNext() = move(1)
            override fun onSkipToPrevious() = move(-1)
            override fun onSeekTo(position: Long) = seek(position)
            override fun onStop() = finish()
        })
        // before Android 8 the buttons of headphones and of the lock screen reach a player only when it asks for them
        @Suppress("DEPRECATION")
        session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS or MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS)
        session.isActive = true
        main.post(tick)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            PLAY -> {
                queue = read(intent.getStringExtra("queue"))
                index = intent.getIntExtra("index", 0).coerceIn(0, maxOf(0, queue.size - 1))
                start()
            }
            PAUSE -> pause()
            RESUME -> resume()
            NEXT -> move(1)
            PREVIOUS -> move(-1)
            SEEK -> seek(intent.getLongExtra("position", 0))
            STOP -> finish()
        }
        // asked for something with nothing to play: nothing keeps running
        if (queue.isEmpty()) stopSelf()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        release()
        letFocusGo()
        session.release()
        playing = false
        loading = false
        super.onDestroy()
    }

    /** Plays the song of the line at `index`, from its start. */
    private fun start() {
        val song = queue.getOrNull(index) ?: return finish()
        asked += 1
        val mine = asked
        release()
        problem = ""
        loading = true
        playing = false
        position = 0
        duration = 0
        show(song)
        if (song.where != "computer") return prepare(mine) { setDataSource(this@Player, Songs.uri(song.id.toLong())) }
        val computer = computer ?: return failed(mine, "Questa canzone è sul computer, e il computer non risponde.")
        val folder = File(cacheDir, "music").apply { mkdirs() }
        // only the song playing is kept: the one before goes
        folder.listFiles()?.forEach { it.delete() }
        val file = File(folder, song.id.filter(Char::isLetterOrDigit))
        val arriving = Arriving(file, song.size)
        thread(name = "song") {
            val whole = try {
                take(computer, song, file, arriving)
            } catch (unreachable: IOException) {
                false
            }
            arriving.whole = whole
            main.post {
                if (!whole) failed(mine, "La canzone non è arrivata dal computer: riprova da casa, con Regista aperto.")
                // a song whose size the computer did not say plays once it is whole
                else if (song.size <= 0) prepare(mine) { setDataSource(file.path) }
            }
        }
        if (song.size > 0) prepare(mine) { setDataSource(arriving) }
    }

    private fun prepare(mine: Int, source: MediaPlayer.() -> Unit) {
        if (mine != asked) return
        val made = MediaPlayer()
        made.setAudioAttributes(attributes)
        // the processor stays awake while a song plays with the screen off, and only then
        made.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK)
        made.setOnPreparedListener {
            if (mine != asked) return@setOnPreparedListener
            loading = false
            duration = it.duration.toLong()
            if (takeFocus()) {
                it.start()
                playing = true
            }
            queue.getOrNull(index)?.let(::show)
        }
        made.setOnCompletionListener { if (mine == asked) move(1, byTheUser = false) }
        made.setOnErrorListener { _, _, _ ->
            failed(mine, "Questa canzone non si riesce a suonare.")
            true
        }
        try {
            made.source()
            made.prepareAsync()
            player = made
        } catch (wrong: Exception) {
            // a song gone meanwhile, or a file Android cannot read
            made.release()
            failed(mine, "Non riesco ad aprire questa canzone.")
        }
    }

    /** A song that cannot be played is said on the page and in the notification; the user goes on from there. */
    private fun failed(mine: Int, why: String) {
        if (mine != asked) return
        release()
        problem = why
        loading = false
        playing = false
        queue.getOrNull(index)?.let(::show)
    }

    private fun pause() {
        player?.takeIf { playing }?.let {
            it.pause()
            position = it.currentPosition.toLong()
        }
        playing = false
        update()
    }

    private fun resume() {
        val made = player ?: return start()
        if (loading) return
        if (takeFocus()) {
            made.start()
            playing = true
            interrupted = false
        }
        update()
    }

    private fun seek(to: Long) {
        player?.takeIf { !loading }?.seekTo(to.toInt())
        position = to
        update()
    }

    /** The next song of the line, or the one before: a few seconds into a song, "back" starts it again. */
    private fun move(step: Int, byTheUser: Boolean = true) {
        if (step < 0 && position > 3000) return seek(0)
        val next = index + step
        if (next !in queue.indices) {
            // the line is over
            if (!byTheUser) finish()
            return
        }
        index = next
        start()
    }

    /** Stops, and the notification goes. */
    private fun finish() {
        asked += 1
        release()
        letFocusGo()
        queue = emptyList()
        index = 0
        playing = false
        loading = false
        position = 0
        duration = 0
        problem = ""
        stopForeground(STOP_FOREGROUND_REMOVE)
        foreground = false
        MusicWidget.show(this)
        stopSelf()
    }

    private fun release() {
        player?.release()
        player = null
    }

    private fun takeFocus(): Boolean {
        val answer = if (Build.VERSION.SDK_INT >= 26) {
            val request = focus ?: AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                .setAudioAttributes(attributes)
                .setOnAudioFocusChangeListener(changed)
                .build()
                .also { focus = it }
            audio.requestAudioFocus(request)
        } else {
            @Suppress("DEPRECATION")
            audio.requestAudioFocus(changed, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN)
        }
        val granted = answer == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
        if (granted && !listening) {
            registerReceiver(noisy, IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY))
            listening = true
        }
        return granted
    }

    private fun letFocusGo() {
        if (Build.VERSION.SDK_INT >= 26) focus?.let(audio::abandonAudioFocusRequest)
        else @Suppress("DEPRECATION") audio.abandonAudioFocus(changed)
        if (listening) unregisterReceiver(noisy)
        listening = false
    }

    /** Takes a song of the computer into `file`, saying how much has arrived as it arrives; true when it is whole and checked. */
    private fun take(computer: Computer, song: Song, file: File, arriving: Arriving): Boolean =
        computer.fetch("/phone/music/${song.id}") { stream, fingerprint ->
            val digest = MessageDigest.getInstance("SHA-256")
            file.outputStream().use { out ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = stream.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                    out.write(buffer, 0, read)
                    arriving.got += read
                }
            }
            digest.digest().joinToString("") { "%02x".format(it) }.equals(fingerprint, ignoreCase = true)
        }

    /** What plays now, for the lock screen, the notification and the buttons of headphones. */
    private fun show(song: Song) {
        session.setMetadata(
            MediaMetadata.Builder()
                .putString(MediaMetadata.METADATA_KEY_TITLE, song.title)
                .putString(MediaMetadata.METADATA_KEY_ARTIST, song.artist)
                .putLong(MediaMetadata.METADATA_KEY_DURATION, duration)
                .build(),
        )
        update()
    }

    private fun update() {
        val state = if (loading) PlaybackState.STATE_BUFFERING else if (playing) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED
        session.setPlaybackState(
            PlaybackState.Builder()
                .setActions(
                    PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_SKIP_TO_NEXT or
                        PlaybackState.ACTION_SKIP_TO_PREVIOUS or PlaybackState.ACTION_SEEK_TO or PlaybackState.ACTION_STOP,
                )
                .setState(state, position, if (playing) 1f else 0f)
                .build(),
        )
        MusicWidget.show(this)
        val song = queue.getOrNull(index) ?: return
        val shown = notification(song)
        if (foreground) {
            getSystemService(NotificationManager::class.java).notify(SHOWN, shown)
        } else {
            // the player is in front from now on: Android does not stop it with the screen off
            if (Build.VERSION.SDK_INT >= 29) startForeground(SHOWN, shown, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK) else startForeground(SHOWN, shown)
            foreground = true
        }
    }

    private fun notification(song: Song): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "Musica", NotificationManager.IMPORTANCE_LOW))
        }
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val said = when {
            problem.isNotEmpty() -> problem
            loading && song.where == "computer" -> "La prendo dal computer…"
            else -> song.artist
        }
        return builder
            .setSmallIcon(R.drawable.spark)
            .setContentTitle(song.title)
            .setContentText(said)
            .setContentIntent(open)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .addAction(action(android.R.drawable.ic_media_previous, "Indietro", PREVIOUS))
            .addAction(if (playing) action(android.R.drawable.ic_media_pause, "Pausa", PAUSE) else action(android.R.drawable.ic_media_play, "Suona", RESUME))
            .addAction(action(android.R.drawable.ic_media_next, "Avanti", NEXT))
            .addAction(action(android.R.drawable.ic_menu_close_clear_cancel, "Chiudi", STOP))
            .setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken).setShowActionsInCompactView(0, 1, 2))
            .build()
    }

    private fun action(icon: Int, title: String, what: String): Notification.Action =
        Notification.Action.Builder(Icon.createWithResource(this, icon), title, pressed(this, what)).build()

    companion object {
        const val PLAY = "app.regista.music.PLAY"
        const val PAUSE = "app.regista.music.PAUSE"
        const val RESUME = "app.regista.music.RESUME"
        const val NEXT = "app.regista.music.NEXT"
        const val PREVIOUS = "app.regista.music.PREVIOUS"
        const val SEEK = "app.regista.music.SEEK"
        const val STOP = "app.regista.music.STOP"
        private const val CHANNEL = "music"
        private const val SHOWN = 7

        /** The computer the songs of the computer come from: the one that answered when the user pressed play. */
        @Volatile var computer: Computer? = null

        @Volatile var queue: List<Song> = emptyList()
            private set
        @Volatile var index = 0
            private set
        @Volatile var playing = false
            private set
        @Volatile var loading = false
            private set
        @Volatile var position = 0L
            private set
        @Volatile var duration = 0L
            private set
        @Volatile var problem = ""
            private set

        /** What the page shows of the player: the song, where it is in its line, whether it plays, how far, why not. */
        fun state(): JSONObject = JSONObject()
            .put("song", queue.getOrNull(index)?.json() ?: JSONObject.NULL)
            .put("index", index)
            .put("count", queue.size)
            .put("playing", playing)
            .put("loading", loading)
            .put("position", position)
            .put("duration", duration)
            .put("problem", problem)

        /** Asks the player to do something: Android starts it first, if it was not running. */
        fun ask(context: Context, action: String, extras: Intent.() -> Unit = {}) {
            context.startService(Intent(context, Player::class.java).setAction(action).apply(extras))
        }

        /** The same, for a button outside the app: the notification's, or the widget's. */
        fun pressed(context: Context, action: String): PendingIntent =
            PendingIntent.getService(context, action.hashCode(), Intent(context, Player::class.java).setAction(action), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

        private fun read(queue: String?): List<Song> = try {
            val list = JSONArray(queue ?: "[]")
            (0 until list.length()).map { at ->
                val song = list.getJSONObject(at)
                Song(song.optString("where"), song.getString("id"), song.optString("title"), song.optString("artist"), song.optLong("size"))
            }
        } catch (garbled: JSONException) {
            emptyList()
        }
    }
}

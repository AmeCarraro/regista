package app.regista

import android.app.Activity
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.MediaController
import android.widget.TextView
import android.widget.VideoView

/** Android's native decoder and playback controls; no models, server or WebView streaming. */
class VideoActivity : Activity() {
    private lateinit var video: VideoView
    private lateinit var message: TextView
    private var uri: Uri? = null
    private var position = 0
    private var resume = true
    private var prepared = false

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val item = Videos(this).named(intent.getStringExtra("id").orEmpty())
        if (item == null) { finish(); return }
        uri = Uri.parse(item.getString("uri"))
        position = saved?.getInt("position") ?: 0
        resume = saved?.getBoolean("playing") ?: true
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(16, 16, 16, 16)
            setBackgroundColor(0xFF0B0910.toInt())
        }
        content.addView(Button(this).apply { text = "Chiudi video"; setOnClickListener { finish() } })
        content.addView(TextView(this).apply { text = item.getString("title"); setTextColor(-1); textSize = 18f })
        message = TextView(this).apply { setTextColor(-1); textSize = 16f }
        content.addView(message)
        video = VideoView(this)
        content.addView(video, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(content)
        video.setMediaController(MediaController(this).apply { setAnchorView(video) })
        video.setOnPreparedListener {
            prepared = true
            message.text = ""
            if (position > 0) video.seekTo(position)
            if (resume) video.start()
        }
        video.setOnErrorListener { _, _, _ ->
            message.text = "Non riesco a riprodurre questo video: il file potrebbe non essere più accessibile o il formato non essere supportato dal telefono."
            true
        }
    }

    override fun onStart() {
        super.onStart()
        if (!::video.isInitialized) return
        if (Player.loading) Player.ask(this, Player.STOP)
        else if (Player.playing) Player.ask(this, Player.PAUSE)
        message.text = "Apro il video…"
        try { video.setVideoURI(uri) } catch (_: Exception) { message.text = "Video non accessibile. Sceglilo di nuovo dalla scheda Video." }
    }

    override fun onPause() {
        if (::video.isInitialized && prepared) {
            position = video.currentPosition
            resume = video.isPlaying
            video.pause()
        }
        super.onPause()
    }

    override fun onStop() {
        if (::video.isInitialized) { video.stopPlayback(); prepared = false }
        super.onStop()
    }

    override fun onSaveInstanceState(out: Bundle) {
        out.putInt("position", if (prepared) video.currentPosition else position)
        out.putBoolean("playing", if (prepared && video.isPlaying) true else resume)
        super.onSaveInstanceState(out)
    }
}

package app.regista

import android.Manifest
import android.annotation.TargetApi
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognitionSupport
import android.speech.RecognitionSupportCallback
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import org.json.JSONObject

/** One utterance for the command preview. Only Android's on-device recognizer may hear it. */
class CommandSpeech(private val app: Activity, private val changed: () -> Unit) {
    @Volatile var available = false
        private set

    private data class State(val status: String, val text: String = "", val error: String = "")

    @Volatile private var state = State("idle")
    private val main = Handler(Looper.getMainLooper())
    private var checking: SpeechRecognizer? = null
    private var listening: SpeechRecognizer? = null
    private var foreground = false
    private var awaitingPermission = false
    private val checkTimeout = Runnable { endCheck() }
    private val listenTimeout = Runnable { finish(State("error", error = NO_SPEECH)) }

    fun json(): String = state.let {
        JSONObject().put("status", it.status).apply {
            if (it.text.isNotEmpty()) put("text", it.text)
            if (it.error.isNotEmpty()) put("error", it.error)
        }.toString()
    }

    fun onStart() {
        foreground = true
        if (Build.VERSION.SDK_INT < 31 || !app.packageManager.hasSystemFeature(PackageManager.FEATURE_MICROPHONE) ||
            !SpeechRecognizer.isOnDeviceRecognitionAvailable(app)) {
            availability(false)
            return
        }
        if (Build.VERSION.SDK_INT >= 33) checkItalian() else availability(true)
    }

    fun onStop() {
        foreground = false
        endCheck()
        cancel()
    }

    @TargetApi(33)
    private fun checkItalian() {
        availability(false)
        try {
            val probe = SpeechRecognizer.createOnDeviceSpeechRecognizer(app)
            checking = probe
            main.postDelayed(checkTimeout, 5_000)
            probe.checkRecognitionSupport(request(), app.mainExecutor, object : RecognitionSupportCallback {
                override fun onSupportResult(support: RecognitionSupport) {
                    if (checking !== probe) return
                    endCheck()
                    availability(support.installedOnDeviceLanguages.any {
                        it.equals("it", ignoreCase = true) || it.equals(LANGUAGE, ignoreCase = true)
                    })
                }

                override fun onError(error: Int) {
                    if (checking === probe) endCheck()
                }
            })
        } catch (unavailable: RuntimeException) {
            endCheck()
        }
    }

    private fun endCheck() {
        main.removeCallbacks(checkTimeout)
        val probe = checking
        checking = null
        probe?.destroy()
    }

    fun listen() {
        if (!foreground || !available || state.status == "listening" || awaitingPermission) return
        publish(State("listening"))
        if (app.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            startListening()
        } else {
            awaitingPermission = true
            app.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), PERMISSION)
        }
    }

    fun permissionResult(granted: Boolean) {
        if (!awaitingPermission) return
        awaitingPermission = false
        if (state.status != "listening") return
        if (granted) startListening() else finish(State("error", error = MICROPHONE))
    }

    fun cancel() = finish(State("idle"))

    private fun availability(supported: Boolean) {
        if (supported == available) return
        available = supported
        changed()
    }

    private fun publish(next: State) {
        if (state == next) return
        state = next
        changed()
    }

    private fun startListening() {
        if (Build.VERSION.SDK_INT < 31 || !foreground || !available) return finish(State("error", error = UNAVAILABLE))
        try {
            val recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(app)
            listening = recognizer
            recognizer.setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle?) {
                    if (listening !== recognizer) return
                    val heard = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim().orEmpty()
                    finish(when {
                        heard.isBlank() -> State("error", error = NO_SPEECH)
                        heard.length > 500 -> State("error", error = "Il comando trascritto supera 500 caratteri.")
                        else -> State("result", text = heard)
                    })
                }

                override fun onError(error: Int) {
                    if (listening !== recognizer) return
                    val message = when (error) {
                        SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> NO_SPEECH
                        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> MICROPHONE
                        SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED, SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE -> UNAVAILABLE
                        else -> "La dettatura non è riuscita. Puoi scrivere il comando."
                    }
                    finish(State("error", error = message))
                }

                override fun onReadyForSpeech(params: Bundle?) = Unit
                override fun onBeginningOfSpeech() = Unit
                override fun onRmsChanged(rmsdB: Float) = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() = Unit
                override fun onPartialResults(partialResults: Bundle?) = Unit
                override fun onEvent(eventType: Int, params: Bundle?) = Unit
            })
            main.postDelayed(listenTimeout, 20_000)
            recognizer.startListening(request())
        } catch (unavailable: RuntimeException) {
            finish(State("error", error = UNAVAILABLE))
        }
    }

    private fun finish(next: State) {
        main.removeCallbacks(listenTimeout)
        val recognizer = listening
        listening = null
        recognizer?.cancel()
        recognizer?.destroy()
        publish(next)
    }

    private fun request() = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE, LANGUAGE)
        .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)

    companion object {
        const val PERMISSION = 6
        private const val LANGUAGE = "it-IT"
        private const val NO_SPEECH = "Non ho riconosciuto il comando. Riprova o scrivilo."
        private const val MICROPHONE = "Consenti l’uso del microfono per dettare il comando."
        private const val UNAVAILABLE = "La dettatura italiana offline non è disponibile su questo dispositivo."
    }
}

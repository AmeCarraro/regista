package app.regista

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.BarcodeResult
import com.journeyapps.barcodescanner.CameraPreview
import com.journeyapps.barcodescanner.DecoratedBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory

/** A local QR reader. Camera frames are decoded on the phone and never stored or transmitted. */
class PairingScanner : Activity() {
    private lateinit var scanner: DecoratedBarcodeView
    private var requested = false
    private var resumed = false
    private var active = false
    private var finished = false
    private val message get() = findViewById<TextView>(R.id.scan_message)
    private val permissionButton get() = findViewById<Button>(R.id.scan_permission)

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        setContentView(R.layout.pairing_scanner)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        requested = saved?.getBoolean("camera_requested") ?: false
        scanner = findViewById(R.id.scanner)
        scanner.setStatusText("")
        scanner.decoderFactory = DefaultDecoderFactory(listOf(BarcodeFormat.QR_CODE))
        scanner.barcodeView.addStateListener(object : CameraPreview.StateListener {
            override fun previewSized() {}
            override fun previewStarted() { message.text = "Inquadra il codice. Ti chiederò conferma prima di collegarti." }
            override fun previewStopped() {}
            override fun cameraClosed() {}
            override fun cameraError(error: Exception) {
                active = false
                message.text = "Fotocamera non disponibile. Chiudi le altre app che la usano e riprova, oppure incolla il collegamento."
                permissionButton.text = "Riprova fotocamera"
                permissionButton.visibility = View.VISIBLE
            }
        })
        scanner.decodeContinuous(object : BarcodeCallback {
            override fun barcodeResult(result: BarcodeResult) {
                if (finished || !resumed) return
                val text = result.text ?: return
                if (readInvite(text) == null) {
                    message.text = "Questo QR non è un collegamento di Regista. Inquadra quello sul tuo PC."
                    return
                }
                finished = true
                scanner.pause()
                setResult(RESULT_OK, Intent().putExtra(INVITE, text))
                finish()
            }
        })
        findViewById<Button>(R.id.scan_cancel).setOnClickListener { finish() }
        permissionButton.setOnClickListener {
            when {
                allowed() -> startCamera()
                requested && !shouldShowRequestPermissionRationale(Manifest.permission.CAMERA) ->
                    startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                else -> askCamera()
            }
        }
        if (!packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) {
            message.text = "Questo dispositivo non ha una fotocamera. Puoi incollare il collegamento del PC."
        } else if (!allowed() && !requested) askCamera()
    }

    private fun allowed() = checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun askCamera() {
        requested = true
        requestPermissions(arrayOf(Manifest.permission.CAMERA), CAMERA)
    }

    private fun startCamera() {
        if (!resumed || finished || active) return
        if (!packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) return
        if (!allowed()) {
            message.text = "Consenti la fotocamera per leggere il QR. Puoi anche tornare indietro e incollare il link."
            permissionButton.text = if (requested && !shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) "Apri permessi fotocamera" else "Consenti fotocamera"
            permissionButton.visibility = View.VISIBLE
            return
        }
        permissionButton.visibility = View.GONE
        message.text = "Apro la fotocamera…"
        active = true
        scanner.resume()
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        startCamera()
    }

    override fun onPause() {
        resumed = false
        active = false
        scanner.pauseAndWait()
        super.onPause()
    }

    override fun onRequestPermissionsResult(request: Int, permissions: Array<String>, results: IntArray) {
        super.onRequestPermissionsResult(request, permissions, results)
        if (request == CAMERA) startCamera()
    }

    override fun onSaveInstanceState(out: Bundle) {
        out.putBoolean("camera_requested", requested)
        super.onSaveInstanceState(out)
    }

    companion object {
        private const val CAMERA = 1
        const val INVITE = "app.regista.QR_INVITE"
    }
}

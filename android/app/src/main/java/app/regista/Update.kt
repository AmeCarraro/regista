package app.regista

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.widget.Toast
import java.io.InputStream
import java.security.DigestInputStream
import java.security.MessageDigest

/**
 * A newer app for this phone, from the computer it was paired with, with no cable: the computer says it has
 * one, it comes over the same encrypted link as everything else and is checked against the fingerprint the
 * computer gives of it, and Android installs it only after asking the user, and only if it is signed with
 * the same key as this one.
 */
class Update(private val context: Context) {
    /** The version the computer has, when it is newer than this one; 0 when it is not, or not known yet. */
    @Volatile var newer = 0L

    /** The user asked for it: it is taken as soon as the computer answers. */
    @Volatile var wanted = false

    /** How much of it has arrived, of how much, while it is taken; size is 0 at any other time. */
    @Volatile var got = 0L
    @Volatile var size = 0L

    /** This app's own version: a number that grows at every build (build.gradle.kts). */
    val version: Long = context.packageManager.getPackageInfo(context.packageName, 0).let {
        if (Build.VERSION.SDK_INT >= 28) it.longVersionCode else @Suppress("DEPRECATION") it.versionCode.toLong()
    }

    /**
     * Writes the app as it arrives into a session of Android's installer, and hands it over: Android then asks
     * the user (Installed). False, and nothing handed over, when what arrived is not what the computer said.
     */
    fun install(stream: InputStream, fingerprint: String): Boolean {
        val installer = context.packageManager.packageInstaller
        val asked = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        asked.setAppPackageName(context.packageName)
        val id = installer.createSession(asked)
        var handed = false
        installer.openSession(id).use { session ->
            try {
                val seen = MessageDigest.getInstance("SHA-256")
                session.openWrite("regista.apk", 0, size).use { out ->
                    val input = DigestInputStream(stream, seen)
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        out.write(buffer, 0, read)
                        got += read
                    }
                    session.fsync(out)
                }
                if (!seen.digest().joinToString("") { "%02x".format(it) }.equals(fingerprint, ignoreCase = true)) return false
                // Android fills in what it says, so the intent must let it write
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
                session.commit(PendingIntent.getBroadcast(context, id, Intent(context, Installed::class.java), flags).intentSender)
                handed = true
            } finally {
                if (!handed) session.abandon()
            }
        }
        return true
    }
}

/** What Android says of the app handed to it: it asks the user first, then installs it, or says why not. */
class Installed : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = if (Build.VERSION.SDK_INT >= 33) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_INTENT)
                }
                confirm?.let { context.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            }
            // installed: this app has been replaced, and the user opens the new one
            PackageInstaller.STATUS_SUCCESS -> {}
            PackageInstaller.STATUS_FAILURE_ABORTED -> say(context, "Aggiornamento annullato: l'app resta com'era.")
            else -> say(context, "Android non ha installato l'app nuova: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "non dice perché"}.")
        }
    }

    private fun say(context: Context, line: String) = Toast.makeText(context, line, Toast.LENGTH_LONG).show()
}

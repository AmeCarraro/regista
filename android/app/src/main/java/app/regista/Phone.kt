package app.regista

import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.IOException

/**
 * The phone's own screen: a page that travels inside the app (built from web/src/telefono into
 * the app's files), shown from those files as if from a site, with no server and no network,
 * and the few calls that page may make to the app. It works with no computer.
 */
class Phone(
    private val app: MainActivity,
    private val library: Library,
    private val places: Places,
    private val gallery: Gallery,
    private val memory: Memory,
) {
    @JavascriptInterface
    fun pictures(): String = library.json()

    @JavascriptInterface
    fun reading(): String = JSONObject().put("allowed", gallery.allowed).put("done", library.done).put("total", library.total).toString()

    @JavascriptInterface
    fun state(): String = app.state().toString()

    @JavascriptInterface
    fun country(name: String): String = places.country(name)?.toString() ?: "null"

    @JavascriptInterface
    fun city(written: String): String = places.city(written)?.toString() ?: "null"

    @JavascriptInterface
    fun open(id: String) {
        id.toLongOrNull()?.let { picture -> app.runOnUiThread { app.view(gallery.named(picture)) } }
    }

    /** Puts pictures in line for the computer. They go when the computer can be reached, now or later. */
    @JavascriptInterface
    fun send(ids: String): String {
        val chosen = try {
            JSONArray(ids).let { list -> (0 until list.length()).map { list.getString(it) }.filter { it.toLongOrNull() != null } }
        } catch (wrong: org.json.JSONException) {
            emptyList()
        }
        if (chosen.isNotEmpty()) {
            memory.offer(chosen)
            app.runOnUiThread { app.offered(chosen.size) }
        }
        return JSONObject().put("queued", chosen.size).toString()
    }

    /** What the page asks for: its own files, and the small copies of the pictures. Nothing else is answered, and nothing goes out. */
    fun answer(request: WebResourceRequest): WebResourceResponse {
        val address = request.url
        val path = address.path.orEmpty()
        if (address.scheme != "https" || address.host != HOST) return refused()
        if (path.startsWith("/thumb/")) {
            val small = path.removePrefix("/thumb/").toLongOrNull()?.let(gallery::small) ?: return refused(404)
            return WebResourceResponse("image/jpeg", null, 200, "OK", mapOf("Cache-Control" to "max-age=86400"), ByteArrayInputStream(small))
        }
        val file = path.removePrefix("/").takeIf { it.startsWith("telefono/") && ".." !in it } ?: return refused(404)
        return try {
            WebResourceResponse(kindOf(file), if (kindOf(file).startsWith("text/")) "utf-8" else null, app.assets.open(file))
        } catch (missing: IOException) {
            refused(404)
        }
    }

    private fun refused(status: Int = 403) = WebResourceResponse("text/plain", "utf-8", status, if (status == 404) "Not Found" else "Forbidden", emptyMap(), ByteArrayInputStream(ByteArray(0)))

    private fun kindOf(file: String) = when (file.substringAfterLast('.').lowercase()) {
        "html" -> "text/html"
        "js" -> "text/javascript"
        "css" -> "text/css"
        "svg" -> "image/svg+xml"
        "woff2" -> "font/woff2"
        "png" -> "image/png"
        else -> "application/octet-stream"
    }

    companion object {
        // a name reserved for pages that an app shows from its own files: no site in the world answers to it
        const val HOST = "appassets.androidplatform.net"
        const val START = "https://$HOST/telefono/telefono.html"
    }
}

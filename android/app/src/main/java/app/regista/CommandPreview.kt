package app.regista

import android.content.res.AssetManager
import org.json.JSONObject

/** Retired experiment: kept as a migration adapter without a model runtime or downloads. */
@Suppress("UNUSED_PARAMETER")
class CommandPreview(assets: AssetManager) {
    val available = false
    fun preview(text: String): String = JSONObject().put("error", "Usa il catalogo del PC.").toString()
    fun close() {}
}

package app.regista

import android.content.Context

/** Migration adapter for old gallery records. Photo inference now runs exclusively on the PC. */
@Suppress("UNUSED_PARAMETER")
class Sight(context: Context) {
    var got = 0L
    var size = 0L
    val ready = false
    fun sentence(text: String): FloatArray = FloatArray(SIZE)
    fun picture(jpeg: ByteArray): FloatArray? = null
    companion object { const val SIZE = 512 }
}

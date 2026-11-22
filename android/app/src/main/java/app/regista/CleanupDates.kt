package app.regista

import java.text.ParsePosition
import java.text.SimpleDateFormat
import java.util.Locale

data class CleanupDay(val date: String, val source: String)

object CleanupDates {
    private val whatsappName = Regex("^(IMG|VID)-(\\d{4})(\\d{2})(\\d{2})-WA\\d+\\.[^.]+$", RegexOption.IGNORE_CASE)

    private fun valid(day: String): Boolean {
        if (!day.matches(Regex("\\d{4}-\\d{2}-\\d{2}")) || day < "1971-01-01") return false
        val parser = SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).apply { isLenient = false }
        val position = ParsePosition(0)
        return parser.parse(day, position) != null && position.index == day.length
    }

    fun forFile(whatsapp: Boolean, name: String, modified: String, recorded: String): CleanupDay {
        val filed = modified.takeIf(::valid).orEmpty()
        if (!whatsapp) {
            return if (valid(recorded) && recorded != filed) CleanupDay(recorded, "capture")
            else CleanupDay(filed, if (filed.isEmpty()) "" else "file")
        }
        val named = whatsappName.matchEntire(name)?.let { "${it.groupValues[2]}-${it.groupValues[3]}-${it.groupValues[4]}" }
            ?.takeIf(::valid).orEmpty()
        // A more recent file timestamp keeps a potentially recent WhatsApp copy out of an old range.
        return if (named.isNotEmpty() && named >= filed) CleanupDay(named, "whatsapp_name")
        else CleanupDay(filed, if (filed.isEmpty()) "" else "file")
    }

    fun includes(day: CleanupDay, since: String, until: String): Boolean =
        (since.isEmpty() && until.isEmpty()) ||
            (day.date.isNotEmpty() && (since.isEmpty() || day.date >= since) && (until.isEmpty() || day.date <= until))
}

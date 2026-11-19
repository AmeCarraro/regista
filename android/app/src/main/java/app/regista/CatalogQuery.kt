package app.regista

import java.text.Normalizer
import java.util.Locale

/** Pure query planning, tested independently of Android and without any model. */
object CatalogQuery {
    fun expressions(query: String, counts: Map<String, String>, groups: List<List<String>>): List<String> {
        require(query.length <= 1000) { "Ricerca troppo lunga." }
        val text = Normalizer.normalize(query, Normalizer.Form.NFKC).lowercase(Locale.ROOT)
        val words = Regex("[\\p{L}\\p{N}]+").findAll(text).map { it.value }.toList()
        require(words.size <= 30) { "Usa al massimo 30 parole nella ricerca." }
        require(query.isBlank() || words.isNotEmpty()) { "Scrivi parole o tag da cercare." }
        val expressions = mutableListOf<String>()
        var index = 0
        while (index < words.size) {
            val word = words[index++]
            val alternatives = if (word in counts && index < words.size && words[index] !in counts) {
                val subject = words[index++]
                counts.filterValues { it == counts.getValue(word) }.keys.map { "$it $subject" }
            } else groups.firstOrNull { word in it } ?: listOf(word)
            expressions += alternatives.joinToString(" OR ") { "\"${it.replace("\"", "\"\"")}\"" }
        }
        return expressions
    }
}

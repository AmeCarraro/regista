package app.regista

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class CatalogQueryTest {
    private val counts = linkedMapOf("2" to "due", "due" to "due", "3" to "tre", "tre" to "tre")
    private val synonyms = listOf(listOf("cane", "cani", "cucciolo"), listOf("gatto", "gatti"))

    @Test fun quantitiesStayWithTheirSubject() {
        assertEquals(listOf("\"2 gatti\" OR \"due gatti\"", "\"nero\""), CatalogQuery.expressions("due gatti nero", counts, synonyms))
        assertEquals(CatalogQuery.expressions("2 gatti", counts, synonyms), CatalogQuery.expressions("due gatti", counts, synonyms))
        assertEquals(listOf("\"gatto\" OR \"gatti\"", "\"2 cani\" OR \"due cani\""), CatalogQuery.expressions("gatti due cani", counts, synonyms))
    }

    @Test fun synonymsAndUnicodeAreNormalized() {
        assertEquals(listOf("\"cane\" OR \"cani\" OR \"cucciolo\""), CatalogQuery.expressions("ＣＡＮＩ", counts, synonyms))
        assertEquals(listOf("\"città\""), CatalogQuery.expressions("città", counts, synonyms))
        assertEquals(emptyList<String>(), CatalogQuery.expressions("   ", counts, synonyms))
    }

    @Test fun userTextNeverBecomesQueryOperatorsOrSql() {
        val expressions = CatalogQuery.expressions("\" OR * ' --", counts, synonyms)
        assertEquals(listOf("\"or\""), expressions)
        assertFalse(CatalogQuery.expressions("a); DROP TABLE photos", counts, synonyms).any { it.contains(';') || it.contains(')') })
    }

    @Test(expected = IllegalArgumentException::class) fun punctuationIsNotAnEmptySearch() {
        CatalogQuery.expressions("***", counts, synonyms)
    }

    @Test(expected = IllegalArgumentException::class) fun longQueriesAreRejected() {
        CatalogQuery.expressions("a".repeat(1001), counts, synonyms)
    }

    @Test(expected = IllegalArgumentException::class) fun tooManyWordsAreRejected() {
        CatalogQuery.expressions(List(31) { "a" }.joinToString(" "), counts, synonyms)
    }
}

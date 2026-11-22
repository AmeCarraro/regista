package app.regista

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CleanupDatesTest {
    @Test fun whatsappCutoffIncludesTheLastDayOf2024() {
        val day = CleanupDates.forFile(true, "IMG-20241231-WA0012.jpg", "", "2022-05-04")
        assertEquals(CleanupDay("2024-12-31", "whatsapp_name"), day)
        assertTrue(CleanupDates.includes(day, "", "2024-12-31"))
        assertFalse(CleanupDates.includes(day, "", "2024-12-30"))
    }

    @Test fun recentPhoneDateProtectsAnOlderWhatsappName() {
        val day = CleanupDates.forFile(true, "VID-20241101-WA0004.mp4", "2025-01-01", "2023-01-01")
        assertEquals(CleanupDay("2025-01-01", "file"), day)
        assertFalse(CleanupDates.includes(day, "", "2024-12-31"))
    }

    @Test fun whatsappIgnoresCaptureDateAndInvalidCalendarDays() {
        val day = CleanupDates.forFile(true, "IMG-20240231-WA0001.jpg", "", "2024-01-15")
        assertEquals(CleanupDay("", ""), day)
        assertFalse(CleanupDates.includes(day, "2024-01-01", "2024-12-31"))
    }
}

package app.regista

import org.junit.Assert.*
import org.junit.Test

class ImportGroupsTest {
    @Test fun hiddenMessengerFoldersKeepTheirSourceAndDocumentsHaveIndependentBlocks() {
        assertEquals("whatsapp-media",ImportGroups.key("primary:Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/Sent","image"))
        assertEquals("whatsapp-media",ImportGroups.key("Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video","video"))
        assertEquals("whatsapp-documents-pdf",ImportGroups.key("WhatsApp/Media/WhatsApp Documents","document","bolletta.pdf"))
        assertEquals("telegram-documents-excel",ImportGroups.key("primary:Android/media/org.telegram.messenger/Telegram/Telegram Documents","document","spese.XLSX"))
        assertEquals("telegram-documents-excel",ImportGroups.key("Telegram/Telegram Documents","document","vecchio.xls"))
        assertEquals("whatsapp-documents-word",ImportGroups.key("WhatsApp/Media/WhatsApp Documents","document","test.docx"))
        assertEquals("normal-media",ImportGroups.key("DCIM/Camera","image"))
    }
    @Test fun fileNamesDoNotTurnUnrelatedFoldersIntoMessengerSources() {
        assertEquals("normal",ImportGroups.source("Pictures/MyWhatsAppBackup"))
        assertEquals("normal-documents-txt",ImportGroups.key("Download","document","notes.txt"))
    }
    @Test fun anAcknowledgedQueueCanResumePendingZipFinalizationAfterRestart() {
        val state=ImportCheckpoint(work="work",peer="peer",prepared=true,total=2,copied=2,
            groups=mapOf("whatsapp-media" to 2),batches=mapOf("whatsapp-media" to "batch"),phase="finalizing")
        assertTrue(state.canResume("peer",""))
        assertFalse(state.copy(phase="done").canResume("peer",""))
        assertFalse(state.canResume("another-pc",""))
    }
}

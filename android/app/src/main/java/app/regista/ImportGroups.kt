package app.regista

/** A user sync freezes independent source/category blocks; .nomedia never affects SAF traversal. */
object ImportGroups {
    fun source(folder:String):String {
        val parts=folder.lowercase(java.util.Locale.ROOT).split(Regex("[/\\\\:]+"))
        if(parts.any { it in setOf("whatsapp","com.whatsapp","com.whatsapp.w4b") || it.startsWith("whatsapp ") }) return "whatsapp"
        if(parts.any { it in setOf("telegram","org.telegram.messenger","org.telegram.messenger.web") || it.startsWith("telegram ") }) return "telegram"
        return "normal"
    }
    fun documentType(name:String)=when(name.substringAfterLast('.').lowercase(java.util.Locale.ROOT)) {
        "pdf" -> "pdf"; "xls","xlsx" -> "excel"; "doc","docx" -> "word"; "csv" -> "csv"; "txt" -> "txt"; else -> ""
    }
    fun key(folder:String,kind:String,name:String="")=source(folder)+when(kind) { "document" -> "-documents-"+documentType(name); "audio" -> "-audio"; else -> "-media" }
    fun label(key:String)=when(key.substringBefore('-')) { "whatsapp" -> "WhatsApp"; "telegram" -> "Telegram"; else -> "Telefono" }+
        if(key.contains("-documents-")) " · "+key.substringAfter("-documents-").uppercase(java.util.Locale.ROOT) else if(key.endsWith("-audio")) " · audio" else " · foto e video"
}

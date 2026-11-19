package app.regista

import java.util.Locale

/** Path checks are for the external-storage provider only; document IDs of other providers are opaque. */
object BackupFolderPolicy {
    fun privateAndroidPath(documentId: String): Boolean {
        val relative = documentId.substringAfter(':', documentId).replace('\\', '/')
        val parts = relative.split('/').filter { it.isNotBlank() }.map { it.lowercase(Locale.ROOT) }
        return parts.size >= 2 && parts[0] == "android" && parts[1] in setOf("data", "obb")
    }

    fun label(name: String): String = name.filterNot(Char::isISOControl).replace('/', '_').replace('\\', '_')
        .trim().take(300).takeUnless { it.isEmpty() || it == "." || it == ".." } ?: "cartella"
}

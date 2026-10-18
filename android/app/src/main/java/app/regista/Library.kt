package app.regista

import android.content.ContentValues
import android.content.Context
import android.util.Base64
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * What the app knows of each picture of this phone: the day it was taken and where (the country
 * and, in Italy, the region), read once
 * from the picture itself (Gallery.notes), and, once the phone has its own models (Sight), what
 * it shows, as 512 numbers. All kept in a small database of the app's own, so that a search on
 * the phone takes a moment also among thousands of pictures. Nothing here changes a picture.
 */
class Library(context: Context, private val gallery: Gallery, private val places: Places, private val sight: Sight) :
    SQLiteOpenHelper(context, "library.db", null, 3) {

    /** How many pictures have been read, of how many there are. */
    @Volatile var done = 0
        private set

    @Volatile var total = 0
        private set

    /** How many pictures the phone has looked at with its own model, and how many it has still to. */
    @Volatile var seen = 0
        private set

    @Volatile var unseen = 0
        private set

    private val reading = AtomicBoolean(false)

    override fun onCreate(db: SQLiteDatabase) {
        // vector: what the picture shows, as 512 numbers; empty when it could not be looked at, null until it is
        db.execSQL("CREATE TABLE photo (id INTEGER PRIMARY KEY, stamp TEXT NOT NULL, name TEXT NOT NULL, day TEXT NOT NULL, lat REAL, lon REAL, country TEXT NOT NULL, region TEXT, vector BLOB)")
    }

    override fun onUpgrade(db: SQLiteDatabase, before: Int, now: Int) {
        if (before < 2) db.execSQL("ALTER TABLE photo ADD COLUMN vector BLOB")
        // null until worked out, from the position the picture has (placed)
        if (before < 3) db.execSQL("ALTER TABLE photo ADD COLUMN region TEXT")
    }

    /**
     * Reads what is new or has changed in the gallery, and then, if the phone has its models,
     * looks at the pictures it has not looked at yet, the newest first: in a thread of its own,
     * slower than the screen. Asked while it works, it does nothing.
     */
    fun refresh() {
        if (!gallery.allowed || !reading.compareAndSet(false, true)) return
        thread(name = "library", priority = Thread.MIN_PRIORITY) {
            try {
                read()
                if (sight.ready) look()
            } finally {
                reading.set(false)
            }
        }
    }

    private fun counted() {
        readableDatabase.rawQuery("SELECT count(vector), count(*) - count(vector) FROM photo", null).use { rows ->
            if (rows.moveToFirst()) {
                seen = rows.getInt(0)
                unseen = rows.getInt(1)
            }
        }
    }

    private fun look() {
        while (true) {
            counted()
            val next = ArrayList<Long>()
            readableDatabase.rawQuery("SELECT id FROM photo WHERE vector IS NULL ORDER BY day DESC LIMIT 32", null).use { rows -> while (rows.moveToNext()) next += rows.getLong(0) }
            if (next.isEmpty()) return
            for (id in next) {
                val vector = gallery.small(id)?.let(sight::picture)
                // one that cannot be looked at gets an empty answer, so that it is not tried again and again
                val bytes = vector?.let { values -> ByteBuffer.allocate(values.size * 4).order(ByteOrder.LITTLE_ENDIAN).also { it.asFloatBuffer().put(values) }.array() } ?: ByteArray(0)
                writableDatabase.update("photo", ContentValues().apply { put("vector", bytes) }, "id = ?", arrayOf(id.toString()))
            }
        }
    }

    /** The pictures the phone has not looked at yet, the newest first: their numbers and stamps, to ask the computer for. */
    fun notLookedAt(): List<Pair<Long, String>> {
        val found = ArrayList<Pair<Long, String>>()
        readableDatabase.rawQuery("SELECT id, stamp FROM photo WHERE vector IS NULL OR length(vector) = 0 ORDER BY day DESC", null).use { rows ->
            while (rows.moveToNext()) found += rows.getLong(0) to rows.getString(1)
        }
        return found
    }

    /**
     * Keeps what the computer read in some pictures as the phone's own: {"id": base64 of 512 numbers}.
     * Only for a picture still as it was when the computer was asked (the same stamp) and not looked at
     * since. Says how many were kept.
     */
    fun keep(vectors: JSONObject, stamps: Map<Long, String>): Int {
        val db = writableDatabase
        var kept = 0
        db.beginTransaction()
        try {
            for (name in vectors.keys()) {
                val id = name.toLongOrNull() ?: continue
                val stamp = stamps[id] ?: continue
                val bytes = runCatching { Base64.decode(vectors.getString(name), Base64.DEFAULT) }.getOrNull() ?: continue
                if (bytes.size != Sight.SIZE * 4) continue
                kept += db.update(
                    "photo", ContentValues().apply { put("vector", bytes) },
                    "id = ? AND stamp = ? AND (vector IS NULL OR length(vector) = 0)", arrayOf(id.toString(), stamp),
                )
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        counted()
        return kept
    }

    /** How close every picture the phone has looked at is to what a sentence says: {"id": score}. */
    fun scores(sentence: FloatArray): String {
        val all = JSONObject()
        readableDatabase.rawQuery("SELECT id, vector FROM photo WHERE length(vector) = ${Sight.SIZE * 4}", null).use { rows ->
            while (rows.moveToNext()) {
                val vector = ByteBuffer.wrap(rows.getBlob(1)).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
                var score = 0f
                for (index in 0 until Sight.SIZE) score += vector.get(index) * sentence[index]
                all.put(rows.getLong(0).toString(), score.toDouble())
            }
        }
        return all.toString()
    }

    private fun read() {
        val photos = gallery.all()
        val db = writableDatabase
        val known = HashMap<Long, String>()
        db.rawQuery("SELECT id, stamp FROM photo", null).use { rows -> while (rows.moveToNext()) known[rows.getLong(0)] = rows.getString(1) }
        // a picture no longer in the gallery is forgotten here too
        val there = photos.mapTo(HashSet()) { it.id }
        known.keys.filter { it !in there }.chunked(500).forEach { gone -> db.execSQL("DELETE FROM photo WHERE id IN (${gone.joinToString(",")})") }
        val fresh = photos.filter { known[it.id] != it.stamp }
        total = photos.size
        done = photos.size - fresh.size
        for (batch in fresh.chunked(50)) {
            db.beginTransaction()
            try {
                for (photo in batch) {
                    val notes = gallery.notes(photo)
                    val latitude = notes.latitude
                    val longitude = notes.longitude
                    val row = ContentValues().apply {
                        put("id", photo.id)
                        put("stamp", photo.stamp)
                        put("name", photo.name)
                        put("day", notes.day)
                        if (latitude != null && longitude != null) {
                            val (country, region) = places.where(latitude, longitude)
                            put("lat", latitude)
                            put("lon", longitude)
                            put("country", country)
                            put("region", region)
                        } else {
                            putNull("lat")
                            putNull("lon")
                            put("country", "")
                            put("region", "")
                        }
                    }
                    db.insertWithOnConflict("photo", null, row, SQLiteDatabase.CONFLICT_REPLACE)
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
            done += batch.size
        }
        placed(db)
    }

    /** The region of the pictures read before the app knew of regions, from the position they have: once. */
    private fun placed(db: SQLiteDatabase) {
        val missing = ArrayList<Triple<Long, Double, Double>>()
        db.rawQuery("SELECT id, lat, lon FROM photo WHERE region IS NULL AND lat IS NOT NULL", null).use { rows ->
            while (rows.moveToNext()) missing += Triple(rows.getLong(0), rows.getDouble(1), rows.getDouble(2))
        }
        db.beginTransaction()
        try {
            for ((id, latitude, longitude) in missing) {
                val (country, region) = places.where(latitude, longitude)
                db.update("photo", ContentValues().apply { put("country", country); put("region", region) }, "id = ?", arrayOf(id.toString()))
            }
            db.execSQL("UPDATE photo SET region = '' WHERE region IS NULL")
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    /** Every picture known, as the phone's page reads them: {"id", "name", "day", "lat", "lon", "country", "region"}. */
    fun json(): String {
        val all = JSONArray()
        readableDatabase.rawQuery("SELECT id, name, day, lat, lon, country, region FROM photo", null).use { rows ->
            while (rows.moveToNext()) {
                val one = JSONObject().put("id", rows.getLong(0).toString()).put("name", rows.getString(1)).put("day", rows.getString(2))
                    .put("country", rows.getString(5)).put("region", rows.getString(6) ?: "")
                if (!rows.isNull(3)) one.put("lat", rows.getDouble(3)).put("lon", rows.getDouble(4))
                all.put(one)
            }
        }
        return all.toString()
    }
}

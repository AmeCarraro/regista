package app.regista

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * What the app knows of each picture of this phone: the day it was taken and where, read once
 * from the picture itself (Gallery.notes) and kept in a small database of the app's own, so that
 * a search on the phone takes a moment also among thousands of pictures. Nothing here changes a
 * picture.
 */
class Library(context: Context, private val gallery: Gallery, private val places: Places) :
    SQLiteOpenHelper(context, "library.db", null, 1) {

    /** How many pictures have been read, of how many there are. */
    @Volatile var done = 0
        private set

    @Volatile var total = 0
        private set

    private val reading = AtomicBoolean(false)

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE photo (id INTEGER PRIMARY KEY, stamp TEXT NOT NULL, name TEXT NOT NULL, day TEXT NOT NULL, lat REAL, lon REAL, country TEXT NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, before: Int, now: Int) {}

    /** Reads what is new or has changed in the gallery, in a thread of its own. Asked while it reads, it does nothing. */
    fun refresh() {
        if (!gallery.allowed || !reading.compareAndSet(false, true)) return
        thread(name = "library") {
            try {
                read()
            } finally {
                reading.set(false)
            }
        }
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
                            put("lat", latitude)
                            put("lon", longitude)
                            put("country", places.countryOf(latitude, longitude))
                        } else {
                            putNull("lat")
                            putNull("lon")
                            put("country", "")
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
    }

    /** Every picture known, as the phone's page reads them: {"id", "name", "day", "lat", "lon", "country"}. */
    fun json(): String {
        val all = JSONArray()
        readableDatabase.rawQuery("SELECT id, name, day, lat, lon, country FROM photo", null).use { rows ->
            while (rows.moveToNext()) {
                val one = JSONObject().put("id", rows.getLong(0).toString()).put("name", rows.getString(1)).put("day", rows.getString(2)).put("country", rows.getString(5))
                if (!rows.isNull(3)) one.put("lat", rows.getDouble(3)).put("lon", rows.getDouble(4))
                all.put(one)
            }
        }
        return all.toString()
    }
}

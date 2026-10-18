package app.regista

import android.content.Context
import org.json.JSONObject
import java.util.Locale
import java.util.zip.ZipInputStream
import kotlin.math.abs
import kotlin.math.cos

/**
 * Places, on the phone itself. The countries as Android names them, in Italian and in English,
 * and the cities of a table the app carries: the same one the computer uses, from GeoNames
 * (geonames.org, licence CC BY 4.0), the cities with more than 15,000 inhabitants. With it a
 * position becomes a country and a region, and a name becomes a place, with no network.
 */
class Places(private val context: Context) {
    private var latitudes = DoubleArray(0)
    private var longitudes = DoubleArray(0)
    private var codes = emptyArray<String>()
    // the region of every city, as "IT.14": the country, then the code GeoNames gives the region in it
    private var regions = emptyArray<String>()
    private var people = IntArray(0)

    // every name of a city, in small letters -> the city it names: its own name before a name it is
    // also known by (Venice is Venice, though a larger town elsewhere is also called so by someone),
    // and then the larger city
    private val named = HashMap<String, Int>()

    @Volatile private var loaded = false

    /** Reads the table, once: a few seconds on an old phone, so the app does it in the background when it opens. */
    @Synchronized
    fun ready() {
        if (loaded) return
        val lats = ArrayList<Double>(40_000)
        val lons = ArrayList<Double>(40_000)
        val countries = ArrayList<String>(40_000)
        val areas = ArrayList<String>(40_000)
        val sizes = ArrayList<Int>(40_000)
        // a city's own names, and the other names it is known by, kept apart until the end: an own name always wins
        val others = HashMap<String, Int>()
        try {
            ZipInputStream(context.assets.open("places/cities15000.zip")).use { packed ->
                if (packed.nextEntry == null) return@use
                packed.bufferedReader().forEachLine { line ->
                    // the columns, as GeoNames documents them: 1 name, 2 name in plain letters, 3 other names,
                    // 4 and 5 position, 8 country, 10 region, 14 inhabitants
                    val cells = line.split('\t', limit = 16)
                    if (cells.size < 15) return@forEachLine
                    val city = lats.size
                    lats += cells[4].toDoubleOrNull() ?: 0.0
                    lons += cells[5].toDoubleOrNull() ?: 0.0
                    countries += cells[8].intern()
                    areas += "${cells[8]}.${cells[10]}".intern()
                    sizes += cells[14].toIntOrNull() ?: 0
                    for (key in listOf(cells[1], cells[2])) rank(named, key.lowercase(Locale.ROOT), city, sizes)
                    for (name in cells[3].split(',')) rank(others, name.lowercase(Locale.ROOT), city, sizes)
                }
            }
        } catch (missing: java.io.IOException) {
            // an app built without the table knows no city: countries still work, by their names
        }
        for ((key, city) in others) if (key !in named) named[key] = city
        latitudes = lats.toDoubleArray()
        longitudes = lons.toDoubleArray()
        codes = countries.toTypedArray()
        regions = areas.toTypedArray()
        people = sizes.toIntArray()
        loaded = true
    }

    /** Keeps for a name the larger of the cities it names. */
    private fun rank(names: HashMap<String, Int>, key: String, city: Int, sizes: List<Int>) {
        // the short names in the table are mostly airport codes, and many others are in other alphabets
        if (key.length < 4 || !LATIN.matches(key)) return
        val before = names[key]
        if (before == null || sizes[before] < sizes[city]) names[key] = city
    }

    /** The country a name is of, given in small letters: {"code", "name"}, the name as Italians write it. Null for no country. */
    fun country(name: String): JSONObject? {
        val code = COUNTRIES[name.trim().lowercase(Locale.ROOT)] ?: return null
        return JSONObject().put("code", code).put("name", Locale("", code).getDisplayCountry(Locale.ITALIAN))
    }

    /**
     * The city a name is of, as the user wrote it: {"name", "latitude", "longitude"}, or null.
     * A name written in small letters is taken only for a large city: many towns have names
     * that are also words, and "sale" is not Salé.
     */
    fun city(written: String): JSONObject? {
        ready()
        val name = written.trim()
        val index = named[name.lowercase(Locale.ROOT)] ?: return null
        if (!name.first().isUpperCase() && people[index] < LARGE) return null
        // the name as the user wrote it, as a name is written: "parigi" is "Parigi"
        val shown = name.split(' ').joinToString(" ") { part -> part.replaceFirstChar { it.titlecase(Locale.ITALIAN) } }
        return JSONObject().put("name", shown).put("latitude", latitudes[index]).put("longitude", longitudes[index])
    }

    /** The country and the region a position is in, as ("IT", "IT.14"): those of the nearest city. Empty if not known. */
    fun where(latitude: Double, longitude: Double): Pair<String, String> {
        ready()
        // the nearest on a flat map stretched as the Earth is at that latitude: near enough to tell the country
        val stretch = cos(Math.toRadians(latitude))
        var best = -1
        var nearest = Double.MAX_VALUE
        for (city in latitudes.indices) {
            val north = latitudes[city] - latitude
            var east = abs(longitudes[city] - longitude)
            if (east > 180) east = 360 - east
            val distance = north * north + (east * stretch) * (east * stretch)
            if (distance < nearest) {
                nearest = distance
                best = city
            }
        }
        return if (best >= 0) Pair(codes[best], regions[best]) else Pair("", "")
    }

    private companion object {
        val LATIN = Regex("[a-zà-ÿ' .-]+")

        // a city this large is a place also when its name is written in small letters
        const val LARGE = 1_000_000

        /** Every country by its Italian and English names in small letters, and by a few other names people use. */
        val COUNTRIES: Map<String, String> by lazy {
            val found = HashMap<String, String>()
            for (code in Locale.getISOCountries()) {
                val place = Locale("", code)
                for (language in listOf(Locale.ITALIAN, Locale.ENGLISH)) found[place.getDisplayCountry(language).lowercase(Locale.ROOT)] = code
            }
            found += mapOf(
                "america" to "US", "usa" to "US", "stati uniti d'america" to "US", "inghilterra" to "GB", "gran bretagna" to "GB",
                "scozia" to "GB", "galles" to "GB", "england" to "GB", "scotland" to "GB", "wales" to "GB", "uk" to "GB",
                "olanda" to "NL", "holland" to "NL", "repubblica ceca" to "CZ", "corea" to "KR", "vaticano" to "VA",
                "emirati" to "AE", "birmania" to "MM", "myanmar" to "MM", "russia" to "RU", "taiwan" to "TW",
            )
            found
        }
    }
}

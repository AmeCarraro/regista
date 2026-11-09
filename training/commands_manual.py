"""Italian commands written by hand for evaluation, separate from training."""

# Each slot is the exact text to recover, including spelling and capitalization.
_CASES = (
    ("Mostrami le foto dei cani", "search_photos", {"tag": "cani"}),
    ("E le foto delle mongolfiere dove sono?", "search_photos", {"tag": "mongolfiere"}),
    ("Mi fai vedere quelle del Trentino?", "search_photos", {"tag": "Trentino"}),
    ("Trova tutti gli scatti di Val d'Orcia", "search_photos", {"tag": "Val d'Orcia"}),
    ("Vorrei vedere le foto con le volpi", "search_photos", {"tag": "volpi"}),
    ("Mi tiri fuori le foto che ho segnato Da scegliere?", "search_photos", {"tag": "Da scegliere"}),
    ("Regista, aprimi le foto di Lago di Tovel", "search_photos", {"tag": "Lago di Tovel"}),
    ("Posso vedere gli scatti etichettati 'Gita di classe'?", "search_photos", {"tag": "Gita di classe"}),
    ("Dov'erano le foto del Giappone? Mostramele.", "search_photos", {"tag": "Giappone"}),
    ("Cerca in galleria le foto di García Márquez", "search_photos", {"tag": "García Márquez"}),
    ("A queste metti il tag Kyoto, grazie", "add_tag", {"tag": "Kyoto"}),
    ("Il tag Nikkō va aggiunto a tutte le foto selezionate", "add_tag", {"tag": "Nikkō"}),
    ("Vorrei etichettare tutte quelle che ho selezionato come Mercatini a Bolzano", "add_tag", {"tag": "Mercatini a Bolzano"}),
    ("Queste immagini vanno segnate con 'Rifugio Fanes'", "add_tag", {"tag": "Rifugio Fanes"}),
    ("Aggiungimi alle foto scelte il tag Per l'album della nonna", "add_tag", {"tag": "Per l'album della nonna"}),
    ("Per tutte le immagini selezionate scrivi Giornata al museo come tag", "add_tag", {"tag": "Giornata al museo"}),
    ("Puoi mettere sulle foto selezionate un'etichetta che si chiama Foto per il saggio?", "add_tag", {"tag": "Foto per il saggio"}),
    ("Aggiungi Da mandare a Chiara alle foto spuntate", "add_tag", {"tag": "Da mandare a Chiara"}),
    ("Assegna L'ultima sera a questi scatti", "add_tag", {"tag": "L'ultima sera"}),
    ("Segna tutte queste qui come Costa d'Avorio", "add_tag", {"tag": "Costa d'Avorio"}),
    ("Mi levi il tag Scozia dalle foto che ho scelto?", "remove_tag", {"tag": "Scozia"}),
    ("Per favore togli Stampare in grande solo dalle foto spuntate", "remove_tag", {"tag": "Stampare in grande"}),
    ("Elimina da queste foto l'etichetta Da inviare", "remove_tag", {"tag": "Da inviare"}),
    ("Su tutte le foto selezionate rimuovi 'Vacanza in Grecia'", "remove_tag", {"tag": "Vacanza in Grecia"}),
    ("Sulle immagini selezionate non voglio più il tag Rimini 2024", "remove_tag", {"tag": "Rimini 2024"}),
    ("Queste che ho scelto, toglici il tag Sera d'estate", "remove_tag", {"tag": "Sera d'estate"}),
    ("Puoi cancellare l'etichetta Lago di Garda da questi scatti?", "remove_tag", {"tag": "Lago di Garda"}),
    ("Il tag Doppioni da controllare non ci va più su queste foto", "remove_tag", {"tag": "Doppioni da controllare"}),
    ("Riproduci Imagine di John Lennon", "play_song", {"title": "Imagine", "artist": "John Lennon"}),
    ("Mi metti La cura di Franco Battiato?", "play_song", {"title": "La cura", "artist": "Franco Battiato"}),
    ("Vorrei sentire Una musica può fare di Max Gazzè", "play_song", {"title": "Una musica può fare", "artist": "Max Gazzè"}),
    ("Di Björk, fammi ascoltare Jóga", "play_song", {"title": "Jóga", "artist": "Björk"}),
    ("Avvia Smells Like Teen Spirit", "play_song", {"title": "Smells Like Teen Spirit"}),
    ("Metti 'Senza fine', quella di Gino Paoli", "play_song", {"title": "Senza fine", "artist": "Gino Paoli"}),
    ("Dai, fai partire il pezzo Blue in Green", "play_song", {"title": "Blue in Green"}),
    ("Puoi riprodurre 'Àguas de Março' di Elis Regina?", "play_song", {"title": "Àguas de Março", "artist": "Elis Regina"}),
    ("Voglio ascoltare La canzone di Marinella di Fabrizio De André", "play_song", {"title": "La canzone di Marinella", "artist": "Fabrizio De André"}),
    ("Regista, suona 'Svefn-g-englar' dei Sigur Rós", "play_song", {"title": "Svefn-g-englar", "artist": "Sigur Rós"}),
    ("Metti la stessa cosa su tutte quelle che vedi", "clarify", {}),
    ("Apri la canzone che piace a me", "clarify", {}),
    ("Cosa vuoi dire con tag?", "clarify", {}),
    ("Non mettere Giappone sulle foto per il momento", "clarify", {}),
    ("Ho cambiato idea, lascia perdere", "clarify", {}),
    ("Manda queste foto a mia sorella", "clarify", {}),
    ("Che artista canta La cura?", "clarify", {}),
    ("Toglimi quello dalle foto", "clarify", {}),
    ("Fai vedere quelle, sai quali intendo", "clarify", {}),
    ("Non riprodurre Imagine adesso", "clarify", {}),
)


def examples():
    """Return each labeled command with offsets into its original text."""
    rows = []
    for text, intent, values in _CASES:
        spans = []
        for slot, value in values.items():
            start = text.index(value)
            spans.append((slot, start, start + len(value)))
        rows.append((text, intent, spans))
    return rows

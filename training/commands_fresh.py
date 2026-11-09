"""A second handwritten Italian command set reserved for evaluation."""


CASES = (
    ("Mi cerchi le foto delle tartarughe marine?", "search_photos", {"tag": "tartarughe marine"}),
    ("E quelle di Castel del Monte me le fai vedere?", "search_photos", {"tag": "Castel del Monte"}),
    ("Vorrei rivedere gli scatti che ho segnato Gita alla diga", "search_photos", {"tag": "Gita alla diga"}),
    ("Ci sono foto con il tag Cena di fine corso?", "search_photos", {"tag": "Cena di fine corso"}),
    ("Aprimi la raccolta Alba sul Brenta", "search_photos", {"tag": "Alba sul Brenta"}),
    ("Per favore trovami le fotografie di San Vito Lo Capo", "search_photos", {"tag": "San Vito Lo Capo"}),
    ("Fammi vedere le foto dei ricci", "search_photos", {"tag": "ricci"}),
    ("Mostrami tutte le immagini col tag «Ritratti in controluce»", "search_photos", {"tag": "Ritratti in controluce"}),
    ("Cerco le foto con i girasoli", "search_photos", {"tag": "girasoli"}),
    ("Mi tiri fuori quelle con il tag Strade di montagna?", "search_photos", {"tag": "Strade di montagna"}),
    ("Alle foto che ho appena scelto aggiungi il tag Giro dell'Elba", "add_tag", {"tag": "Giro dell'Elba"}),
    ("Su tutte queste immagini scrivi Notte dei musei come etichetta", "add_tag", {"tag": "Notte dei musei"}),
    ("Ti va di mettere il tag Da spedire a Lorenzo su queste foto?", "add_tag", {"tag": "Da spedire a Lorenzo"}),
    ("A tutte quelle spuntate assegna il tag Sera in piazza", "add_tag", {"tag": "Sera in piazza"}),
    ("Queste foto mettile sotto 'Ricordi del campeggio'", "add_tag", {"tag": "Ricordi del campeggio"}),
    ("Per queste immagini vorrei il tag Museo della carta", "add_tag", {"tag": "Museo della carta"}),
    ("Come tag a tutte queste dai Foto da ritagliare", "add_tag", {"tag": "Foto da ritagliare"}),
    ("Metti il tag Ponte di Rialto anche su quelle che ho selezionato", "add_tag", {"tag": "Ponte di Rialto"}),
    ("Le foto selezionate le puoi etichettare come Corso di ceramica?", "add_tag", {"tag": "Corso di ceramica"}),
    ("Aggiungi alle immagini spuntate l'etichetta Sotto la pioggia, grazie", "add_tag", {"tag": "Sotto la pioggia"}),
    ("Dalle foto che ho selezionato leva il tag Compleanno di Teo", "remove_tag", {"tag": "Compleanno di Teo"}),
    ("Il tag Pausa pranzo toglilo solo da queste immagini", "remove_tag", {"tag": "Pausa pranzo"}),
    ("Puoi rimuovere da tutte quelle spuntate il tag Porto vecchio?", "remove_tag", {"tag": "Porto vecchio"}),
    ("Queste non vanno sotto Primi piani, togli quel tag", "remove_tag", {"tag": "Primi piani"}),
    ("Cancella l'etichetta 'Foto per il calendario' dagli scatti selezionati", "remove_tag", {"tag": "Foto per il calendario"}),
    ("Senti, mi levi dalle immagini selezionate il tag Prima della partenza?", "remove_tag", {"tag": "Prima della partenza"}),
    ("Il tag Fuori stagione qui non c'entra, rimuovilo da tutte queste foto", "remove_tag", {"tag": "Fuori stagione"}),
    ("Da questi scatti vorrei togliere l'etichetta La strada di casa", "remove_tag", {"tag": "La strada di casa"}),
    ("Togli solo il tag Cose da ricordare dalle foto spuntate", "remove_tag", {"tag": "Cose da ricordare"}),
    ("Metti La costruzione di un amore di Ivano Fossati", "play_song", {"title": "La costruzione di un amore", "artist": "Ivano Fossati"}),
    ("Mi fai ascoltare 'Le tasche piene di sassi' di Jovanotti?", "play_song", {"title": "Le tasche piene di sassi", "artist": "Jovanotti"}),
    ("Fai partire La notte dei desideri", "play_song", {"title": "La notte dei desideri"}),
    ("Di Pino Daniele voglio sentire Quando", "play_song", {"title": "Quando", "artist": "Pino Daniele"}),
    ("Puoi mettere 'I Want You Back' dei Jackson 5?", "play_song", {"title": "I Want You Back", "artist": "Jackson 5"}),
    ("Regista riproduci Due vite di Marco Mengoni", "play_song", {"title": "Due vite", "artist": "Marco Mengoni"}),
    ("Vorrei ascoltare La guerra di Piero", "play_song", {"title": "La guerra di Piero"}),
    ("Per favore avvia la canzone Una giornata uggiosa", "play_song", {"title": "Una giornata uggiosa"}),
    ("Mi metti il pezzo 'Oração ao Tempo' di Caetano Veloso?", "play_song", {"title": "Oração ao Tempo", "artist": "Caetano Veloso"}),
    ("Suona Il cielo in una stanza, quella di Mina", "play_song", {"title": "Il cielo in una stanza", "artist": "Mina"}),
    ("Non togliere il tag Foto da ritagliare da quelle che ho scelto", "clarify", {}),
    ("Non far partire Due vite, cambio idea", "clarify", {}),
    ("Per ora non aggiungere l'etichetta Corso di ceramica", "clarify", {}),
    ("Metti il tag che avevamo detto prima", "clarify", {}),
    ("Cercami una di quelle foto, non so quale", "clarify", {}),
    ("Quella del disco blu me la fai sentire?", "clarify", {}),
    ("Manda a Matteo le foto di Castel del Monte", "clarify", {}),
    ("Quanto dura La notte dei desideri?", "clarify", {}),
    ("Per sbaglio ho selezionato troppe foto", "clarify", {}),
    ("Elimina tutte le foto con il tag Pausa pranzo", "clarify", {}),
)


def examples():
    """Return commands with half-open offsets into the original wording."""
    rows = []
    for text, intent, values in CASES:
        spans = []
        for slot, value in values.items():
            start = text.index(value)
            spans.append((slot, start, start + len(value)))
        rows.append((text, intent, spans))
    return rows

// The twenty regions of Italy, as app/places.py knows them on the computer: by the code GeoNames
// gives each (the country, then the code of the region in it), with its name, the names a request
// may call it by, in Italian and in English, and how it is said after "scattate".

export type Region = { name: string; names: string[]; at: string }

export const REGIONS: Record<string, Region> = {
  'IT.01': { name: 'Abruzzo', names: ['abruzzo'], at: 'in Abruzzo' },
  'IT.02': { name: 'Basilicata', names: ['basilicata'], at: 'in Basilicata' },
  'IT.03': { name: 'Calabria', names: ['calabria'], at: 'in Calabria' },
  'IT.04': { name: 'Campania', names: ['campania'], at: 'in Campania' },
  'IT.05': { name: 'Emilia-Romagna', names: ['emilia-romagna', 'emilia romagna', 'emilia', 'romagna'], at: 'in Emilia-Romagna' },
  'IT.06': { name: 'Friuli-Venezia Giulia', names: ['friuli-venezia giulia', 'friuli venezia giulia', 'friuli', 'venezia giulia'], at: 'in Friuli-Venezia Giulia' },
  'IT.07': { name: 'Lazio', names: ['lazio', 'latium'], at: 'nel Lazio' },
  'IT.08': { name: 'Liguria', names: ['liguria'], at: 'in Liguria' },
  'IT.09': { name: 'Lombardia', names: ['lombardia', 'lombardy'], at: 'in Lombardia' },
  'IT.10': { name: 'Marche', names: ['marche', 'the marches'], at: 'nelle Marche' },
  'IT.11': { name: 'Molise', names: ['molise'], at: 'in Molise' },
  'IT.12': { name: 'Piemonte', names: ['piemonte', 'piedmont'], at: 'in Piemonte' },
  'IT.13': { name: 'Puglia', names: ['puglia', 'apulia'], at: 'in Puglia' },
  'IT.14': { name: 'Sardegna', names: ['sardegna', 'sardinia'], at: 'in Sardegna' },
  'IT.15': { name: 'Sicilia', names: ['sicilia', 'sicily'], at: 'in Sicilia' },
  'IT.16': { name: 'Toscana', names: ['toscana', 'tuscany'], at: 'in Toscana' },
  'IT.17': { name: 'Trentino-Alto Adige', names: ['trentino-alto adige', 'trentino alto adige', 'trentino', 'alto adige', 'south tyrol'], at: 'in Trentino-Alto Adige' },
  'IT.18': { name: 'Umbria', names: ['umbria'], at: 'in Umbria' },
  'IT.19': { name: "Valle d'Aosta", names: ["valle d'aosta", "val d'aosta", 'aosta valley'], at: "in Valle d'Aosta" },
  'IT.20': { name: 'Veneto', names: ['veneto'], at: 'in Veneto' },
}

/** The code of the region a name is of, given in small letters: "sardegna" is "IT.14". */
export const REGION_NAMED = new Map(Object.entries(REGIONS).flatMap(([code, region]) => region.names.map((name) => [name, code] as const)))

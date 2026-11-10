function normalized(name: string): string {
  return name.toLowerCase().normalize('NFC').replace(/[‘’]/g, "'").trim().replace(/\s+/g, ' ')
}

/** All exact title matches, restricted to the exact artist when the command named one. */
export function commandSongs<T extends { title: string; artist: string }>(songs: readonly T[], title: string, artist?: string): T[] {
  const name = normalized(title)
  const by = artist === undefined ? undefined : normalized(artist)
  if (!name || by === '') return []
  return songs.filter((song) => normalized(song.title) === name && (by === undefined || normalized(song.artist) === by))
}

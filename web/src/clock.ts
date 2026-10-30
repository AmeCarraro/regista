/** A length of time as players write it: "3:07" for 187 seconds, "1:02:05" past an hour. */
export function clock(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = String(seconds % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}

/** The songs whose title, artist, album or folder have all the words written, in any order and case. */
export function matching<T extends { title: string; artist: string; album: string; folder?: string }>(songs: T[], written: string): T[] {
  const words = written.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return songs
  return songs.filter((song) => {
    const said = `${song.title} ${song.artist} ${song.album} ${song.folder ?? ''}`.toLowerCase()
    return words.every((word) => said.includes(word))
  })
}

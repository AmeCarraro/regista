import { useEffect, useState } from 'react'
import Musica from './Musica.tsx'
import Telefono from './Telefono.tsx'

/** The pictures and the music: the app's tabs choose which shows, and both stay as they were left. In a browser, #musica. */
export default function Screens() {
  const [music, setMusic] = useState(() => location.hash === '#musica')
  useEffect(() => {
    window.registaView = (tab) => setMusic(tab === 'music')
  }, [])
  return (
    <>
      <div hidden={music}>
        <Telefono />
      </div>
      <div hidden={!music}>
        <Musica visible={music} />
      </div>
    </>
  )
}

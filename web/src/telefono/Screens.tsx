import { useEffect, useState } from 'react'
import { connect } from './bridge.ts'
import Musica from './Musica.tsx'
import Telefono from './Telefono.tsx'

/** The pictures and the music: the app's tabs choose which shows, and both stay as they were left. In a browser, #musica. */
export default function Screens() {
  // the app may have been opened on its music tab, by the widget, before this page was there to be told
  const [music, setMusic] = useState(() => connect().tab() === 'music')
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

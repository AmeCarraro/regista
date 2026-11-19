import { useEffect, useState } from 'react'
import { connect } from './bridge.ts'
import Musica from './Musica.tsx'
import Telefono from './Telefono.tsx'
import Video from './Video.tsx'

/** The pictures and the music: the app's tabs choose which shows, and both stay as they were left. In a browser, #musica. */
export default function Screens() {
  // the app may have been opened on its music tab, by the widget, before this page was there to be told
  const [tab, setTab] = useState(() => connect().tab())
  useEffect(() => {
    window.registaView = setTab
    return () => { delete window.registaView }
  }, [])
  return (
    <>
      <div hidden={tab !== 'phone'}>
        <Telefono visible={tab === 'phone'} />
      </div>
      <div hidden={tab !== 'music'}>
        <Musica visible={tab === 'music'} />
      </div>
      <Video visible={tab === 'video'} />
    </>
  )
}

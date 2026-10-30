import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// the typefaces travel with the app, as with the computer's page: nothing is fetched from elsewhere
import '@fontsource-variable/inter'
import '@fontsource-variable/space-grotesk'
import '../index.css'
import './telefono.css'
import Screens from './Screens.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Screens />
  </StrictMode>,
)

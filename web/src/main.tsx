import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// the three typefaces travel with the page: nothing is fetched from another site
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import '@fontsource-variable/space-grotesk'
import './index.css'
import './side.css'
import './chat.css'
import './music.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

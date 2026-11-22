import type { ReactNode } from 'react'
import { Logo } from '../icons.tsx'

export default function PhoneHeader({ section, children }: { section: string; children?: ReactNode }) {
  return <header className="top">
    <Logo className="logo" />
    <div className="name"><b>Regista</b><span>{section}</span></div>
    {children}
  </header>
}

import { createContext } from 'react'

/**
 * What the page knows about the pictures beyond a single search: which ones went
 * to the trash since they were shown, and a mark that changes whenever the library
 * does, so that a small copy that could not be loaded is asked for again.
 */
export const Shelf = createContext<{ gone: ReadonlySet<string>; epoch: string }>({ gone: new Set(), epoch: '' })

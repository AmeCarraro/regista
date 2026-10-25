import { createContext } from 'react'

/** Why a picture is no longer where it was shown: thrown away, or moved into another folder. */
export type Gone = 'trash' | 'move'

/**
 * What the page knows about the pictures beyond a single search: which ones went
 * to the trash or to another folder since they were shown, and a mark that changes
 * whenever the library does, so that a small copy that could not be loaded is asked for again.
 */
export const Shelf = createContext<{ gone: ReadonlyMap<string, Gone>; epoch: string }>({ gone: new Map(), epoch: '' })

export type CatalogRequest = <T>(path: string, body?: unknown, method?: string) => Promise<T>

export const catalogRequest: CatalogRequest = async <T,>(path: string, body?: unknown, method = 'POST'): Promise<T> => {
  const response = await fetch(path, body === undefined ? undefined : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) throw new Error(result.detail || 'Il computer non risponde.')
  return result as T
}

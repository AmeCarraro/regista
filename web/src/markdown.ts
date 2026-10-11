// A model writes a small subset of markdown: code blocks, inline code and bold.
// Parsing just that keeps the page free of an HTML injection risk: nothing the
// model writes is ever inserted as HTML.

export type Block = { kind: 'code'; text: string } | { kind: 'text'; text: string }

export type Inline =
  | { kind: 'plain'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'bold'; text: string }

/** Splits a reply into code blocks and text. A fence still open, while the model is writing, counts as code. */
export function splitBlocks(markdown: string): Block[] {
  const blocks: Block[] = []
  markdown.split('```').forEach((part, index) => {
    if (index % 2 === 1) {
      // the first line of a fence is the language tag, not code
      const firstLineEnd = part.indexOf('\n')
      const code = firstLineEnd === -1 ? '' : part.slice(firstLineEnd + 1)
      blocks.push({ kind: 'code', text: code.replace(/\n$/, '') })
    } else if (part.trim()) {
      blocks.push({ kind: 'text', text: part.trim() })
    }
  })
  return blocks
}

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/

/** Splits a line of text into plain text, inline code and bold. */
export function splitInline(text: string): Inline[] {
  return text
    .split(INLINE)
    .filter((piece) => piece !== '')
    .map((piece): Inline => {
      if (piece.length > 2 && piece.startsWith('`') && piece.endsWith('`')) {
        return { kind: 'code', text: piece.slice(1, -1) }
      }
      if (piece.length > 4 && piece.startsWith('**') && piece.endsWith('**')) {
        return { kind: 'bold', text: piece.slice(2, -2) }
      }
      return { kind: 'plain', text: piece }
    })
}

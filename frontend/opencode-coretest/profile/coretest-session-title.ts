const defaultTitle = /^(New session|Child session) - \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/

export function coreTestSessionTitle(title?: string) {
  if (!title) return title
  const kind = title.match(defaultTitle)?.[1]
  if (kind === "New session") return "\u65b0\u5efa\u4f1a\u8bdd"
  if (kind === "Child session") return "\u5b50\u4f1a\u8bdd"
  return title
}

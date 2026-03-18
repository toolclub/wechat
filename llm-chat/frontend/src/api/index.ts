const API_BASE = ''

export async function fetchModels(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/models`)
  const data = await res.json()
  return data.models || []
}

export async function fetchConversations() {
  const res = await fetch(`${API_BASE}/api/conversations`)
  const data = await res.json()
  return data.conversations || []
}

export async function createConversation(title: string = '新对话') {
  const res = await fetch(`${API_BASE}/api/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  return res.json()
}

export async function fetchConversation(id: string) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}`)
  return res.json()
}

export async function deleteConversation(id: string) {
  await fetch(`${API_BASE}/api/conversations/${id}`, { method: 'DELETE' })
}

export async function sendMessage(
  conversationId: string,
  message: string,
  model: string,
  onChunk: (text: string) => void,
  onDone: () => void,
) {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      model,
    }),
  })

  const reader = res.body?.getReader()
  const decoder = new TextDecoder()

  if (!reader) return

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const text = decoder.decode(value)
    for (const line of text.split('\n')) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.content) onChunk(data.content)
        if (data.done) onDone()
      } catch {}
    }
  }
}

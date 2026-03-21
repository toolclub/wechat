import { ref } from 'vue'
import type { Message, ConversationInfo, SendPayload } from '../types'
import * as api from '../api'

export function useChat() {
  const conversations = ref<ConversationInfo[]>([])
  const currentConvId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const loading = ref(false)
  const models = ref<string[]>([])
  const selectedModel = ref('qwen2.5:14b')

  async function loadModels() {
    models.value = await api.fetchModels()
    if (models.value.length && !models.value.includes(selectedModel.value)) {
      selectedModel.value = models.value[0]
    }
  }

  async function loadConversations() {
    conversations.value = await api.fetchConversations()
  }

  async function selectConversation(id: string) {
    currentConvId.value = id
    const data = await api.fetchConversation(id)
    messages.value = (data.messages || []).map((m: Message) => ({
      role: m.role,
      content: m.content,
      images: m.images,
      timestamp: m.timestamp,
    }))
  }

  async function newConversation() {
    const data = await api.createConversation()
    currentConvId.value = data.id
    messages.value = []
    await loadConversations()
  }

  async function removeConversation(id: string) {
    await api.deleteConversation(id)
    if (currentConvId.value === id) {
      currentConvId.value = null
      messages.value = []
    }
    await loadConversations()
  }

  async function send({ text, images }: SendPayload) {
    if (!text.trim() && images.length === 0) return
    if (loading.value) return

    // 如果没有当前对话，先创建
    if (!currentConvId.value) {
      const data = await api.createConversation(text.slice(0, 30) || '图片对话')
      currentConvId.value = data.id
    }

    // 添加用户消息
    messages.value.push({ role: 'user', content: text, images: images.length > 0 ? images : undefined })

    // 添加空的 assistant 消息（流式填充）
    messages.value.push({ role: 'assistant', content: '' })
    const assistantIdx = messages.value.length - 1

    loading.value = true

    try {
      await api.sendMessage(
        currentConvId.value!,
        text,
        selectedModel.value,
        images,
        (chunk) => {
          messages.value[assistantIdx].content += chunk
        },
        () => {
          loading.value = false
          loadConversations()
        },
      )
    } catch {
      messages.value[assistantIdx].content = '⚠️ 请求失败，请检查后端和 Ollama 是否正常运行。'
      loading.value = false
    }
  }

  return {
    conversations, currentConvId, messages, loading,
    models, selectedModel,
    loadModels, loadConversations, selectConversation,
    newConversation, removeConversation, send,
  }
}

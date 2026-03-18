export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp?: number
}

export interface ConversationInfo {
  id: string
  title: string
  updated_at: number
}

export interface ConversationDetail {
  id: string
  title: string
  system_prompt: string
  messages: Message[]
  mid_term_summary: string
}

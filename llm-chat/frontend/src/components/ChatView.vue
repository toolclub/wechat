<script setup lang="ts">
import { nextTick, watch, ref } from 'vue'
import type { Message } from '../types'
import MessageItem from './MessageItem.vue'
import InputBox from './InputBox.vue'

const props = defineProps<{
  messages: Message[]
  loading: boolean
  selectedModel: string
}>()

const emit = defineEmits<{ send: [text: string] }>()

const messagesContainer = ref<HTMLDivElement>()

watch(
  () => props.messages.length > 0 ? props.messages[props.messages.length - 1].content : '',
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)
</script>

<template>
  <div class="chat-view">
    <!-- 顶部栏 -->
    <div class="chat-header">
      <span class="model-name">{{ selectedModel || '本地模型' }}</span>
    </div>

    <!-- 消息区 -->
    <div class="messages" ref="messagesContainer">
      <div v-if="messages.length === 0" class="empty-state">
        <div class="empty-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#d0d0d0" stroke-width="1.5">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <h2>有什么可以帮你的？</h2>
        <p>选择左侧对话，或点击「新对话」开始</p>
      </div>

      <div class="messages-inner">
        <MessageItem
          v-for="(msg, i) in messages"
          :key="i"
          :message="msg"
        />
        <!-- 生成中光标 -->
        <div v-if="loading && messages.length > 0 && messages[messages.length-1].role === 'assistant' && !messages[messages.length-1].content" class="typing-indicator">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>

    <!-- 输入框 -->
    <InputBox :loading="loading" @send="emit('send', $event)" />
  </div>
</template>

<style scoped>
.chat-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #ffffff;
}

.chat-header {
  padding: 14px 24px;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.model-name {
  font-size: 15px;
  font-weight: 600;
  color: #0d0d0d;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0 8px;
}

.messages-inner {
  max-width: 760px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
  gap: 10px;
  color: #999;
}
.empty-icon {
  margin-bottom: 6px;
}
.empty-state h2 {
  font-size: 20px;
  color: #555;
  font-weight: 600;
}
.empty-state p {
  font-size: 14px;
  color: #aaa;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0 0 52px;
}
.typing-indicator span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #bbb;
  animation: bounce 1.2s infinite;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-6px); }
}
</style>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useChat } from './composables/useChat'
import Sidebar from './components/Sidebar.vue'
import ChatView from './components/ChatView.vue'

const chat = useChat()

onMounted(() => {
  chat.loadModels()
  chat.loadConversations()
})
</script>

<template>
  <div class="app">
    <Sidebar
      :conversations="chat.conversations.value"
      :currentConvId="chat.currentConvId.value"
      :models="chat.models.value"
      :selectedModel="chat.selectedModel.value"
      @new-chat="chat.newConversation()"
      @select="chat.selectConversation($event)"
      @delete="chat.removeConversation($event)"
      @update:selectedModel="chat.selectedModel.value = $event"
    />
    <ChatView
      :messages="chat.messages.value"
      :loading="chat.loading.value"
      :selectedModel="chat.selectedModel.value"
      @send="chat.send($event)"
    />
  </div>
</template>

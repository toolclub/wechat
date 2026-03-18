<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ConversationInfo } from '../types'

const props = defineProps<{
  conversations: ConversationInfo[]
  currentConvId: string | null
  models: string[]
  selectedModel: string
}>()

const emit = defineEmits<{
  newChat: []
  select: [id: string]
  delete: [id: string]
  'update:selectedModel': [model: string]
}>()

const searchQuery = ref('')

const filteredConversations = computed(() =>
  props.conversations.filter(c =>
    c.title.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
)
</script>

<template>
  <div class="sidebar">
    <div class="sidebar-top">
      <button class="new-chat-btn" @click="emit('newChat')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M12 5v14M5 12h14"/>
        </svg>
        新对话
      </button>
    </div>

    <div class="search-wrap">
      <svg class="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      <input v-model="searchQuery" class="search-input" placeholder="搜索对话..." />
    </div>

    <div class="conv-list">
      <p v-if="filteredConversations.length === 0" class="empty-hint">
        {{ searchQuery ? '无匹配结果' : '暂无对话' }}
      </p>
      <div
        v-for="conv in filteredConversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: conv.id === currentConvId }"
        @click="emit('select', conv.id)"
      >
        <svg class="bubble-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span class="conv-title">{{ conv.title }}</span>
        <button class="del-btn" @click.stop="emit('delete', conv.id)" title="删除">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="sidebar-footer">
      <p class="footer-label">当前模型</p>
      <select
        class="model-select"
        :value="selectedModel"
        @change="emit('update:selectedModel', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 260px;
  flex-shrink: 0;
  background: #171717;
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.sidebar-top {
  padding: 12px 12px 6px;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 14px;
  background: transparent;
  color: #ececec;
  border: 1px solid #333;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13.5px;
  font-family: inherit;
  transition: background 0.15s;
}
.new-chat-btn:hover {
  background: #2a2a2a;
}

.search-wrap {
  position: relative;
  padding: 6px 12px 8px;
}
.search-icon {
  position: absolute;
  left: 22px;
  top: 50%;
  transform: translateY(-55%);
  color: #555;
  pointer-events: none;
}
.search-input {
  width: 100%;
  padding: 7px 10px 7px 28px;
  background: #2a2a2a;
  color: #d0d0d0;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
}
.search-input::placeholder { color: #555; }

.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}

.empty-hint {
  text-align: center;
  color: #444;
  font-size: 12px;
  padding: 20px 0;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin: 1px 0;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  color: #b0b0b0;
}
.conv-item:hover {
  background: #252525;
  color: #e0e0e0;
}
.conv-item.active {
  background: #2a2a2a;
  color: #ffffff;
}
.bubble-icon {
  flex-shrink: 0;
  color: #4a4a4a;
}
.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.del-btn {
  background: none;
  border: none;
  color: #4a4a4a;
  cursor: pointer;
  padding: 2px;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s;
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.conv-item:hover .del-btn { opacity: 1; }
.del-btn:hover { color: #e74c3c; }

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid #272727;
}
.footer-label {
  font-size: 11px;
  color: #4a4a4a;
  margin-bottom: 5px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.model-select {
  width: 100%;
  padding: 7px 10px;
  background: #252525;
  color: #d0d0d0;
  border: 1px solid #333;
  border-radius: 8px;
  font-size: 12px;
  font-family: inherit;
  outline: none;
  cursor: pointer;
}
</style>

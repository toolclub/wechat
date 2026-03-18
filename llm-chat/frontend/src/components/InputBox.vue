<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ loading: boolean }>()
const emit = defineEmits<{ send: [text: string] }>()

const input = ref('')

function handleSend() {
  if (!input.value.trim() || props.loading) return
  emit('send', input.value)
  input.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="input-wrapper">
    <div class="input-box" :class="{ disabled: loading }">
      <textarea
        v-model="input"
        @keydown="handleKeydown"
        placeholder="有问题，尽管问... （Enter 发送，Shift+Enter 换行）"
        :disabled="loading"
        rows="1"
        class="input-textarea"
      />
      <button
        class="send-btn"
        @click="handleSend"
        :disabled="loading || !input.trim()"
        :title="loading ? '生成中...' : '发送'"
      >
        <svg v-if="!loading" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
        </svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor" class="spin">
          <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z" opacity=".3"/>
          <path d="M12 2a10 10 0 0 1 10 10h-2a8 8 0 0 0-8-8z"/>
        </svg>
      </button>
    </div>
    <p class="hint">AI 可能出错，请核实重要信息。</p>
  </div>
</template>

<style scoped>
.input-wrapper {
  padding: 8px 24px 16px;
  max-width: 760px;
  margin: 0 auto;
  width: 100%;
}

.input-box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: #f4f4f4;
  border: 1px solid #e5e5e5;
  border-radius: 16px;
  padding: 10px 12px 10px 16px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.input-box:focus-within {
  border-color: #c0c0c0;
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.06);
}
.input-box.disabled {
  opacity: 0.7;
}

.input-textarea {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.6;
  color: #0d0d0d;
  resize: none;
  max-height: 200px;
  overflow-y: auto;
}
.input-textarea::placeholder {
  color: #aaa;
}

.send-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #0d0d0d;
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, opacity 0.15s;
}
.send-btn:hover:not(:disabled) {
  background: #333;
}
.send-btn:disabled {
  background: #d0d0d0;
  cursor: not-allowed;
}

.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.hint {
  text-align: center;
  font-size: 11px;
  color: #bbb;
  margin-top: 8px;
}
</style>

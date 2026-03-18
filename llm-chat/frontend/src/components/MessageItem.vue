<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import type { Message } from '../types'

const props = defineProps<{ message: Message }>()

const renderedContent = computed(() => {
  if (props.message.role === 'assistant') {
    return marked.parse(props.message.content || '') as string
  }
  return ''
})
</script>

<template>
  <div class="msg-row" :class="message.role">
    <!-- 用户消息：右对齐气泡 -->
    <template v-if="message.role === 'user'">
      <div class="user-bubble">{{ message.content }}</div>
    </template>

    <!-- AI 消息：左对齐，带图标 -->
    <template v-else>
      <div class="ai-row">
        <div class="ai-avatar">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2zM9 14a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm6 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z"/>
          </svg>
        </div>
        <div class="ai-content markdown-body" v-html="renderedContent"></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.msg-row {
  padding: 6px 0;
  width: 100%;
}

/* 用户消息 */
.msg-row.user {
  display: flex;
  justify-content: flex-end;
  padding-right: 16px;
}
.user-bubble {
  max-width: 70%;
  background: #f0f0f0;
  color: #0d0d0d;
  padding: 10px 16px;
  border-radius: 18px 18px 4px 18px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

/* AI 消息 */
.msg-row.assistant {
  display: flex;
  justify-content: flex-start;
  padding-left: 4px;
}
.ai-row {
  display: flex;
  gap: 12px;
  max-width: 85%;
  align-items: flex-start;
}
.ai-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #19c37d;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  margin-top: 2px;
}
.ai-content {
  flex: 1;
  font-size: 14px;
  line-height: 1.7;
  color: #0d0d0d;
  min-width: 0;
}
</style>

<style>
/* Markdown 渲染样式（非 scoped，作用于 v-html 内容） */
.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  font-weight: 600;
  margin: 16px 0 8px;
  line-height: 1.3;
}
.markdown-body h1 { font-size: 1.4em; }
.markdown-body h2 { font-size: 1.2em; }
.markdown-body h3 { font-size: 1.05em; }

.markdown-body p {
  margin: 0 0 10px;
}
.markdown-body p:last-child {
  margin-bottom: 0;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 20px;
  margin: 6px 0 10px;
}
.markdown-body li {
  margin: 3px 0;
}

.markdown-body strong {
  font-weight: 600;
}
.markdown-body em {
  font-style: italic;
}

.markdown-body code {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
}

.markdown-body pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 14px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
  font-size: 13px;
  line-height: 1.6;
}
.markdown-body pre code {
  background: none;
  padding: 0;
  color: inherit;
}

.markdown-body blockquote {
  border-left: 3px solid #d0d0d0;
  padding-left: 12px;
  color: #666;
  margin: 8px 0;
}

.markdown-body hr {
  border: none;
  border-top: 1px solid #e5e5e5;
  margin: 14px 0;
}

.markdown-body table {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
}
.markdown-body th,
.markdown-body td {
  border: 1px solid #e5e5e5;
  padding: 6px 12px;
  text-align: left;
}
.markdown-body th {
  background: #f7f7f7;
  font-weight: 600;
}
</style>

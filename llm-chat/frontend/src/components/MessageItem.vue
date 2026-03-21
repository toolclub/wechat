<script setup lang="ts">
import { computed, ref } from 'vue'
import { marked } from 'marked'
import type { Message } from '../types'
import { CopyDocument, Check, User } from '@element-plus/icons-vue'

const props = defineProps<{ message: Message }>()
const copied = ref(false)

const renderedContent = computed(() => {
  if (props.message.role === 'assistant') {
    return marked.parse(props.message.content || '') as string
  }
  return ''
})

async function copy() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {}
}
</script>

<template>
  <div class="msg" :class="message.role">

    <!-- 用户消息 -->
    <template v-if="message.role === 'user'">
      <div class="user-wrap">
        <!-- 图片 -->
        <div v-if="message.images?.length" class="user-imgs">
          <el-image
            v-for="(img, i) in message.images"
            :key="i"
            :src="img"
            :preview-src-list="message.images"
            :initial-index="i"
            fit="cover"
            class="user-img"
          />
        </div>
        <!-- 文字 -->
        <div v-if="message.content" class="user-bubble">{{ message.content }}</div>
      </div>
      <!-- 用户头像 -->
      <div class="user-avatar">
        <el-icon><User /></el-icon>
      </div>
    </template>

    <!-- AI 消息 -->
    <template v-else>
      <!-- AI 头像 -->
      <div class="ai-avatar">
        <svg width="13" height="13" viewBox="0 0 64 64" fill="none">
          <path d="M36 8L22 34H31L28 56L46 28H36Z" fill="white"/>
        </svg>
      </div>
      <div class="ai-content-wrap">
        <div class="ai-content markdown-body" v-html="renderedContent"></div>
        <!-- 操作行 -->
        <div v-if="message.content" class="ai-actions">
          <el-tooltip :content="copied ? '已复制！' : '复制内容'" placement="top" :show-after="300">
            <button class="action-btn" :class="{ copied }" @click="copy">
              <el-icon><component :is="copied ? Check : CopyDocument" /></el-icon>
              <span>{{ copied ? '已复制' : '复制' }}</span>
            </button>
          </el-tooltip>
        </div>
      </div>
    </template>

  </div>
</template>

<style scoped>
.msg {
  width: 100%;
  padding: 10px 0;
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

/* 用户 */
.msg.user {
  flex-direction: row-reverse;
}
.user-avatar {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #374151 0%, #1f2937 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  flex-shrink: 0;
  margin-top: 2px;
}
.user-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  max-width: 68%;
}
.user-imgs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}
.user-img {
  width: 200px;
  height: 200px;
  border-radius: var(--cf-radius-md) !important;
  border: 1.5px solid var(--cf-border);
  cursor: zoom-in;
}
.user-bubble {
  background: var(--cf-card);
  color: var(--cf-text-1);
  padding: 10px 16px;
  border-radius: 18px 6px 18px 18px;
  font-size: 14.5px;
  font-weight: 400;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1.5px solid var(--cf-border);
  box-shadow: var(--cf-shadow-xs);
  letter-spacing: -0.1px;
}

/* AI */
.msg.assistant {
  flex-direction: row;
}
.ai-avatar {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #312e81 0%, #6366f1 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
  box-shadow: 0 2px 8px rgba(99,102,241,0.3);
}
.ai-content-wrap {
  flex: 1;
  min-width: 0;
  max-width: 86%;
}
.ai-content {
  font-size: 14.5px;
  line-height: 1.75;
  color: var(--cf-text-1);
  letter-spacing: -0.1px;
}

/* 操作行 */
.ai-actions {
  display: flex;
  gap: 4px;
  margin-top: 8px;
  opacity: 0;
  transition: opacity 0.2s;
}
.msg.assistant:hover .ai-actions { opacity: 1; }

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: var(--cf-card);
  border: 1.5px solid var(--cf-border);
  border-radius: 8px;
  color: var(--cf-text-4);
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.action-btn:hover {
  border-color: #a5b4fc;
  color: var(--cf-indigo);
  background: var(--cf-active);
}
.action-btn.copied {
  border-color: #bbf7d0;
  color: #16a34a;
  background: #f0fdf4;
}
</style>

<style>
/* ── Markdown 全局样式 ── */
.markdown-body { word-break: break-word; }

.markdown-body p { margin: 0 0 10px; }
.markdown-body p:last-child { margin-bottom: 0; }

.markdown-body h1, .markdown-body h2, .markdown-body h3 {
  font-weight: 700;
  margin: 20px 0 8px;
  line-height: 1.3;
  color: #111827;
  letter-spacing: -0.3px;
}
.markdown-body h1 { font-size: 1.4em; }
.markdown-body h2 { font-size: 1.2em; border-bottom: 1px solid #e4e6ef; padding-bottom: 6px; }
.markdown-body h3 { font-size: 1.05em; }

.markdown-body ul, .markdown-body ol {
  padding-left: 22px;
  margin: 6px 0 12px;
}
.markdown-body li { margin: 5px 0; line-height: 1.65; }

.markdown-body strong { font-weight: 700; color: #111827; }
.markdown-body em { font-style: italic; }

.markdown-body a {
  color: #6366f1;
  text-decoration: underline;
  text-decoration-color: #c7d2fe;
  text-underline-offset: 2px;
}
.markdown-body a:hover { text-decoration-color: #6366f1; }

.markdown-body code {
  background: #eef2ff;
  color: #4f46e5;
  padding: 2px 7px;
  border-radius: 6px;
  font-family: 'Fira Code', 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
  font-weight: 500;
  border: 1px solid #e0e7ff;
}

.markdown-body pre {
  background: #0f172a;
  color: #e2e8f0;
  padding: 16px 18px;
  border-radius: 12px;
  overflow-x: auto;
  margin: 12px 0;
  font-size: 13px;
  line-height: 1.65;
  border: 1px solid #1e293b;
  box-shadow: 0 4px 16px rgba(0,0,0,0.15);
}
.markdown-body pre code {
  background: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
  border: none;
  font-weight: 400;
}

.markdown-body blockquote {
  border-left: 3px solid #a5b4fc;
  padding: 8px 16px;
  color: #6b7280;
  margin: 12px 0;
  background: #f5f3ff;
  border-radius: 0 8px 8px 0;
  font-style: italic;
}

.markdown-body hr {
  border: none;
  border-top: 1px solid #e4e6ef;
  margin: 18px 0;
}

.markdown-body table {
  border-collapse: collapse;
  width: 100%;
  margin: 14px 0;
  font-size: 13.5px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e4e6ef;
}
.markdown-body th, .markdown-body td {
  border: 1px solid #e4e6ef;
  padding: 8px 14px;
  text-align: left;
}
.markdown-body th {
  background: #f3f4f8;
  font-weight: 600;
  color: #374151;
  font-size: 13px;
}
.markdown-body tr:nth-child(even) td { background: #f9fafb; }
.markdown-body tr:hover td { background: #eef2ff; }
</style>

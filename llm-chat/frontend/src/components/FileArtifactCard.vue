<script setup lang="ts">
import type { FileArtifact } from '../types'
import { isPreviewable } from '../types'

const props = defineProps<{
  file: FileArtifact
}>()

const emit = defineEmits<{
  select: [file: FileArtifact]
  download: [file: FileArtifact]
}>()

const LANG_ICON: Record<string, string> = {
  html: '🌐', svg: '🎨', css: '🎨', javascript: '⚡', typescript: '⚡',
  python: '🐍', ruby: '💎', go: '🔷', rust: '🦀', java: '☕',
  shell: '🖥️', json: '📋', yaml: '📋', xml: '📋', markdown: '📝',
  sql: '🗃️', vue: '💚', text: '📄', pptx: '📊', pdf: '📕',
}
const LANG_LABEL: Record<string, string> = {
  html: 'HTML', svg: 'SVG', css: 'CSS', javascript: 'JavaScript', typescript: 'TypeScript',
  python: 'Python', ruby: 'Ruby', go: 'Go', rust: 'Rust', java: 'Java',
  shell: 'Shell', json: 'JSON', yaml: 'YAML', xml: 'XML', markdown: 'Markdown',
  sql: 'SQL', vue: 'Vue', text: 'Text', pptx: 'PowerPoint', pdf: 'PDF',
}

const icon = LANG_ICON[props.file.language] || '📄'
const langLabel = LANG_LABEL[props.file.language] || props.file.language
const previewable = isPreviewable(props.file.language)
const isPpt = props.file.language === 'pptx'

// 文件大小：二进制文件用 size 字段，文本用 content.length
const sizeKb = props.file.size
  ? (props.file.size / 1024).toFixed(1)
  : (props.file.content.length / 1024).toFixed(1)

function downloadFile() {
  const isBinary = props.file.binary || ['pptx', 'pdf'].includes(props.file.language)
  if (isBinary) {
    try {
      const byteChars = atob(props.file.content)
      const bytes = new Uint8Array(byteChars.length)
      for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i)
      const blob = new Blob([bytes], { type: 'application/octet-stream' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = props.file.name; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { console.error('下载失败:', e) }
  } else {
    const blob = new Blob([props.file.content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = props.file.name; a.click()
    URL.revokeObjectURL(url)
  }
}
</script>

<template>
  <div class="artifact-card" :class="{ 'artifact-card--ppt': isPpt }" @click="emit('select', file)">
    <div class="artifact-icon" :class="{ 'artifact-icon--ppt': isPpt }">{{ icon }}</div>
    <div class="artifact-info">
      <div class="artifact-name">{{ file.name }}</div>
      <div class="artifact-meta">
        <span class="artifact-lang">{{ langLabel }}</span>
        <span class="artifact-sep">·</span>
        <span class="artifact-size">{{ sizeKb }} KB</span>
        <span v-if="file.slide_count" class="artifact-sep">·</span>
        <span v-if="file.slide_count" class="artifact-slides">{{ file.slide_count }} 页</span>
        <span v-if="previewable" class="artifact-preview-badge">可预览</span>
        <span v-if="isPpt" class="artifact-download-badge">点击预览</span>
      </div>
    </div>
    <div class="artifact-action">
      <svg v-if="isPpt" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
      </svg>
      <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M9 18l6-6-6-6"/>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.artifact-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #fff;
  border: 1.5px solid #D0EEF9;
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34,1.56,0.64,1);
  box-shadow: 0 1px 6px rgba(0,174,236,0.06);
  max-width: 360px;
  margin: 6px 0;
}
.artifact-card:hover {
  border-color: #00AEEC;
  box-shadow: 0 4px 16px rgba(0,174,236,0.12);
  transform: translateY(-2px) scale(1.01);
}
.artifact-card:active {
  transform: translateY(0) scale(0.99);
}

/* PPT 卡片特殊样式 — 橙色主题 */
.artifact-card--ppt {
  border-color: #FFD6A5;
  box-shadow: 0 1px 6px rgba(255,152,0,0.08);
}
.artifact-card--ppt:hover {
  border-color: #FF9800;
  box-shadow: 0 4px 16px rgba(255,152,0,0.15);
}

.artifact-icon {
  font-size: 24px;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, #E3F6FD 0%, #FDE8EF 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.artifact-icon--ppt {
  background: linear-gradient(135deg, #FFF3E0 0%, #FFE0B2 100%);
}

.artifact-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.artifact-name {
  font-size: 13px;
  font-weight: 600;
  color: #18191C;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.artifact-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #9499A0;
}
.artifact-lang {
  font-weight: 500;
  color: #00AEEC;
}
.artifact-card--ppt .artifact-lang {
  color: #FF9800;
}
.artifact-sep { color: #C9CCD0; }
.artifact-slides { font-weight: 500; }
.artifact-preview-badge {
  font-size: 10px;
  font-weight: 500;
  color: #FB7299;
  background: rgba(251,114,153,0.08);
  padding: 0px 5px;
  border-radius: 8px;
  margin-left: 2px;
}
.artifact-download-badge {
  font-size: 10px;
  font-weight: 500;
  color: #FF9800;
  background: rgba(255,152,0,0.08);
  padding: 0px 5px;
  border-radius: 8px;
  margin-left: 2px;
}

.artifact-action {
  color: #C9CCD0;
  flex-shrink: 0;
  transition: color 0.15s;
}
.artifact-card:hover .artifact-action { color: #00AEEC; }
.artifact-card--ppt:hover .artifact-action { color: #FF9800; }
</style>

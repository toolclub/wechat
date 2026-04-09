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
  archive: '📦',
}
const LANG_LABEL: Record<string, string> = {
  html: 'HTML', svg: 'SVG', css: 'CSS', javascript: 'JavaScript', typescript: 'TypeScript',
  python: 'Python', ruby: 'Ruby', go: 'Go', rust: 'Rust', java: 'Java',
  shell: 'Shell', json: 'JSON', yaml: 'YAML', xml: 'XML', markdown: 'Markdown',
  sql: 'SQL', vue: 'Vue', text: 'Text', pptx: 'PowerPoint', pdf: 'PDF',
  archive: '压缩包',
}

const icon = LANG_ICON[props.file.language] || '📄'
const langLabel = LANG_LABEL[props.file.language] || props.file.language
const previewable = isPreviewable(props.file.language)
const isPpt = props.file.language === 'pptx'
const isArchive = props.file.language === 'archive'
const isDownloadable = isArchive || (props.file as any).downloadable

// 文件大小：二进制文件用 size 字段，文本用 content.length
const sizeKb = props.file.size
  ? (props.file.size / 1024).toFixed(1)
  : (props.file.content.length / 1024).toFixed(1)

function downloadFile(e?: Event) {
  e?.stopPropagation()  // 不触发 select
  if (props.file.id) {
    // 通过后端 API 下载（支持二进制/打包文件）
    const a = document.createElement('a')
    a.href = `/api/artifacts/${props.file.id}/download`
    a.download = props.file.name
    a.click()
    return
  }
  // 兜底：前端直接下载（内存中有 content 时）
  const isBinary = props.file.binary || ['pptx', 'pdf', 'archive'].includes(props.file.language)
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
        <span v-if="isArchive" class="artifact-archive-badge">可下载</span>
      </div>
    </div>
    <!-- 下载按钮（所有有 id 的 artifact 都可下载） -->
    <div v-if="file.id" class="artifact-dl-btn" title="下载" @click="downloadFile($event)">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
    </div>
    <div class="artifact-action">
      <svg v-if="isArchive" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      <svg v-else-if="isPpt" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
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
  background: var(--cf-card, #fff);
  border: 1.5px solid rgba(0,174,236,0.18);
  border-radius: var(--cf-radius-md, 14px);
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34,1.56,0.64,1);
  box-shadow: 0 1px 6px rgba(0,174,236,0.06);
  max-width: 360px;
  margin: 6px 0;
}
.artifact-card:hover {
  border-color: var(--cf-bili-blue, #00AEEC);
  box-shadow: 0 4px 18px rgba(0,174,236,0.14), 0 0 8px rgba(0,174,236,0.06);
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

.artifact-archive-badge {
  font-size: 10px;
  font-weight: 500;
  color: #00B578;
  background: rgba(0,181,120,0.08);
  padding: 0px 5px;
  border-radius: 8px;
  margin-left: 2px;
}

.artifact-dl-btn {
  color: var(--cf-text-4, #C9CCD0);
  flex-shrink: 0;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  transition: all 0.15s;
}
.artifact-dl-btn:hover {
  color: var(--cf-bili-blue, #00AEEC);
  background: rgba(0,174,236,0.08);
}

.artifact-action {
  color: #C9CCD0;
  flex-shrink: 0;
  transition: color 0.15s;
}
.artifact-card:hover .artifact-action { color: #00AEEC; }
.artifact-card--ppt:hover .artifact-action { color: #FF9800; }
</style>

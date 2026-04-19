<script setup lang="ts">
/**
 * 用户上传文件预览模态（纯前端预览生态，不涉及下载）：
 *   - text/code        → highlight.js（首 4KB 嗅探，二进制内容直接跳颜文字）
 *   - markdown         → marked 渲染 / 切换源码视图
 *   - csv/xlsx/xls     → SheetJS sheet_to_html（lazy 单 sheet，行数封顶 1000）
 *   - image / svg      → 浏览器原生 <img>
 *   - pdf              → 浏览器原生 iframe
 *   - video / audio    → 浏览器原生 <video>/<audio>
 *   - pptx/office/archive/binary/design → 颜文字提示，0 网络请求
 *
 * 性能策略：
 *   - 关闭即销毁（destroy-on-close + Blob URL 释放）
 *   - 仅在 dialog visible 时拉数据
 *   - 文本类直接读 Blob.text()，避免 base64 → JSON 往返
 *   - SheetJS 走 dynamic import，未触发 Excel 时不进 vendor chunk
 *   - 单文件 ≤50MB（上传时已限）
 */
import { ref, watch, computed, onBeforeUnmount } from 'vue'
import hljs from 'highlight.js/lib/common'
import { Marked } from 'marked'
import { fetchArtifactBlob } from '../api'

interface UploadedFileLite {
  id: number
  name: string
  size: number
  language: string
  path?: string
}

const props = defineProps<{
  modelValue: boolean
  file: UploadedFileLite | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 浏览器原生不能渲染的桶 → 颜文字 + 一句标签描述
const UNSUPPORTED_LANGS: Record<string, string> = {
  pptx: 'PPT 文件',
  office: 'Office 文档',
  archive: '归档/打包文件',
  binary: '可执行/二进制文件',
  design: '设计稿',
}

// ── 通用加载状态 ──────────────────────────────────────────────────────────────
const loading = ref(false)
const errorMsg = ref('')
const binaryDetected = ref(false)

// ── 文本/代码 ────────────────────────────────────────────────────────────────
const textContent = ref('')
const TEXT_RENDER_LIMIT = 500 * 1024  // 500KB hljs 渲染上限，超出截断 + 提示
const textTruncated = ref(false)
const highlightedHtml = computed(() => {
  if (!textContent.value) return ''
  const lang = props.file?.language || 'text'
  try {
    if (hljs.getLanguage(lang)) {
      return hljs.highlight(textContent.value, { language: lang, ignoreIllegals: true }).value
    }
    return hljs.highlightAuto(textContent.value).value
  } catch {
    return textContent.value.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] as string))
  }
})

// ── Markdown 渲染（仅当 language === 'markdown' 时显示切换） ─────────────────
const mdViewMode = ref<'rendered' | 'source'>('rendered')
const markedInstance = new Marked({ gfm: true, breaks: false })
const markdownHtml = computed(() => {
  if (props.file?.language !== 'markdown' || !textContent.value) return ''
  try {
    return markedInstance.parse(textContent.value) as string
  } catch {
    return ''
  }
})
const isMarkdownFile = computed(() => props.file?.language === 'markdown')

// ── Excel/CSV ────────────────────────────────────────────────────────────────
interface SheetMeta { name: string; html: string; truncated: boolean; loaded: boolean }
const sheetNames = ref<string[]>([])
const sheets = ref<Record<string, SheetMeta>>({})
const activeSheet = ref('')
const SHEET_ROW_LIMIT = 1000
let _wb: any = null  // 持有 workbook 引用，供 lazy 渲染当前 sheet 用

// ── PDF / 图片 / 视频 / 音频 ────────────────────────────────────────────────
const blobUrl = ref('')

function reset() {
  loading.value = false
  errorMsg.value = ''
  binaryDetected.value = false
  textContent.value = ''
  textTruncated.value = false
  mdViewMode.value = 'rendered'
  sheetNames.value = []
  sheets.value = {}
  activeSheet.value = ''
  _wb = null
  if (blobUrl.value) {
    URL.revokeObjectURL(blobUrl.value)
    blobUrl.value = ''
  }
}

/** 嗅探 Uint8Array：返回 true 表示像二进制 */
function looksBinary(bytes: Uint8Array): boolean {
  if (!bytes.length) return false
  let nonPrintable = 0
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i]
    if (b === 0) return true                        // 任何 NUL → 必是二进制
    if (b < 9 || (b > 13 && b < 32) || b === 127) nonPrintable++
  }
  return nonPrintable / bytes.length > 0.1          // > 10% 控制字符
}

async function load() {
  if (!props.file) return
  reset()
  loading.value = true
  const lang = props.file.language
  try {
    if (lang in UNSUPPORTED_LANGS) {
      // 颜文字桶：0 请求
    } else if (lang === 'image' || lang === 'svg') {
      const blob = await fetchArtifactBlob(props.file.id)
      blobUrl.value = URL.createObjectURL(blob)
    } else if (lang === 'pdf' || lang === 'video' || lang === 'audio') {
      const blob = await fetchArtifactBlob(props.file.id)
      blobUrl.value = URL.createObjectURL(blob)
    } else if (lang === 'spreadsheet') {
      await loadSpreadsheet()
    } else {
      // text / code / json / md / xml / ...
      const blob = await fetchArtifactBlob(props.file.id)
      const peek = new Uint8Array(await blob.slice(0, 4096).arrayBuffer())
      if (looksBinary(peek)) {
        binaryDetected.value = true
      } else {
        let text = await blob.text()
        if (text.length > TEXT_RENDER_LIMIT) {
          text = text.slice(0, TEXT_RENDER_LIMIT)
          textTruncated.value = true
        }
        textContent.value = text
      }
    }
  } catch (e: any) {
    errorMsg.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadSpreadsheet() {
  const blob = await fetchArtifactBlob(props.file!.id)
  const buf = await blob.arrayBuffer()
  const XLSX = await import('xlsx')
  // 仅 read 元数据 + 首个 sheet 的 HTML，其它 sheet 切 tab 时再算
  _wb = XLSX.read(new Uint8Array(buf), { type: 'array' })
  const names = _wb.SheetNames as string[]
  sheetNames.value = names
  if (names.length) {
    activeSheet.value = names[0]
    renderSheet(names[0])
  }
}

function renderSheet(name: string) {
  if (!_wb || sheets.value[name]?.loaded) return
  // 同步导入 OK：上面已 await 过一次
  import('xlsx').then((XLSX) => {
    const ws = _wb.Sheets[name]
    if (!ws) return
    let truncated = false
    if (ws['!ref']) {
      const range = XLSX.utils.decode_range(ws['!ref'])
      if (range.e.r - range.s.r + 1 > SHEET_ROW_LIMIT) {
        range.e.r = range.s.r + SHEET_ROW_LIMIT - 1
        ws['!ref'] = XLSX.utils.encode_range(range)
        truncated = true
      }
    }
    const html = XLSX.utils.sheet_to_html(ws, { id: '', editable: false })
    sheets.value = { ...sheets.value, [name]: { name, html, truncated, loaded: true } }
  })
}

function selectSheet(name: string) {
  activeSheet.value = name
  if (!sheets.value[name]?.loaded) renderSheet(name)
}

// 触发：每次模态打开时拉数据；关闭时释放
watch([visible, () => props.file?.id], ([v]) => {
  if (v && props.file) {
    load()
  } else if (!v) {
    reset()
  }
})

onBeforeUnmount(reset)

// ── 计算/工具 ────────────────────────────────────────────────────────────────
const fileSizeKb = computed(() => {
  if (!props.file) return '0'
  return (props.file.size / 1024).toFixed(1)
})

const langLabel = computed(() => {
  if (!props.file) return ''
  const map: Record<string, string> = {
    spreadsheet: '电子表格', image: '图片', svg: 'SVG',
    pptx: 'PowerPoint', office: 'Office', pdf: 'PDF',
    archive: '归档', binary: '二进制', design: '设计稿',
    video: '视频', audio: '音频',
    text: '文本', markdown: 'Markdown',
  }
  return map[props.file.language] || props.file.language
})

const isUnsupported = computed(() => {
  if (binaryDetected.value) return true
  if (!props.file) return false
  return props.file.language in UNSUPPORTED_LANGS
})
const unsupportedLabel = computed(() => {
  if (binaryDetected.value) return '检测到二进制内容'
  if (!props.file) return ''
  return UNSUPPORTED_LANGS[props.file.language] || ''
})
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="file?.name || '文件预览'"
    width="78vw"
    top="6vh"
    destroy-on-close
    append-to-body
    class="upload-preview-dialog"
  >
    <template #header="{ close }">
      <div class="upv-header">
        <div class="upv-header-left">
          <span class="upv-icon">📄</span>
          <span class="upv-title" :title="file?.path || file?.name">{{ file?.name }}</span>
          <el-tag size="small" effect="plain" type="primary">{{ langLabel }}</el-tag>
          <span class="upv-size">{{ fileSizeKb }} KB</span>
        </div>
        <div class="upv-header-right">
          <!-- Markdown 视图切换 -->
          <div v-if="isMarkdownFile && textContent" class="upv-md-toggle">
            <button class="upv-md-btn" :class="{ active: mdViewMode === 'rendered' }" @click="mdViewMode = 'rendered'">渲染</button>
            <button class="upv-md-btn" :class="{ active: mdViewMode === 'source' }" @click="mdViewMode = 'source'">源码</button>
          </div>
          <el-button size="small" text title="关闭" @click="close">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
              <path d="M12 4L4 12M4 4l8 8"/>
            </svg>
          </el-button>
        </div>
      </div>
    </template>

    <div class="upv-body">
      <!-- 加载中 -->
      <div v-if="loading" class="upv-loading">
        <svg class="upv-pc-svg" width="80" height="64" viewBox="0 0 80 64">
          <rect x="12" y="2" width="56" height="38" rx="4" fill="#E3F6FD" stroke="#00AEEC" stroke-width="2"/>
          <circle cx="32" cy="18" r="3" fill="#00AEEC"><animate attributeName="r" values="3;2;3" dur="1.5s" repeatCount="indefinite"/></circle>
          <circle cx="48" cy="18" r="3" fill="#00AEEC"><animate attributeName="r" values="3;2;3" dur="1.5s" begin="0.1s" repeatCount="indefinite"/></circle>
          <path d="M35 27 Q40 32 45 27" fill="none" stroke="#00AEEC" stroke-width="1.5" stroke-linecap="round"/>
          <rect x="28" y="40" width="24" height="4" rx="1" fill="#00AEEC"/>
          <rect x="22" y="44" width="36" height="3" rx="1.5" fill="#00AEEC"/>
        </svg>
        <div class="upv-loading-text">正在加载预览<span class="upv-dot-anim"></span></div>
      </div>

      <!-- 错误 -->
      <div v-else-if="errorMsg" class="upv-error">
        <div class="upv-kaomoji">(´；ω；`)</div>
        <div class="upv-error-msg">{{ errorMsg }}</div>
      </div>

      <!-- 颜文字：所有不可预览的桶 + 嗅探到二进制 -->
      <div v-else-if="isUnsupported" class="upv-empty">
        <div class="upv-kaomoji">(｡•́︿•̀｡)</div>
        <div class="upv-empty-text">不支持在线预览</div>
        <div v-if="unsupportedLabel" class="upv-empty-sub">{{ unsupportedLabel }}</div>
      </div>

      <!-- 图片 / SVG -->
      <div v-else-if="(file?.language === 'image' || file?.language === 'svg') && blobUrl" class="upv-image-wrap">
        <el-image :src="blobUrl" fit="contain" :preview-src-list="[blobUrl]" class="upv-image" />
      </div>

      <!-- 视频 -->
      <div v-else-if="file?.language === 'video' && blobUrl" class="upv-media-wrap">
        <video :src="blobUrl" controls class="upv-video" />
      </div>

      <!-- 音频 -->
      <div v-else-if="file?.language === 'audio' && blobUrl" class="upv-audio-wrap">
        <div class="upv-audio-icon">🎵</div>
        <div class="upv-audio-name">{{ file?.name }}</div>
        <audio :src="blobUrl" controls class="upv-audio" />
      </div>

      <!-- PDF -->
      <iframe v-else-if="file?.language === 'pdf' && blobUrl" :src="blobUrl" class="upv-pdf-frame" />

      <!-- 表格 -->
      <div v-else-if="file?.language === 'spreadsheet' && sheetNames.length" class="upv-sheet-wrap">
        <div v-if="sheetNames.length > 1" class="upv-sheet-tabs">
          <button
            v-for="name in sheetNames" :key="name"
            class="upv-sheet-tab" :class="{ active: name === activeSheet }"
            @click="selectSheet(name)"
          >{{ name }}</button>
        </div>
        <div v-if="sheets[activeSheet]?.truncated" class="upv-truncate-tip">
          仅显示前 {{ SHEET_ROW_LIMIT }} 行
        </div>
        <div v-if="sheets[activeSheet]?.loaded" class="upv-sheet-scroll" v-html="sheets[activeSheet].html" />
        <div v-else class="upv-sheet-loading">解析中...</div>
      </div>

      <!-- Markdown 渲染视图 -->
      <div v-else-if="isMarkdownFile && mdViewMode === 'rendered' && textContent" class="upv-md-rendered">
        <div v-if="textTruncated" class="upv-truncate-tip">
          文件较大，仅渲染前 {{ Math.floor(TEXT_RENDER_LIMIT / 1024) }} KB
        </div>
        <div class="upv-md-body" v-html="markdownHtml" />
      </div>

      <!-- 代码/文本（含 markdown 源码） -->
      <div v-else-if="textContent" class="upv-code-wrap">
        <div v-if="textTruncated" class="upv-truncate-tip">
          文件较大，仅渲染前 {{ Math.floor(TEXT_RENDER_LIMIT / 1024) }} KB
        </div>
        <pre class="upv-code"><code class="hljs" v-html="highlightedHtml"></code></pre>
      </div>

      <!-- 兜底：空 -->
      <div v-else class="upv-empty">
        <div class="upv-kaomoji">(｡•́︿•̀｡)</div>
        <div class="upv-empty-text">无可预览内容</div>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.upv-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding-right: 4px;
}
.upv-header-left { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; }
.upv-icon { font-size: 16px; }
.upv-title {
  font-size: 14px; font-weight: 600; color: #18191C;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 460px;
}
.upv-size { font-size: 12px; color: #9499A0; }
.upv-header-right { display: flex; align-items: center; gap: 8px; }

.upv-md-toggle {
  display: inline-flex; padding: 2px; background: #F1F2F3; border-radius: 6px;
}
.upv-md-btn {
  border: none; background: transparent; cursor: pointer;
  padding: 3px 10px; font-size: 12px; color: #61666D; border-radius: 4px;
  transition: all 0.15s;
}
.upv-md-btn:hover { color: #00AEEC; }
.upv-md-btn.active { background: #fff; color: #00AEEC; font-weight: 600; }

.upv-body {
  height: 76vh; min-height: 420px;
  display: flex; flex-direction: column; overflow: hidden;
  background: #F8F9FA; border-radius: 8px;
}

/* loading */
.upv-loading {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 14px;
}
.upv-pc-svg { animation: upv-bob 1.4s ease-in-out infinite; }
@keyframes upv-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
.upv-loading-text { font-size: 13px; color: #00AEEC; font-weight: 500; }
.upv-dot-anim::after {
  content: '...'; display: inline-block; width: 18px; text-align: left;
  animation: upv-dots 1.2s steps(4) infinite;
}
@keyframes upv-dots { 0% { content: ''; } 33% { content: '.'; } 66% { content: '..'; } 100% { content: '...'; } }

/* error / empty */
.upv-error, .upv-empty {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 12px;
}
.upv-kaomoji {
  font-size: 36px; color: #00AEEC; font-weight: 500;
  letter-spacing: 1px; user-select: none;
  animation: upv-bob 2.4s ease-in-out infinite;
}
.upv-error-msg { font-size: 14px; color: #9499A0; }
.upv-empty-text { font-size: 15px; color: #61666D; font-weight: 500; }
.upv-empty-sub { font-size: 12.5px; color: #9499A0; }

/* image */
.upv-image-wrap {
  flex: 1; display: flex; align-items: center; justify-content: center;
  background: #2B2D31; padding: 20px;
}
.upv-image { max-width: 100%; max-height: 100%; }

/* video */
.upv-media-wrap {
  flex: 1; display: flex; align-items: center; justify-content: center;
  background: #000; padding: 20px;
}
.upv-video { max-width: 100%; max-height: 100%; outline: none; }

/* audio */
.upv-audio-wrap {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 16px;
  background: linear-gradient(135deg, #E3F6FD 0%, #FFF4F8 100%);
}
.upv-audio-icon { font-size: 64px; }
.upv-audio-name {
  font-size: 14px; color: #61666D;
  max-width: 70%; text-align: center;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.upv-audio { width: 80%; max-width: 480px; }

/* pdf */
.upv-pdf-frame { flex: 1; width: 100%; border: none; background: #fff; }

/* spreadsheet */
.upv-sheet-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.upv-sheet-tabs {
  display: flex; gap: 2px; padding: 6px 10px 0;
  background: #F1F2F3; border-bottom: 1px solid #E3E5E7; overflow-x: auto;
}
.upv-sheet-tab {
  padding: 6px 14px; border: none; cursor: pointer; font-size: 12px;
  color: #61666D; background: transparent; border-radius: 6px 6px 0 0;
  white-space: nowrap; transition: background 0.15s;
}
.upv-sheet-tab:hover { background: #E3E5E7; }
.upv-sheet-tab.active { background: #fff; color: #00AEEC; font-weight: 600; }
.upv-truncate-tip {
  padding: 6px 14px; font-size: 12px; color: #FB7299;
  background: #FFF4F8; border-bottom: 1px solid #FFE0EC;
}
.upv-sheet-scroll { flex: 1; overflow: auto; background: #fff; }
.upv-sheet-loading {
  flex: 1; display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: #9499A0;
}
.upv-sheet-scroll :deep(table) {
  border-collapse: collapse; font-size: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
}
.upv-sheet-scroll :deep(th),
.upv-sheet-scroll :deep(td) {
  border: 1px solid #E3E5E7; padding: 4px 8px; min-width: 60px;
  white-space: nowrap; color: #18191C;
}
.upv-sheet-scroll :deep(tr:nth-child(even)) { background: #FAFBFC; }

/* markdown */
.upv-md-rendered { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #fff; }
.upv-md-body {
  flex: 1; padding: 24px 32px; overflow: auto;
  font-size: 14px; line-height: 1.75; color: #18191C;
}
.upv-md-body :deep(h1),
.upv-md-body :deep(h2),
.upv-md-body :deep(h3) {
  margin: 18px 0 12px; line-height: 1.35; color: #18191C;
}
.upv-md-body :deep(h1) { font-size: 24px; border-bottom: 1px solid #E3E5E7; padding-bottom: 8px; }
.upv-md-body :deep(h2) { font-size: 20px; }
.upv-md-body :deep(h3) { font-size: 16px; }
.upv-md-body :deep(p) { margin: 10px 0; }
.upv-md-body :deep(ul),
.upv-md-body :deep(ol) { padding-left: 24px; margin: 10px 0; }
.upv-md-body :deep(li) { margin: 4px 0; }
.upv-md-body :deep(code) {
  padding: 2px 6px; background: #F1F2F3; border-radius: 4px;
  font-size: 13px; font-family: 'Consolas', 'Monaco', monospace;
}
.upv-md-body :deep(pre) {
  background: #FAFBFC; padding: 12px 14px; border-radius: 6px;
  overflow: auto; margin: 12px 0;
}
.upv-md-body :deep(pre code) { padding: 0; background: transparent; }
.upv-md-body :deep(blockquote) {
  border-left: 4px solid #00AEEC; padding: 4px 14px;
  background: #F4FAFD; color: #61666D; margin: 12px 0;
}
.upv-md-body :deep(table) {
  border-collapse: collapse; margin: 12px 0; font-size: 13px;
}
.upv-md-body :deep(th),
.upv-md-body :deep(td) { border: 1px solid #E3E5E7; padding: 6px 12px; }
.upv-md-body :deep(a) { color: #00AEEC; text-decoration: none; }
.upv-md-body :deep(a:hover) { text-decoration: underline; }
.upv-md-body :deep(img) { max-width: 100%; height: auto; }

/* code */
.upv-code-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #fff; }
.upv-code {
  flex: 1; margin: 0; padding: 16px;
  background: #FAFBFC; overflow: auto;
  font-size: 12.5px; line-height: 1.6;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
}
.upv-code code { background: transparent; }
</style>

<style>
/* el-dialog 自定义：全局穿透（scoped 不能影响 el-dialog 根节点） */
.upload-preview-dialog .el-dialog__header { padding: 12px 18px; border-bottom: 1px solid #E3E5E7; margin-right: 0; }
.upload-preview-dialog .el-dialog__body { padding: 12px 16px 16px; }
.upload-preview-dialog .el-dialog__headerbtn { display: none; }
</style>

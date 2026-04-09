<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { SendPayload } from '../types'
import { Picture, Promotion, Loading } from '@element-plus/icons-vue'

const props = defineProps<{
  loading: boolean
  centered?: boolean
}>()

const emit = defineEmits<{ send: [payload: SendPayload] }>()

const input = ref('')
const pendingImages = ref<string[]>([])
const fileInputRef = ref<HTMLInputElement>()
const textareaRef = ref<HTMLTextAreaElement>()

// ── Agent 模式开关 ──
const AGENT_MODE_KEY = 'cf_agent_mode'
const agentMode = ref(true)
const tipVisible = ref(false)
const tipText = ref('')
const flipping = ref(false)
let tipTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  const saved = localStorage.getItem(AGENT_MODE_KEY)
  if (saved !== null) agentMode.value = saved === 'true'
})

function toggleAgent() {
  if (flipping.value) return
  flipping.value = true
  // 压扁到 0 时切换状态，再弹回来
  setTimeout(() => {
    agentMode.value = !agentMode.value
    localStorage.setItem(AGENT_MODE_KEY, String(agentMode.value))
  }, 160)
  setTimeout(() => { flipping.value = false }, 320)

  tipText.value = agentMode.value
    ? 'Chat · 轻快直接'
    : 'Agent · 规划搜索推理'
  tipVisible.value = true
  if (tipTimer) clearTimeout(tipTimer)
  tipTimer = setTimeout(() => { tipVisible.value = false }, 2000)
}

// ── PPT 主题选择器（图片缩略图版） ──
const pptPanelOpen = ref(false)
const selectedPptTheme = ref<{ id: string; label: string } | null>(null)

interface PptTheme {
  id: string
  label: string
  desc: string
  bg: string       // 背景色
  primary: string   // 标题色
  accent: string    // 装饰色
  textColor: string // 正文色
}

const PPT_THEMES: PptTheme[] = [
  { id: 'tech_blue',      label: '科技蓝',   desc: '技术分享',   bg: '#FFFFFF', primary: '#1A73E8', accent: '#00AEEC', textColor: '#5F6368' },
  { id: 'biz_dark',       label: '商务深色', desc: '商业汇报',   bg: '#1E1E2E', primary: '#FFFFFF', accent: '#FF6D00', textColor: '#B0BEC5' },
  { id: 'fresh_green',    label: '清新绿',   desc: '教育培训',   bg: '#FFFFFF', primary: '#2E7D32', accent: '#66BB6A', textColor: '#4E7D4E' },
  { id: 'minimal_white',  label: '极简白',   desc: '万用百搭',   bg: '#FFFFFF', primary: '#18191C', accent: '#00AEEC', textColor: '#9499A0' },
  { id: 'bilibili_pink',  label: 'B站粉蓝', desc: '创意娱乐',   bg: '#FFFFFF', primary: '#00AEEC', accent: '#FB7299', textColor: '#61666D' },
  { id: 'gradient_purple', label: '渐变紫',  desc: '产品发布',   bg: '#1A1A2E', primary: '#E0AAFF', accent: '#C77DFF', textColor: '#B8B8D0' },
  { id: 'warm_orange',    label: '暖橙',     desc: '营销策划',   bg: '#FFF8F0', primary: '#E65100', accent: '#FF9800', textColor: '#795548' },
  { id: 'ocean_deep',     label: '深海蓝',   desc: '数据报告',   bg: '#0D1B2A', primary: '#E0E1DD', accent: '#00B4D8', textColor: '#778DA9' },
  { id: 'rose_gold',      label: '玫瑰金',   desc: '时尚美妆',   bg: '#FFF5F5', primary: '#B76E79', accent: '#E8A0A0', textColor: '#8B6B6B' },
  { id: 'ink_zen',        label: '水墨禅',   desc: '文化国风',   bg: '#F5F0E8', primary: '#2C2C2C', accent: '#8B4513', textColor: '#5C5C5C' },
  { id: 'neon_cyber',     label: '赛博霓虹', desc: '游戏科幻',   bg: '#0A0A1A', primary: '#00FF88', accent: '#FF0080', textColor: '#6666AA' },
  { id: 'sky_light',      label: '天空蓝',   desc: '工作汇报',   bg: '#F0F8FF', primary: '#1565C0', accent: '#42A5F5', textColor: '#546E7A' },
]

/** 生成 PPT 主题缩略图 SVG（看起来像真实的幻灯片） */
function buildThemeSvg(t: PptTheme): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="113" viewBox="0 0 200 113">
    <rect width="200" height="113" rx="4" fill="${t.bg}"/>
    <rect x="14" y="30" width="60" height="5" rx="2" fill="${t.primary}"/>
    <rect x="14" y="40" width="90" height="3" rx="1" fill="${t.textColor}" opacity="0.5"/>
    <rect x="14" y="47" width="75" height="3" rx="1" fill="${t.textColor}" opacity="0.4"/>
    <rect x="14" y="54" width="82" height="3" rx="1" fill="${t.textColor}" opacity="0.3"/>
    <rect x="14" y="64" width="40" height="12" rx="3" fill="${t.accent}" opacity="0.8"/>
    <rect x="120" y="25" width="65" height="55" rx="4" fill="${t.accent}" opacity="0.12"/>
    <circle cx="152" cy="48" r="10" fill="${t.accent}" opacity="0.25"/>
    <rect x="0" y="0" width="200" height="5" rx="0" fill="${t.accent}"/>
    <rect x="14" y="95" width="30" height="2" rx="1" fill="${t.textColor}" opacity="0.2"/>
    <rect x="156" y="95" width="30" height="2" rx="1" fill="${t.textColor}" opacity="0.2"/>
  </svg>`
}

function getThemeSvgDataUri(t: PptTheme): string {
  return 'data:image/svg+xml,' + encodeURIComponent(buildThemeSvg(t))
}

/** 选中主题 → 将缩略图转为 PNG 加入 pendingImages */
function selectPptTheme(theme: PptTheme) {
  selectedPptTheme.value = { id: theme.id, label: theme.label }
  pptPanelOpen.value = false

  // SVG → Canvas → PNG base64 → 加入图片附件
  const svg = buildThemeSvg(theme)
  const blob = new Blob([svg], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  const img = new Image()
  img.onload = () => {
    const canvas = document.createElement('canvas')
    canvas.width = 400; canvas.height = 226
    const ctx2d = canvas.getContext('2d')!
    ctx2d.drawImage(img, 0, 0, 400, 226)
    const pngDataUri = canvas.toDataURL('image/png')
    // 替换掉之前的主题图片（如果有）
    pendingImages.value = pendingImages.value.filter(i => !i.startsWith('data:image/png;base64,iVBOR'))
    pendingImages.value.unshift(pngDataUri)
    URL.revokeObjectURL(url)
    setTimeout(() => textareaRef.value?.focus(), 100)
  }
  img.src = url
}

function clearPptTheme() {
  selectedPptTheme.value = null
  // 移除主题图片
  pendingImages.value = pendingImages.value.filter(i => !i.startsWith('data:image/png;base64,iVBOR'))
}

function togglePptPanel() {
  pptPanelOpen.value = !pptPanelOpen.value
}

const canSend = () => (input.value.trim() || pendingImages.value.length > 0) && !props.loading

function handleSend() {
  if (!canSend()) return
  let text = input.value
  if (selectedPptTheme.value) {
    text = `[PPT模式 | 主题: ${selectedPptTheme.value.id} (${selectedPptTheme.value.label})]\n${text}\n请使用 create_ppt 工具，参考附带的主题风格图片生成 PPT。`
  }
  emit('send', { text, images: [...pendingImages.value], agentMode: agentMode.value })
  input.value = ''
  pendingImages.value = []
  selectedPptTheme.value = null
  if (textareaRef.value) textareaRef.value.style.height = 'auto'
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

function compressImage(dataUrl: string, maxPx = 1280, quality = 0.82): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      let { width, height } = img
      if (width > maxPx || height > maxPx) {
        if (width >= height) { height = Math.round(height * maxPx / width); width = maxPx }
        else { width = Math.round(width * maxPx / height); height = maxPx }
      }
      const canvas = document.createElement('canvas')
      canvas.width = width; canvas.height = height
      canvas.getContext('2d')!.drawImage(img, 0, 0, width, height)
      resolve(canvas.toDataURL('image/jpeg', quality))
    }
    img.onerror = () => resolve(dataUrl)
    img.src = dataUrl
  })
}

async function addImageFile(file: File) {
  if (!file.type.startsWith('image/')) return
  const reader = new FileReader()
  reader.onload = async ev => {
    const raw = ev.target?.result as string
    if (!raw) return
    pendingImages.value.push(await compressImage(raw))
  }
  reader.readAsDataURL(file)
}

function handlePaste(e: ClipboardEvent) {
  for (const item of Array.from(e.clipboardData?.items || [])) {
    if (item.type.startsWith('image/')) { e.preventDefault(); const f = item.getAsFile(); if (f) addImageFile(f) }
  }
}
function handleFileSelect(e: Event) {
  for (const f of Array.from((e.target as HTMLInputElement).files || [])) addImageFile(f)
  if (fileInputRef.value) fileInputRef.value.value = ''
}
function handleDrop(e: DragEvent) {
  e.preventDefault()
  for (const f of Array.from(e.dataTransfer?.files || [])) addImageFile(f)
}
function removeImage(i: number) { pendingImages.value.splice(i, 1) }
</script>

<template>
  <div class="input-root" :class="{ centered }" @dragover.prevent @drop="handleDrop">
    <div class="input-card" :class="{ 'is-loading': loading }">

      <!-- 已选主题标签 + 图片预览 -->
      <div v-if="selectedPptTheme || pendingImages.length > 0" class="attachments-bar">
        <!-- PPT 主题标签 -->
        <div v-if="selectedPptTheme" class="ppt-tag">
          <span class="ppt-tag-label">📊 {{ selectedPptTheme.label }}</span>
          <button class="ppt-tag-close" @click="clearPptTheme" title="取消PPT模式">
            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <!-- 图片预览 -->
        <div v-for="(img, i) in pendingImages" :key="i" class="img-thumb">
          <img :src="img" alt="图片" />
          <button class="img-remove" @click="removeImage(i)" title="移除">
            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      </div>

      <div class="textarea-area">
        <textarea
          ref="textareaRef" v-model="input"
          @keydown="handleKeydown" @paste="handlePaste" @input="autoResize"
          :placeholder="centered ? '随便问点什么吧~ (●ˇ∀ˇ●)' : '发消息... （Enter 发送 · Shift+Enter 换行 · 支持粘贴截图）'"
          :disabled="loading" rows="1" class="the-textarea"
        />
      </div>

      <div class="toolbar">
        <div class="tl">
          <input ref="fileInputRef" type="file" accept="image/*" multiple style="display:none" @change="handleFileSelect" />
          <el-tooltip content="上传图片 / 粘贴截图 (Ctrl+V)" placement="top" :show-after="400">
            <button class="tool-btn" @click="fileInputRef?.click()" :disabled="loading">
              <el-icon><Picture /></el-icon>
            </button>
          </el-tooltip>

          <!-- ═══ Agent / Chat 翻牌切换 ═══ -->
          <button
            class="mode-flip"
            :class="{ 'mode-flip--ani': flipping }"
            @click="toggleAgent"
            :disabled="loading"
            :title="agentMode ? 'Agent 模式（点击切换）' : 'Chat 模式（点击切换）'"
          >
            <span class="mode-flip-inner">
              <!-- 内容随 agentMode 实时切换，动画只是视觉挤压弹回 -->
              <template v-if="agentMode">
                <svg class="mode-ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00AEEC" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="4" y="8" width="16" height="12" rx="3"/>
                  <circle cx="9" cy="14" r="1.3" fill="#00AEEC" stroke="none"/>
                  <circle cx="15" cy="14" r="1.3" fill="#00AEEC" stroke="none"/>
                  <line x1="12" y1="4" x2="12" y2="8"/>
                  <circle cx="12" cy="3" r="1.5"/>
                </svg>
                <span class="mode-txt" style="color:#00AEEC">Agent</span>
              </template>
              <template v-else>
                <svg class="mode-ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FB7299" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
                  <line x1="8" y1="9" x2="16" y2="9"/>
                  <line x1="8" y1="13" x2="13" y2="13"/>
                </svg>
                <span class="mode-txt" style="color:#FB7299">Chat</span>
              </template>
            </span>
          </button>

          <!-- ═══ PPT 按钮 ═══ -->
          <el-tooltip content="创建 PPT" placement="top" :show-after="400">
            <button
              class="tool-btn ppt-btn"
              :class="{ 'ppt-btn--active': pptPanelOpen || selectedPptTheme }"
              @click="togglePptPanel"
              :disabled="loading"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="3" width="20" height="14" rx="2"/>
                <line x1="8" y1="21" x2="16" y2="21"/>
                <line x1="12" y1="17" x2="12" y2="21"/>
              </svg>
            </button>
          </el-tooltip>

          <span v-if="pendingImages.length > 0" class="img-badge">{{ pendingImages.length }} 张图片</span>
        </div>

        <div class="tr">
          <span v-if="input.length > 20" class="char-count">{{ input.length }}</span>
          <el-tooltip :content="loading ? '生成中...' : (canSend() ? '发送 (Enter)' : '请输入内容')" placement="top" :show-after="300">
            <button class="send-btn" :class="{ active: canSend(), loading }" @click="handleSend" :disabled="!canSend()">
              <el-icon v-if="!loading" class="send-icon"><Promotion /></el-icon>
              <el-icon v-else class="spin"><Loading /></el-icon>
            </button>
          </el-tooltip>
        </div>
      </div>
    </div>

    <div class="input-footer">
      <Transition name="mode-tip">
        <div v-if="tipVisible" class="mode-tip-bar">{{ tipText }}</div>
      </Transition>
      <Transition name="mode-hint">
        <span v-if="!tipVisible" class="hint">Enter 发送 · Shift+Enter 换行</span>
      </Transition>
    </div>

    <!-- ═══ PPT 主题画廊（在输入框下方展开） ═══ -->
    <Transition name="ppt-panel">
      <div v-if="pptPanelOpen" class="ppt-gallery">
        <div class="ppt-gallery-header">
          <span class="ppt-gallery-title">选择 PPT 主题风格</span>
          <button class="ppt-gallery-close" @click="pptPanelOpen = false">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div class="ppt-gallery-grid">
          <button
            v-for="t in PPT_THEMES" :key="t.id"
            class="ppt-gallery-card"
            :class="{ 'ppt-gallery-card--selected': selectedPptTheme?.id === t.id }"
            @click="selectPptTheme(t)"
          >
            <img class="ppt-gallery-img" :src="getThemeSvgDataUri(t)" :alt="t.label" />
            <div class="ppt-gallery-info">
              <span class="ppt-gallery-name">{{ t.label }}</span>
              <span class="ppt-gallery-desc">{{ t.desc }}</span>
            </div>
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.input-root { width: 100%; }
.input-root.centered { max-width: 680px; margin: 0 auto; }

.input-card {
  background: var(--cf-card, #fff);
  border: 1.5px solid var(--cf-border, #DFE3E8);
  border-radius: var(--cf-radius-md, 14px);
  box-shadow: var(--cf-shadow-xs);
  overflow: hidden;
  transition: box-shadow 0.3s, border-color 0.3s;
}
.input-card:focus-within {
  border-color: var(--cf-bili-blue, #00AEEC);
  box-shadow: var(--cf-shadow-sm), 0 0 0 3px rgba(0,174,236,0.08), 0 0 16px rgba(0,174,236,0.06);
}
.input-card.is-loading { opacity: 0.75; }

.img-previews { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 14px 0; }
.img-thumb { position: relative; width: 68px; height: 68px; border-radius: 12px; overflow: hidden; border: 1.5px solid var(--cf-border); }
.img-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.img-remove {
  position: absolute; top: 3px; right: 3px; width: 18px; height: 18px; border-radius: 50%;
  background: rgba(0,0,0,0.6); color: #fff; border: none; cursor: pointer;
  display: flex; align-items: center; justify-content: center; padding: 0;
}
.img-remove:hover { background: rgba(242,93,89,0.9); }

.textarea-area { padding: 14px 18px 6px; }
.the-textarea {
  width: 100%; background: none; border: none; outline: none;
  font-size: 14.5px; font-family: inherit; font-weight: 400; line-height: 1.65;
  color: var(--cf-text-1); resize: none; max-height: 220px; overflow-y: auto;
}
.the-textarea::placeholder { color: var(--cf-text-4); }

.toolbar { display: flex; align-items: center; justify-content: space-between; padding: 6px 14px 10px; }
.tl, .tr { display: flex; align-items: center; gap: 6px; }

.tool-btn {
  width: 30px; height: 30px; border-radius: 8px; background: none; border: none;
  color: #00AEEC; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 17px;
  transition: all 0.15s; opacity: 0.7;
}
.tool-btn:hover:not(:disabled) { opacity: 1; background: rgba(0,174,236,0.08); }
.tool-btn:disabled { opacity: 0.25; cursor: not-allowed; }

.img-badge { font-size: 11px; color: #00AEEC; background: rgba(0,174,236,0.06); padding: 2px 8px; border-radius: 10px; font-weight: 500; }
.char-count { font-size: 11px; color: var(--cf-text-4); font-variant-numeric: tabular-nums; }

.send-btn {
  width: 32px; height: 32px; border-radius: 10px;
  background: #E3E5E7; color: #9499A0;
  border: none; cursor: pointer;
  display: flex; align-items: center; justify-content: center; font-size: 15px;
  transition: all 0.2s cubic-bezier(0.34,1.56,0.64,1);
}
.send-btn.active {
  background: #00AEEC;
  color: #fff;
  box-shadow: 0 2px 8px rgba(0,174,236,0.3);
}
.send-btn.active:hover { transform: scale(1.06); box-shadow: 0 3px 12px rgba(0,174,236,0.35); }
.send-btn:disabled:not(.active) { cursor: not-allowed; opacity: 0.5; }
.send-icon { font-size: 14px; }
.spin { font-size: 15px; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ═══════════════════════════════════════════════════════════════════
   翻牌切换 — 无边框、极浅色、Bilibili 简笔画线条风
   用 scaleX 压扁→切换内容→弹回，不用 3D 翻转，逻辑简单不出错
   ═══════════════════════════════════════════════════════════════════ */
.mode-flip {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 8px;
  margin-left: 2px;                /* 标准间距，由 .tl 的 gap: 6px 控制 */
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  transition: background 0.15s, transform 0.15s;
  position: relative;
}
.mode-flip:hover:not(:disabled) {
  background: rgba(0,0,0,0.03);
}
.mode-flip:active:not(:disabled) {
  transform: scale(0.94);
}
.mode-flip:disabled { opacity: 0.4; cursor: not-allowed; }

.mode-flip-inner {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: transform 0.32s cubic-bezier(0.34,1.56,0.64,1);
}

/* 压扁动画 */
.mode-flip--ani .mode-flip-inner {
  animation: flip-squash 0.32s cubic-bezier(0.34,1.56,0.64,1);
}
@keyframes flip-squash {
  0%   { transform: scaleX(1) scaleY(1); }
  45%  { transform: scaleX(0) scaleY(1.15); }
  55%  { transform: scaleX(0) scaleY(1.15); }
  100% { transform: scaleX(1) scaleY(1); }
}

.mode-ico {
  flex-shrink: 0;
  display: block;
}

.mode-txt {
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.2px;
  line-height: 1;
  white-space: nowrap;
}

/* ── 底部提示 ── */
.input-footer { position: relative; height: 28px; margin-top: 6px; }

.mode-tip-bar {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  padding: 0 14px; border-radius: 10px;
  background: rgba(0,0,0,0.025);
  color: #999;
  font-size: 11.5px;
  font-weight: 400;
  letter-spacing: 0.1px;
  white-space: nowrap;
  animation: tip-fade 0.25s ease-out;
}
@keyframes tip-fade {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.hint {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: #9499A0; pointer-events: none; font-weight: 400;
}

.mode-tip-enter-active, .mode-tip-leave-active { transition: opacity 0.2s; }
.mode-tip-enter-from, .mode-tip-leave-to { opacity: 0; }
.mode-hint-enter-active, .mode-hint-leave-active { transition: opacity 0.2s; }
.mode-hint-enter-from, .mode-hint-leave-to { opacity: 0; }

/* ═══════════════════════════════════════════════════════════════════
   附件栏（PPT 主题标签 + 图片预览）
   ═══════════════════════════════════════════════════════════════════ */
.attachments-bar {
  display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 14px 0; align-items: center;
}

/* PPT 主题标签 */
.ppt-tag {
  display: inline-flex; align-items: center; gap: 6px;
  height: 30px; padding: 0 10px 0 8px;
  background: #FFF8F0; border: 1.5px solid #FFD6A5; border-radius: 8px;
  font-size: 12px; font-weight: 500; color: #E65100;
}
.ppt-tag-colors { display: flex; gap: 2px; }
.ppt-tag-dot { width: 8px; height: 8px; border-radius: 50%; border: 1px solid rgba(0,0,0,0.1); }
.ppt-tag-label { white-space: nowrap; }
.ppt-tag-close {
  width: 16px; height: 16px; border-radius: 50%; border: none; background: transparent;
  color: #E65100; cursor: pointer; display: flex; align-items: center; justify-content: center;
  margin-left: 2px; transition: background 0.1s;
}
.ppt-tag-close:hover { background: rgba(230,81,0,0.1); }

/* ═══ PPT 按钮 ═══ */
.ppt-btn--active { color: #FF9800 !important; opacity: 1 !important; }

/* ═══ PPT 主题画廊（输入框下方） ═══ */
.ppt-gallery {
  margin-top: 10px;
  background: #fff;
  border: 1.5px solid #E3E5E7;
  border-radius: 14px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.08);
  padding: 12px 14px;
  overflow: hidden;
}
.ppt-gallery-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px;
}
.ppt-gallery-title {
  font-size: 13px; font-weight: 600; color: #18191C;
}
.ppt-gallery-close {
  width: 24px; height: 24px; border-radius: 6px; border: none; background: transparent;
  color: #9499A0; cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.1s;
}
.ppt-gallery-close:hover { background: #F1F2F3; color: #18191C; }

.ppt-gallery-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.ppt-gallery-card {
  display: flex; flex-direction: column; gap: 6px;
  padding: 0; border: 2px solid transparent; border-radius: 10px;
  background: #fff; cursor: pointer; transition: all 0.18s;
  overflow: hidden;
}
.ppt-gallery-card:hover {
  border-color: #00AEEC;
  box-shadow: 0 3px 12px rgba(0,174,236,0.15);
  transform: translateY(-2px);
}
.ppt-gallery-card--selected {
  border-color: #FF9800;
  box-shadow: 0 3px 12px rgba(255,152,0,0.2);
}

.ppt-gallery-img {
  width: 100%;
  aspect-ratio: 16/9;
  object-fit: cover;
  border-radius: 8px 8px 0 0;
  border-bottom: 1px solid #F1F2F3;
}

.ppt-gallery-info {
  padding: 2px 8px 8px;
  display: flex; flex-direction: column; gap: 1px;
}
.ppt-gallery-name { font-size: 11.5px; font-weight: 600; color: #18191C; }
.ppt-gallery-desc { font-size: 10px; color: #9499A0; }

/* 画廊动画 */
.ppt-panel-enter-active { transition: opacity 0.2s, max-height 0.25s ease-out; }
.ppt-panel-leave-active { transition: opacity 0.15s, max-height 0.2s ease-in; }
.ppt-panel-enter-from { opacity: 0; max-height: 0; }
.ppt-panel-leave-to { opacity: 0; max-height: 0; }
.ppt-panel-enter-to, .ppt-panel-leave-from { max-height: 400px; }
</style>

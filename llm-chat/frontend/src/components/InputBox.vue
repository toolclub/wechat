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

const canSend = () => (input.value.trim() || pendingImages.value.length > 0) && !props.loading

function handleSend() {
  if (!canSend()) return
  emit('send', { text: input.value, images: [...pendingImages.value], agentMode: agentMode.value })
  input.value = ''
  pendingImages.value = []
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

      <div v-if="pendingImages.length > 0" class="img-previews">
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
  </div>
</template>

<style scoped>
.input-root { width: 100%; }
.input-root.centered { max-width: 680px; margin: 0 auto; }

.input-card {
  background: #fff;
  border: 1.5px solid #E3E5E7;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  overflow: hidden;
  transition: box-shadow 0.25s, border-color 0.25s;
}
.input-card:focus-within {
  border-color: #00AEEC;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04), 0 0 0 3px rgba(0,174,236,0.06);
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
</style>

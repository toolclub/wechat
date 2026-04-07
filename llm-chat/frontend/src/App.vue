<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import { useChat } from './composables/useChat'
import Sidebar from './components/Sidebar.vue'
import ChatView from './components/ChatView.vue'
import CognitivePanel from './components/CognitivePanel.vue'

const chat = useChat()

onMounted(async () => {
  await chat.loadConversations()
  await chat.restoreFromHash()
})

// ── 面板折叠/展开（用户可手动控制） ──────────────────────────────────────────
const panelOpen = ref(true)

// 是否存在值得展示的认知内容（计划或日志）
const hasCognitiveContent = computed(() => {
  const cog = chat.cognitive.value
  return cog.plan.length > 0 || cog.traceLog.length > 0 || cog.historyEvents.length > 0
})

// 面板展示条件：
//   1. 正在规划中（planning 状态）→ 自动弹出
//   2. 有认知内容 AND 用户未折叠
// 不包括 routing/thinking/tool 状态，避免简单问题也触发面板一闪
const showCognitivePanel = computed(() => {
  const status = chat.agentStatus.value.state
  if (status === 'planning') return true
  return hasCognitiveContent.value && panelOpen.value
})

// 开始规划时自动打开面板
watch(() => chat.agentStatus.value.state, (state) => {
  if (state === 'planning') panelOpen.value = true
})

// 切换会话时折叠认知面板（新会话没有历史计划）
watch(() => chat.currentConvId.value, () => {
  panelOpen.value = true  // 默认开，但 showCognitivePanel 还受 hasCognitiveContent 控制
})

// 当前目标（最新用户消息，优先用 workflowGoal 避免显示后端指令文本）
const currentGoal = computed(() => {
  const msgs = chat.messages.value
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]
    if (m.role === 'user') return m.workflowGoal || m.content
  }
  return ''
})

// 当前对话标题（来自对话列表，就是第一条消息 / 后端生成的摘要标题）
const currentConvTitle = computed(() => {
  if (!chat.currentConvId.value) return ''
  const conv = chat.conversations.value.find(c => c.id === chat.currentConvId.value)
  return conv?.title ?? ''
})
</script>

<template>
  <div class="app">
    <Sidebar
      :conversations="chat.conversations.value"
      :currentConvId="chat.currentConvId.value"
      :activeConvIds="chat.activeConvIds.value"
      @new-chat="chat.newConversation()"
      @select="chat.selectConversation($event)"
      @delete="chat.removeConversation($event)"
    />

    <!-- 主内容区 -->
    <div class="main-area">
      <!-- 左侧：对话视图 -->
      <ChatView
        :messages="chat.messages.value"
        :loading="chat.loading.value"
        :agentStatus="chat.agentStatus.value"
        :cognitive="chat.cognitive.value"
        :has-cognitive-content="hasCognitiveContent"
        :panel-open="panelOpen"
        :conv-title="currentConvTitle"
        :can-continue="chat.canContinue.value"
        :class="showCognitivePanel ? 'chat-with-panel' : 'chat-full'"
        @send="chat.send($event)"
        @stop="chat.stopConversation()"
        @toggle-panel="panelOpen = !panelOpen"
        @clarification-submit="chat.submitClarification($event)"
        @continue="chat.continueLast()"
        @regenerate="chat.regenerate()"
        @edit-message="chat.editMessage($event.index, $event.content)"
      />

      <!-- 右侧：认知面板 -->
      <transition name="panel-slide">
        <CognitivePanel
          v-if="showCognitivePanel"
          :cognitive="chat.cognitive.value"
          :loading="chat.loading.value"
          :user-message="currentGoal"
          class="cognitive-panel-slot"
          @collapse="panelOpen = false"
          @modify-plan="chat.applyModifiedPlan($event)"
        />
      </transition>
    </div>
  </div>
</template>

<style>
:root {
  /* 背景 & 表面 — 参考 vue3-demo 清爽风格 */
  --cf-bg:          #F5F7FA;   /* 主内容背景：中性浅灰，不偏蓝 */
  --cf-sidebar:     #ffffff;   /* 侧边栏：纯白卡片 */
  --cf-card:        #ffffff;
  --cf-hover:       #F0F2F5;
  --cf-active:      #EBF0FF;   /* 蓝调高亮，与主色呼应 */

  /* 边框 */
  --cf-border:      #DCDFE6;   /* Element Plus 标准边框色 */
  --cf-border-soft: #EBEEF5;

  /* 文字 — Element Plus 标准色阶 */
  --cf-text-1: #303133;
  --cf-text-2: #606266;
  --cf-text-3: #909399;
  --cf-text-4: #C0C4CC;
  --cf-text-5: #DCDFE6;

  /* 主色 — 蓝紫双色体系 */
  --cf-indigo:  #6B9EFF;       /* 主蓝，与 vue3-demo 一致 */
  --cf-indigo-d:#5a8eef;
  --cf-purple:  #6366f1;       /* 紫色，用于特殊高亮 */
  --cf-green:   #67C23A;
  --cf-red:     #F56C6C;
  --cf-amber:   #E6A23C;

  /* 阴影 — 轻量层次 */
  --cf-shadow-xs: 0 2px 8px rgba(0,0,0,0.04);
  --cf-shadow-sm: 0 4px 16px rgba(0,0,0,0.08);
  --cf-shadow-md: 0 8px 24px rgba(0,0,0,0.10);
  --cf-shadow-lg: 0 12px 32px rgba(0,0,0,0.12);

  /* 圆角 */
  --cf-radius-sm: 8px;
  --cf-radius-md: 12px;
  --cf-radius-lg: 16px;

  --cf-sidebar-w: 240px;
}

body.dark {
  --cf-bg:          #0f0f0f;
  --cf-sidebar:     #1a1a1a;
  --cf-card:        #1a1a1a;
  --cf-hover:       #2a2a2a;
  --cf-active:      #1e2433;

  --cf-border:      #2e2e2e;
  --cf-border-soft: #252525;

  --cf-text-1: #e5e5e5;
  --cf-text-2: #a3a3a3;
  --cf-text-3: #737373;
  --cf-text-4: #525252;
  --cf-text-5: #404040;

  --cf-indigo:  #818cf8;
  --cf-indigo-d:#6366f1;
  --cf-purple:  #a78bfa;
  --cf-green:   #4ade80;
  --cf-red:     #f87171;
  --cf-amber:   #fbbf24;

  --cf-shadow-xs: 0 2px 8px rgba(0,0,0,0.3);
  --cf-shadow-sm: 0 4px 16px rgba(0,0,0,0.4);
  --cf-shadow-md: 0 8px 24px rgba(0,0,0,0.5);
  --cf-shadow-lg: 0 12px 32px rgba(0,0,0,0.6);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
               'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  font-size: 14px;
  color: var(--cf-text-1);
  background: var(--cf-bg);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* 全局滚动条 */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: #9ca3af; }

#app { height: 100%; }

/* ── Dark mode: body & scrollbar ── */
body.dark {
  background: var(--cf-bg);
  color: var(--cf-text-1);
}
body.dark ::-webkit-scrollbar-thumb { background: #404040; }
body.dark ::-webkit-scrollbar-thumb:hover { background: #525252; }

/* Dark mode overrides for components with hardcoded colors */
body.dark .chat-view,
body.dark .messages-scroll { background: #141414; }
body.dark .chat-header { background: #1a1a1a; border-bottom-color: var(--cf-border); box-shadow: 0 1px 6px rgba(0,0,0,0.3); }
body.dark .user-bubble { background: #2a2a2a; color: #e5e5e5; }
body.dark .ai-avatar { background: #1a1a1a; border-color: #333; }
body.dark .user-avatar { background: #2a2a2a; border-color: #333; }
body.dark .hero-title { background: linear-gradient(135deg, #e5e5e5 0%, #818cf8 100%); -webkit-background-clip: text; background-clip: text; }
body.dark .hero-icon-wrap { background: #1a1a1a; border-color: #333; }
body.dark .header-brand-icon { background: #1a1a1a; border-color: #333; }
body.dark .logo-icon { background: #1a1a1a; border-color: #333; }

/* Dark code blocks */
body.dark .markdown-body .code-block { background: #1e1e1e; border-color: #333; }
body.dark .markdown-body .code-header { background: #252525; border-bottom-color: #333; }
body.dark .markdown-body .code-lang-badge { color: #a3a3a3; }
body.dark .markdown-body .code-pre { background: #1e1e1e; }
body.dark .markdown-body code { background: #2a2a3a; color: #a78bfa; border-color: #333; }
body.dark .markdown-body th { background: #252525; color: #e5e5e5; }
body.dark .markdown-body th, body.dark .markdown-body td { border-color: #333; }
body.dark .markdown-body tr:nth-child(even) td { background: #1e1e1e; }
body.dark .markdown-body tr:hover td { background: #1e2433; }
body.dark .markdown-body blockquote { background: #1a1a2a; color: #a3a3a3; border-left-color: #6366f1; }
body.dark .markdown-body h1, body.dark .markdown-body h2, body.dark .markdown-body h3 { color: #e5e5e5; }
body.dark .markdown-body h2 { border-bottom-color: #333; }
body.dark .markdown-body strong { color: #e5e5e5; }
body.dark .markdown-body a { color: #818cf8; text-decoration-color: #4338ca; }

/* Dark mode for tool blocks and think blocks */
body.dark .tool-block { background: #1a1a1a; border-color: #2e2e2e; }
body.dark .tool-block-sources .tool-header-flat { background: #1a1a1a; border-color: #2e2e2e; border-left-color: #6366f1; }
body.dark .think-block { background: #1a1a2a; border-color: #2e2e3e; }
body.dark .think-body { background: #151520; border-top-color: #2e2e3e; }

/* Dark mode for step borders */
body.dark .section-wrap.has-step { border-left-color: #333; }

/* Dark SVG fills in logo/icons */
body.dark .sidebar-logo svg path,
body.dark .header-brand-icon svg path,
body.dark .hero-icon-wrap svg path,
body.dark .ai-avatar svg path { fill: #e5e5e5; }
body.dark .user-avatar svg circle { fill: #a3a3a3; }
body.dark .user-avatar svg path { stroke: #a3a3a3; }

/* Dark workflow card */
body.dark .wf-card { background: #1a1a2a; border-color: #2e2e3e; }
body.dark .wf-card-header { background: #1e1e2e; border-bottom-color: #2e2e3e; }

/* Dark mode model status in sidebar */
body.dark .model-status { background: linear-gradient(135deg, #0a1a0a, #0a200a); border-color: #1a3a1a; }
body.dark .status-text { color: #4ade80; }
body.dark .status-icon { color: #4ade80; }

/* Dark input area */
body.dark .input-card { background: #1a1a1a; border-color: #333; }
body.dark .the-textarea { color: #e5e5e5; }
body.dark .input-card:focus-within { border-color: #6366f1; box-shadow: var(--cf-shadow-lg), 0 0 0 4px rgba(99,102,241,0.15); }

/* Dark continue button */
body.dark .continue-btn { background: #1a1a1a; }

/* Dark empty state suggestions */
body.dark .sug-card { background: #1a1a1a; border-color: #333; color: var(--cf-text-2); }

/* Dark cognitive panel */
body.dark .ai-avatar--breathing { background: #1a1a2e !important; }
</style>

<style scoped>
/* 整体布局：全屏卡片风格，四周统一间距 */
.app {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--cf-bg);
  padding: 12px;
  gap: 12px;
}
.main-area {
  flex: 1;
  display: flex;
  min-width: 0;
  gap: 12px;
  overflow: hidden;
}

/* 对话视图宽度 */
.chat-with-panel { flex: 0 0 60%; min-width: 0; }
.chat-full       { flex: 1;       min-width: 0; }

/* 认知面板 */
.cognitive-panel-slot {
  flex: 0 0 40%;
  min-width: 280px;
  max-width: 480px;
}

/* 面板滑入/滑出 */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.panel-slide-enter-from,
.panel-slide-leave-to {
  flex-basis: 0 !important;
  min-width: 0 !important;
  max-width: 0 !important;
  opacity: 0;
}
</style>

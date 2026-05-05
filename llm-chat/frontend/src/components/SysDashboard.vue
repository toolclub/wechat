<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { 
  User, ChatDotRound, Cpu, PieChart, TrendCharts, Refresh, ArrowLeft, Close
} from '@element-plus/icons-vue'
import { get } from '../api'

const props = defineProps<{
  adminKey: string
}>()

const emit = defineEmits<{
  back: []
}>()

const loading = ref(true)
const stats = ref<any>(null)
const users = ref<any[]>([])

// 图表实例
let trendChart: echarts.ECharts | null = null
let modelChart: echarts.ECharts | null = null

const trendChartRef = ref<HTMLElement | null>(null)
const modelChartRef = ref<HTMLElement | null>(null)

async function fetchData() {
  loading.value = true
  try {
    const headers = { 'X-Admin-Key': props.adminKey }
    const [statsData, usersData] = await Promise.all([
      get<any>('/api/admin/stats', {}, headers),
      get<any[]>('/api/admin/users', {}, headers)
    ])
    stats.value = statsData
    users.value = usersData
    
    await nextTick()
    renderCharts()
  } catch (err) {
    console.error('获取管理数据失败:', err)
  } finally {
    loading.value = false
  }
}

function renderCharts() {
  if (!stats.value) return

  // 1. 趋势图
  if (trendChartRef.value) {
    if (!trendChart) trendChart = echarts.init(trendChartRef.value)
    trendChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['消息数', 'Token 消耗'], bottom: 0 },
      grid: { left: '3%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
      xAxis: { type: 'category', data: stats.value.charts.trend.days },
      yAxis: [
        { type: 'value', name: '消息', position: 'left' },
        { type: 'value', name: 'Tokens', position: 'right' }
      ],
      series: [
        {
          name: '消息数',
          type: 'bar',
          data: stats.value.charts.trend.messages,
          itemStyle: { color: '#00AEEC' },
          barWidth: '40%'
        },
        {
          name: 'Token 消耗',
          type: 'line',
          yAxisIndex: 1,
          data: stats.value.charts.trend.tokens,
          itemStyle: { color: '#FB7299' },
          lineStyle: { width: 3 },
          smooth: true,
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(251, 114, 153, 0.3)' },
              { offset: 1, color: 'rgba(251, 114, 153, 0)' }
            ])
          }
        }
      ]
    })
  }

  // 2. 模型分布图
  if (modelChartRef.value) {
    if (!modelChart) modelChart = echarts.init(modelChartRef.value)
    modelChart.setOption({
      tooltip: { trigger: 'item' },
      legend: { orient: 'vertical', left: 'left', top: 'center' },
      series: [
        {
          name: '模型使用量',
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
          label: { show: false, position: 'center' },
          emphasis: { label: { show: true, fontSize: 16, fontWeight: 'bold' } },
          data: stats.value.charts.models
        }
      ]
    })
  }
}

function handleResize() {
  trendChart?.resize()
  modelChart?.resize()
}

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})

function formatTime(ts: number) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}
</script>

<template>
  <div class="admin-dashboard">
    <!-- 头部导航 -->
    <div class="admin-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" circle @click="emit('back')" />
        <h2 class="header-title">系统管理面板</h2>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="fetchData" :loading="loading">刷新数据</el-button>
        <el-button type="danger" plain :icon="Close" @click="emit('back')">退出</el-button>
      </div>
    </div>

    <div v-if="loading && !stats" class="loading-state">
      <el-skeleton :rows="10" animated />
    </div>

    <div v-else class="admin-content">
      <!-- 数据概览卡片 -->
      <div class="stats-grid">
        <div class="stat-card blue">
          <div class="stat-icon"><el-icon><User /></el-icon></div>
          <div class="stat-info">
            <div class="stat-label">总用户 / 今日新增</div>
            <div class="stat-value">{{ stats.summary.total_users }} <span class="sub">/ {{ stats.summary.new_users_today }}</span></div>
          </div>
        </div>
        <div class="stat-card pink">
          <div class="stat-icon"><el-icon><ChatDotRound /></el-icon></div>
          <div class="stat-info">
            <div class="stat-label">总对话 / 总消息</div>
            <div class="stat-value">{{ stats.summary.total_conversations }} <span class="sub">/ {{ stats.summary.total_messages }}</span></div>
          </div>
        </div>
        <div class="stat-card purple">
          <div class="stat-icon"><el-icon><Cpu /></el-icon></div>
          <div class="stat-info">
            <div class="stat-label">总 Token 消耗</div>
            <div class="stat-value">{{ (stats.summary.total_prompt_tokens + stats.summary.total_completion_tokens).toLocaleString() }}</div>
          </div>
        </div>
        <div class="stat-card green">
          <div class="stat-icon"><el-icon><TrendCharts /></el-icon></div>
          <div class="stat-info">
            <div class="stat-label">推理 Token (Reasoning)</div>
            <div class="stat-value">{{ stats.summary.total_reasoning_tokens.toLocaleString() }}</div>
          </div>
        </div>
      </div>

      <!-- 图表区域 -->
      <div class="charts-row">
        <div class="chart-container main-chart">
          <div class="chart-header">
            <el-icon><TrendCharts /></el-icon>
            <span>使用趋势 (最近 7 天)</span>
          </div>
          <div ref="trendChartRef" class="chart-body"></div>
        </div>
        <div class="chart-container side-chart">
          <div class="chart-header">
            <el-icon><PieChart /></el-icon>
            <span>模型分布</span>
          </div>
          <div ref="modelChartRef" class="chart-body"></div>
        </div>
      </div>

      <!-- 最近访问用户 -->
      <div class="users-section">
        <div class="section-header">
          <el-icon><User /></el-icon>
          <span>最近活跃用户 (Top 50)</span>
        </div>
        <el-table :data="users" border stripe style="width: 100%" size="small" class="admin-table">
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column prop="email" label="邮箱" min-width="180" />
          <el-table-column label="最近登录" width="180">
            <template #default="scope">{{ formatTime(scope.row.last_login_at) }}</template>
          </el-table-column>
          <el-table-column label="注册时间" width="180">
            <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="scope">
              <el-tag :type="scope.row.is_active ? 'success' : 'danger'" size="small">
                {{ scope.row.is_active ? '活跃' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-dashboard {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  overflow-y: auto;
  padding: 24px;
}

.admin-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-title {
  font-size: 22px;
  font-weight: 800;
  color: #1e293b;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}

.stat-card {
  background: #fff;
  border-radius: 16px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  border: 1px solid #f1f5f9;
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.stat-card.blue .stat-icon { background: #e0f2fe; color: #00aeec; }
.stat-card.pink .stat-icon { background: #fdf2f8; color: #fb7299; }
.stat-card.purple .stat-icon { background: #f3e8ff; color: #a855f7; }
.stat-card.green .stat-icon { background: #dcfce7; color: #22c55e; }

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-label {
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

.stat-value {
  font-size: 24px;
  font-weight: 800;
  color: #1e293b;
}

.stat-value .sub {
  font-size: 14px;
  color: #94a3b8;
  font-weight: normal;
}

.charts-row {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.chart-container {
  background: #fff;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  border: 1px solid #f1f5f9;
}

.chart-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 20px;
}

.chart-body {
  height: 320px;
}

.users-section {
  background: #fff;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  border: 1px solid #f1f5f9;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 20px;
}

.admin-table {
  border-radius: 8px;
  overflow: hidden;
}

body.dark .admin-dashboard { background: #0f172a; }
body.dark .stat-card, body.dark .chart-container, body.dark .users-section {
  background: #1e293b;
  border-color: #334155;
}
body.dark .header-title, body.dark .stat-value, body.dark .chart-header, body.dark .section-header {
  color: #f1f5f9;
}
</style>

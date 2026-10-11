<template>
  <div class="block-summary">
    <!-- 汇总面板（design D5）：进度/总数/匹配数/失败数，StatCard 风格 -->
    <div class="summary-grid">
      <div class="summary-item">
        <div class="summary-label">执行进度</div>
        <div class="summary-value num">{{ summary.scanned }} / {{ summary.total }}</div>
        <div class="summary-foot">
          <div class="progress"><div class="progress__bar" :style="{ width: pct + '%' }"></div></div>
        </div>
      </div>
      <div class="summary-item">
        <div class="summary-label">匹配信号数</div>
        <div class="summary-value num text-rise">{{ summary.matched }}</div>
        <div class="summary-foot">命中策略的股票均记录为信号</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">失败数</div>
        <div class="summary-value num" :class="summary.failed > 0 ? 'text-fall' : ''">{{ summary.failed }}</div>
        <div class="summary-foot">数据缺失或执行异常的股票</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">参数版本</div>
        <div class="summary-value num">v{{ task.params_version }}</div>
        <div class="summary-foot">每次参数编辑递增，信号按版本归因</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { StrategyTask } from '@/api/types'

/** summary 块：汇总面板（进度/总数/匹配数/失败数 + 参数版本） */
const props = defineProps<{
  task: StrategyTask
  summary: { total: number; scanned: number; matched: number; failed: number }
}>()

const pct = computed(() => {
  if (!props.summary.total) return 0
  return Math.min(100, Math.round((props.summary.scanned / props.summary.total) * 100))
})
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--sp-md);
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--sp-md);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  background: var(--bg-surface);
}
.summary-label {
  font-size: 11px;
  color: var(--text-secondary);
}
.summary-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.summary-foot {
  font-size: 11px;
  color: var(--text-disabled);
}
.progress {
  height: 4px;
  background: var(--bg-surface-hover);
  border-radius: var(--r-full);
  overflow: hidden;
  position: relative;
}
.progress__bar {
  height: 100%;
  background: var(--accent-base);
  border-radius: var(--r-full);
}
.text-rise {
  color: var(--rise);
}
.text-fall {
  color: var(--fall);
}
</style>

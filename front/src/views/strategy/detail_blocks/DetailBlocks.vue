<template>
  <!-- detail_blocks 渲染器（strategy-task-redesign 4.5 / design D5）：
       按 definition.detail_schema 声明顺序渲染积木块；
       per_stock 块在数据缺失（scope='all' 后端不返回）时静默隐藏（spec） -->
  <div class="detail-blocks">
    <template v-for="(block, i) in schema" :key="i">
      <!-- 未知块类型：向后兼容（design：新块类型需前端注册组件；未注册静默跳过） -->
      <!-- summary 块：汇总面板 -->
      <section v-if="block.type === 'summary'" class="db-section">
        <BlockSummary :task="task" :summary="summary" />
      </section>

      <!-- per_stock 块：逐股结果（数据缺失 → v-if 静默隐藏，不报错） -->
      <section v-else-if="block.type === 'per_stock' && perStock != null" class="db-section">
        <div class="db-title">逐股结果</div>
        <BlockPerStock :rows="perStock" />
      </section>

      <!-- signals 块：信号表格 -->
      <section v-else-if="block.type === 'signals'" class="db-section">
        <div class="db-title">信号列表</div>
        <BlockSignals
          :rows="signalsPage.list"
          :total="signalsPage.total"
          :states="states"
          :columns="columns"
          @row-click="$emit('signal-click', $event)"
          @goto-all="$emit('goto-signals')"
        />
      </section>

      <!-- kv 块：键值摘要 -->
      <section v-else-if="block.type === 'kv'" class="db-section">
        <div class="db-title">{{ block.title || '策略摘要' }}</div>
        <BlockKv :items="block.items" :kv-payload="kvPayload" />
      </section>

      <!-- timeline 块：时间线 -->
      <section v-else-if="block.type === 'timeline'" class="db-section">
        <div class="db-title">执行时间线</div>
        <BlockTimeline :events="timeline" />
      </section>

      <!-- chart 块（v1 预留扩展）：信号日期分布 -->
      <section v-else-if="block.type === 'chart'" class="db-section">
        <div class="db-title">信号日期分布</div>
        <BlockChart :signals="signalsPage.list" />
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import BlockSummary from './BlockSummary.vue'
import BlockPerStock from './BlockPerStock.vue'
import BlockSignals from './BlockSignals.vue'
import BlockKv from './BlockKv.vue'
import BlockTimeline from './BlockTimeline.vue'
import BlockChart from './BlockChart.vue'
import type {
  StrategyTask,
  StrategyTaskStockResult,
  StrategySignalRow,
  StrategyStateDecl,
  StrategyColumnDecl,
  DetailBlockDecl,
  PageRes,
} from '@/api/types'

/**
 * detail_blocks 渲染容器：按 detail_schema 声明顺序映射到积木组件，
 * 块 props 全部来自声明字段 + detail API 响应（新策略组合既有积木零前端改动）。
 */
defineProps<{
  schema: DetailBlockDecl[]
  task: StrategyTask
  summary: { total: number; scanned: number; matched: number; failed: number }
  /** undefined（scope='all'）→ per_stock 块静默隐藏 */
  perStock?: StrategyTaskStockResult[]
  signalsPage: PageRes<StrategySignalRow>
  states: StrategyStateDecl[]
  columns: StrategyColumnDecl[]
  kvPayload: Record<string, number | string | null>
  timeline: { date: string; event: string; state: string }[]
}>()

defineEmits<{
  'signal-click': [row: StrategySignalRow]
  'goto-signals': []
}>()
</script>

<style scoped>
.detail-blocks {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
}
.db-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
}
.db-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  padding-left: 8px;
  border-left: 3px solid var(--accent-base);
}
</style>

<script setup lang="ts">
/**
 * ChartLegend.vue — 行情图例（kline-chart-change D7 / 任务 5.1、5.2、5.3）
 * 挂载于 StockPanel.vue 头部（股票名称/代码下方），布局
 * （spec「行情图例中文化与标的面板布局」）：
 *   1) 现价行：大号价格 + ChangeBadge 涨跌徽章（沿用原 sp-quote 视觉），
 *      数据 = 当前展示 K 线的收盘价与涨跌幅（收盘−前收）/前收×100%；
 *   2) 时间 / 3) 今开 / 4) 最高 / 5) 最低 / 6) 量能 中文标签行。
 * 数据（bar + prevClose）由 useChartLegend 共享状态提供（任务 5.4）：
 *   悬停跟随十字光标、无悬停回退最新一根；bar 为 null（K 线数据未就绪）时
 *   现价行回退标的接口报价（fallbackPrice / fallbackChangePct），字段行隐藏。
 * 样式全部走 design.css token（任务 5.2）：无硬编码色值，随主题 token 自动迁移。
 */
import { computed } from 'vue'
import type { LegendBar } from '@/composables/useChartLegend'
import ChangeBadge from '@/components/ui/ChangeBadge.vue'

const props = defineProps<{
  /** 当前展示 K 线（悬停优先、回退最新）；null = K 线数据未就绪 */
  bar: LegendBar | null
  /** 前收盘价（本地序列推导）；首根 / 未知 bar 为 null → 涨跌幅显示 -- */
  prevClose: number | null
  /** K 线未就绪时现价行回退的标的接口报价（价格） */
  fallbackPrice?: number | null
  /** K 线未就绪时现价行回退的标的接口涨跌幅（%） */
  fallbackChangePct?: number | null
}>()

/** 无值占位符（spec「首根 K 线无前收」「数据未就绪回退」场景） */
const PLACEHOLDER = '--'

/** 现价行价格：K 线收盘价优先，未就绪回退标的报价；均无效则隐藏现价行 */
const price = computed<number | null>(() => {
  if (props.bar) return Number.isFinite(props.bar.close) ? props.bar.close : null
  const fp = props.fallbackPrice
  return typeof fp === 'number' && Number.isFinite(fp) ? fp : null
})

/** 涨跌幅度 %：（收盘 − 前收）/ 前收 × 100（spec 计算契约）；无有效前收 → null（显示 --） */
const changePct = computed<number | null>(() => {
  if (props.bar) {
    const prev = props.prevClose
    if (prev === null || !Number.isFinite(prev) || prev === 0) return null
    return ((props.bar.close - prev) / prev) * 100
  }
  const fp = props.fallbackChangePct
  return typeof fp === 'number' && Number.isFinite(fp) ? fp : null
})

function fmtPrice(v: number): string {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtVolume(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return PLACEHOLDER
  return v.toLocaleString('zh-CN')
}

/** YYYY-MM-DD HH:mm；日线 bar（时间 00:00）只显示日期 */
function fmtTime(ts: number): string {
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  const date = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  const hh = d.getHours()
  const mm = d.getMinutes()
  return hh === 0 && mm === 0 ? date : `${date} ${p(hh)}:${p(mm)}`
}
</script>

<template>
  <div class="chart-legend">
    <!-- 第一行：现价行（大号价格 + 涨跌徽章；数据随十字光标联动） -->
    <div v-if="price !== null" class="legend-quote">
      <span class="legend-price num">{{ fmtPrice(price) }}</span>
      <ChangeBadge v-if="changePct !== null" :value="changePct" />
      <span v-else class="legend-change-placeholder num">{{ PLACEHOLDER }}</span>
    </div>
    <!-- 其后：时间 / 今开 / 最高 / 最低 / 量能（字段中文标签映射；K 线未就绪时隐藏） -->
    <template v-if="bar">
      <div class="legend-row">
        <span class="legend-label">时间</span>
        <span class="legend-value">{{ fmtTime(bar.timestamp) }}</span>
      </div>
      <div class="legend-row">
        <span class="legend-label">今开</span>
        <span class="legend-value">{{ fmtPrice(bar.open) }}</span>
      </div>
      <div class="legend-row">
        <span class="legend-label">最高</span>
        <span class="legend-value">{{ fmtPrice(bar.high) }}</span>
      </div>
      <div class="legend-row">
        <span class="legend-label">最低</span>
        <span class="legend-value">{{ fmtPrice(bar.low) }}</span>
      </div>
      <div class="legend-row">
        <span class="legend-label">量能</span>
        <span class="legend-value">{{ fmtVolume(bar.volume) }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 全部走 design.css token（任务 5.2）：无硬编码 hex/rgba，主题化（任务组 6）零改动 */
.chart-legend {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1.5;
}

/* 第一行：现价行（沿用原 sp-quote 视觉：大号价格 + ChangeBadge 徽章） */
.legend-quote {
  display: flex;
  align-items: center;
  gap: var(--sp-md);
}
.legend-price {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
  line-height: 1;
}
/* 涨跌幅占位（首根无前收等）：与 ChangeBadge 同尺寸的中性 pill */
.legend-change-placeholder {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: var(--r-sm);
  color: var(--text-secondary);
  background: var(--bg-surface-hover);
}

.legend-row {
  display: grid;
  grid-template-columns: 4.5em 1fr;
  align-items: baseline;
  column-gap: var(--sp-sm);
  white-space: nowrap;
}

.legend-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.legend-value {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
</style>

<template>
  <div class="block-kv">
    <!-- 键值摘要块（design D5）：title + items 声明驱动，取值来自 kv_payload -->
    <div class="kv-grid">
      <div v-for="item in items" :key="item.key" class="kv-item">
        <div class="kv-label">{{ item.label }}</div>
        <div class="kv-value num" :class="kvValueClass(kvPayload[item.key], item.fmt)">
          {{ fmt(kvPayload[item.key], item.fmt) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { DetailBlockKvItem } from '@/api/types'

/**
 * 成功判定口径（strategy-signal-outcome spec「信号存储与状态机」，
 * design D13 加权求和修订（2026-10-15 窗口调整）：口径在 UI 常量注释说明，不做设置项）：
 *
 *   总收益 = +5 日收益率×30% + +10 日收益率×50% + +15 日收益率×20%，
 *   总收益 > 5% 判成功，否则判失败；三时段任一越界未来（数据不足）
 *   → 待定（pending），不计入准确率分母。
 *
 * 绩效统计键（kv_payload，D6 通用聚合注入；2026-10-15 修订：删 pending_cnt
 * 数据不足数——kv 块不再展示该统计项）：
 *   accuracy = success / (success + failed)（小数或 null，分母 0 → null）
 *   success_cnt / failed_cnt：两态计数（整数）
 *   avg_ret_5d / avg_ret_10d / avg_ret_15d：非 NULL 收益率均值（小数或 null）
 */
const SUCCESS_CRITERION = '总收益 = 5日涨幅×30% + 10日涨幅×50% + 15日涨幅×20%，> 5% 判成功；待定 = 数据不足不入准确率分母'

/** kv 块：键值摘要（items 声明 → kv_payload 取值，fmt 按类型格式化；
 *  pct = 小数转百分比（绩效统计 accuracy/avg_ret_* 用，null → '--'）） */
const props = defineProps<{
  title?: string
  items: DetailBlockKvItem[]
  kvPayload: Record<string, number | string | null>
}>()

void SUCCESS_CRITERION

function fmt(v: number | string | null | undefined, type?: 'int' | 'float' | 'str' | 'pct'): string {
  if (v == null || v === '') return '--'
  if (type === 'pct') {
    const n = Number(v)
    if (!Number.isFinite(n)) return '--'
    return `${(n * 100).toFixed(1)}%`
  }
  if (type === 'float') return Number(v).toFixed(2)
  if (type === 'int') return String(Math.round(Number(v)))
  return String(v)
}

/** kv 值着色（A 股红涨绿跌，pct 项：avg_ret_* 正数红/负数绿） */
function kvValueClass(v: number | string | null | undefined, type?: 'int' | 'float' | 'str' | 'pct'): string {
  if (type !== 'pct') return ''
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ''
  return n > 0 ? 'text-rise' : 'text-fall'
}
</script>

<style scoped>
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--sp-md);
}
.kv-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--sp-md);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  background: var(--bg-surface);
}
.kv-label {
  font-size: 11px;
  color: var(--text-secondary);
}
.kv-value {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}
</style>

<template>
  <div class="block-signals">
    <!-- 信号表格（design D5：复用信号列表列声明）：通用列 + columns 声明驱动私有列
         + states 声明着色 + 参数版本标识 -->
    <el-table :data="rows" size="small" empty-text="暂无信号" row-key="code" @row-click="$emit('row-click', $event)">
      <el-table-column label="名称 / 编码" min-width="130">
        <template #default="{ row }">
          <div class="cell-stock">
            <span class="nm">{{ row.name }}</span>
            <span class="cd mono">{{ row.code }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="信号日期" width="100" align="center">
        <template #default="{ row }">
          <span class="num">{{ row.signal_date }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="86" align="center">
        <template #default="{ row }">
          <span class="badge" :class="badgeClass(row.state)">{{ stateLabel(row.state) }}</span>
        </template>
      </el-table-column>
      <!-- 方向 / 入场参考价两通用列（D12 display 层裁剪）：任务详情信号列表
           固定不渲染（量价策略恒为买方向；入场参考价与 B 日股价价格分量同源重复）。
           策略信号页主列表（StrategySignalView）不受此裁剪，仍渲染完整通用列 -->
      <el-table-column label="参数版本" width="84" align="center">
        <template #default="{ row }">
          <span class="badge badge--accent mono">v{{ row.params_version }}</span>
        </template>
      </el-table-column>
      <!-- 私有列（columns 声明驱动）：date 居中定宽 / 数值右对齐 / str 原样文本
           / pct 涨跌百分比（正涨红负跌绿、NULL '--'）/ price_pct「价格 | 涨跌幅」
           合并单元格（D12）/ outcome 成功判定 badge -->
      <el-table-column
        v-for="col in visibleColumns"
        :key="col.key"
        :width="colWidth(col.type)"
        :align="col.type === 'date' || col.type === 'str' ? 'center' : 'right'"
        :class-name="col.type === 'outcome' ? '' : 'col-num'"
      >
        <!-- outcome 列头带规则提示图标（D13）：悬浮展示加权求和成功判定规则，
             复用 TaskDialog 参数说明图标交互（QuestionFilled + el-tooltip） -->
        <template v-if="col.type === 'outcome'" #header>
          <span class="col-head-outcome">
            {{ col.label }}
            <el-tooltip :content="OUTCOME_RULE" placement="top" :show-after="200">
              <el-icon class="col-head-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
        </template>
        <template v-else #header>
          <span>{{ col.label }}</span>
        </template>
        <template #default="{ row }">
          <!-- outcome：成功判定 badge（success 绿 / failed 红 / pending 灰） -->
          <span v-if="col.type === 'outcome'" class="badge" :class="outcomeBadgeClass(row.outcome)">
            {{ outcomeLabel(row.outcome) }}
          </span>
          <!-- pct：涨跌百分比（正涨红 / 负跌绿 / 0 灰、NULL '--'） -->
          <span v-else-if="col.type === 'pct'" class="num" :class="pctClass(cellValue(row, col.key))">
            {{ fmtPct(cellValue(row, col.key)) }}
          </span>
          <!-- price_pct：合并单元格「价格 | 涨跌幅」（D12）：
               价格分量普通 float 文本，涨幅分量复用 pct 渲染规则
               （正涨红 / 负跌绿 / 0 灰、NULL '--'），两值 ' | ' 分隔 -->
          <template v-else-if="col.type === 'price_pct'">
            <span class="num">{{ fmtPrice(cellValue(row, col.priceKey || '')) }}</span>
            <span class="num pp-sep">|</span>
            <span class="num" :class="pctClass(cellValue(row, col.pctKey || ''))">
              {{ fmtPct(cellValue(row, col.pctKey || '')) }}
            </span>
          </template>
          <span v-else class="num">{{ fmtPayload(cellValue(row, col.key), col.type) }}</span>
        </template>
      </el-table-column>
    </el-table>
    <!-- 首页之外的完整信号列表入口（父级跳转信号列表 Tab） -->
    <div class="signals-foot" v-if="total > rows.length">
      <button class="btn btn--ghost btn--sm" @click="$emit('goto-all')">查看全部 {{ total }} 条信号</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import type { StrategySignalRow, StrategyStateDecl, StrategyColumnDecl } from '@/api/types'

/** 成功判定加权求和规则文案（D13，spec「成功判定规则悬浮提示」场景）：
 *  总收益 = 7日涨幅×50% + 14日涨幅×30% + 30日涨幅×20%；
 *  总收益 > 5% 判成功，否则失败；数据不足（未到 30 日）不计入统计 */
const OUTCOME_RULE =
  '成功判定规则：总收益 = 7日涨幅×50% + 14日涨幅×30% + 30日涨幅×20%；总收益 > 5% 判成功，否则失败；数据不足（三时段未齐）不计入准确率统计'

/** signals 块：该任务信号表格（detail API signals_page 首页数据 + 列声明） */
const props = defineProps<{
  rows: StrategySignalRow[]
  total: number
  states: StrategyStateDecl[]
  columns: StrategyColumnDecl[]
}>()

defineEmits<{
  'row-click': [row: StrategySignalRow]
  'goto-all': []
}>()

/** D12 display 层列裁剪黑名单（columns 声明不动，仅模板渲染跳过）：
 *  direction（方向）与 entry_ref_price（入场参考价）两通用列在任务详情
 *  信号列表不出现；策略信号页主列表（StrategySignalView）不受影响 */
const HIDDEN_COL_KEYS = new Set(['direction', 'entry_ref_price'])
const visibleColumns = computed(() => props.columns.filter((c) => !HIDDEN_COL_KEYS.has(c.key)))

const COLOR_CLASS: Record<string, string> = {
  info: 'badge--info',
  warning: 'badge--warning',
  danger: 'badge--rise',
  success: 'badge--fall',
}
function stateLabel(v: string) {
  return props.states.find((s) => s.value === v)?.label || v
}
function badgeClass(v: string) {
  const decl = props.states.find((s) => s.value === v)
  return COLOR_CLASS[decl?.color || 'info'] || 'badge--info'
}
/** 列取值（strategy-signal-outcome 5.1）：先 payload[key]（策略私有过程字段，
 *  D10），无该键时回退行级字段（ret_7d/ret_14d/ret_30d/outcome 绩效列、
 *  entry_ref_price B 点价格列——行级列不在 payload） */
function cellValue(row: StrategySignalRow, key: string): number | string | undefined {
  const pv = row.payload?.[key]
  if (pv !== undefined) return pv ?? undefined
  return row[key as keyof StrategySignalRow] as number | string | undefined
}
function colWidth(type: StrategyColumnDecl['type']): number {
  if (type === 'date') return 100
  if (type === 'str') return 96
  if (type === 'pct') return 88
  // price_pct 合并列（价格 | 涨跌幅双值）比单值列更宽
  if (type === 'price_pct') return 140
  if (type === 'outcome') return 80
  return 84
}
/** pct 列格式化（D7）：小数 0.173 → +17.3%（正数带 + 号）；NULL/undefined → '--' */
function fmtPct(v: number | string | undefined): string {
  if (v == null || v === '') return '--'
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  const sign = n > 0 ? '+' : ''
  return `${sign}${(n * 100).toFixed(1)}%`
}
/** pct 列着色（A 股红涨绿跌）：正数 --rise / 负数 --fall / 0 与空值不着色 */
function pctClass(v: number | string | undefined): string {
  if (v == null || v === '') return ''
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ''
  return n > 0 ? 'text-rise' : 'text-fall'
}
/** outcome 列（D7）：成功判定 badge——success 成功绿 / failed 失败红 /
 *  pending 待定灰 / NULL（旧信号无绩效）'--' */
const OUTCOME_BADGE: Record<string, string> = {
  success: 'badge--fall',
  failed: 'badge--rise',
  pending: 'badge--disabled',
}
const OUTCOME_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
  pending: '待定',
}
function outcomeLabel(v: string | null | undefined): string {
  return OUTCOME_LABEL[v || ''] || '--'
}
function outcomeBadgeClass(v: string | null | undefined): string {
  return OUTCOME_BADGE[v || ''] || 'badge--disabled'
}
function fmtPayload(v: number | string | undefined, type: StrategyColumnDecl['type']): string {
  if (v == null) return '--'
  if (type === 'float') return Number(v).toFixed(2)
  if (type === 'int') return String(Math.round(Number(v)))
  return String(v)
}
/** price_pct 价格分量格式化（D12）：float 两位小数文本；NULL/undefined → '--'。
 *  取值同 cellValue 双路径（payload 先、行级回退），可能为 number/string */
function fmtPrice(v: number | string | null | undefined): string {
  if (v == null || v === '') return '--'
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return n.toFixed(2)
}
</script>

<style scoped>
.cell-stock {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cell-stock .nm {
  color: var(--text-primary);
  font-size: 12px;
}
.cell-stock .cd {
  color: var(--text-disabled);
  font-size: 11px;
}
/* price_pct 合并列两值分隔符（弱化视觉层级，涨幅分量才是着色重点） */
.pp-sep {
  color: var(--text-disabled);
  margin: 0 2px;
}
/* outcome 列头（D13）：label + 规则提示图标 */
.col-head-outcome {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.col-head-icon {
  color: var(--text-disabled);
  font-size: 13px;
  cursor: help;
}
.signals-foot {
  display: flex;
  justify-content: center;
  padding-top: var(--sp-sm);
}
</style>

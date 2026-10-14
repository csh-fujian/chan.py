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
      <!-- 信号日期列删除（strategy-volume-breakout-pullback D7：与 A 日列
           冲突——A 日即信号日期，三值合并列 a_col 已含日期分量） -->
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
          <!-- price_pct：合并单元格「价格 | 涨幅」（D12）：
               价格分量普通 float 文本，涨幅分量复用 pct 渲染规则
               （正涨红 / 负跌绿 / 0 灰、NULL '--'），两值 ' | ' 分隔 -->
          <template v-else-if="col.type === 'price_pct'">
            <span class="num">{{ fmtPrice(cellValue(row, col.priceKey || '')) }}</span>
            <span class="num pp-sep">|</span>
            <span class="num" :class="pctClass(cellValue(row, col.pctKey || ''))">
              {{ fmtPct(cellValue(row, col.pctKey || '')) }}
            </span>
          </template>
          <!-- date_price_pct：三值合并单元格「日期 | 价格 | 涨幅」
               （strategy-volume-breakout-pullback D7，A/B 日列整合）；
               b_col 带 popup 标记时可点击弹出多 B 级事件详情表 -->
          <template v-else-if="col.type === 'date_price_pct'">
            <span
              class="num dpc"
              :class="{ 'dpc--popup': col.popup === 'b_events' && bEventsOf(row).length }"
              @click.stop="col.popup === 'b_events' && openBDialog(row, col.label)"
            >
              {{ fmtDay(cellValue(row, col.dateKey || '')) }}
              <span class="pp-sep">|</span>
              {{ fmtPrice(cellValue(row, col.priceKey || '')) }}
              <span class="pp-sep">|</span>
              <span :class="pctClass(cellValue(row, col.pctKey || ''))">
                {{ fmtPct(cellValue(row, col.pctKey || '')) }}
              </span>
            </span>
          </template>
          <span v-else class="num">{{ fmtPayload(cellValue(row, col.key), col.type) }}</span>
        </template>
      </el-table-column>
    </el-table>
    <!-- B 级事件详情弹窗（strategy-volume-breakout-pullback D7/4.2）：B 列点击
         展开——等级/时间（30m 带时刻）/价格/涨幅/独立绩效；30m 事件时间展示
         日期+时间、日线只展示日期；旧口径信号（无 b_events）提示旧口径 -->
    <el-dialog
      v-model="bDialogVisible"
      :title="bDialogTitle"
      width="720px"
      append-to-body
      class="b-events-dialog"
    >
      <el-table v-if="bDialogEvents.length" :data="bDialogEvents" size="small">
        <el-table-column label="等级" width="70" align="center">
          <template #default="{ row }">
            <!-- Bx 等级悬浮提示（2026-10-15 修订）：白话说明五级触发逻辑 -->
            <el-tooltip :content="B_LEVEL_RULE[row.b_level] || ''" placement="top" :show-after="200">
              <span class="badge badge--accent b-level-badge">{{ row.b_level }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150" align="center">
          <template #default="{ row }">
            <span class="num">{{ fmtBTime(row.b_time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="周期" width="64" align="center">
          <template #default="{ row }">
            <span class="num">{{ row.b_kl_type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="价格" width="90" align="right">
          <template #default="{ row }">
            <span class="num">{{ fmtPrice(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="当日涨幅" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.day_pct)">{{ fmtPct(row.day_pct) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="5日收益" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.ret_5d)">{{ fmtPct(row.ret_5d) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="10日收益" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.ret_10d)">{{ fmtPct(row.ret_10d) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="15日收益" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.ret_15d)">{{ fmtPct(row.ret_15d) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="判定" width="70" align="center">
          <template #default="{ row }">
            <span class="badge" :class="outcomeBadgeClass(row.outcome)">{{ outcomeLabel(row.outcome) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="b-events-empty">
        旧口径信号：无 B 级事件明细（该信号产生于 B 点分级判定上线前，可重新运行任务按新口径产出）
      </div>
    </el-dialog>
    <!-- 首页之外的完整信号列表入口（父级跳转信号列表 Tab） -->
    <div class="signals-foot" v-if="total > rows.length">
      <button class="btn btn--ghost btn--sm" @click="$emit('goto-all')">查看全部 {{ total }} 条信号</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import type { StrategySignalRow, StrategyStateDecl, StrategyColumnDecl, BEventRow } from '@/api/types'

/** 成功判定加权求和规则文案（2026-10-15 修订，spec「成功判定规则悬浮提示」场景）：
 *  总收益 = 5日涨幅×30% + 10日涨幅×50% + 15日涨幅×20%；
 *  总收益 > 5% 判成功，否则失败；数据不足（三时段未齐）不计入统计 */
const OUTCOME_RULE =
  '成功判定规则：总收益 = 5日涨幅×30% + 10日涨幅×50% + 15日涨幅×20%；总收益 > 5% 判成功，否则失败；数据不足（三时段未齐）不计入准确率统计'

/** B 点五级触发逻辑白话（2026-10-15 修订，spec「B 等级悬浮提示触发逻辑」场景）：
 *  悬浮弹窗「等级」列的 Bx 标记展示对应判定规则 */
const B_LEVEL_RULE: Record<string, string> = {
  B1: 'B1 初步确认：日线 MACD 柱由绿转红（金叉），或绿柱绝对值连续 3 根缩短（下跌动能衰竭）',
  B2: 'B2 中部肯定：30 分钟周期 MACD 柱面积底背离——价格创新低而绿柱面积不创新低',
  B3: 'B3 买点确认：30 分钟周期出现缠论任意等级买点',
  B4: 'B4 买点确认：日线周期出现缠论任意等级买点',
  B: 'B 最终确认：放量突破回调期高点（收盘创窗口新高且量能充足），确认级别最高',
}

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
 *  D10），无该键时回退行级字段（ret_5d/ret_10d/ret_15d/outcome 绩效列、
 *  entry_ref_price B 点价格列——行级列不在 payload） */
function cellValue(row: StrategySignalRow, key: string): number | string | undefined {
  const pv = row.payload?.[key]
  if (pv !== undefined) return Array.isArray(pv) ? undefined : (pv ?? undefined)
  return row[key as keyof StrategySignalRow] as number | string | undefined
}
function colWidth(type: StrategyColumnDecl['type']): number {
  if (type === 'date') return 100
  if (type === 'str') return 96
  if (type === 'pct') return 88
  // price_pct 合并列（价格 | 涨幅双值）比单值列更宽
  if (type === 'price_pct') return 140
  // date_price_pct 三值合并列（日期 | 价格 | 涨幅，D7 A/B 日整合）
  if (type === 'date_price_pct') return 230
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
/** date_price_pct 日期分量格式化（D7）：'YYYY-MM-DD HH:MM:SS' 截 10 位日期；
 *  b_date（30m 事件时间）在列单元格只展示日期分量，时刻在弹窗展示 */
function fmtDay(v: number | string | null | undefined): string {
  if (v == null || v === '') return '--'
  return String(v).slice(0, 10)
}

// ----------------------------------------------------------------------
// B 级事件弹窗（strategy-volume-breakout-pullback D7/4.2）
// ----------------------------------------------------------------------

const bDialogVisible = ref(false)
const bDialogTitle = ref('')
const bDialogEvents = ref<BEventRow[]>([])

/** 行的 B 级事件集合（detail API 任务详情行 payload.b_events 已嵌入） */
function bEventsOf(row: StrategySignalRow): BEventRow[] {
  const v = row.payload?.b_events
  return Array.isArray(v) ? (v as BEventRow[]) : []
}

function openBDialog(row: StrategySignalRow, colLabel: string): void {
  bDialogEvents.value = bEventsOf(row)
  bDialogTitle.value = `${row.name}（${row.code}）· ${colLabel}级买点详情`
  bDialogVisible.value = true
}

/** B 事件时间展示（D4）：30m 判定（b_time 含非零时刻）展示 'MM-DD HH:MM'；
 *  日线判定（00:00:00）只展示日期 'YYYY-MM-DD' */
function fmtBTime(t: string): string {
  if (!t) return '--'
  if (t.length >= 19 && !t.endsWith('00:00:00')) return t.slice(5, 16)
  return t.slice(0, 10)
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
/* date_price_pct 三值合并单元格（D7）：B 列带事件时可点击弹窗（下划线提示） */
.dpc--popup {
  cursor: pointer;
  border-bottom: 1px dashed var(--text-disabled);
}
.dpc--popup:hover {
  border-bottom-color: var(--text-primary);
}
/* B 级事件弹窗旧口径提示文案 */
.b-events-empty {
  color: var(--text-disabled);
  font-size: 12px;
  padding: 12px 0;
  text-align: center;
}
/* Bx 等级标记（2026-10-15）：悬浮提示触发逻辑，图标交互提示 */
.b-level-badge {
  cursor: help;
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

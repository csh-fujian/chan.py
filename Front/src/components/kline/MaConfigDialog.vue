<template>
  <el-dialog
    v-model="visible"
    title="均线配置"
    width="420px"
    :close-on-click-modal="false"
    append-to-body
    class="ma-config-dialog"
  >
    <div class="ma-hint">配置主图移动均线的天数与颜色，确认后立即生效并持久保存</div>
    <div class="ma-rows">
      <div v-for="(row, i) in rows" :key="i" class="ma-row">
        <el-input-number
          v-model="row.days"
          class="ma-row__days"
          :min="1"
          :step="1"
          :precision="0"
          :controls="false"
          size="small"
          placeholder="天数"
        />
        <el-color-picker v-model="row.color" size="small" class="ma-row__color" />
        <button class="ma-row__del" type="button" title="删除" @click="rows.splice(i, 1)">
          <el-icon><Delete /></el-icon>
        </button>
      </div>
      <div v-if="rows.length === 0" class="ma-empty">暂无均线，点击下方添加</div>
    </div>
    <button class="ma-add" type="button" @click="addRow">
      <el-icon><Plus /></el-icon> 添加均线
    </button>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="onConfirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * MaConfigDialog.vue — 主图均线配置弹窗（kline-chart-change D2）
 * 行式列表：天数输入 + 颜色选择 + 删除，尾部新增行；
 * 确认时校验天数 ≥1 整数、拒绝重复天数（ElMessage.warning），写入 chartConfig store。
 */
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { useChartConfigStore, type MaLineConfig } from '@/stores/chartConfig'

const props = defineProps<{
  modelValue: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [v: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const chartConfig = useChartConfigStore()

/** 编辑中行（days 可能被清空，color 可能为空 → 确认时兜底） */
interface EditRow {
  days: number | undefined
  color: string | null
}

const rows = ref<EditRow[]>([])

/** 新增行候选天数（取首个未占用值，避免一上来就撞重复） */
const ADD_DAY_CANDIDATES = [30, 120, 250, 15, 3, 8, 13, 21, 34, 55, 89, 144, 2, 4, 6, 7, 9, 11, 12]
/** 新增行候选颜色（避开红涨绿跌语义色） */
const ADD_COLOR_CANDIDATES = ['#F0B90B', '#60A5FA', '#C084FC', '#F472B6', '#22D3EE', '#FB923C', '#A3E635', '#94A3B8']

/** 从 store 快照编辑行（打开时调用，取消不回写） */
function snapshotFromStore(): void {
  rows.value = chartConfig.mainMA.map((m) => ({ days: m.days, color: m.color }))
}

/** 当前编辑中的合法天数集合（供重复检测） */
function currentDaysList(): number[] {
  return rows.value
    .map((r) => r.days)
    .filter((d): d is number => typeof d === 'number' && Number.isInteger(d) && d >= 1)
}

/** 检查行集合是否存在重复天数，存在则 warning 并返回 true */
function warnIfDuplicate(list: number[]): boolean {
  const seen = new Set<number>()
  for (const d of list) {
    if (seen.has(d)) {
      ElMessage.warning(`已存在 ${d} 日均线，请勿重复`)
      return true
    }
    seen.add(d)
  }
  return false
}

function addRow(): void {
  const used = new Set(currentDaysList())
  // 编辑态已撞重复时先提示修复，不再叠加新行
  if (warnIfDuplicate(currentDaysList())) return
  const days = ADD_DAY_CANDIDATES.find((d) => !used.has(d)) ?? Math.max(...used, 0) + 1
  const usedColors = new Set(rows.value.map((r) => r.color).filter((c): c is string => !!c))
  const color = ADD_COLOR_CANDIDATES.find((c) => !usedColors.has(c)) ?? ADD_COLOR_CANDIDATES[0]
  rows.value.push({ days, color })
}

function onConfirm(): void {
  // 校验天数：≥1 整数
  for (const r of rows.value) {
    if (typeof r.days !== 'number' || !Number.isInteger(r.days) || r.days < 1) {
      ElMessage.warning('均线天数需为 ≥1 的整数')
      return
    }
  }
  // 拒绝重复天数
  if (warnIfDuplicate(currentDaysList())) return
  const list: MaLineConfig[] = rows.value.map((r) => ({
    days: r.days as number,
    color: r.color ?? ADD_COLOR_CANDIDATES[0],
  }))
  chartConfig.setMainMA(list)
  visible.value = false
}

// 打开弹窗时从 store 取当前配置快照；取消不生效
watch(visible, (v) => {
  if (v) snapshotFromStore()
})
</script>

<style scoped>
.ma-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: var(--sp-md);
}

.ma-rows {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  max-height: 320px;
  overflow-y: auto;
}

.ma-row {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
}
.ma-row__days {
  width: 110px;
}
.ma-row__days :deep(.el-input__wrapper) {
  background: var(--bg-surface);
  box-shadow: 0 0 0 1px var(--border-base) inset;
}
.ma-row__del {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--text-secondary);
  transition: all 0.15s ease;
}
.ma-row__del:hover {
  background: var(--rise-dim);
  color: var(--rise);
}

.ma-empty {
  font-size: 12px;
  color: var(--text-disabled);
  padding: var(--sp-sm) 0;
}

.ma-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: var(--sp-md);
  padding: 5px 12px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--r-sm);
  color: var(--text-secondary);
  font-size: 12px;
  transition: all 0.15s ease;
}
.ma-add:hover {
  color: var(--accent-hover);
  border-color: var(--accent-base);
}
</style>

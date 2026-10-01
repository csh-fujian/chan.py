<template>
  <el-dialog
    v-model="visible"
    title="量均线配置"
    width="360px"
    :close-on-click-modal="false"
    append-to-body
    class="vol-config-dialog"
  >
    <div class="vol-hint">配置成交量副图移动均线的天数，确认后立即生效并持久保存</div>
    <div class="vol-rows">
      <div v-for="(row, i) in rows" :key="i" class="vol-row">
        <el-input-number
          v-model="row.days"
          class="vol-row__days"
          :min="1"
          :step="1"
          :precision="0"
          :controls="false"
          size="small"
          placeholder="天数"
        />
        <button class="vol-row__del" type="button" title="删除" @click="rows.splice(i, 1)">
          <el-icon><Delete /></el-icon>
        </button>
      </div>
      <div v-if="rows.length === 0" class="vol-empty">暂无量均线，点击下方添加</div>
    </div>
    <button class="vol-add" type="button" @click="addRow">
      <el-icon><Plus /></el-icon> 添加量均线
    </button>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="onConfirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * VolConfigDialog.vue — 成交量均线配置弹窗（kline-chart-change D2）
 * 仅天数增删改（无颜色），校验天数 ≥1 整数、拒绝重复天数（ElMessage.warning），
 * 写入 chartConfig store，由 KLineChart 的 watch 即时应用到 VOL 副图。
 */
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { useChartConfigStore, type VolMaConfig } from '@/stores/chartConfig'

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

/** 编辑中行（days 可能被清空 → 确认时校验） */
interface EditRow {
  days: number | undefined
}

const rows = ref<EditRow[]>([])

/** 新增行候选天数（取首个未占用值） */
const ADD_DAY_CANDIDATES = [5, 10, 20, 60, 30, 120, 15, 3, 8, 13, 21, 34, 55, 2, 4, 6, 7, 9, 11]

/** 从 store 快照编辑行（打开时调用，取消不回写） */
function snapshotFromStore(): void {
  rows.value = chartConfig.volMA.map((v) => ({ days: v.days }))
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
      ElMessage.warning(`已存在 ${d} 日量均线，请勿重复`)
      return true
    }
    seen.add(d)
  }
  return false
}

function addRow(): void {
  // 编辑态已撞重复时先提示修复，不再叠加新行
  if (warnIfDuplicate(currentDaysList())) return
  const used = new Set(currentDaysList())
  const days = ADD_DAY_CANDIDATES.find((d) => !used.has(d)) ?? Math.max(...used, 0) + 1
  rows.value.push({ days })
}

function onConfirm(): void {
  // 校验天数：≥1 整数
  for (const r of rows.value) {
    if (typeof r.days !== 'number' || !Number.isInteger(r.days) || r.days < 1) {
      ElMessage.warning('量均线天数需为 ≥1 的整数')
      return
    }
  }
  // 拒绝重复天数
  if (warnIfDuplicate(currentDaysList())) return
  const list: VolMaConfig[] = rows.value.map((r) => ({ days: r.days as number }))
  chartConfig.setVolMA(list)
  visible.value = false
}

// 打开弹窗时从 store 取当前配置快照；取消不生效
watch(visible, (v) => {
  if (v) snapshotFromStore()
})
</script>

<style scoped>
.vol-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: var(--sp-md);
}

.vol-rows {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  max-height: 280px;
  overflow-y: auto;
}

.vol-row {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
}
.vol-row__days {
  width: 110px;
}
.vol-row__days :deep(.el-input__wrapper) {
  background: var(--bg-surface);
  box-shadow: 0 0 0 1px var(--border-base) inset;
}
.vol-row__del {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--text-secondary);
  transition: all 0.15s ease;
}
.vol-row__del:hover {
  background: var(--rise-dim);
  color: var(--rise);
}

.vol-empty {
  font-size: 12px;
  color: var(--text-disabled);
  padding: var(--sp-sm) 0;
}

.vol-add {
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
.vol-add:hover {
  color: var(--accent-hover);
  border-color: var(--accent-base);
}
</style>

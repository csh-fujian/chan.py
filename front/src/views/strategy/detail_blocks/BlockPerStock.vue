<template>
  <div class="block-per-stock">
    <!-- 逐股结果表格（design D5）：股票/匹配/执行状态/执行时间/摘要 + 参数版本 -->
    <el-table :data="rows" size="small" empty-text="暂无逐股结果">
      <el-table-column label="名称 / 编码" min-width="130">
        <template #default="{ row }">
          <div class="cell-stock">
            <span class="nm">{{ row.name }}</span>
            <span class="cd mono">{{ row.code }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="匹配结果" width="90" align="center">
        <template #default="{ row }">
          <span class="badge" :class="row.run_status === 'failed' ? 'badge--warning' : row.matched ? 'badge--rise' : 'badge--default'">
            {{ row.run_status === 'failed' ? '失败' : row.matched ? '命中' : '未匹配' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="信号日期" width="100" align="center">
        <template #default="{ row }">
          <span class="num">{{ row.signal_date || '--' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="参数版本" width="80" align="center">
        <template #default="{ row }">
          <span class="badge badge--accent mono">v{{ row.params_version }}</span>
        </template>
      </el-table-column>
      <el-table-column label="执行时间" width="100" align="center">
        <template #default="{ row }">
          <span class="num">{{ fmtDate(row.executed_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="摘要" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span :class="row.run_status === 'failed' ? 'msg-failed' : 'msg'">{{ row.message }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import type { StrategyTaskStockResult } from '@/api/types'

/** per_stock 块：逐股结果表格（scope='all' 时数据不返回，容器层已静默隐藏本块） */
defineProps<{
  rows: StrategyTaskStockResult[]
}>()

function fmtDate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
.msg {
  font-size: 12px;
  color: var(--text-secondary);
}
.msg-failed {
  font-size: 12px;
  color: var(--warning);
}
</style>

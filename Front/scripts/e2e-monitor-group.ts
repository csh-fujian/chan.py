/**
 * monitor-group E2E（mock 数据层全链路）— tasks 6.1
 *
 * 直接驱动 Front/src/mock/data/monitor.ts（MSW handlers 的底层数据层），
 * 验证 spec 核心链路：加入监控选组/不选组 → 新建分组查重 → 过滤三形态 →
 * 重命名 → 拖拽排序 → 删除置未分组 → 计数联动
 *
 * 运行：cd Front && npx tsx scripts/e2e-monitor-group.ts
 */
import { strict as assert } from 'node:assert'
import type { MonitorItem } from '../src/api/types'
import {
  monitorGroups,
  monitorItems,
  completedItems,
  createGroup,
  renameGroup,
  removeGroup,
  reorderGroups,
  filterByGroupId,
} from '../src/mock/data/monitor'

const pass = (name: string) => console.log(`  PASS ${name}`)
const throws = (fn: () => unknown, msg: string) => {
  try {
    fn()
    throw new Error(`应抛异常: ${msg}`)
  } catch (e) {
    if ((e as Error).message.includes('应抛异常')) throw e
    return (e as Error).message
  }
}

// --- 前置：初始 mock 状态 ---
const initialGroupIds = monitorGroups.map((g) => g.id)
console.log(`初始分组: ${monitorGroups.map((g) => g.name).join(' / ')}；监控中 ${monitorItems.length} 条、已完成 ${completedItems.length} 条\n`)

// --- 1. 加入监控携带分组（spec: 选择分组加入）---
const g1 = monitorGroups[0]
const item1: MonitorItem = {
  id: 900001, code: 'sz.E2E001', name: 'E2E一号', kl_type: 'D',
  bsp_type: 'T2B', bsp_date: Date.now(), bsp_price: 10, entry_price: 10,
  monitor_start_time: '2026-10-04 10:00:00', current_pnl_pct: 1.5, group_id: g1.id,
} as unknown as MonitorItem
monitorItems.push(item1)
assert.equal(monitorItems[monitorItems.length - 1].group_id, g1.id)
pass('加入监控选组：记录归属所选分组')

// --- 2. 不选分组加入（spec: 不选分组加入）---
const item2 = { ...item1, id: 900002, code: 'sz.E2E002', group_id: null }
monitorItems.push(item2 as unknown as MonitorItem)
assert.equal(monitorItems[monitorItems.length - 1].group_id, null)
pass('不选分组加入：归入未分组')

// --- 3. 弹窗内快速新建分组（spec：名称合法即时创建，末尾追加）---
const g = createGroup(' E2E临时组 ')
assert.equal(g.name, 'E2E临时组')
assert.equal(g.sort_order, Math.max(...monitorGroups.map((x) => x.sort_order)))
pass('新建分组：去首尾空白、sort_order 末尾追加')

// --- 4. 名称查重（spec：分组名称非法）---
assert.match(throws(() => createGroup('E2E临时组'), '重名'), /已存在/)
assert.match(throws(() => createGroup('   '), '空名'), /不能为空/)
pass('查重：重名/空名抛明确错误')

// --- 5. 过滤三形态（spec：监控中/已完成按分组过滤 + 未分组 + 全部）---
const gid = String(g1.id)
const f1 = filterByGroupId(monitorItems, gid)
assert.ok(f1.length > 0 && f1.every((m) => m.group_id === g1.id))
const f2 = filterByGroupId(monitorItems, 'ungrouped')
assert.ok(f2.length > 0 && f2.every((m) => m.group_id === null))
const f3 = filterByGroupId(monitorItems, null)
assert.equal(f3.length, monitorItems.length)
const fc = filterByGroupId(completedItems, gid)
assert.ok(fc.length > 0 && fc.every((m) => m.group_id === g1.id))
pass('过滤：数值 id / ungrouped / 缺省三形态 + 已完成 tab 同口径')

// --- 6. 重命名（spec：重命名分组）---
renameGroup(g.id, 'E2E改名组')
assert.equal(g.name, 'E2E改名组')
throws(() => renameGroup(g.id, monitorGroups.find((x) => x.id !== g.id)!.name), '撞名')
pass('重命名：成功 + 撞名抛错')

// --- 7. 拖拽排序（spec：拖拽排序）---
const ids = monitorGroups.map((x) => x.id).slice().reverse()
reorderGroups(ids)
assert.deepEqual(monitorGroups.map((x) => x.id), ids)
pass('拖拽排序：顺序持久化为新序')

// --- 8. 删除置未分组（spec：删除分组，记录不删除）---
const item3 = { ...item1, id: 900003, code: 'sz.E2E003', group_id: g.id }
monitorItems.push(item3 as unknown as MonitorItem)
const done = { ...(completedItems[0] ?? { id: 900004, code: 'sz.E2E004', profit: 3 }), group_id: g.id } as never
completedItems.push(done)
removeGroup(g.id)
assert.ok(!monitorGroups.some((x) => x.id === g.id))
assert.equal(monitorItems.filter((m) => m.group_id === g.id).length, 0)
assert.equal(completedItems.filter((m) => (m as { group_id: number | null }).group_id === g.id).length, 0)
assert.ok(monitorItems.some((m) => m.code === 'sz.E2E003')) // 记录仍在（置 null）
pass('删除分组：组内监控中+已完成记录置未分组、不删除')

// --- 清理 E2E 遗留，恢复初始组序 ---
const e2eCodes = ['sz.E2E001', 'sz.E2E002', 'sz.E2E003']
for (let i = monitorItems.length - 1; i >= 0; i--) {
  if (e2eCodes.includes(monitorItems[i].code)) monitorItems.splice(i, 1)
}
completedItems.pop() // 移除刚 push 的 done
reorderGroups(initialGroupIds)

console.log('\n全部通过 ✓')

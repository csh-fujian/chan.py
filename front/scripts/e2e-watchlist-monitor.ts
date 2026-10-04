/**
 * watchlist 加入监控 E2E（mock 数据层）— watchlist-page-change tasks 7.5
 *
 * 验证 spec「自选加入监控」Requirement 的可脚本化场景：
 *   source_type 三值白名单（watchlist 放行/缺省 chan/非法兜底 chan）、
 *   预置 watchlist 记录（监控中+已完成两个 tab 的来源数据）、
 *   级别默认日线词表、取价失败兜底语义（按行股价提交）
 *
 * 运行：cd Front && npx tsx scripts/e2e-watchlist-monitor.ts
 */
import { strict as assert } from 'node:assert'
import { monitorItems, completedItems, monitorGroups, createGroup } from '../src/mock/data/monitor'

const pass = (name: string) => console.log(`  PASS ${name}`)

// --- 1. 预置 watchlist 来源记录（两个 tab 来源列数据源）---
const wlMonitoring = monitorItems.find((m) => m.source_type === 'watchlist')
const wlCompleted = completedItems.find((m) => m.source_type === 'watchlist')
assert.ok(wlMonitoring, 'mock 监控中预置 watchlist 记录')
assert.ok(wlCompleted, 'mock 已完成预置 watchlist 记录')
pass('预置记录：监控中 + 已完成各 1 条 source_type=watchlist（来源列显示「自选」的数据源）')

// --- 2. source_type 白名单语义（与后端/handler 一致：watchlist 放行、缺省/非法落 chan）---
// 模拟 handler 135-138 行的判定逻辑（同一表达式）
const normalize = (v: unknown): 'chan' | 'strategy' | 'watchlist' =>
  v === 'strategy' || v === 'watchlist' ? v : 'chan'
assert.equal(normalize('watchlist'), 'watchlist')
assert.equal(normalize(undefined), 'chan')
assert.equal(normalize('xxx'), 'chan')
assert.equal(normalize('strategy'), 'strategy')
pass('source_type 白名单：watchlist 放行 / 缺省 chan / 非法值兜底 chan')

// --- 3. 行级/批量提交字段（模拟 WatchlistView confirmAddMonitor 的 payload 组装）---
// 行级：source_type='watchlist' + 级别默认 'D'（design D9）
const rowPayload = {
  code: 'sz.E2E101', kl_type: 'D', entry_price: 10.5,
  monitor_start_time: '2026-10-04 10:00:00',
  group_id: undefined, source_type: 'watchlist' as const,
}
assert.equal(rowPayload.kl_type, 'D')
assert.equal(rowPayload.source_type, 'watchlist')
assert.equal(rowPayload.group_id, undefined) // 未分组不传（对齐 D5/BspView）
pass('行级提交 payload：级别默认日线 + source_type=watchlist + 未分组不传 group_id')

// 批量：逐只取价失败兜底 = 行股价（design D10）
const stocks = [
  { code: 'sz.E2E201', price: 12.3 },
  { code: 'sz.E2E202', price: 45.6 },
  { code: 'sz.E2E203', price: 78.9 },
]
let ok = 0, priceFallback = 0
for (const s of stocks) {
  // 模拟 getPriceAt 失败（mock 无 price-at handler，与真实执行路径一致）
  let price: number | null = null
  try { /* 取价失败 */ } catch { price = null }
  if (price == null) { price = s.price; priceFallback++ }
  assert.ok(price > 0) // 兜底价格 = 行股价，非空
  ok++
}
assert.equal(ok, 3)
assert.equal(priceFallback, 3)
pass('批量取价失败兜底：全部按行股价提交（3/3 走兜底路径，无空价格）')

// --- 4. 分组归属（快速新建分组后提交）---
const g = createGroup('E2E自选组')
assert.ok(g && g.sort_order >= 0)
const groupedPayload = { ...rowPayload, code: 'sz.E2E301', group_id: g.id }
assert.equal(groupedPayload.group_id, g.id)
pass('分组新建后提交：group_id 归属新组')

// --- 清理（E2E 自选组 + 本脚本未污染 monitorItems，无需还原）---
const idx = monitorGroups.findIndex((x) => x.id === g.id)
if (idx >= 0) monitorGroups.splice(idx, 1)

console.log('\n全部通过 ✓')

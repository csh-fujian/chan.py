// chan 覆盖层统一注册入口
// design.md D5：4 个自定义 overlay — 笔/线段/中枢/买卖点
// kline-chart-change D6：+ 虚拟（模拟交易）买卖点 chan_vbsp
// chan-pattern-buy-signal：+ 形态信号 chan_pattern
// chan-pattern-sell-signal：+ 顶部看跌形态 chan_sell_pattern（独立 overlay，design D2）
export { registerChanBi } from './chan_bi'
export { registerChanSeg } from './chan_seg'
export { registerChanZs } from './chan_zs'
export { registerChanBsp, chanBspLabel, bspBoxSize, setChanBspHoverHooks, type ChanBspHoverHooks } from './chan_bsp'
export { registerChanVBsp, vBspLabel, vBspRadius } from './chan_vbsp'
export { registerChanPattern, setChanPatternClickHooks, type ChanPatternMeta, type ChanPatternClickHooks } from './chan_pattern'
export { registerChanSellPattern, setChanSellPatternClickHooks, type ChanSellPatternMeta, type ChanSellPatternClickHooks } from './chan_sell_pattern'
export type { ChanZsMeta } from './chan_zs'
export type { ChanBiMeta } from './chan_bi'
export type { ChanSegMeta } from './chan_seg'
export type { ChanBspMeta } from './chan_bsp'
export type { ChanVBspMeta } from './chan_vbsp'
import { registerChanBi } from './chan_bi'
import { registerChanSeg } from './chan_seg'
import { registerChanZs } from './chan_zs'
import { registerChanBsp } from './chan_bsp'
import { registerChanVBsp } from './chan_vbsp'
import { registerChanPattern } from './chan_pattern'
import { registerChanSellPattern } from './chan_sell_pattern'

let allRegistered = false

/** 注册全部 7 个缠论覆盖层。幂等，重复调用安全。须在 init() 之前调用。 */
export function registerAllChanOverlays(): void {
  if (allRegistered) return
  allRegistered = true
  registerChanBi()
  registerChanSeg()
  registerChanZs()
  registerChanBsp()
  registerChanVBsp()
  registerChanPattern()
  registerChanSellPattern()
}

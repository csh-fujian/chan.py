// chan 覆盖层统一注册入口
// design.md D5：4 个自定义 overlay — 笔/线段/中枢/买卖点
// kline-chart-change D6：+ 虚拟（模拟交易）买卖点 chan_vbsp
export { registerChanBi } from './chan_bi'
export { registerChanSeg } from './chan_seg'
export { registerChanZs } from './chan_zs'
export { registerChanBsp, chanBspLabel, bspBoxSize } from './chan_bsp'
export { registerChanVBsp, vBspLabel, vBspRadius } from './chan_vbsp'
export type { ChanZsMeta } from './chan_zs'
export type { ChanBspMeta } from './chan_bsp'
export type { ChanVBspMeta } from './chan_vbsp'

import { registerChanBi } from './chan_bi'
import { registerChanSeg } from './chan_seg'
import { registerChanZs } from './chan_zs'
import { registerChanBsp } from './chan_bsp'
import { registerChanVBsp } from './chan_vbsp'

let allRegistered = false

/** 注册全部 5 个缠论覆盖层。幂等，重复调用安全。须在 init() 之前调用。 */
export function registerAllChanOverlays(): void {
  if (allRegistered) return
  allRegistered = true
  registerChanBi()
  registerChanSeg()
  registerChanZs()
  registerChanBsp()
  registerChanVBsp()
}

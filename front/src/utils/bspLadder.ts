// bspLadder.ts — 买卖点确认阶梯（bsp-ladder-change）四级定义与工具
// 前端唯一词表：K 线图 hover 说明卡（design D5）与买卖点页「级别」列（design D6）
// 共用，避免两处文案漂移。语义与后端 WebAPI/bsp_ladder.py 对齐：
// L4 确认买卖点（is_sure 水位线口径）、L3 背驰预警、L1 小级别区间套佐证、L2 虚笔候选兜底；
// 判定顺序 L4 > L3 > L1 > L2（L3 与 L1 同时成立时标 L3）。
// 仓位指引按方向镜像：买点 = 建仓阶梯（观察 1/4 → 加至 1/2 → 满仓），
// 卖点 = 退出阶梯（减至 3/4 → 减至 1/2 → 空仓），tooltip 按买卖方向取对应文案。

export type LadderLevel = 'L1' | 'L2' | 'L3' | 'L4'

export interface LadderInfo {
  level: LadderLevel
  /** 级别名称 */
  name: string
  /** 一句说明 */
  desc: string
  /** 买点仓位指引（纯展示文案，不做仓位计算，design Non-Goals） */
  position: string
  /** 卖点仓位指引（买点镜像：建仓阶梯 ↔ 退出阶梯，如「加仓至 1/2」↔「减仓至 1/2」） */
  positionSell: string
}

export const LADDER_LEVELS: readonly LadderInfo[] = [
  {
    level: 'L1',
    name: '小级别区间套',
    desc: '子级别出现同向买卖点共振，为本级别信号提供跨级别佐证',
    position: '观察仓 1/4',
    positionSell: '减至 3/4',
  },
  {
    level: 'L2',
    name: '虚笔候选',
    desc: '依托虚笔/分型形成的候选买卖点，可能随后续重算漂移或消失',
    position: '观察仓 1/4',
    positionSell: '减至 3/4',
  },
  {
    level: 'L3',
    name: '背驰预警',
    desc: '所在笔力度对比触发背驰判定，动能衰竭的反转预警',
    position: '加仓至 1/2',
    positionSell: '减仓至 1/2',
  },
  {
    level: 'L4',
    name: '确认买卖点',
    desc: '依托线段已确认，信号定型，不再随重算漂移',
    position: '满仓',
    positionSell: '空仓',
  },
]

const LEVEL_MAP: Record<string, LadderInfo> = Object.fromEntries(
  LADDER_LEVELS.map((l) => [l.level, l]),
)

/** 是否为合法级别值 */
export function isLadder(v: unknown): v is LadderLevel {
  return typeof v === 'string' && v in LEVEL_MAP
}

/** 取级别定义；缺 ladder / 非法值返回 null（调用方兜底「未定级」，spec 兜底场景） */
export function ladderInfo(v: string | null | undefined): LadderInfo | null {
  return v ? (LEVEL_MAP[v] ?? null) : null
}

/** 按方向取仓位指引（卖点镜像文案：买点 position / 卖点 positionSell） */
export function ladderPosition(info: LadderInfo, isBuy: boolean): string {
  return isBuy ? info.position : info.positionSell
}

/** 判定顺序脚注（tooltip 底部说明） */
export const LADDER_ORDER_NOTE = '判定顺序 L4 > L3 > L1 > L2；L3 与 L1 同时成立时标 L3'

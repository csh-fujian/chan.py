// bollIndicator.ts — BOLL 指标创建模板（create-time 包装，不动全局注册）
// kline-chart-change D4 / 任务 2.3 风险兜底：BOLL 副图叠加 sub_candle 蜡烛柱后，
// 需要保证 pane 量程覆盖蜡烛 high/low，且不与库内置的半透明 OHLC 标记重复绘制。
//
// 背景（klinecharts@9.8.12 源码验证）：
// - 内置 BOLL 带 shouldOhlc: true →（a）pane 量程计入 K 线 high/low
//   （YAxisImp.calcRange 的 shouldCompareHighLow），（b）IndicatorView 会在副图
//   自动画一套 OHLC 标记（默认 alpha 绿涨红跌，与本项目红涨绿跌语义相反）。
// - 关掉 shouldOhlc 后（避免与 sub_candle 双重蜡烛），量程只看 BOLL 三线
//   （由 close 派生），high/low 会超出量程被裁剪 —— overlay 点不参与量程计算。
//
// 因此：calc 仍沿用内置 BOLL（getBollMd + up/mid/dn，逻辑逐行拷贝自
// dist/index.esm.js `bollingerBands`，Apache-2.0），仅追加 hi_ext/lo_ext 两个
// 不可见 figure（透明 line、不出现在 tooltip）把 high/low 撑进量程 ——
// 即 design.md 风险节的「不可见 hi/lo 极值线」兜底。BOLL 三线计算与显示不变。
import type { IndicatorCreate, IndicatorFigureStyle, KLineData, Indicator } from 'klinecharts'

/** 不可见极值线样式：透明描边（size 避免 0，画布 lineWidth=0 会被忽略），仅参与量程计算 */
const HIDDEN_EXT_STYLE: IndicatorFigureStyle = {
  color: 'transparent',
  size: 1,
}

/**
 * 计算布林指标中的标准差（拷贝自 klinecharts 内置 getBollMd）
 */
function getBollMd(dataList: KLineData[], ma: number): number {
  const dataSize = dataList.length
  let sum = 0
  dataList.forEach((data) => {
    const closeMa = data.close - ma
    sum += closeMa * closeMa
  })
  sum = Math.abs(sum)
  return Math.sqrt(sum / dataSize)
}

/**
 * 构造 BOLL 副图指标创建参数：
 * - shouldOhlc: false —— 关闭库内置 OHLC 标记（由 sub_candle overlay 承担蜡烛）
 * - figures —— 内置 up/mid/dn 三线 + 不可见 hi_ext/lo_ext 量程撑开线
 *   （ext figure 不设 title → 不进 tooltip 图例）
 * - calc —— 内置 BOLL 计算 + 追加 hi_ext/lo_ext 输出
 */
export function createBollIndicator(): IndicatorCreate {
  return {
    name: 'BOLL',
    shouldOhlc: false,
    figures: [
      { key: 'up', title: 'UP: ', type: 'line' },
      { key: 'mid', title: 'MID: ', type: 'line' },
      { key: 'dn', title: 'DN: ', type: 'line' },
      // 不可见 hi/lo 极值线：让 pane 量程覆盖蜡烛 high/low（design.md 风险兜底）
      { key: 'hi_ext', type: 'line', styles: () => HIDDEN_EXT_STYLE },
      { key: 'lo_ext', type: 'line', styles: () => HIDDEN_EXT_STYLE },
    ],
    calc: (dataList: KLineData[], indicator: Indicator): Array<Record<string, number>> => {
      const params = indicator.calcParams
      const p = (params[0] as number) - 1
      let closeSum = 0
      return dataList.map((kLineData, i) => {
        const close = kLineData.close
        const boll: Record<string, number> = {}
        closeSum += close
        if (i >= p) {
          boll.mid = closeSum / (params[0] as number)
          const md = getBollMd(dataList.slice(i - p, i + 1), boll.mid)
          boll.up = boll.mid + (params[1] as number) * md
          boll.dn = boll.mid - (params[1] as number) * md
          closeSum -= dataList[i - p].close
        }
        // 量程撑开：不可见极值线取当根 high/low
        boll.hi_ext = kLineData.high
        boll.lo_ext = kLineData.low
        return boll
      })
    },
  }
}

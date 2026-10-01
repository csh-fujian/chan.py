// volIndicator.ts — 自定义 VOL 指标（同名覆盖 klinecharts 内置 VOL）
// kline-chart-change D4 / 任务 2.2：量柱逐柱「涨红空心、跌绿实心」。
//
// 实现方式：registerIndicator('VOL') 在 chart init 之前覆盖内置注册。
// calc / regenerateFigures 沿用 klinecharts@9.8.12 内置 VOL（Apache-2.0，
// dist/index.esm.js `volume` + `getVolumeFigure`）——量均线（默认 5/10/20）
// 的计算与线形生成逻辑保持一致，仅替换 volume figure 的 styles(data,...) 回调，
// 使其按 kLineData 逐柱返回空心/实心样式；bars[0] 默认样式作平盘兜底。
import {
  registerIndicator,
  IndicatorSeries,
  PolygonType,
  type IndicatorFigure,
  type IndicatorFigureStyle,
  type KLineData,
  type Indicator,
} from 'klinecharts'
import { getChanPalette } from '@/components/chan/palette'

/** 量柱 figure：bars[0] 仅作默认兜底，主体样式由 styles 回调逐柱决定。
 *  涨跌色取 palette（任务 6.3）：红涨绿跌语义色主题不变，styles 回调在重绘时实时取色。 */
function getVolumeFigure(): IndicatorFigure {
  return {
    key: 'volume',
    title: 'VOLUME: ',
    type: 'bar',
    baseValue: 0,
    styles: (data): IndicatorFigureStyle => {
      const pal = getChanPalette()
      const kLineData = data.current.kLineData as KLineData | undefined
      if (kLineData && kLineData.close > kLineData.open) {
        // 上涨：红空心（stroke 描边，内部透明）
        return {
          style: PolygonType.Stroke,
          color: pal.rise,
          borderColor: pal.rise,
          borderSize: 1,
        }
      }
      if (kLineData && kLineData.close < kLineData.open) {
        // 下跌：绿实心
        return { style: PolygonType.Fill, color: pal.fall }
      }
      // 平盘（close === open）/ 无数据：回退 bars[0] 默认实心
      return { style: PolygonType.Fill }
    },
  }
}

let registered = false

/**
 * 注册自定义 VOL 指标（覆盖内置同名指标）。
 * 幂等，重复调用安全。须在 chart init() 之前调用。
 */
export function registerVolIndicator(): void {
  if (registered) return
  registered = true

  registerIndicator({
    name: 'VOL',
    shortName: 'VOL',
    series: IndicatorSeries.Volume,
    // 与内置 VOL 默认一致
    calcParams: [5, 10, 20],
    shouldFormatBigNumber: true,
    precision: 0,
    minValue: 0,
    figures: [
      { key: 'ma1', title: 'MA5: ', type: 'line' },
      { key: 'ma2', title: 'MA10: ', type: 'line' },
      { key: 'ma3', title: 'MA20: ', type: 'line' },
      getVolumeFigure(),
    ],
    // 量均线 figure 随参数天数动态重建（沿用内置 regenerateFigures 逻辑）
    regenerateFigures: (calcParams): IndicatorFigure[] => {
      const figures: IndicatorFigure[] = calcParams.map((p, i) => ({
        key: `ma${i + 1}`,
        title: `MA${p}: `,
        type: 'line',
      }))
      figures.push(getVolumeFigure())
      return figures
    },
    // 量均线计算（沿用内置 calc：各天数的成交量移动平均）
    calc: (dataList: KLineData[], indicator: Indicator): Array<Record<string, number>> => {
      const params = indicator.calcParams
      const figures = indicator.figures
      const volSums: number[] = []
      return dataList.map((kLineData, i) => {
        const volume = kLineData.volume ?? 0
        const vol: Record<string, number> = { volume }
        params.forEach((p, index) => {
          volSums[index] = (volSums[index] ?? 0) + volume
          if (i >= (p as number) - 1) {
            vol[figures[index].key] = volSums[index] / (p as number)
            volSums[index] -= dataList[i - ((p as number) - 1)].volume ?? 0
          }
        })
        return vol
      })
    },
  })
}

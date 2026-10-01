import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 主图均线单条配置：天数 + 线色 */
export interface MaLineConfig {
  days: number
  color: string
}

/** 成交量均线单条配置：仅天数（量均线线色走库默认） */
export interface VolMaConfig {
  days: number
}

/**
 * localStorage 键。负载带 version 字段（结构演进时可平滑迁移/回退默认）。
 * 读写模式沿用 auth.ts 的显式 localStorage 读写。
 */
const STORAGE_KEY = 'chan_chart_config'
const CONFIG_VERSION = 1

/**
 * 主图默认均线 5/10/20/60，四条互异颜色。
 * 刻意避开 --rise 红 / --fall 绿，防止均线与涨跌 K 线语义混淆。
 */
const DEFAULT_MAIN_MA: MaLineConfig[] = [
  { days: 5, color: '#F0B90B' }, // 琥珀（近 --warning）
  { days: 10, color: '#60A5FA' }, // 浅蓝（近 --accent-hover）
  { days: 20, color: '#C084FC' }, // 紫
  { days: 60, color: '#F472B6' }, // 粉
]

/** 成交量默认均线 5/10/20（与 klinecharts 内置 VOL 默认一致） */
const DEFAULT_VOL_MA: VolMaConfig[] = [{ days: 5 }, { days: 10 }, { days: 20 }]

interface PersistedConfig {
  version: number
  mainMA: MaLineConfig[]
  volMA: VolMaConfig[]
}

function isIntegerDays(d: unknown): d is number {
  return typeof d === 'number' && Number.isInteger(d) && d >= 1
}

/** 读取并严格校验持久化配置；任何不合法即回退默认值（写入侧已规范化，此处只防御脏数据） */
function loadPersisted(): PersistedConfig | null {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(STORAGE_KEY)
  } catch (e) {
    console.warn('[chartConfig.loadPersisted] 读取 localStorage 失败，使用默认配置', {
      error: e instanceof Error ? e.message : String(e),
    })
    return null
  }
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedConfig>
    if (parsed.version !== CONFIG_VERSION) {
      console.warn('[chartConfig.loadPersisted] 持久化版本不匹配，使用默认配置', {
        version: parsed.version,
        expected: CONFIG_VERSION,
      })
      return null
    }
    if (!Array.isArray(parsed.mainMA) || !Array.isArray(parsed.volMA)) {
      console.warn('[chartConfig.loadPersisted] 持久化结构不合法，使用默认配置', { raw })
      return null
    }
    const mainMA: MaLineConfig[] = []
    const seenMain = new Set<number>()
    for (const item of parsed.mainMA) {
      if (!item || !isIntegerDays(item.days) || typeof item.color !== 'string' || !item.color) {
        console.warn('[chartConfig.loadPersisted] 丢弃非法主图均线项', { item })
        return null
      }
      if (seenMain.has(item.days)) {
        console.warn('[chartConfig.loadPersisted] 主图均线天数重复，使用默认配置', { days: item.days })
        return null
      }
      seenMain.add(item.days)
      mainMA.push({ days: item.days, color: item.color })
    }
    const volMA: VolMaConfig[] = []
    const seenVol = new Set<number>()
    for (const item of parsed.volMA) {
      if (!item || !isIntegerDays(item.days)) {
        console.warn('[chartConfig.loadPersisted] 丢弃非法量均线项', { item })
        return null
      }
      if (seenVol.has(item.days)) {
        console.warn('[chartConfig.loadPersisted] 量均线天数重复，使用默认配置', { days: item.days })
        return null
      }
      seenVol.add(item.days)
      volMA.push({ days: item.days })
    }
    return { version: CONFIG_VERSION, mainMA, volMA }
  } catch (e) {
    console.warn('[chartConfig.loadPersisted] 持久化配置解析失败，使用默认配置', {
      error: e instanceof Error ? e.message : String(e),
    })
    return null
  }
}

/** 规范化主图均线：天数取整 ≥1、去重（保留首个）、兜底颜色 */
function normalizeMainMA(list: MaLineConfig[]): MaLineConfig[] {
  const seen = new Set<number>()
  const out: MaLineConfig[] = []
  for (const m of list) {
    const days = Math.floor(Number(m.days))
    if (!isIntegerDays(days)) {
      console.warn('[chartConfig.normalizeMainMA] 丢弃非法天数', { item: m })
      continue
    }
    if (seen.has(days)) {
      console.warn('[chartConfig.normalizeMainMA] 丢弃重复天数', { days })
      continue
    }
    seen.add(days)
    out.push({ days, color: m.color || DEFAULT_MAIN_MA[0].color })
  }
  return out
}

/** 规范化量均线：天数取整 ≥1、去重（保留首个） */
function normalizeVolMA(list: VolMaConfig[]): VolMaConfig[] {
  const seen = new Set<number>()
  const out: VolMaConfig[] = []
  for (const v of list) {
    const days = Math.floor(Number(v.days))
    if (!isIntegerDays(days)) {
      console.warn('[chartConfig.normalizeVolMA] 丢弃非法天数', { item: v })
      continue
    }
    if (seen.has(days)) {
      console.warn('[chartConfig.normalizeVolMA] 丢弃重复天数', { days })
      continue
    }
    seen.add(days)
    out.push({ days })
  }
  return out
}

export const useChartConfigStore = defineStore('chartConfig', () => {
  const persisted = loadPersisted()
  const mainMA = ref<MaLineConfig[]>(persisted?.mainMA ?? DEFAULT_MAIN_MA.map((m) => ({ ...m })))
  const volMA = ref<VolMaConfig[]>(persisted?.volMA ?? DEFAULT_VOL_MA.map((v) => ({ ...v })))

  /** 落盘当前配置（版本化负载） */
  function persist(): void {
    try {
      const payload: PersistedConfig = {
        version: CONFIG_VERSION,
        mainMA: mainMA.value,
        volMA: volMA.value,
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    } catch (e) {
      console.warn('[chartConfig.persist] 写入 localStorage 失败', {
        error: e instanceof Error ? e.message : String(e),
      })
    }
  }

  /** 更新主图均线配置（规范化 + 去重后落盘），图表侧 watch 后即时应用 */
  function setMainMA(list: MaLineConfig[]): void {
    mainMA.value = normalizeMainMA(list)
    persist()
  }

  /** 更新量均线配置（规范化 + 去重后落盘），图表侧 watch 后即时应用 */
  function setVolMA(list: VolMaConfig[]): void {
    volMA.value = normalizeVolMA(list)
    persist()
  }

  return {
    mainMA,
    volMA,
    setMainMA,
    setVolMA,
  }
})

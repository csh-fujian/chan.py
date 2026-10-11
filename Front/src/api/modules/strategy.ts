import client from '../client'
import type {
  StrategyDefinition,
  StrategyTask,
  StrategyTaskDetail,
  StrategySignalRow,
  StrategyTaskScopeType,
  PageRes,
} from '@/api/types'

/**
 * 策略任务 API（strategy-task-redesign design D6 任务契约）：
 * - 定义层只读（GET /strategy/definitions，含任务树 + 信号计数 + desc/detail_schema 透出）
 * - 任务生命周期：创建（范围三来源解析 + params 校验 422）/ 列表（进度）/ 编辑（paused 才可编辑）/
 *   启停 / 续跑（full=重新运行 | remaining=剩余继续）/ 转正 / 复制 / 删除
 * - 信号查询：按 task_id 分页 + 状态/方向/日期范围/关键词筛选
 * - 任务详情：GET /strategy/tasks/{id}/detail（detail_schema 声明驱动的渲染数据源）
 * 原实例端点全部废弃（BREAKING）。
 */

/** 策略定义列表（侧栏策略树数据源：策略大类分组 → 定义 → 任务节点 + 计数） */
export function getStrategyDefinitions() {
  return client.get<unknown, StrategyDefinition[]>('/strategy/definitions')
}

/** 任务列表查询参数（v1 前端本地过滤即可，接口预留 query 参数） */
export interface StrategyTaskQuery {
  strategy_id?: string
  user_group?: string
  status?: string
}

/** 任务列表（含进度；进度轮询间隔 3s，与 design D4 一致） */
export function getStrategyTasks(query: StrategyTaskQuery = {}) {
  return client.get<unknown, StrategyTask[]>('/strategy/tasks', { params: query })
}

/** 创建任务请求体（design D3：范围三来源解析 + 全量兜底；params 按 params_schema 校验） */
export interface CreateStrategyTaskPayload {
  strategy_id: string
  label: string
  /** 用户自定义分组（空串 = 未分组；新分组名直接传入即创建） */
  user_group?: string
  /** 任务参数（int/float → 数值，enum → 选项 value 字符串；按定义 params_schema 校验） */
  params: Record<string, number | string>
  /** 股票范围类型：manual/watchlist/bsp_query/all（未选股票 = 'all' 全量 A 股，默认排 ST/*ST） */
  scope_type: StrategyTaskScopeType
  /** manual：前端直接传 code 列表（后端按快照固化） */
  scope_codes?: string[]
  /** watchlist：来源文件夹 id（后端读该文件夹股票固化快照） */
  folder_id?: number
  /** bsp_query：/bsp 页查询条件快照（后端调 bsp_store 查询取 code 列表固化） */
  bsp_query?: {
    bsp_type?: string
    kl_type?: string
    direction?: 'buy' | 'sell' | ''
    date_from?: string
    date_to?: string
    sure?: string
  }
  /** 任务形态：test（一次性测试，缺省）/ persistent（长期任务，挂 EOD 日终调度） */
  mode?: 'test' | 'persistent'
}

/** 创建任务（params 非法 422 + 中文 detail） */
export function createStrategyTask(payload: CreateStrategyTaskPayload) {
  return client.post<unknown, StrategyTask>('/strategy/tasks', payload)
}

/** 编辑任务请求体（仅 paused 可编辑；test 可改参数与范围，persistent 仅范围——参数冻结） */
export interface UpdateStrategyTaskPayload {
  label?: string
  user_group?: string
  /** 仅 test 任务允许修改；persistent 传该字段被拒绝（提示复制任务调参）；
   *  int/float → 数值，enum → 选项 value 字符串 */
  params?: Record<string, number | string>
  scope_type?: StrategyTaskScopeType
  scope_codes?: string[]
  folder_id?: number
  bsp_query?: CreateStrategyTaskPayload['bsp_query']
}

/** 编辑任务（服务端检测 params 变化时 params_version +1） */
export function updateStrategyTask(id: number, payload: UpdateStrategyTaskPayload) {
  return client.patch<unknown, StrategyTask>(`/strategy/tasks/${id}`, payload)
}

/** 启动任务（pending/paused → running，进度从当前值推进） */
export function startStrategyTask(id: number) {
  return client.post<unknown, { success: boolean }>(`/strategy/tasks/${id}/start`)
}

/** 暂停任务（running → paused，已产生信号与逐股结果保留） */
export function pauseStrategyTask(id: number) {
  return client.post<unknown, { success: boolean }>(`/strategy/tasks/${id}/pause`)
}

/** 续跑方式（design D2 两种语义） */
export type ResumeMode = 'full' | 'remaining'

/** 续跑任务：full = 重新运行（默认，清空旧信号与逐股结果全量重扫）/
 *  remaining = 剩余股票继续（保留已扫结果，从当前进度用新参数续扫） */
export function resumeStrategyTask(id: number, rerun: ResumeMode) {
  return client.post<unknown, { success: boolean }>(`/strategy/tasks/${id}/resume`, { rerun })
}

/** 转正（done 的 test 任务 → persistent，挂 EOD 日终调度；既有信号保留） */
export function promoteStrategyTask(id: number) {
  return client.post<unknown, StrategyTask>(`/strategy/tasks/${id}/promote`)
}

/** 复制任务（继承参数与范围为新的 test 任务，可自由编辑——调参路径） */
export function copyStrategyTask(id: number) {
  return client.post<unknown, StrategyTask>(`/strategy/tasks/${id}/copy`)
}

/** 删除任务（级联删除其信号与逐股结果，不可恢复；UI 侧先确认） */
export function deleteStrategyTask(id: number) {
  return client.delete<unknown, { success: boolean }>(`/strategy/tasks/${id}`)
}

/** 任务详情（detail_schema 声明驱动的渲染数据源；scope='all' 时不含 per_stock） */
export function getStrategyTaskDetail(id: number) {
  return client.get<unknown, StrategyTaskDetail>(`/strategy/tasks/${id}/detail`)
}

/** 信号查询参数（task_id 必传：信号按任务隔离；其余为可选筛选） */
export interface StrategySignalQuery {
  task_id: number
  page: number
  page_size: number
  /** 状态筛选（取值域 = 所属定义 states；空 = 不过滤） */
  state?: string
  /** 方向筛选（buy/sell；空 = 不过滤） */
  direction?: 'buy' | 'sell' | ''
  /** 日期范围起点（YYYY-MM-DD，闭区间；空 = 不过滤） */
  date_from?: string | null
  /** 日期范围终点（YYYY-MM-DD，闭区间；空 = 不过滤） */
  date_to?: string | null
  /** 关键词（编码/名称模糊匹配；选中候选后为精确 code） */
  keyword?: string
}

/** 信号列表（服务端分页 + 全筛选；行携带 params_version 版本标识） */
export function getStrategySignals(query: StrategySignalQuery) {
  return client.get<unknown, PageRes<StrategySignalRow>>('/strategy/signals', { params: query })
}

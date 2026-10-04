import client from '../client'
import type { PerformanceStat, PerformanceSample } from '@/api/types'

/**
 * 买卖点绩效统计（performance-page-change design D2/D3/D9）。
 * source / instance_id 为侧栏来源树筛选参数：
 * - 'chan' / 'watchlist' → source 传该值
 * - 'strategy:<id>' → source='strategy' 且 instance_id=id
 * - 全部来源 → 均不传；params 仅携带非空值
 * group_id 为侧栏分组树筛选参数（design D9）：
 * - 'ungrouped' 哨兵 → 未分组；正整数字符串 → 精确匹配；全部分组 → 不传
 */
export function getPerformanceStats(
  source?: string,
  instance_id?: number,
  group_id?: string,
) {
  return client.get<unknown, PerformanceStat[]>('/performance/stats', {
    params: { source, instance_id, group_id },
  })
}

/**
 * 样本明细（bsp_type / kl_type / source / instance_id / group_id 可选筛选，
 * 语义与真后端 completed 过滤一致；params 仅携带非空值）
 */
export function getPerformanceSamples(
  bsp_type?: string,
  kl_type?: string,
  source?: string,
  instance_id?: number,
  group_id?: string,
) {
  return client.get<unknown, PerformanceSample[]>('/performance/samples', {
    params: { bsp_type, kl_type, source, instance_id, group_id },
  })
}

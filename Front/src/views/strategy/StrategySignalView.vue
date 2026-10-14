<template>
  <div class="page-layout">
    <!-- 主面板（strategy-task-list-redesign：删左侧策略任务树，单列布局；
         类型过滤 → 任务列表查询条件级联，新建入口 → 列表上方按钮） -->
    <div class="main-panel">
      <div class="strategy-page">
        <!-- 视图 Tab：任务列表 | 信号列表 -->
        <div class="view-tabs reveal reveal--1">
          <button
            v-for="t in viewTabs"
            :key="t.key"
            class="tab-btn"
            :class="{ 'is-active': activeView === t.key }"
            @click="activeView = t.key"
          >
            {{ t.label }}
          </button>
        </div>

        <!-- ===== 任务列表 Tab ===== -->
        <div v-show="activeView === 'tasks'" class="task-view">
          <!-- 工具栏：新建按钮 + 查询条件（strategy-task-list-redesign design D2/D3：
               全量任务数据已在前端（allTasks），查询条件为内存过滤） -->
          <div class="toolbar reveal reveal--1">
            <button class="btn btn--primary" @click="openCreateTask()">
              <el-icon><Plus /></el-icon>
              新建策略任务
            </button>
            <span class="toolbar-spacer"></span>
            <el-cascader
              v-model="taskQuery.typePath"
              :options="typeCascadeOptions"
              placeholder="策略任务类型"
              clearable
              :props="{ emitPath: false }"
              style="width: 220px"
              @change="onTaskQueryChange"
            />
            <el-input
              v-model="taskQuery.label"
              placeholder="任务名"
              clearable
              style="width: 150px"
              @change="onTaskQueryChange"
            />
            <el-input
              v-model="taskQuery.group"
              placeholder="分组"
              clearable
              style="width: 130px"
              @change="onTaskQueryChange"
            />
            <el-select
              v-model="taskQuery.mode"
              placeholder="形态"
              clearable
              style="width: 100px"
              @change="onTaskQueryChange"
            >
              <el-option label="长期" value="persistent" />
              <el-option label="测试" value="test" />
            </el-select>
            <el-date-picker
              v-model="taskDateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="创建开始"
              end-placeholder="创建结束"
              unlink-panels
              clearable
              style="width: 240px"
              @change="onTaskQueryChange"
            />
            <el-select
              v-model="taskQuery.accuracyBand"
              placeholder="准确率"
              clearable
              style="width: 120px"
              @change="onTaskQueryChange"
            >
              <el-option label="80-100" value="high" />
              <el-option label="60-80" value="mid" />
              <el-option label="60 以下" value="low" />
              <el-option label="无数据" value="none" />
            </el-select>
          </div>

          <div class="panel reveal reveal--2">
          <div class="tbl-wrap" v-loading="tasksLoading">
            <el-table :data="filteredTasks" empty-text="暂无任务" row-key="id">
              <el-table-column label="任务名" min-width="130">
                <template #default="{ row }">
                  <span class="cell-task-nm">{{ row.label }}</span>
                </template>
              </el-table-column>
              <!-- 策略任务类型列（strategy-task-list-redesign：group_name:name
                   分层展示；原任务名下的策略名子文本由本列承接） -->
              <el-table-column label="策略任务类型" min-width="170">
                <template #default="{ row }">
                  <span class="num strategy-type">{{ strategyTypeOf(row.strategy_id) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="分组" width="110" align="center">
                <template #default="{ row }">
                  <span class="badge badge--default">{{ row.user_group || '未分组' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="形态" width="80" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="row.mode === 'persistent' ? 'badge--accent' : 'badge--info'">
                    {{ row.mode === 'persistent' ? '长期' : '测试' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="STATUS_COLOR[row.status] || 'badge--default'">
                    {{ STATUS_LABEL[row.status] || row.status }}
                  </span>
                </template>
              </el-table-column>
              <!-- 执行进度：el-progress 进度条 + 已扫/总数 -->
              <el-table-column label="执行进度" min-width="170">
                <template #default="{ row }">
                  <div class="cell-progress">
                    <el-progress
                      :percentage="progressPct(row)"
                      :stroke-width="6"
                      :show-text="false"
                      :color="row.status === 'done' ? '#2EBD85' : undefined"
                    />
                    <span class="num progress-text">
                      {{ row.progress_scanned }} / {{ row.progress_total }}
                      <span v-if="row.status === 'running'" class="running-hint">扫描中</span>
                    </span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="信号数" width="80" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num link" @click="gotoSignals(row)">{{ row.signal_count }}</span>
                </template>
              </el-table-column>
              <!-- 准确率列（strategy-task-list-redesign：列表节点批量聚合；
                   无样本 null → '--'，口径同任务详情绩效统计） -->
              <el-table-column label="准确率" width="90" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num" :class="accuracyClass(row.accuracy)">{{ fmtAccuracy(row.accuracy) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="创建人" width="80" align="center">
                <template #default="{ row }">{{ row.created_by }}</template>
              </el-table-column>
              <el-table-column label="创建时间" width="100" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDate(row.created_at) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="230" align="center" fixed="right">
                <template #default="{ row }">
                  <!-- 启动 / 暂停（按状态互斥） -->
                  <el-button
                    v-if="row.status === 'pending' || row.status === 'paused'"
                    link type="primary" size="small"
                    @click="onStartTask(row)"
                  >启动</el-button>
                  <el-button
                    v-if="row.status === 'running'"
                    link type="warning" size="small"
                    @click="onPauseTask(row)"
                  >暂停</el-button>
                  <!-- 续跑（paused/done 的任务） -->
                  <el-button
                    v-if="row.status === 'paused' || row.status === 'done'"
                    link type="primary" size="small"
                    @click="openResumeDialog(row)"
                  >续跑</el-button>
                  <!-- 编辑（仅 paused） -->
                  <el-button
                    v-if="row.status === 'paused'"
                    link type="primary" size="small"
                    @click="openEditDialog(row)"
                  >编辑</el-button>
                  <!-- 转正（done 的 test 任务） -->
                  <el-button
                    v-if="row.status === 'done' && row.mode === 'test'"
                    link type="primary" size="small"
                    @click="onPromoteTask(row)"
                  >转正</el-button>
                  <!-- 复制 / 删除 -->
                  <el-button link type="primary" size="small" @click="onCopyTask(row)">复制</el-button>
                  <el-button link type="danger" size="small" @click="onDeleteTask(row)">删除</el-button>
                  <!-- 详情 -->
                  <el-button link size="small" @click="openDetail(row)">详情</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <EmptyState description="暂无任务，点击上方「新建策略任务」创建" />
              </template>
            </el-table>
          </div>
          </div>
        </div>

        <!-- ===== 信号列表 Tab（沿用原筛选 + 服务端分页骨架，查询挂 task_id） ===== -->
        <div v-show="activeView === 'signals'" class="signal-view">
          <!-- 工具栏：股票搜索 | 状态（states 声明驱动）| 方向 | 日期范围 | 查询/重置 -->
          <div class="toolbar reveal reveal--1">
            <el-autocomplete
              ref="acRef"
              v-model="keywordInput"
              :fetch-suggestions="queryStocks"
              :trigger-on-focus="false"
              :debounce="300"
              placeholder="代码 / 名称 / 拼音"
              :prefix-icon="Search"
              clearable
              style="width: 180px"
              @select="onSelectSuggestion"
              @clear="onKeywordClear"
            >
              <template #default="{ item }">
                <div class="sug-item" :class="{ 'sug-item--empty': item.placeholder }">
                  <template v-if="item.placeholder">
                    <span class="sug-item__empty">{{ item.name }}</span>
                  </template>
                  <template v-else>
                    <span class="sug-item__code mono">{{ item.code }}</span>
                    <span class="sug-item__name">{{ item.name }}</span>
                  </template>
                </div>
              </template>
            </el-autocomplete>
            <!-- 状态下拉：options 由当前任务所属定义的 states 声明渲染 -->
            <el-select v-model="query.state" placeholder="状态" style="width: 120px" :disabled="!currentDefinition" @change="onQueryChange">
              <el-option label="全部状态" value="" />
              <el-option
                v-for="s in currentDefinition?.states || []"
                :key="s.value"
                :label="s.label"
                :value="s.value"
              />
            </el-select>
            <el-select v-model="query.direction" placeholder="方向" style="width: 100px" @change="onQueryChange">
              <el-option label="全部方向" value="" />
              <el-option label="买" value="buy" />
              <el-option label="卖" value="sell" />
            </el-select>
            <!-- 日期范围（闭区间，YYYY-MM-DD） -->
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              unlink-panels
              clearable
              style="width: 220px"
              @change="onQueryChange"
            />
            <button class="btn btn--primary" @click="onQuery">查询</button>
            <button class="btn btn--default" @click="onReset">重置</button>
          </div>

          <!-- 信号列表（服务端分页）：通用列 + columns 声明驱动私有列 + states 声明着色
               + 参数版本标识（strategy-task-redesign：混合参数任务按版本归因） -->
          <div class="panel reveal reveal--2">
            <div class="tbl-wrap" v-loading="loading">
              <el-table
                v-if="currentTaskId != null"
                :key="currentTaskId"
                :data="records"
                empty-text="暂无信号记录"
                row-key="code"
                @row-click="onRowClick"
              >
                <el-table-column label="名称 / 编码" min-width="140">
                  <template #default="{ row }">
                    <div class="cell-stock">
                      <span class="nm">{{ row.name }}</span>
                      <span class="cd mono">{{ row.code }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="行业" min-width="150">
                  <template #default="{ row }">
                    <IndustryBadges :industries="row.industries" />
                  </template>
                </el-table-column>
                <!-- 信号日期列删除（strategy-volume-breakout-pullback D7：与
                     A 日列冲突——A 日即信号日期，a_col 三值合并列已含日期分量） -->
                <!-- 状态列：states 声明 color 映射 badge 样式类 -->
                <el-table-column label="状态" width="90" align="center">
                  <template #default="{ row }">
                    <span class="badge" :class="stateBadgeClass(row.state)">{{ stateLabel(row.state) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="方向" width="70" align="center">
                  <template #default="{ row }">
                    <span class="badge" :class="row.is_buy ? 'badge--rise' : 'badge--fall'">
                      {{ row.is_buy ? '买' : '卖' }}
                    </span>
                  </template>
                </el-table-column>
                <!-- 参数版本标识（spec：信号行标注产生它的参数版本，如「参数 v2」） -->
                <el-table-column label="参数版本" width="90" align="center">
                  <template #default="{ row }">
                    <span class="badge badge--accent mono">参数 v{{ row.params_version }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="入场参考价" width="100" align="right" class-name="col-num">
                  <template #default="{ row }">
                    <span class="num">{{ formatPrice(row.entry_ref_price) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="止损参考价" width="100" align="right" class-name="col-num">
                  <template #default="{ row }">
                    <span class="num">{{ formatPrice(row.stop_ref_price) }}</span>
                  </template>
                </el-table-column>
                <!-- 私有列（columns 声明驱动，row.payload[key] 取值渲染；
                     pct/price_pct/outcome/date_price_pct 新列型兜底（D7/D12/
                     strategy-volume-breakout-pullback D7）：主列表仍按
                     完整声明渲染全列（通用列不裁剪，仅任务详情裁剪）；
                     pct/price_pct 涨幅分量转百分比文本、price_pct 合并列
                     「价格 | 涨跌幅」双值、date_price_pct 三值合并列
                     「日期 | 价格 | 涨幅」（b_col 可点击弹 B 事件表——
                     走单信号 b-events 接口）、outcome 中文标签，保持不报错） -->
                <el-table-column
                  v-for="col in currentDefinition?.columns || []"
                  :key="col.key"
                  :label="col.label"
                  :width="col.type === 'date' ? 110 : col.type === 'outcome' ? 80 : col.type === 'price_pct' ? 140 : col.type === 'date_price_pct' ? 230 : 90"
                  :align="col.type === 'date' ? 'center' : 'right'"
                  class-name="col-num"
                >
                  <template #default="{ row }">
                    <!-- price_pct：合并单元格「价格 | 涨跌幅」（D12 兜底渲染，
                         价格分量普通 float 文本，涨幅分量 pct 规则着色） -->
                    <template v-if="col.type === 'price_pct'">
                      <span class="num">{{ fmtPriceComponent(colValue(row, col.priceKey || '')) }}</span>
                      <span class="num pp-sep">|</span>
                      <span class="num" :class="pctClass(colValue(row, col.pctKey || ''))">
                        {{ formatPayload(colValue(row, col.pctKey || ''), 'pct') }}
                      </span>
                    </template>
                    <!-- date_price_pct：三值合并单元格「日期 | 价格 | 涨幅」
                         （strategy-volume-breakout-pullback D7，A/B 日列整合）；
                         b_col 带 popup 标记时点击弹出 B 级事件详情表 -->
                    <template v-else-if="col.type === 'date_price_pct'">
                      <span
                        class="num dpc"
                        :class="{ 'dpc--popup': col.popup === 'b_events' && bEventsOf(row).length }"
                        @click.stop="col.popup === 'b_events' && openBDialog(row, col.label)"
                      >
                        {{ fmtDayComponent(colValue(row, col.dateKey || '')) }}
                        <span class="pp-sep">|</span>
                        {{ fmtPriceComponent(colValue(row, col.priceKey || '')) }}
                        <span class="pp-sep">|</span>
                        <span :class="pctClass(colValue(row, col.pctKey || ''))">
                          {{ formatPayload(colValue(row, col.pctKey || ''), 'pct') }}
                        </span>
                      </span>
                    </template>
                    <span
                      v-else
                      class="num"
                      :class="col.type === 'pct' ? pctClass(colValue(row, col.key)) : ''"
                    >{{ formatPayload(colValue(row, col.key), col.type) }}</span>
                  </template>
                </el-table-column>
                <template #empty>
                  <EmptyState description="暂无信号记录，请调整筛选条件" />
                </template>
              </el-table>
              <EmptyState v-else description="请在任务列表点击信号数进入信号列表" />
            </div>
            <div class="pager" v-if="total > 0">
              <el-pagination
                v-model:current-page="query.page"
                v-model:page-size="query.page_size"
                :total="total"
                :page-sizes="[20]"
                layout="total, prev, pager, next, jumper"
                background
                @current-change="loadList"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建任务弹窗（4.3：params_schema 驱动表单 + 范围三来源 + 全量兜底；
         strategy-task-list-redesign 4.1：弹窗内先选策略任务类型级联联动） -->
    <TaskDialog
      v-model:visible="taskDialogVisible"
      :definitions="definitions"
      :known-groups="knownGroups"
      @saved="reloadDefinitions"
    />

    <!-- 编辑与续跑弹窗（4.4：paused 编辑 + 重新运行/剩余继续二选一） -->
    <TaskEditDialog
      v-model:visible="editDialogVisible"
      :task="editDialogTask"
      :definition="editDialogDef"
      :known-groups="knownGroups"
      @saved="reloadDefinitions"
    />

    <!-- 续跑选择弹窗（从任务列表「续跑」入口，二选一默认重新运行） -->
    <TaskResumeDialog
      v-model:visible="resumeDialogVisible"
      :task="resumeDialogTask"
      @resumed="reloadDefinitions"
    />

    <!-- 任务详情抽屉（4.5：detail_blocks 渲染器，按 detail_schema 声明渲染） -->
    <TaskDetailDrawer
      v-model:visible="detailVisible"
      :task-id="detailTaskId"
    />

    <!-- 信号详情抽屉 -->
    <SignalDrawer
      v-model:visible="drawerVisible"
      :signal="drawerSignal"
      :definition="currentDefinition"
      :task="currentTask"
    />

    <!-- B 级事件详情弹窗（strategy-volume-breakout-pullback D7/4.2）：主列表
         B 列点击展开，数据走单信号 b-events 接口（列表行不嵌全集） -->
    <el-dialog
      v-model="bDialogVisible"
      :title="bDialogTitle"
      width="720px"
      append-to-body
      class="b-events-dialog"
    >
      <el-table v-if="bDialogEvents.length" :data="bDialogEvents" size="small">
        <el-table-column label="等级" width="70" align="center">
          <template #default="{ row }">
            <span class="badge badge--accent">{{ row.b_level }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150" align="center">
          <template #default="{ row }">
            <span class="num">{{ fmtBTime(row.b_time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="周期" width="64" align="center">
          <template #default="{ row }">
            <span class="num">{{ row.b_kl_type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="价格" width="90" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatPrice(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="当日涨幅" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.day_pct)">{{ formatPayload(row.day_pct, 'pct') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="5日收益" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.ret_5d)">{{ formatPayload(row.ret_5d, 'pct') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="10日收益" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.ret_10d)">{{ formatPayload(row.ret_10d, 'pct') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="15日收益" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="pctClass(row.ret_15d)">{{ formatPayload(row.ret_15d, 'pct') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="判定" width="70" align="center">
          <template #default="{ row }">
            <span class="badge" :class="outcomeBadgeClass(row.outcome)">{{ outcomeLabel(row.outcome) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="b-events-empty">
        旧口径信号：无 B 级事件明细（该信号产生于 B 点分级判定上线前，可重新运行任务按新口径产出）
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import type { AutocompleteInstance } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus } from '@element-plus/icons-vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import TaskDialog from './TaskDialog.vue'
import TaskEditDialog from './TaskEditDialog.vue'
import TaskResumeDialog from './TaskResumeDialog.vue'
import TaskDetailDrawer from './TaskDetailDrawer.vue'
import SignalDrawer from './SignalDrawer.vue'
import {
  getStrategyDefinitions,
  getStrategySignals,
  getSignalBEvents,
  startStrategyTask,
  pauseStrategyTask,
  promoteStrategyTask,
  copyStrategyTask,
  deleteStrategyTask,
} from '@/api/modules/strategy'
import { searchStocks } from '@/api/modules/stock'
import type {
  StrategyDefinition,
  StrategyTask,
  StrategySignalRow,
  StrategyColumnDecl,
  BEventRow,
} from '@/api/types'

/**
 * 策略任务页（strategy-task-redesign 4.2 / strategy-task-list-redesign 单列化）：
 * - 单列布局：视图 Tab（任务列表/信号列表）；原左侧策略任务树已删除——
 *   类型过滤迁移到任务列表查询条件级联，新建入口迁移到列表上方按钮
 * - 任务列表：查询条件（策略类型级联/任务名/分组/形态/创建时间/准确率分档）
 *   前端内存过滤 + 准确率/策略任务类型列 + 启停/续跑/编辑/转正/复制/删除/详情
 * - 信号列表：按 task_id 服务端分页，沿用原筛选骨架
 * - 私有列 / 状态着色 / 任务表单全部由定义声明驱动渲染（新策略接入零前端改动）
 * - running 任务进度轮询 3s（design D4）
 */

// ---- 定义与任务树 ----
const definitions = ref<StrategyDefinition[]>([])
const currentTaskId = ref<number | null>(null)
const tasksLoading = ref(false)

/** 视图 Tab（任务列表 / 信号列表） */
const activeView = ref<'tasks' | 'signals'>('tasks')
const viewTabs = [
  { key: 'tasks' as const, label: '任务列表' },
  { key: 'signals' as const, label: '信号列表' },
]

/** 已知分组名集合（创建/编辑弹窗分组下拉可选项来源） */
const knownGroups = computed<string[]>(() => {
  const set = new Set<string>()
  for (const def of definitions.value) {
    for (const t of def.tasks) {
      if (t.user_group) set.add(t.user_group)
    }
  }
  return Array.from(set)
})

/** 任务列表数据（全定义任务按创建时间倒序；真实后端 created_at 为 ISO
 *  字符串、mock 为毫秒时间戳，统一经 Date 归一化比较） */
const allTasks = computed<StrategyTask[]>(() =>
  definitions.value
    .flatMap((d) => d.tasks)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
)

// ---- 任务列表查询条件（design D2：全量任务在前端，内存过滤） ----
const taskQuery = reactive({
  /** 策略任务类型级联选中叶子（definition id），空 = 全部 */
  typePath: '' as string | null,
  /** 任务名模糊 */
  label: '',
  /** 分组模糊 */
  group: '',
  /** 形态：persistent/test，空 = 全部 */
  mode: '' as 'persistent' | 'test' | '',
  /** 准确率分档：high(>=0.8) / mid(0.6~0.8) / low(<0.6) / none(null) */
  accuracyBand: '' as 'high' | 'mid' | 'low' | 'none' | '',
  /** 创建时间区间（YYYY-MM-DD 闭区间） */
  date_from: '',
  date_to: '',
})

const taskDateRange = ref<[string, string] | null>(null)
watch(taskDateRange, (v) => {
  taskQuery.date_from = v?.[0] || ''
  taskQuery.date_to = v?.[1] || ''
})

/** 级联选项：策略大类（group_name）→ 策略定义（叶子 value = definition id） */
const typeCascadeOptions = computed(() => {
  const groups: { value: string; label: string; children: { value: string; label: string }[] }[] = []
  for (const def of definitions.value) {
    const g = groups.find((x) => x.value === def.group_name)
    if (g) g.children.push({ value: def.id, label: def.name })
    else groups.push({ value: def.group_name, label: def.group_name, children: [{ value: def.id, label: def.name }] })
  }
  return groups
})

function onTaskQueryChange() {
  // 级联/输入即时生效（computed 过滤链自动重算，无需额外请求）
}

/** 任务列表展示集：查询条件内存过滤（strategy-task-list-redesign design D2/D3；
 *  准确率分档语义：null 仅命中「无数据」档，不命中任何数值档） */
const filteredTasks = computed<StrategyTask[]>(() => {
  let list = allTasks.value
  if (taskQuery.typePath) list = list.filter((t) => t.strategy_id === taskQuery.typePath)
  if (taskQuery.label.trim()) {
    const kw = taskQuery.label.trim().toLowerCase()
    list = list.filter((t) => t.label.toLowerCase().includes(kw))
  }
  if (taskQuery.group.trim()) {
    const kw = taskQuery.group.trim().toLowerCase()
    list = list.filter((t) => (t.user_group || '').toLowerCase().includes(kw))
  }
  if (taskQuery.mode) list = list.filter((t) => t.mode === taskQuery.mode)
  if (taskQuery.date_from || taskQuery.date_to) {
    const from = taskQuery.date_from ? new Date(taskQuery.date_from + 'T00:00:00').getTime() : -Infinity
    const to = taskQuery.date_to ? new Date(taskQuery.date_to + 'T23:59:59').getTime() : Infinity
    list = list.filter((t) => t.created_at >= from && t.created_at <= to)
  }
  if (taskQuery.accuracyBand) {
    list = list.filter((t) => {
      const a = t.accuracy
      switch (taskQuery.accuracyBand) {
        case 'high': return a != null && a >= 0.8
        case 'mid': return a != null && a >= 0.6 && a < 0.8
        case 'low': return a != null && a < 0.6
        case 'none': return a == null
        default: return true
      }
    })
  }
  return list
})

/** 准确率格式化（null → '--'，小数 → 百分比） */
function fmtAccuracy(a: number | null | undefined): string {
  if (a == null || !Number.isFinite(a)) return '--'
  return `${(a * 100).toFixed(1)}%`
}

/** 准确率着色（A 股语义：高准确率红涨色标） */
function accuracyClass(a: number | null | undefined): string {
  if (a == null || !Number.isFinite(a)) return ''
  if (a >= 0.8) return 'text-rise'
  if (a >= 0.6) return ''
  return 'text-fall'
}

/** 任务名查定义（策略任务类型列 group_name:name 拼接用） */
function defOf(strategyId: string): StrategyDefinition | undefined {
  return definitions.value.find((d) => d.id === strategyId)
}

/** 策略任务类型分层展示（「策略大类:策略名」，如「量价策略:放量启动回调」） */
function strategyTypeOf(strategyId: string): string {
  const d = defOf(strategyId)
  return d ? `${d.group_name}:${d.name}` : strategyId
}

/** 当前任务（操作与加监控上下文用） */
const currentTask = computed<StrategyTask | null>(() => {
  if (currentTaskId.value == null) return null
  return allTasks.value.find((t) => t.id === currentTaskId.value) || null
})

/** 当前任务所属定义（states/columns 声明来源） */
const currentDefinition = computed<StrategyDefinition | null>(() => {
  const t = currentTask.value
  if (!t) return null
  return definitions.value.find((d) => d.id === t.strategy_id) || null
})

async function loadDefinitions() {
  tasksLoading.value = true
  try {
    definitions.value = await getStrategyDefinitions()
    // 默认选中第一个任务（无选中时）
    if (currentTaskId.value == null) {
      const first = definitions.value.flatMap((d) => d.tasks)[0]
      if (first) currentTaskId.value = first.id
    }
  } catch (e) {
    console.warn('[StrategySignalView.loadDefinitions] 策略定义加载失败', { error: e })
    definitions.value = []
  } finally {
    tasksLoading.value = false
  }
}

/** 任务变更后重载树（新建/删除/启停/编辑操作后侧栏与列表同步） */
async function reloadDefinitions() {
  await loadDefinitions()
  if (activeView.value === 'signals') await loadList()
}

// ---- 进度轮询（design D4：running 任务 3s 间隔轮询任务列表） ----
let pollTimer: ReturnType<typeof setInterval> | null = null

const hasRunningTask = computed(() => allTasks.value.some((t) => t.status === 'running'))

function ensurePolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!hasRunningTask.value) return
    // 静默刷新：不置 loading，避免表格闪烁
    try {
      definitions.value = await getStrategyDefinitions()
    } catch {
      // 轮询失败静默：下一轮重试
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ---- 任务列表操作 ----
const STATUS_LABEL: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  paused: '已暂停',
  done: '已完成',
}
const STATUS_COLOR: Record<string, string> = {
  pending: 'badge--default',
  running: 'badge--info',
  paused: 'badge--warning',
  done: 'badge--fall',
}

function progressPct(t: StrategyTask): number {
  if (!t.progress_total) return 0
  return Math.min(100, Math.round((t.progress_scanned / t.progress_total) * 100))
}

function fmtDate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function refreshTree() {
  try {
    definitions.value = await getStrategyDefinitions()
  } catch (e) {
    console.warn('[StrategySignalView.refreshTree] 刷新失败', { error: e })
  }
}

async function onStartTask(task: StrategyTask) {
  try {
    await startStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已启动`)
    await refreshTree()
  } catch {
    // 409 等失败已由拦截器提示
  }
}

async function onPauseTask(task: StrategyTask) {
  try {
    await pauseStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已暂停，可编辑参数与范围后续跑`)
    await refreshTree()
  } catch {
    // 失败已由拦截器提示
  }
}

async function onPromoteTask(task: StrategyTask) {
  try {
    await ElMessageBox.confirm(
      `确定将任务「${task.label}」转正为长期任务吗？转正后挂入日终调度，每日自动增量扫描；既有信号保留，参数将冻结（调参需复制为新的测试任务）。`,
      '任务转正',
      { type: 'warning', confirmButtonText: '确认转正', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await promoteStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已转正为长期任务（纳入日终调度）`)
    await refreshTree()
  } catch (e) {
    console.warn('[StrategySignalView.onPromoteTask] 转正失败', { id: task.id, error: e })
  }
}

async function onCopyTask(task: StrategyTask) {
  try {
    const copy = await copyStrategyTask(task.id)
    ElMessage.success(`已复制为测试任务「${copy.label}」（参数与范围同源，可自由编辑）`)
    await refreshTree()
  } catch (e) {
    console.warn('[StrategySignalView.onCopyTask] 复制失败', { id: task.id, error: e })
  }
}

async function onDeleteTask(task: StrategyTask) {
  const signalNote = task.signal_count > 0 ? `其 ${task.signal_count} 条历史信号与逐股结果将被一并删除。` : '其逐股结果将被一并删除。'
  try {
    await ElMessageBox.confirm(
      `确定删除任务「${task.label}」吗？任务不可恢复，${signalNote}`,
      '删除任务',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已删除`)
    // 删除的是当前选中任务 → 回退到首个可用任务
    if (currentTaskId.value === task.id) {
      currentTaskId.value = null
      const first = definitions.value.flatMap((d) => d.tasks).find((t) => t.id !== task.id)
      if (first) currentTaskId.value = first.id
    }
    await refreshTree()
    await loadList()
  } catch (e) {
    console.warn('[StrategySignalView.onDeleteTask] 删除任务失败', { id: task.id, error: e })
  }
}

/** 点击信号数跳到信号列表 Tab（选中该任务；切换任务语义：筛选保留、
 *  状态取值域随新定义回退、页码重置） */
function gotoSignals(task: StrategyTask) {
  if (currentTaskId.value !== task.id) {
    currentTaskId.value = task.id
    query.page = 1
    // 状态筛选取值域随定义变化：不在新定义 states 内的值回退「全部」
    const def = currentDefinition.value
    if (def && query.state && !def.states.some((s) => s.value === query.state)) {
      query.state = ''
    }
  }
  activeView.value = 'signals'
  loadList()
}

// ---- 信号查询状态（切换任务：保留筛选、重置页码、重新请求） ----
const query = reactive({
  page: 1,
  page_size: 20,
  state: '',
  direction: '' as 'buy' | 'sell' | '',
  date_from: '',
  date_to: '',
  keyword: '',
})

const dateRange = ref<[string, string] | null>(null)

function syncDateRangeToQuery() {
  query.date_from = dateRange.value?.[0] || ''
  query.date_to = dateRange.value?.[1] || ''
}

const loading = ref(false)
const records = ref<StrategySignalRow[]>([])
const total = ref(0)

async function loadList() {
  if (currentTaskId.value == null) {
    records.value = []
    total.value = 0
    return
  }
  loading.value = true
  syncDateRangeToQuery()
  try {
    const res = await getStrategySignals({
      task_id: currentTaskId.value,
      page: query.page,
      page_size: query.page_size,
      state: query.state || undefined,
      direction: query.direction || undefined,
      date_from: query.date_from || undefined,
      date_to: query.date_to || undefined,
      keyword: query.keyword || undefined,
    })
    records.value = res.list
    total.value = res.total
  } catch (e) {
    console.warn('[StrategySignalView.loadList] 信号查询失败', {
      taskId: currentTaskId.value,
      error: e,
    })
    records.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// ---- 状态着色 / 文案（states 声明驱动） ----
const COLOR_CLASS: Record<string, string> = {
  info: 'badge--info',
  warning: 'badge--warning',
  danger: 'badge--rise',
  success: 'badge--fall',
}
function stateDeclOf(value: string) {
  return currentDefinition.value?.states.find((s) => s.value === value) || null
}
function stateLabel(value: string) {
  return stateDeclOf(value)?.label || value
}
function stateBadgeClass(value: string) {
  const decl = stateDeclOf(value)
  return COLOR_CLASS[decl?.color || 'info'] || 'badge--info'
}

// ---- 私有列格式化（columns 声明 type 驱动） ----
function formatPayload(v: number | string | null | undefined, type: StrategyColumnDecl['type']): string {
  if (v == null) return '--'
  if (type === 'float') return Number(v).toFixed(2)
  // pct/outcome/price_pct 新列型兜底（strategy-signal-outcome D7/D12）：
  // /signals 独立页按完整声明渲染全列（不裁剪通用列，也渲染 price_pct
  // 合并列——价格分量普通文本 + 涨幅分量 pct 规则），保证不显示裸小数
  if (type === 'pct' || type === 'price_pct') {
    const n = Number(v)
    if (!Number.isFinite(n)) return '--'
    return `${n > 0 ? '+' : ''}${(n * 100).toFixed(1)}%`
  }
  if (type === 'outcome') {
    const LABELS: Record<string, string> = { success: '成功', failed: '失败', pending: '待定' }
    return LABELS[String(v)] || '--'
  }
  return String(v)
}

/** price_pct 合并列兜底（D12/6.6）：价格分量 float 文本（不足 '--'） */
function fmtPriceComponent(v: number | string | null | undefined): string {
  if (v == null || v === '') return '--'
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return n.toFixed(2)
}

/** 列取值兜底（strategy-signal-outcome 5.1）：先 payload[key]，无键回退行级
 *  字段（ret_5d 等绩效列与 outcome 不在 payload） */
function colValue(row: StrategySignalRow, key: string): number | string | null | undefined {
  const pv = row.payload?.[key]
  if (pv !== undefined) return Array.isArray(pv) ? undefined : pv
  return row[key as keyof StrategySignalRow] as number | string | null | undefined
}

/** pct 列着色（A 股红涨绿跌） */
function pctClass(v: number | string | null | undefined): string {
  if (v == null || v === '') return ''
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ''
  return n > 0 ? 'text-rise' : 'text-fall'
}

function formatPrice(v: number | null | undefined) {
  if (v == null) return '--'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ---- B 级事件弹窗（strategy-volume-breakout-pullback D7/4.2） ----
/** 主列表 B 列点击 → 走单信号 b-events 接口取全集（列表行不嵌） */
const bDialogVisible = ref(false)
const bDialogTitle = ref('')
const bDialogEvents = ref<BEventRow[]>([])

/** 行内已有 b_events（payload 嵌入的任务详情路径）或按 b_count 判断可弹窗 */
function bEventsOf(row: StrategySignalRow): BEventRow[] {
  const v = row.payload?.b_events
  return Array.isArray(v) ? (v as BEventRow[]) : []
}

async function openBDialog(row: StrategySignalRow, colLabel: string): Promise<void> {
  bDialogTitle.value = `${row.name}（${row.code}）· ${colLabel}级买点详情`
  bDialogVisible.value = true
  const embedded = bEventsOf(row)
  if (embedded.length) {
    bDialogEvents.value = embedded
    return
  }
  // 主列表行无嵌入全集：payload.b_count > 0 或旧口径（b_count 缺省视为旧口径
  // 也可点击尝试，接口返回空列表时弹「旧口径信号」提示）
  if (row.id == null) {
    bDialogEvents.value = []
    return
  }
  try {
    const res = await getSignalBEvents(row.id)
    bDialogEvents.value = res.b_events || []
  } catch {
    bDialogEvents.value = []
    ElMessage.error('B 级事件查询失败')
  }
}

/** B 事件时间展示（D4）：30m 判定（b_time 含非零时刻）展示 'MM-DD HH:MM'；
 *  日线判定（00:00:00）只展示日期 'YYYY-MM-DD' */
function fmtBTime(t: string): string {
  if (!t) return '--'
  if (t.length >= 19 && !t.endsWith('00:00:00')) return t.slice(5, 16)
  return t.slice(0, 10)
}

/** date_price_pct 日期分量格式化（D7）：截 10 位日期（b_date 30m 时间列内
 *  只展示日期分量，时刻在弹窗展示） */
function fmtDayComponent(v: number | string | null | undefined): string {
  if (v == null || v === '') return '--'
  return String(v).slice(0, 10)
}

const OUTCOME_BADGE: Record<string, string> = {
  success: 'badge--fall',
  failed: 'badge--rise',
  pending: 'badge--disabled',
}
const OUTCOME_LABELS: Record<string, string> = { success: '成功', failed: '失败', pending: '待定' }
function outcomeLabel(v: string | null | undefined) {
  return OUTCOME_LABELS[v || ''] || '--'
}
function outcomeBadgeClass(v: string | null | undefined) {
  return OUTCOME_BADGE[v || ''] || 'badge--disabled'
}

// ---- 股票搜索（el-autocomplete 模糊下拉选 code，复制 BspView 实现模式） ----
interface StockSuggestion {
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与查询 */
  placeholder?: boolean
}
const acRef = ref<AutocompleteInstance | null>(null)
const keywordInput = ref('')
const selectedCode = ref('')

async function queryStocks(q: string, cb: (items: StockSuggestion[]) => void) {
  const text = q.trim()
  if (!text) {
    cb([])
    return
  }
  try {
    const list = await searchStocks(text)
    if (!list.length) {
      cb([{ value: text, code: '', name: '无匹配候选', placeholder: true }])
      return
    }
    cb(list.map((s) => ({ value: s.code, code: s.code, name: s.name })))
  } catch {
    cb([])
  }
}

function onSelectSuggestion(item: StockSuggestion) {
  if (item.placeholder) return
  selectedCode.value = item.code
  keywordInput.value = item.code
  acRef.value?.close()
}

function onKeywordClear() {
  selectedCode.value = ''
}

function syncKeywordToQuery() {
  query.keyword = selectedCode.value || keywordInput.value.trim()
}

function onQueryChange() {
  query.page = 1
  loadList()
}

function onQuery() {
  syncKeywordToQuery()
  query.page = 1
  loadList()
}

function onReset() {
  keywordInput.value = ''
  selectedCode.value = ''
  query.keyword = ''
  query.state = ''
  query.direction = ''
  dateRange.value = null
  syncDateRangeToQuery()
  query.page = 1
  loadList()
}

// ---- 新建任务（4.3 TaskDialog 承载；strategy-task-list-redesign 4.1：
//      弹窗内先选策略任务类型，definitions 全量传入） ----
const taskDialogVisible = ref(false)

function openCreateTask() {
  taskDialogVisible.value = true
}

// ---- 编辑与续跑（4.4 TaskEditDialog / TaskResumeDialog 承载） ----
const editDialogVisible = ref(false)
const editDialogTask = ref<StrategyTask | null>(null)
const editDialogDef = ref<StrategyDefinition | null>(null)

function openEditDialog(task: StrategyTask) {
  editDialogTask.value = task
  editDialogDef.value = definitions.value.find((d) => d.id === task.strategy_id) || null
  editDialogVisible.value = true
}

const resumeDialogVisible = ref(false)
const resumeDialogTask = ref<StrategyTask | null>(null)

function openResumeDialog(task: StrategyTask) {
  resumeDialogTask.value = task
  resumeDialogVisible.value = true
}

// ---- 任务详情（4.5 TaskDetailDrawer 承载） ----
const detailVisible = ref(false)
const detailTaskId = ref<number | null>(null)

function openDetail(task: StrategyTask) {
  detailTaskId.value = task.id
  detailVisible.value = true
}

// ---- 信号详情抽屉 ----
const drawerVisible = ref(false)
const drawerSignal = ref<StrategySignalRow | null>(null)

function onRowClick(row: StrategySignalRow) {
  drawerSignal.value = row
  drawerVisible.value = true
}

// ---- 生命周期 ----
onMounted(async () => {
  await loadDefinitions()
  await loadList()
  ensurePolling()
})

onUnmounted(stopPolling)
</script>

<style scoped>
.strategy-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  flex: 1;
}
/* ---- 视图 Tab ---- */
.view-tabs {
  display: flex;
  gap: var(--sp-sm);
}
.tab-btn {
  padding: 6px 16px;
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: all 0.15s;
}
.tab-btn:hover {
  color: var(--text-primary);
}
.tab-btn.is-active {
  color: var(--accent-hover);
  background: var(--accent-dim);
  border-color: var(--accent-border);
  font-weight: 500;
}
/* ---- 任务列表 ---- */
.task-view {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
}
.toolbar-spacer {
  flex: 1;
}
.cell-task-nm {
  color: var(--text-primary);
  font-size: 13px;
}
.strategy-type {
  font-size: 12px;
  color: var(--text-secondary);
}
.cell-task {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cell-task .nm {
  color: var(--text-primary);
  font-size: 13px;
}
.cell-task .sub {
  color: var(--text-disabled);
  font-size: 11px;
}
.cell-progress {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  min-width: 0;
}
.cell-progress :deep(.el-progress) {
  flex: 1;
  min-width: 60px;
}
.progress-text {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.running-hint {
  margin-left: 4px;
  color: var(--accent-hover);
}
.num.link {
  color: var(--accent-hover);
  cursor: pointer;
}
.num.link:hover {
  text-decoration: underline;
}
/* ---- 信号视图（沿用原骨架） ---- */
.signal-view {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
}
.cell-stock {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cell-stock .nm {
  color: var(--text-primary);
  font-size: 13px;
}
.cell-stock .cd {
  color: var(--text-disabled);
  font-size: 11px;
}
/* price_pct 合并列两值分隔符（D12：弱化分隔符视觉层级） */
.pp-sep {
  color: var(--text-disabled);
  margin: 0 2px;
}
/* date_price_pct 三值合并单元格（strategy-volume-breakout-pullback D7）：
   B 列带事件时可点击弹窗（下划线提示） */
.dpc--popup {
  cursor: pointer;
  border-bottom: 1px dashed var(--text-disabled);
}
.dpc--popup:hover {
  border-bottom-color: var(--text-primary);
}
/* B 级事件弹窗旧口径提示文案 */
.b-events-empty {
  color: var(--text-disabled);
  font-size: 12px;
  padding: 12px 0;
  text-align: center;
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-md) var(--sp-lg);
  border-top: 1px solid var(--border-base);
}
.sug-item {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  padding: 2px 0;
}
.sug-item__code {
  width: 84px;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--accent-hover);
}
.sug-item__name {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sug-item__empty {
  font-size: 12px;
  color: var(--text-disabled);
}
</style>

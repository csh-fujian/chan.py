<template>
  <div class="page-layout">
    <!-- 左侧菜单栏：随顶部 tab 切换分组（design D6 单页整合，不走路由） -->
    <Sidebar title="监控">
      <TreeList
        group-label="状态"
        :items="statusItems"
        :active-key="tabMode"
        @update:active-key="onTabChange"
      />
      <!-- 监控中 tab：盈利 / 周期 / 分组过滤 -->
      <template v-if="tabMode === 'monitoring'">
        <!-- 分组过滤树（monitor-group-change 4.1/4.2/4.3）：
             全部/未分组虚拟节点 + 各分组按 sort_order；选中即带 group_id 重查；
             hover 重命名/删除图标 + 新建按钮 + 拖拽排序（虚拟节点不参与拖拽） -->
        <div class="sidebar__group">
          <div class="sidebar__group-label">
            分组
            <span class="spacer"></span>
            <button
              class="btn btn--ghost btn--sm group-create-btn"
              title="新建分组"
              @click="openCreateGroup"
            >
              <el-icon><Plus /></el-icon> 新建
            </button>
          </div>
          <div
            class="tree__item"
            :class="{ 'is-active': activeMonitorGroup === 'all' }"
            @click="onMonitorGroupChange('all')"
          >
            <span class="group-name">全部</span>
            <span class="count">{{ monitorList.length }}</span>
          </div>
          <div
            class="tree__item"
            :class="{ 'is-active': activeMonitorGroup === 'ungrouped' }"
            @click="onMonitorGroupChange('ungrouped')"
          >
            <span class="group-name">未分组</span>
            <span class="count">{{ ungroupedMonitoringCount }}</span>
          </div>
          <draggable
            :list="monitorGroups"
            item-key="id"
            tag="div"
            class="group-drag"
            :delay="200"
            :delay-on-touch-only="false"
            :touch-start-threshold="4"
            filter=".group-edit, .group-del"
            :prevent-on-filter="false"
            @start="onGroupDragStart"
            @end="onGroupDragEnd"
          >
            <template #item="{ element: g }">
              <div
                class="tree__item"
                :class="{ 'is-active': activeMonitorGroup === String(g.id) }"
                @click="onMonitorGroupChange(String(g.id))"
              >
                <span class="group-name" :title="g.name">{{ g.name }}</span>
                <span class="count">{{ g.monitoring_count }}</span>
                <el-icon
                  class="group-edit"
                  title="重命名分组"
                  @click.stop="openRenameGroup(g)"
                  ><EditPen /></el-icon>
                <el-icon
                  class="group-del"
                  title="删除分组"
                  @click.stop="onDeleteGroup(g)"
                  ><Close /></el-icon>
              </div>
            </template>
          </draggable>
        </div>
        <TreeList
          group-label="盈利"
          :items="profitItems"
          :active-key="activeProfit"
          @update:active-key="onProfitChange"
        />
        <TreeList
          group-label="周期"
          :items="klTypeItems"
          :active-key="activeKl"
          @update:active-key="onKlChange"
        />
      </template>
      <!-- 已完成 tab：归因 / 失败原因 / 只读分组过滤 -->
      <template v-else>
        <!-- 已完成 tab 分组树（4.4：只读过滤，无管理动作；选中带 group_id 调 getCompletedList） -->
        <div class="sidebar__group">
          <div class="sidebar__group-label">分组</div>
          <div
            class="tree__item"
            :class="{ 'is-active': activeCompletedGroup === 'all' }"
            @click="onCompletedGroupChange('all')"
          >
            <span class="group-name">全部</span>
            <span class="count">{{ completedList.length }}</span>
          </div>
          <div
            class="tree__item"
            :class="{ 'is-active': activeCompletedGroup === 'ungrouped' }"
            @click="onCompletedGroupChange('ungrouped')"
          >
            <span class="group-name">未分组</span>
            <span class="count">{{ ungroupedCompletedCount }}</span>
          </div>
          <div
            v-for="g in monitorGroups"
            :key="g.id"
            class="tree__item"
            :class="{ 'is-active': activeCompletedGroup === String(g.id) }"
            @click="onCompletedGroupChange(String(g.id))"
          >
            <span class="group-name" :title="g.name">{{ g.name }}</span>
            <span class="count">{{ g.completed_count }}</span>
          </div>
        </div>
        <TreeList
          group-label="归因"
          :items="attrItems"
          :active-key="activeAttr"
          @update:active-key="onAttrChange"
        />
        <TreeList
          group-label="失败原因"
          :items="reasonItems"
          :active-key="activeReason"
          @update:active-key="onReasonChange"
        />
      </template>
    </Sidebar>

    <!-- 分组弹窗：新建 / 重命名 复用同一对话框（对齐 WatchlistView D6 模式，任务 4.2） -->
    <el-dialog
      v-model="groupDialogVisible"
      :title="groupDialogMode === 'create' ? '新建分组' : '重命名分组'"
      width="420px"
      append-to-body
    >
      <el-form @submit.prevent>
        <el-form-item label="分组名">
          <el-input v-model="groupName" placeholder="请输入分组名" autofocus />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="groupDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="groupSaving" @click="onSubmitGroup">确认</el-button>
      </template>
    </el-dialog>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <div class="monitor-page">
        <!-- 顶部 tab（design D6）：整体切换内容区，不走路由跳转 -->
        <div class="tabbar reveal">
          <el-radio-group v-model="tabMode" @change="onTabChange">
            <el-radio-button value="monitoring">监控中</el-radio-button>
            <el-radio-button value="completed">已完成</el-radio-button>
          </el-radio-group>
        </div>

        <!-- ==================== 监控中 tab ==================== -->
        <!-- key 强制分支整体重建：两个 tab 结构相似，unkeyed diff 会原地复用 el-table-column
             组件实例，列组件 inject 到已卸载旧 table 的 store 上导致列注册丢失（表格塌陷 bug） -->
        <div v-if="tabMode === 'monitoring'" key="tab-monitoring">
          <!-- 汇总卡（design D11：总体盈利=收益率求和；新增当前胜率/涨幅最大） -->
          <div class="stat-row">
            <StatCard
              label="总体盈利（%）"
              :value="totalProfitStr"
              :foot="`${monitorList.length} 只监控中 · 收益率求和`"
              :trend="totalProfit >= 0 ? 'up' : 'down'"
              accent
            />
            <StatCard
              label="当前胜率"
              :value="winRateStr"
              :trend="winRate >= 50 ? 'up' : 'down'"
              :foot="`${winCount} 胜 / ${winTotal} 只参与统计`"
            />
            <StatCard
              label="涨幅最大"
              :value="maxChangeStr"
              :trend="(maxChange?.change_pct ?? 0) >= 0 ? 'up' : 'down'"
              :foot="maxChange ? `${maxChange.name} (${maxChange.code}) · ${klLabel(maxChange.kl_type)}` : '暂无数据'"
            />
            <StatCard
              label="监控中数量"
              :value="String(monitorList.length)"
              foot="实时跟踪"
            />
            <StatCard
              label="累计完成"
              :value="String(completedCount)"
              foot="历史已结算监控"
            />
          </div>

          <!-- 搜索（design D7：对齐 K 线页 el-autocomplete 远程候选 + Enter 精确查询 + 查询/重置按钮） + 表格 -->
          <div class="toolbar reveal reveal--4">
            <div class="code-field" @keydown.capture="mSearch.onKeydown">
              <el-autocomplete
                :ref="(i: any) => (mSearch.acRef.value = i)"
                v-model="mSearch.input.value"
                :fetch-suggestions="mSearch.query"
                :trigger-on-focus="false"
                :debounce="0"
                placeholder="代码/名称/拼音 如 sz.000001"
                :prefix-icon="Search"
                clearable
                @input="mSearch.onInput"
                @select="mSearch.onSelect"
                @clear="mSearch.onClear"
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
            </div>
            <el-button type="primary" @click="mSearch.apply">查询</el-button>
            <el-button @click="onResetMonitoringFilters">重置</el-button>
            <!-- 来源下拉（design D14）：字典来自 GET /monitor/sources，与标的查询叠加过滤 -->
            <el-select
              v-model="mSourceValue"
              placeholder="全部来源"
              clearable
              style="width: 200px"
            >
              <el-option
                v-for="s in monitorSources"
                :key="s.value"
                :label="s.label"
                :value="s.value"
              />
            </el-select>
          </div>

          <Panel flush>
            <el-table
              key="monitor-table"
              ref="monitorTableRef"
              v-loading="loading"
              :data="pagedList"
              style="width: 100%"
              row-key="id"
            >
              <el-table-column label="名称 / 编码" min-width="150">
                <template #default="{ row }">
                  <div
                    class="cell-stock cell-stock--link"
                    title="双击跳转 K 线"
                    @dblclick="onGoKline(row)"
                  >
                    <span class="nm">{{ row.name }}</span>
                    <span class="cd mono">{{ row.code }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="行业" min-width="120">
                <template #default="{ row }">
                  <IndustryBadges :industries="row.industries" />
                </template>
              </el-table-column>
              <!-- 来源列（strategy-signal-page 任务 6.1 + D14 + watchlist-page-change 7.2）：strategy 显示
                   「策略名·实例名·状态」小号标签；watchlist 显示「自选」（src-tag 同款样式）；
                   chan（含缺省）显示「缠论」次要文本。位置在买卖点类型列之前 -->
              <el-table-column label="来源" width="100" align="center">
                <template #default="{ row }">
                  <span v-if="row.source_type === 'strategy' && row.strategy_label" class="src-tag" :title="row.strategy_label">
                    {{ row.strategy_label }}
                  </span>
                  <span v-else-if="row.source_type === 'watchlist'" class="src-tag">自选</span>
                  <span v-else class="src-chan">缠论</span>
                </template>
              </el-table-column>
              <!-- 买卖点类型（design D9：原「买卖点」+「方向」两列合并，展示 bsp_type 值，B 系红 / S 系绿） -->
              <el-table-column label="买卖点类型" width="100" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="row.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
                    {{ bspLabel(row.bsp_type, row.direction === 'buy') }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="买卖点价格" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.bsp_price) }}</span>
                </template>
              </el-table-column>
              <!-- 买卖点时间（design D8）：收益计算起点，ms → YYYY-MM-DD HH:mm -->
              <el-table-column label="买卖点时间" width="140" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDateTime(row.bsp_date) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="当前价" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.current_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="涨跌幅" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <ChangeBadge :value="row.change_pct" />
                </template>
              </el-table-column>
              <!-- 收益率（design D8）：current_pnl_pct 自买卖点起累计涨跌，红涨绿跌 -->
              <el-table-column label="收益率" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <ChangeBadge v-if="row.current_pnl_pct != null" :value="row.current_pnl_pct" />
                  <span v-else class="num">--</span>
                </template>
              </el-table-column>
              <el-table-column label="级别" width="80" align="center">
                <template #default="{ row }">
                  <span class="num">{{ klLabel(row.kl_type) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100" align="right" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="row.status === 'monitoring'"
                    link
                    type="danger"
                    size="small"
                    :loading="endingId === row.id"
                    @click="onEnd(row)"
                  >
                    手动结束
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <EmptyState description="暂无监控记录" />
              </template>
            </el-table>

            <div v-if="filteredList.length > pageSize" class="pager-wrap">
              <el-pagination
                v-model:current-page="page"
                :page-size="pageSize"
                :total="filteredList.length"
                layout="prev, pager, next, total"
                background
                small
              />
            </div>
          </Panel>

          <!-- 盈利走势图（design D10：移至列表下方；D8：由监控中列表各标的收益率前端聚合，红涨绿跌分段着色） -->
          <Panel title="盈利走势" sub="监控中标的收益率均值 · 按买卖点时间聚合">
            <template #head>
              <SegControl v-model="profitSeg" :items="segItems" />
            </template>
            <div class="chart chart--grid" style="height:280px">
              <template v-if="profitSeg === 'summary'">
                <ProfitChart :series="summarySeries" split-color />
              </template>
              <template v-else>
                <div class="single-stock-toolbar">
                  <el-select
                    v-model="singleStockId"
                    placeholder="选择标的"
                    filterable
                    size="small"
                    style="width: 200px"
                  >
                    <el-option
                      v-for="r in monitorList"
                      :key="r.id"
                      :label="`${r.name} (${r.code})`"
                      :value="r.id"
                    />
                  </el-select>
                </div>
                <ProfitChart v-if="singleStockId" :series="singleStockSeries" split-color />
                <EmptyState v-else description="请选择标的查看单只走势" />
              </template>
            </div>
          </Panel>
        </div>

        <!-- ==================== 已完成 tab（原 CompletedView 并入，design D6） ==================== -->
        <div v-else key="tab-completed">
          <!-- 顶部统计卡片行 -->
          <div class="stat-row">
            <StatCard label="完成总数" :value="String(completedList.length)" foot="历史已结算" />
            <StatCard
              label="胜率"
              :value="cWinRateStr"
              :trend="cWinRate >= 50 ? 'up' : 'down'"
              foot="盈利占比"
            />
            <StatCard
              label="平均盈利"
              :value="avgProfitStr"
              :trend="avgProfit >= 0 ? 'up' : 'down'"
              foot="所有完成标的"
            />
            <StatCard
              label="盈利比"
              :value="profitRatioStr"
              foot="平均盈利 / 平均亏损"
            />
          </div>

          <!-- 操作工具条（D7 增补：已完成搜索同款 el-autocomplete + 查询/重置） -->
          <div class="toolbar reveal reveal--1">
            <div class="code-field" @keydown.capture="cSearch.onKeydown">
              <el-autocomplete
                :ref="(i: any) => (cSearch.acRef.value = i)"
                v-model="cSearch.input.value"
                :fetch-suggestions="cSearch.query"
                :trigger-on-focus="false"
                :debounce="0"
                placeholder="代码/名称/拼音 如 sz.000001"
                :prefix-icon="Search"
                clearable
                @input="cSearch.onInput"
                @select="cSearch.onSelect"
                @clear="cSearch.onClear"
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
            </div>
            <el-button type="primary" @click="cSearch.apply">查询</el-button>
            <el-button @click="onResetCompletedFilters">重置</el-button>
            <!-- 来源下拉（design D14）：字典来自 GET /monitor/sources，与标的查询叠加过滤 -->
            <el-select
              v-model="cSourceValue"
              placeholder="全部来源"
              clearable
              style="width: 200px"
            >
              <el-option
                v-for="s in monitorSources"
                :key="s.value"
                :label="s.label"
                :value="s.value"
              />
            </el-select>
            <span class="spacer"></span>
            <el-button
              type="primary"
              :loading="batchAnalyzing"
              :disabled="pendingItems.length === 0"
              @click="onBatchAnalyze"
            >
              大模型分析
            </el-button>
            <div v-if="batchAnalyzing" class="progress-hint">
              <span class="lbl">正在对盈利 &lt; 5% 的 {{ pendingItems.length }} 只标的做亏损归因…</span>
              <div class="progress">
                <div class="progress__bar" :style="{ width: batchProgress + '%' }"></div>
              </div>
            </div>
          </div>

          <!-- 完成列表表格 -->
          <Panel title="监控完成记录" sub="已结算卖出" flush>
            <el-table
              key="completed-table"
              ref="completedTableRef"
              v-loading="loading"
              :data="pagedCompletedList"
              style="width: 100%"
              row-key="id"
            >
              <el-table-column label="名称 / 编码" min-width="150">
                <template #default="{ row }">
                  <div
                    class="cell-stock cell-stock--link"
                    title="双击跳转 K 线"
                    @dblclick="onGoKline(row)"
                  >
                    <span class="nm">{{ row.name }}</span>
                    <span class="cd mono">{{ row.code }}</span>
                  </div>
                </template>
              </el-table-column>
              <!-- 来源列（strategy-signal-page 任务 6.1 + D14 + watchlist-page-change 7.2，语义同监控中表格）：
                   strategy 策略标签小号标签；watchlist 显示「自选」（src-tag 同款样式）；
                   chan（含缺省）显示「缠论」次要文本 -->
              <el-table-column label="来源" width="100" align="center">
                <template #default="{ row }">
                  <span v-if="row.source_type === 'strategy' && row.strategy_label" class="src-tag" :title="row.strategy_label">
                    {{ row.strategy_label }}
                  </span>
                  <span v-else-if="row.source_type === 'watchlist'" class="src-tag">自选</span>
                  <span v-else class="src-chan">缠论</span>
                </template>
              </el-table-column>
              <!-- 买卖点类型（design D9：原「买卖点」+「方向」两列合并，展示 bsp_type 值，B 系红 / S 系绿） -->
              <el-table-column label="买卖点类型" width="100" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="row.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
                    {{ bspLabel(row.bsp_type, row.direction === 'buy') }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="买卖点价格" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.bsp_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="结束价格" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.end_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="收益率" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num" :class="(row.profit ?? 0) >= 0 ? 'text-rise' : 'text-fall'">
                    {{ fmtPct(row.profit, true) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="买卖点日期" width="120" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDate(row.bsp_date) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="结束日期" width="120" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDate(row.end_date) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="归因" min-width="160">
                <template #default="{ row }">
                  <span v-if="row.ai_analyzed" class="badge badge--accent">已归因</span>
                  <span v-else class="badge badge--disabled">未归因</span>
                </template>
              </el-table-column>
              <el-table-column label="AI分析" width="100" align="center">
                <template #default="{ row }">
                  <el-button
                    link
                    type="primary"
                    size="small"
                    :loading="analyzingId === row.id"
                    @click="onAnalyze(row)"
                  >
                    {{ row.ai_analyzed ? '重新分析' : '大模型分析' }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100" align="right" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="onViewAttrDetail(row)">
                    查看归因
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <EmptyState description="暂无完成记录" />
              </template>
            </el-table>

            <div v-if="filteredCompletedList.length > cPageSize" class="pager-wrap">
              <el-pagination
                v-model:current-page="cPage"
                :page-size="cPageSize"
                :total="filteredCompletedList.length"
                layout="prev, pager, next, total"
                background
                small
              />
            </div>
          </Panel>

          <!-- 失败原因汇总 -->
          <Panel title="失败原因汇总" sub="盈利 < 5% 的标的 · 大模型归因">
            <div class="sum-list">
              <div v-for="item in lossItems" :key="item.id" class="sum-item">
                <span class="badge" :class="reasonBadgeClass(item)">{{ reasonCategory(item) }}</span>
                <div class="cell-stock" style="min-width:150px">
                  <span class="nm">{{ item.name }}</span>
                  <span class="cd mono">{{ item.code }}</span>
                </div>
                <div class="reason">
                  <span class="t">{{ item.attribution }}</span>
                  <span class="s">证据：{{ reasonCategory(item) }} · {{ fmtDate(item.end_date) }}</span>
                </div>
                <span class="spacer"></span>
                <span class="num text-fall">{{ fmtPct(item.profit, true) }}</span>
                <el-button link type="primary" size="small" @click="onViewAttrDetail(item)">
                  查看详情
                </el-button>
              </div>
              <EmptyState v-if="lossItems.length === 0" description="暂无亏损归因记录" />
            </div>
          </Panel>
        </div>
      </div>
    </div>

    <!-- 归因详情抽屉（design D6：SampleDrawer 保留复用） -->
    <SampleDrawer v-model="drawerVisible" :item="drawerItem" />
  </div>
</template>

<script setup lang="ts">
/**
 * MonitorView.vue — 监控单页（design D6/D7/D8，monitor-page-change 任务组 7）
 * - D6：CompletedView 并入为「已完成」tab，顶部 el-radio-group 整体切换内容区，
 *   不走路由；归因抽屉/批量分析随迁；已完成 tab 仅由顶部 tab 手动切换到达
 *   （原「查看详情」切 tab 定位链路已随 D13 删除）。
 * - D7：搜索框对齐 K 线页（el-autocomplete + searchStocks 远程候选 +
 *   300ms setTimeout 本地防抖 + 后发覆盖 + Enter 语义），点选/回车按 code 精确过滤。
 * - D8：监控中列表新增「买卖点时间」（bsp_date）与「收益率」（current_pnl_pct）
 *   两列；盈利走势改为由列表各标的收益率前端聚合（替换 mock profit-series
 *   随机游走），曲线 >0 红 / <0 绿分段着色 + 0 轴参考线。
 */
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type AutocompleteInstance, type TableInstance } from 'element-plus'
import { Search, Plus, EditPen, Close } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'
import Sidebar from '@/components/layout/Sidebar.vue'
import TreeList from '@/components/ui/TreeList.vue'
import Panel from '@/components/ui/Panel.vue'
import StatCard from '@/components/ui/StatCard.vue'
import SegControl from '@/components/ui/SegControl.vue'
import ChangeBadge from '@/components/ui/ChangeBadge.vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import ProfitChart from '@/components/charts/ProfitChart.vue'
import SampleDrawer from './SampleDrawer.vue'
import { usePagination } from '@/composables/usePagination'
import {
  getMonitorList,
  getCompletedList,
  getMonitorSources,
  endMonitor,
  analyzeMonitor,
  getMonitorGroups,
  createMonitorGroup,
  renameMonitorGroup,
  deleteMonitorGroup,
  reorderMonitorGroups,
  type MonitorGroup,
  type MonitorSource,
} from '@/api/modules/monitor'
import { searchStocks } from '@/api/modules/stock'
import { bspLabel } from '@/utils/bsp'
import type { MonitorItem, CompletedItem, AnalyzeResult } from '@/api/types'

// ---- 数据 ----
const loading = ref(false)
const monitorList = ref<MonitorItem[]>([])
const completedList = ref<CompletedItem[]>([])
const completedCount = ref(0)

// ---- 顶部 tab（design D6：单页双 tab，不走路由） ----
const tabMode = ref<'monitoring' | 'completed'>('monitoring')

/** 两个 tab 的 el-table ref — v-if 切换重建后修复列注册派生（ElementPlus 2.8 表格塌陷修复） */
const monitorTableRef = ref<TableInstance | null>(null)
const completedTableRef = ref<TableInstance | null>(null)

function onTabChange(v: string | number | boolean) {
  const val = String(v)
  if (val !== 'monitoring' && val !== 'completed') return
  tabMode.value = val
  if (val === 'monitoring') page.value = 1
  else cPage.value = 1
}

/**
 * tab 切换后修复 el-table 列派生（ElementPlus 2.8 bug）：
 * v-if 重建 table 时列组件重新注册进 _columns，但内部派生 originColumns 的
 * watcher 被列复用/时序竞态吞掉，originColumns/columns 停留为 0 → colgroup 空、
 * 表格塌陷。手动调 store.updateColumns() 重跑派生，再强制 ElTableBody 重渲。
 */
async function fixTableColumns(tableRef: typeof monitorTableRef) {
  await nextTick()
  const table = tableRef.value as unknown as { store?: { updateColumns?: () => void } } | null
  table?.store?.updateColumns?.()
  // ElTableBody 是独立组件，其渲染快照需要单独强制更新
  const tableEl = (tableRef.value as unknown as { $el?: HTMLElement } | null)?.$el
  const tbody = tableEl?.querySelector('.el-table__body tbody') as (Element & { __vueParentComponent?: unknown }) | null
  type Comp = { type?: { name?: string }; update?: () => void; parent?: Comp } | undefined
  let cur = tbody?.__vueParentComponent as Comp
  while (cur) {
    if (cur.type?.name === 'ElTableBody') { cur.update?.(); break }
    cur = cur.parent
  }
  tableRef.value?.doLayout()
}

watch(tabMode, (val) => {
  if (val === 'monitoring') {
    fixTableColumns(monitorTableRef)
  } else {
    fixTableColumns(completedTableRef)
  }
})

// ---- 监控中 tab 侧栏过滤 ----
const activeProfit = ref('all')
const activeKl = ref('all')

const statusItems = [
  { key: 'monitoring', label: '监控中', count: 0 },
  { key: 'completed', label: '已完成', count: 0 },
]
const profitItems = [
  { key: 'all', label: '全部' },
  { key: 'profit', label: '盈利' },
  { key: 'loss', label: '亏损' },
]
const klTypeItems = [
  { key: 'all', label: '全部周期' },
  { key: '30m', label: '30分钟' },
  { key: '60m', label: '60分钟' },
  { key: 'D', label: '日线' },
  { key: 'W', label: '周线' },
  { key: 'M', label: '月线' },
]

function onProfitChange(k: string) {
  activeProfit.value = k
  page.value = 1
}
function onKlChange(k: string) {
  activeKl.value = k
  page.value = 1
}

// ---------------------------------------------------------------------------
// 分组（monitor-group-change 任务组 4）：两个 tab 各自维护分组过滤状态，
// 跨 tab 切回选择保持（与 activeKl/activeProfit 一致，组件内状态不重置）
// ---------------------------------------------------------------------------
/** 分组树选中 key：'all' / 'ungrouped' / 数值 id 字符串 */
const activeMonitorGroup = ref('all')
const activeCompletedGroup = ref('all')

/** 分组列表（按 sort_order 升序，含组内计数） */
const monitorGroups = ref<MonitorGroup[]>([])

/** 未分组虚拟节点计数（左栏 count 展示用；从两组列表全量统计） */
const ungroupedMonitoringCount = computed(
  () => monitorList.value.filter((r) => r.group_id === null).length,
)
const ungroupedCompletedCount = computed(
  () => completedList.value.filter((r) => r.group_id === null).length,
)

async function loadMonitorGroups() {
  try {
    monitorGroups.value = await getMonitorGroups()
  } catch (e) {
    // 失败已由拦截器提示；保留现有分组树避免清空交互入口
    console.warn('[MonitorView.loadMonitorGroups] 加载监控分组失败', { error: e })
  }
}

/** 选中分组节点即带 group_id 重查（'all' 不传参，design D3）；两个 tab 各自处理 */
async function onMonitorGroupChange(k: string) {
  activeMonitorGroup.value = k
  page.value = 1
  await loadMonitorList()
}

async function onCompletedGroupChange(k: string) {
  activeCompletedGroup.value = k
  cPage.value = 1
  await loadCompletedList()
}

/** 当前选中分组 → API 查询参数（'all' → undefined） */
function toGroupParam(k: string): string | undefined {
  return k === 'all' ? undefined : k
}

// ---------------------------------------------------------------------------
// 分组树管理动作（对齐 WatchlistView 模式，任务 4.2/4.3）：
// hover 重命名/删除图标 + 模式化新建/重命名弹窗 + 删除确认（含组内记录数）+ 拖拽排序
// ---------------------------------------------------------------------------
const groupDialogVisible = ref(false)
const groupDialogMode = ref<'create' | 'rename'>('create')
const editingGroupId = ref<number | null>(null)
const groupName = ref('')
const groupSaving = ref(false)

function openCreateGroup() {
  groupDialogMode.value = 'create'
  editingGroupId.value = null
  groupName.value = ''
  groupDialogVisible.value = true
}

function openRenameGroup(g: MonitorGroup) {
  groupDialogMode.value = 'rename'
  editingGroupId.value = g.id
  groupName.value = g.name
  groupDialogVisible.value = true
}

async function onSubmitGroup() {
  const name = groupName.value.trim()
  if (!name) {
    // 空名拦截：不发请求
    ElMessage.warning('请输入分组名')
    return
  }
  groupSaving.value = true
  try {
    if (groupDialogMode.value === 'rename') {
      const id = editingGroupId.value
      if (id == null) {
        console.warn('[MonitorView.onSubmitGroup] 重命名缺少 editingGroupId，取消提交', { name })
        return
      }
      await renameMonitorGroup(id, name)
      ElMessage.success('分组已重命名')
    } else {
      await createMonitorGroup(name)
      ElMessage.success('分组已创建')
    }
    groupDialogVisible.value = false
    // 管理操作完成后刷新分组树（重命名/新建后名称与计数同步）
    await loadMonitorGroups()
  } catch (e) {
    // 失败（重名/空名 4xx detail）已由拦截器提示
    console.warn('[MonitorView.onSubmitGroup] 保存分组失败', {
      mode: groupDialogMode.value,
      editingGroupId: editingGroupId.value,
      name,
      error: e,
    })
  } finally {
    groupSaving.value = false
  }
}

async function onDeleteGroup(g: MonitorGroup) {
  const total = g.monitoring_count + g.completed_count
  try {
    await ElMessageBox.confirm(
      `确定删除分组「${g.name}」吗？` +
        (total > 0 ? `组内 ${g.monitoring_count} 条监控中、${g.completed_count} 条已完成记录将归入「未分组」，不会被删除。` : ''),
      '删除分组',
      { type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteMonitorGroup(g.id)
    ElMessage.success('分组已删除')
    // 选中项被删 → 回退「全部」；无论选中何值都重查列表
    //（选中「未分组」/「全部」时被删组的记录已归未分组，服务端需重取）
    if (activeMonitorGroup.value === String(g.id)) activeMonitorGroup.value = 'all'
    if (activeCompletedGroup.value === String(g.id)) activeCompletedGroup.value = 'all'
    await Promise.all([loadMonitorList(), loadCompletedList()])
    await loadMonitorGroups()
  } catch (e) {
    console.warn('[MonitorView.onDeleteGroup] 删除分组失败', { id: g.id, error: e })
  }
}

// ---- 分组拖拽排序（复用 WatchlistView draggable 实现，虚拟节点不参与） ----
/** 拖拽前快照：失败回滚用 */
let groupSnapshot: MonitorGroup[] = []

function onGroupDragStart() {
  groupSnapshot = monitorGroups.value.map((g) => ({ ...g }))
}

async function onGroupDragEnd() {
  // vuedraggable 已乐观重排 monitorGroups，这里负责持久化；失败回滚并提示
  const ids = monitorGroups.value.map((g) => g.id)
  try {
    await reorderMonitorGroups(ids)
    // 拖拽后本地顺序已是新序（groups 接口按 sort_order 返回，服务端已全量覆盖）
  } catch (e) {
    monitorGroups.value = groupSnapshot
    console.warn('[MonitorView.onGroupDragEnd] 分组顺序保存失败，已回滚', { ids, error: e })
    ElMessage.error('分组顺序保存失败，已恢复原顺序')
  }
}

// ---- 已完成 tab 侧栏过滤 ----
const activeAttr = ref('all')
const activeReason = ref('all')
const attrItems = [
  { key: 'all', label: '全部' },
  { key: 'analyzed', label: '已归因' },
  { key: 'pending', label: '未归因' },
]
const reasonItems = [
  { key: 'all', label: '全部' },
  { key: 'theory', label: '缠论失效' },
  { key: 'logic', label: '计算逻辑错误' },
]

function onAttrChange(k: string) {
  activeAttr.value = k
  cPage.value = 1
}
function onReasonChange(k: string) {
  activeReason.value = k
  cPage.value = 1
}

// ---- 分页（两个 tab 各一份页码状态） ----
const { page, pageSize, setTotal } = usePagination(20)
const { page: cPage, pageSize: cPageSize } = usePagination(20)

// ---------------------------------------------------------------------------
// 搜索（design D7：对齐 K 线页 el-autocomplete 远程候选 + 300ms 防抖 + Enter 语义；
// 查询/重置按钮；D7 增补：已完成 tab 同款搜索，两 tab 各一份实例）
// ---------------------------------------------------------------------------
interface StockSuggestion {
  /** el-autocomplete valueKey 默认取 value；点选后回填输入框 */
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与过滤 */
  placeholder?: boolean
}

/** 按 code 精确过滤的搜索器实例（监控中/已完成共用逻辑，各自独立状态与页码重置回调） */
interface StockSearch {
  acRef: ReturnType<typeof ref<AutocompleteInstance | null>>
  input: ReturnType<typeof ref<string>>
  selectedCode: ReturnType<typeof ref<string>>
  /** 用户是否用 ↑↓ 浏览过候选（Enter 分流标志，输入内容变化时重置） */
  arrowBrowsed: ReturnType<typeof ref<boolean>>
  /** 查询按钮（D7 增补）：应用当前输入/选中标的的精确过滤 */
  apply: () => void
  /** 重置按钮（D7 增补）：清空输入与选中，恢复全量 */
  reset: () => void
  onInput: (q: string) => void
  query: (q: string, cb: (items: StockSuggestion[]) => void) => void
  onSelect: (item: StockSuggestion) => void
  onKeydown: (e: KeyboardEvent) => void
  onClear: () => void
  dispose: () => void
}

function createStockSearch(onResetPage: () => void): StockSearch {
  const s = reactive({
    timer: null as ReturnType<typeof setTimeout> | null,
    seq: 0,
  })
  const acRef = ref<AutocompleteInstance | null>(null)
  const arrowBrowsed = ref(false)
  const input = ref('')
  /** 精确过滤的标的 code（点选/回车/查询按钮后生效；重置恢复全量） */
  const selectedCode = ref('')

  /** 取消在途/待发的搜索请求（后发覆盖的作废通道） */
  function cancel(): void {
    if (s.timer !== null) {
      clearTimeout(s.timer)
      s.timer = null
    }
    s.seq++
  }

  function reset(): void {
    cancel()
    input.value = ''
    selectedCode.value = ''
    arrowBrowsed.value = false
    acRef.value?.close()
    onResetPage()
  }

  /** 远程搜索候选（D7：300ms 本地 setTimeout 防抖，不引 lodash；过期响应丢弃） */
  function query(q: string, cb: (items: StockSuggestion[]) => void): void {
    if (s.timer !== null) {
      clearTimeout(s.timer)
      s.timer = null
    }
    const text = q.trim()
    if (!text) {
      cancel()
      cb([])
      return
    }
    // 请求发出前先收起旧候选，避免加载态闪烁
    cb([])
    s.timer = setTimeout(async () => {
      s.timer = null
      const seq = ++s.seq
      try {
        const list = await searchStocks(text)
        if (seq !== s.seq) return // 过期响应丢弃（后发覆盖）
        if (!list.length) {
          cb([{ value: text, code: '', name: '无匹配候选', placeholder: true }])
          return
        }
        cb(list.map((st) => ({ value: st.code, code: st.code, name: st.name })))
      } catch (e) {
        if (seq !== s.seq) return
        console.warn('[MonitorView.queryStocks] 股票搜索失败', {
          query: text,
          error: e instanceof Error ? e.message : String(e),
        })
        cb([])
      }
    }, 300)
  }

  function apply(): void {
    cancel()
    arrowBrowsed.value = false
    const v = input.value.trim()
    if (!v) {
      selectedCode.value = ''
    } else {
      selectedCode.value = v
    }
    onResetPage()
  }

  function onInput(q: string): void {
    // 输入变化即重置 Enter 分流标志；已选标的在输入变化时先行失效（回到全量，待点选/回车/查询）
    arrowBrowsed.value = false
    if (selectedCode.value && q.trim() !== selectedCode.value) {
      selectedCode.value = ''
    }
  }

  /** 点选候选：输入框回填 code，按 code 精确过滤（D7） */
  function onSelect(item: StockSuggestion): void {
    cancel()
    arrowBrowsed.value = false
    acRef.value?.close()
    if (item.placeholder) return // 空态提示项：仅收起下拉
    input.value = item.code
    selectedCode.value = item.code
    onResetPage()
  }

  /** Enter 语义（D7，捕获阶段拦截防 autocomplete 默认回车劫持）：
   *  未用 ↑↓ 浏览 → 按输入框原值精确匹配 code；浏览过且有高亮项 → 交给 autocomplete 选中 */
  function onKeydown(e: KeyboardEvent): void {
    // IME 组合确认的 Enter（如中文「平安」上屏）不触发查询
    if (e.isComposing || e.keyCode === 229) return
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      arrowBrowsed.value = true
      return // 继续传播，由 autocomplete 移动高亮
    }
    if (e.key !== 'Enter') return
    const ac = acRef.value
    const highlighted = ac?.highlightedIndex ?? -1
    const count = ac?.suggestions?.length ?? 0
    if (arrowBrowsed.value && highlighted >= 0 && highlighted < count) {
      return // 交给 autocomplete 选中高亮候选
    }
    e.preventDefault()
    e.stopPropagation()
    apply()
  }

  /** 清空输入：恢复全量列表 */
  function onClear(): void {
    reset()
  }

  function dispose(): void {
    cancel()
  }

  return { acRef, input, selectedCode, arrowBrowsed, apply, reset, onInput, query, onSelect, onKeydown, onClear, dispose }
}

/** 监控中 tab 搜索实例 */
const mSearch = createStockSearch(() => {
  page.value = 1
})
/** 已完成 tab 搜索实例（design D7 增补：与监控中同款，独立选中标的） */
const cSearch = createStockSearch(() => {
  cPage.value = 1
})

// ---- 来源下拉（design D14：字典来自后端，两 tab 共用选项、独立选中） ----
const monitorSources = ref<MonitorSource[]>([])
const mSourceValue = ref<string>('') // 监控中 tab 选中来源（'' = 全部）
const cSourceValue = ref<string>('') // 已完成 tab 选中来源（'' = 全部）

/** 来源字典项匹配行：'chan'/'watchlist' 按 source_type；'strategy:<id>' 加 instance_id */
function matchSource(row: MonitorItem, value: string): boolean {
  if (!value) return true
  if (value === 'chan') return (row.source_type ?? 'chan') === 'chan'
  if (value === 'watchlist') return row.source_type === 'watchlist'
  if (value.startsWith('strategy:')) {
    const id = Number(value.slice('strategy:'.length))
    return row.source_type === 'strategy' && row.instance_id === id
  }
  return true
}

async function loadMonitorSources() {
  try {
    monitorSources.value = await getMonitorSources()
  } catch {
    // 失败已由拦截器提示；下拉保持空选项，不影响列表展示
  }
}

/** 重置（monitoring tab）：清空搜索 + 来源选择（D14：重置语义扩展） */
function onResetMonitoringFilters() {
  mSearch.reset()
  mSourceValue.value = ''
}

/** 重置（completed tab）：清空搜索 + 来源选择 */
function onResetCompletedFilters() {
  cSearch.reset()
  cSourceValue.value = ''
}

// ---- 监控中过滤（D7：keyword 条件改为所选 code 精确匹配；D14：来源过滤叠加） ----
const filteredList = computed<MonitorItem[]>(() => {
  let list = monitorList.value
  if (mSearch.selectedCode.value) {
    list = list.filter((r) => r.code === mSearch.selectedCode.value)
  }
  if (mSourceValue.value) {
    list = list.filter((r) => matchSource(r, mSourceValue.value))
  }
  if (activeKl.value !== 'all') {
    list = list.filter((r) => r.kl_type === activeKl.value)
  }
  if (activeProfit.value === 'profit') {
    list = list.filter((r) => (r.max_profit ?? 0) >= 0)
  } else if (activeProfit.value === 'loss') {
    list = list.filter((r) => (r.max_profit ?? 0) < 0)
  }
  return list
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

// ---- 已完成过滤（D7 增补：与监控中同款，按所选 code 精确匹配；D14：来源过滤叠加） ----
const filteredCompletedList = computed(() => {
  let list = completedList.value
  if (cSearch.selectedCode.value) {
    list = list.filter((r) => r.code === cSearch.selectedCode.value)
  }
  if (cSourceValue.value) {
    list = list.filter((r) => matchSource(r, cSourceValue.value))
  }
  if (activeAttr.value === 'analyzed') {
    list = list.filter((r) => r.ai_analyzed)
  } else if (activeAttr.value === 'pending') {
    list = list.filter((r) => !r.ai_analyzed)
  }
  if (activeReason.value !== 'all') {
    list = list.filter((r) => reasonCategory(r) === (activeReason.value === 'theory' ? '缠论失效' : '计算逻辑错误'))
  }
  return list
})

const pagedCompletedList = computed(() => {
  const start = (cPage.value - 1) * cPageSize.value
  return filteredCompletedList.value.slice(start, start + cPageSize.value)
})

// ---- 汇总（监控中 tab，design D11：收益率求和 + 当前胜率 + 涨幅最大；D14：消费来源过滤后列表） ----
const totalProfit = computed(() => {
  // 收益率列求和（null 行跳过）
  const sum = filteredList.value.reduce((acc, r) => acc + (r.current_pnl_pct ?? 0), 0)
  return +sum.toFixed(2)
})
const totalProfitStr = computed(() => `${totalProfit.value >= 0 ? '+' : ''}${totalProfit.value.toFixed(2)}%`)

/** 当前胜率（D11）：current_price > bsp_price 计胜；两者任一缺失的行不计入分母 */
const winCount = computed(() =>
  filteredList.value.filter((r) => r.current_price != null && r.bsp_price != null && r.current_price > r.bsp_price).length,
)
const winTotal = computed(() =>
  filteredList.value.filter((r) => r.current_price != null && r.bsp_price != null).length,
)
const winRate = computed(() => {
  if (winTotal.value === 0) return 0
  return +((winCount.value / winTotal.value) * 100).toFixed(1)
})
const winRateStr = computed(() => `${winRate.value.toFixed(1)}%`)

/** 涨幅最大（D11）：当日涨跌幅（change_pct）最高值，含标的与级别 */
const maxChange = computed<MonitorItem | null>(() => {
  const rows = filteredList.value.filter((r) => r.change_pct != null)
  if (rows.length === 0) return null
  return rows.reduce((best, r) => (r.change_pct > best.change_pct ? r : best))
})
const maxChangeStr = computed(() =>
  maxChange.value ? `${maxChange.value.change_pct >= 0 ? '+' : ''}${maxChange.value.change_pct.toFixed(2)}%` : '--',
)

// ---- 已完成统计（改名 c 前缀，与监控中 D11 统计区分；D14：消费来源过滤后列表） ----
const cWinRate = computed(() => {
  const list = filteredCompletedList.value
  if (list.length === 0) return 0
  const wins = list.filter((r) => r.profit > 0).length
  return +((wins / list.length) * 100).toFixed(1)
})
const cWinRateStr = computed(() => `${cWinRate.value.toFixed(1)}%`)

const avgProfit = computed(() => {
  const list = filteredCompletedList.value
  if (list.length === 0) return 0
  const sum = list.reduce((acc, r) => acc + r.profit, 0)
  return +(sum / list.length).toFixed(2)
})
const avgProfitStr = computed(() => `${avgProfit.value >= 0 ? '+' : ''}${avgProfit.value.toFixed(2)}%`)

const profitRatio = computed(() => {
  const list = filteredCompletedList.value
  const wins = list.filter((r) => r.profit > 0)
  const losses = list.filter((r) => r.profit < 0)
  if (wins.length === 0 || losses.length === 0) return wins.length / (losses.length || 1)
  const avgWin = wins.reduce((a, r) => a + r.profit, 0) / wins.length
  const avgLoss = Math.abs(losses.reduce((a, r) => a + r.profit, 0) / losses.length)
  return +(avgWin / (avgLoss || 1)).toFixed(2)
})
const profitRatioStr = computed(() => profitRatio.value.toFixed(2))

// ---- 失败原因汇总（profit < 5%）----
const lossItems = computed(() => {
  return completedList.value.filter((r) => r.profit < 5)
})

// ---- 待分析标的 ----
const pendingItems = computed(() => {
  return completedList.value.filter((r) => !r.ai_analyzed && r.profit < 5)
})

// ---------------------------------------------------------------------------
// 盈利走势（design D8：由监控中列表各标的收益率前端聚合，替换 mock 随机游走）
// ---------------------------------------------------------------------------
/** 汇总模式：按买卖点时间（收益计算起点）逐标的聚合的累计均值曲线；
 *  null 收益率行跳过不计入（backend 确认口径） */
const summarySeries = computed<{ date: string; value: number }[]>(() => {
  const rows = monitorList.value
    .filter((r) => r.current_pnl_pct != null && Number.isFinite(r.bsp_date))
    .slice()
    .sort((a, b) => a.bsp_date - b.bsp_date)
  if (rows.length === 0) return []
  const series: { date: string; value: number }[] = []
  let sum = 0
  rows.forEach((r, i) => {
    sum += r.current_pnl_pct as number
    const d = new Date(r.bsp_date)
    series.push({
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      value: +(sum / (i + 1)).toFixed(2),
    })
  })
  return series
})

const profitSeg = ref('summary')
const segItems = [
  { label: '汇总', value: 'summary' },
  { label: '单只', value: 'single' },
]

// ---- 单只标的走势（保留：基于买卖点价 → 当前价的收益率序列） ----
const singleStockId = ref<number | null>(null)
const singleStockSeries = computed(() => {
  if (!singleStockId.value) return []
  const row = monitorList.value.find((r) => r.id === singleStockId.value)
  if (!row) return []
  // 有真实收益率（current_pnl_pct）时以终点直连，否则用入场价平走容错
  const start = row.bsp_price
  const endPnl = row.current_pnl_pct
  const end = endPnl != null ? start * (1 + endPnl / 100) : (row.current_price ?? start)
  if (!start) return []
  const series: { date: string; value: number }[] = []
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000)
    const ratio = (13 - i) / 13
    const v = +(((start * (1 + ratio * ((end - start) / start))) - start) / start * 100).toFixed(2)
    series.push({
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      value: v,
    })
  }
  return series
})

// ---- 工具 ----
function fmtPrice(v: number | null | undefined) {
  // 后端 DuckDB 不可用时 current_price 等可为 null（design D5 容错）
  if (v == null) return '--'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
/** 百分比列容错格式化：null/undefined 显示 --（design D5）；signed=true 时带正负号 */
function fmtPct(v: number | null | undefined, signed = false) {
  if (v == null) return '--'
  const s = v.toFixed(2)
  return signed ? `${v >= 0 ? '+' : ''}${s}%` : `${s}%`
}
/** 买卖点时间（ms）→ YYYY-MM-DD HH:mm（design D8：收益计算起点） */
function fmtDateTime(ts: number | null | undefined) {
  if (ts == null) return '--'
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function fmtDate(ts: number | null | undefined) {
  if (ts == null) return '--'
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}-${day}`
}
function klLabel(k: string) {
  const m: Record<string, string> = { '30m': '30分钟', '60m': '60分钟', D: '日线', W: '周线', M: '月线' }
  return m[k] || k
}

function reasonCategory(item: CompletedItem): string {
  const t = item.attribution || ''
  if (/包含|逻辑|计算|中枢区间|端点/.test(t)) return '计算逻辑错误'
  return '缠论失效'
}
function reasonBadgeClass(item: CompletedItem) {
  return reasonCategory(item) === '计算逻辑错误' ? 'badge--info' : 'badge--warning'
}

// ---- 操作：手动结束监控 ----
const endingId = ref<number | null>(null)
async function onEnd(row: MonitorItem) {
  try {
    await ElMessageBox.confirm(`确认手动结束「${row.name}」的监控？`, '提示', {
      type: 'warning',
      confirmButtonText: '确认结束',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  endingId.value = row.id
  try {
    await endMonitor(row.id)
    monitorList.value = monitorList.value.filter((r) => r.id !== row.id)
    ElMessage.success('已结束监控')
  } finally {
    endingId.value = null
  }
}

// ---- 双击名称/编码跳转 K 线页（design D12：携带级别，对齐 BspView 的 period 映射） ----
// 监控周期词表（D4：D/W/M/30m/60m）→ K 线页 period 词表（1d/1w/1M/30m/60m）
const KL_TO_KLINE_PERIOD: Record<string, string> = {
  D: '1d',
  W: '1w',
  M: '1M',
  '30m': '30m',
  '60m': '60m',
}
const router = useRouter()

function onGoKline(row: { code: string; kl_type: string }) {
  const q: { code: string; period?: string } = { code: row.code }
  const period = row.kl_type ? KL_TO_KLINE_PERIOD[row.kl_type] : undefined
  if (period) q.period = period
  router.push({ name: 'kline', query: q })
}

// ---- 归因详情抽屉（design D6：状态随内容并入，SampleDrawer 复用） ----
const drawerVisible = ref(false)
const drawerItem = ref<CompletedItem | null>(null)

function onViewAttrDetail(row: CompletedItem) {
  drawerItem.value = row
  drawerVisible.value = true
}

// ---- AI 分析（design D5：真实归因对接；成功展示归因内容，失败展示明确错误） ----
const analyzingId = ref<number | null>(null)

/** 应用真实返回的归因结果（AttributionRecord[]）到标的行 */
function applyAttribution(row: CompletedItem, res: AnalyzeResult) {
  const evidences = (res.attribution || []).map((a) => a.evidence).filter(Boolean)
  if (evidences.length > 0) row.attribution = evidences.join('\n')
  row.ai_analyzed = true
}

async function onAnalyze(row: CompletedItem) {
  analyzingId.value = row.id
  try {
    const res = await analyzeMonitor(row.id)
    applyAttribution(row, res)
    ElMessage.success('归因分析完成')
    // 展示归因内容
    drawerItem.value = row
    drawerVisible.value = true
  } catch {
    // 失败（400 未配置/盈利≥5、调用失败 5xx）：明确错误文案由 client 拦截器按后端 detail 展示，不写占位结果
  } finally {
    analyzingId.value = null
  }
}

// ---- 批量分析（前端过滤：仅 pnl < 5% 可触发） ----
const batchAnalyzing = ref(false)
const batchProgress = ref(0)
async function onBatchAnalyze() {
  const targets = pendingItems.value
  if (targets.length === 0) {
    ElMessage.info('没有待分析的标的')
    return
  }
  batchAnalyzing.value = true
  batchProgress.value = 0
  let okCount = 0
  let failCount = 0
  try {
    for (let i = 0; i < targets.length; i++) {
      const row = targets[i]
      try {
        const res = await analyzeMonitor(row.id)
        applyAttribution(row, res)
        okCount++
      } catch {
        // 单条失败：错误文案由拦截器按 detail 提示，继续处理后续标的
        failCount++
      }
      batchProgress.value = Math.round(((i + 1) / targets.length) * 100)
    }
    if (failCount === 0) {
      ElMessage.success(`完成 ${okCount} 只标的的归因分析`)
    } else {
      ElMessage.warning(`归因完成 ${okCount} 只，失败 ${failCount} 只`)
    }
  } finally {
    batchAnalyzing.value = false
  }
}

// ---- 加载 ----
/** 按当前选中分组拉监控中列表（group_id 服务端过滤，monitor-group-change D3/D6） */
async function loadMonitorList() {
  loading.value = true
  try {
    const ml = await getMonitorList(undefined, toGroupParam(activeMonitorGroup.value))
    monitorList.value = ml
    statusItems[0].count = ml.length
    setTotal(ml.length)
  } finally {
    loading.value = false
  }
}

/** 按当前选中分组拉已完成列表（语义同上） */
async function loadCompletedList() {
  loading.value = true
  try {
    const cl = await getCompletedList(undefined, toGroupParam(activeCompletedGroup.value))
    completedList.value = cl
    completedCount.value = cl.length
    statusItems[1].count = cl.length
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    const [ml, cl] = await Promise.all([
      getMonitorList(undefined, toGroupParam(activeMonitorGroup.value)),
      getCompletedList(undefined, toGroupParam(activeCompletedGroup.value)),
    ])
    monitorList.value = ml
    completedList.value = cl
    completedCount.value = cl.length
    statusItems[0].count = ml.length
    statusItems[1].count = cl.length
    setTotal(ml.length)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // 分组树先于列表加载（列表带分组过滤参数依赖选中态，默认 'all' 不传参）；
  // 来源字典并行加载（D14，失败不阻塞列表）
  await loadMonitorGroups()
  void loadMonitorSources()
  await loadAll()
})

onBeforeUnmount(() => {
  mSearch.dispose()
  cSearch.dispose()
})
</script>

<style scoped>
.monitor-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2xl);           /* 24px — 统计卡/搜索/表格/图表之间更明确的层级间隔 */
  flex: 1;
}
/* ---- 分组树（monitor-group-change 任务组 4，对齐 WatchlistView 样式模式） ---- */
.group-create-btn {
  padding: 2px 6px;
}
.group-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.sidebar__group-label {
  display: flex;
  align-items: center;
}
.sidebar__group-label .spacer {
  flex: 1;
}
.group-del,
.group-edit {
  color: var(--text-disabled);
  width: 14px;
  height: 14px;
  margin-left: 2px;
  border-radius: var(--r-sm);
  flex-shrink: 0;
}
.group-edit:hover {
  color: var(--accent-hover);
  background: var(--accent-dim);
}
.group-del:hover {
  color: var(--rise);
  background: var(--rise-dim);
}
/* 拖拽分组时的视觉反馈（同 WatchlistView tree__drag） */
:deep(.group-drag .sortable-ghost) {
  opacity: 0.45;
  background: var(--accent-dim);
}
:deep(.group-drag .sortable-chosen) {
  background: var(--bg-surface-hover);
}
/* 顶部 tab（design D6）：显著位置整体切换内容区 */
.tabbar {
  display: flex;
  align-items: center;
  gap: var(--sp-md);
  margin-bottom: 0;             /* tabbar 不额外下移，靠 flex gap 统一控制 */
}
.stat-row {
  display: flex;
  gap: var(--sp-lg);
}
.stat-row > * {
  flex: 1;
}
/* 工具栏（搜索栏）：与上方统计卡增加额外呼吸间距 */
.toolbar {
  margin-top: var(--sp-sm);     /* +8px above — 统计卡 → 搜索栏视觉落差 */
  margin-bottom: var(--sp-sm);  /* +8px below — 搜索栏 → 表格视觉落差 */
}
.cell-stock {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
/* 来源列（strategy-signal-page 任务 6.1）：策略来源小号标签 + 缠论次要文本 */
.src-tag {
  display: inline-block;
  max-width: 100%;
  padding: 1px 6px;
  font-size: 10px;
  line-height: 16px;
  border-radius: var(--r-full);
  background: var(--accent-dim);
  color: var(--accent-hover);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.src-chan {
  font-size: 12px;
  color: var(--text-disabled);
}
.cell-stock .nm {
  color: var(--text-primary);
  font-size: 13px;
}
.cell-stock .cd {
  color: var(--text-disabled);
  font-size: 11px;
}
/* 双击跳转 K 线（design D12）：可交互提示 */
.cell-stock--link {
  cursor: pointer;
}
.cell-stock--link:hover .nm {
  text-decoration: underline;
}
.pager-wrap {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-md) var(--sp-lg);
}
.single-stock-toolbar {
  position: absolute;
  top: 10px;
  right: 14px;
  z-index: 10;
}
/* 搜索候选下拉项（D7：对齐 K 线页 code + 名称插槽） */
.code-field {
  width: 240px;
}
.code-field :deep(.el-autocomplete) {
  width: 100%;
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
.progress-hint {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 360px;
}
.progress-hint .lbl {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.progress-hint .progress {
  flex: 1;
}
.sum-list {
  padding: 4px 0;
}
.sum-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px var(--sp-lg);
  border-bottom: 1px solid var(--border-base);
}
.sum-item:last-child {
  border-bottom: none;
}
.sum-item .reason {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
.sum-item .reason .t {
  font-size: 13px;
  color: var(--text-primary);
}
.sum-item .reason .s {
  font-size: 11px;
  color: var(--text-disabled);
}
</style>

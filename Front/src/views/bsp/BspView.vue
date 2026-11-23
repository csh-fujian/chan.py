<template>
  <div class="page-layout">
    <!-- 左侧菜单栏 -->
    <aside class="panel sidebar reveal reveal--1">
      <div class="sidebar__head">
        买卖点
        <span class="spacer"></span>
      </div>
      <div class="tree">
        <div class="sidebar__group">
          <div class="sidebar__group-label">方向</div>
          <div
            class="tree__item"
            :class="{ 'is-active': query.direction === '' }"
            @click="setDirection('')"
          >
            <el-icon class="tree__icon"><TrendCharts /></el-icon>
            <span>全部方向</span>
            <span class="count">{{ stats.total }}</span>
          </div>
          <div
            class="tree__item"
            :class="{ 'is-active': query.direction === 'buy' }"
            @click="setDirection('buy')"
          >
            <el-icon class="tree__icon"><Top /></el-icon>
            <span>买点</span>
            <span class="count">{{ stats.buy }}</span>
          </div>
          <div
            class="tree__item"
            :class="{ 'is-active': query.direction === 'sell' }"
            @click="setDirection('sell')"
          >
            <el-icon class="tree__icon"><Bottom /></el-icon>
            <span>卖点</span>
            <span class="count">{{ stats.sell }}</span>
          </div>
        </div>
        <div class="sidebar__group">
          <div class="sidebar__group-label">周期</div>
          <div
            v-for="kl in klOptions"
            :key="kl.value"
            class="tree__item"
            :class="{ 'is-active': query.kl_type === kl.value }"
            @click="setKlType(kl.value)"
          >
            <el-icon class="tree__icon"><Calendar /></el-icon>
            <span>{{ kl.label }}</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <div class="bsp-page">
        <!-- 查询筛选区：股票搜索（模糊下拉选 code）| 周期 | 日期 | 买卖点类型 | 方向 -->
        <div class="toolbar reveal reveal--1">
          <!-- 股票搜索（最前）：输入模糊匹配下拉，选中后锁定精确 code，点「查询」才触发 -->
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
          <el-select v-model="query.kl_type" placeholder="周期" style="width: 110px" @change="onQueryChange">
            <el-option v-for="kl in klOptions" :key="kl.value" :label="kl.label" :value="kl.value" />
          </el-select>
          <!-- 日期范围条件（D7/D9）：默认最近三个交易日；双端齐备按闭区间过滤，清空后恢复全期 -->
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
          <el-select v-model="query.bsp_type" placeholder="买卖点类型" style="width: 130px" @change="onQueryChange">
            <el-option label="全部类型" value="" />
            <el-option v-for="t in ALL_BSP_LABELS" :key="t" :label="t" :value="t" />
            <!-- 介入点伪类型（chan-entry-point-candidate 5.3）：值直传后端伪类型参数 -->
            <el-option v-for="o in ENTRY_PSEUDO_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <!-- 级别条件（bsp-page-level-filter-and-batch-monitor D2/D3）：确认阶梯级别单选，
               选项按判定顺序 L4 > L3 > L1 > L2；无「未定级」——存量行按 is_sure 兜底后必为 L4 或 L2 -->
          <el-select v-model="query.ladder" placeholder="级别" style="width: 130px" @change="onQueryChange">
            <el-option label="全部级别" value="" />
            <el-option v-for="l in ladderOptions" :key="l.value" :label="l.label" :value="l.value" />
          </el-select>
          <el-select v-model="query.direction" placeholder="方向" style="width: 100px" @change="onQueryChange">
            <el-option label="全部方向" value="" />
            <el-option label="买" value="buy" />
            <el-option label="卖" value="sell" />
          </el-select>
          <!-- 确认状态筛选（bsp-sure-annotation D4）：默认全部=不传参数；选择后带 sure 参数请求并重置分页 -->
          <el-select v-model="query.sure" placeholder="确认状态" style="width: 110px" @change="onQueryChange">
            <el-option label="全部状态" value="" />
            <el-option label="已确认" value="confirmed" />
            <el-option label="未确认" value="preview" />
          </el-select>
          <button class="btn btn--primary" @click="onQuery">查询</button>
          <button class="btn btn--default" @click="onReset">重置</button>
        </div>

        <!-- 操作工具条 -->
        <div class="toolbar reveal reveal--2">
          <span class="text-secondary" style="font-size: 12px">
            已选 <span class="num">{{ selectedCount }}</span> 项
          </span>
          <span class="spacer"></span>
          <button class="btn btn--default" :disabled="!hasSelected" @click="onBatchWatchlist">
            批量加入自选
          </button>
          <button class="btn btn--default" :disabled="!hasSelected" @click="onBatchMonitor">
            加入监控
          </button>
        </div>

        <!-- 结果区 -->
        <div class="panel reveal reveal--3">
          <el-tabs v-model="activeTab" class="bsp-tabs">
            <el-tab-pane label="结果列表" name="list">
              <div class="tbl-wrap" v-loading="loading">
                <el-table
                  ref="bspTableRef"
                  :data="records"
                  empty-text="暂无买卖点记录"
                  @selection-change="onSelectionChange"
                  @row-dblclick="onRowDblClick"
                  row-key="id"
                >
                  <el-table-column type="selection" width="44" reserve-selection />
                  <el-table-column label="方向" width="70">
                    <template #default="{ row }">
                      <el-tag :type="row.direction === 'sell' ? 'danger' : 'success'" size="small">
                        {{ row.direction === 'sell' ? '卖' : '买' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="编码" width="110">
                    <template #default="{ row }">
                      <span class="mono">{{ row.code }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="名称" width="100">
                    <template #default="{ row }">
                      <span>{{ row.name }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="股价" width="100" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ formatPrice(row.current_price) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="涨跌幅" width="95" align="right">
                    <template #default="{ row }">
                      <ChangeBadge :value="row.change_pct" />
                    </template>
                  </el-table-column>
                  <el-table-column label="行业" min-width="160">
                    <template #default="{ row }">
                      <IndustryBadges :industries="row.industries" />
                    </template>
                  </el-table-column>
                  <el-table-column label="买卖点类型" width="110">
                    <template #default="{ row }">
                      <div class="bsp-type-cell">
                        <span class="badge" :class="row.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
                          {{ bspLabel(row.bsp_type, row.direction === 'buy') }}{{ row.entry_point ? '·介' : '' }}
                        </span>
                        <!-- 未确认标注（bsp-sure-annotation D4）：灰色弱化，确认行无标签，避免与方向色冲突 -->
                        <el-tag v-if="row.is_sure === false" type="info" size="small" class="sure-tag">未确认</el-tag>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="级别" width="100">
                    <template #default="{ row }">
                      <!-- 级别列（chan-bsp-ladder-change）：L4 单徽章；
                           三轴组合值按轴并列徽章（进度/佐证/分型各至多一个）；
                           NULL 显示「未定级」。各徽章 hover 展示轴名与说明。
                           轴名与档名已改为白话（chan-bsp-grading），不再是
                           「判据链进度 · 后半链」这类内部术语。 -->
                      <template v-if="ladderInfosOf(row).length">
                        <el-tooltip
                          v-for="info in ladderInfosOf(row)"
                          :key="info.level"
                          :content="`${info.axis} · ${info.name} — ${info.desc}`"
                          placement="top"
                          :show-after="200"
                        >
                          <span class="badge ladder-badge" :class="ladderBadgeClass(info)">
                            {{ info.level }}
                          </span>
                        </el-tooltip>
                      </template>
                      <span v-else class="badge badge--default">未定级</span>
                    </template>
                  </el-table-column>
                  <!-- 证据强度（chan-bsp-grading）：内部编号看不懂，这一列给
                       用户可直接比较的分数与操作建议。已确认的固定 100 分。 -->
                  <el-table-column label="证据强度" width="112">
                    <template #default="{ row }">
                      <el-tooltip
                        v-if="row.grade"
                        placement="top"
                        :show-after="200"
                        :content="gradeTooltip(row)"
                      >
                        <span class="grade-cell" :class="`is-${gradeTone(row.grade.score)}`">
                          <span class="grade-cell__num mono">{{ row.grade.score }}</span>
                          <span class="grade-cell__qual">{{ row.grade.grade }}</span>
                        </span>
                      </el-tooltip>
                      <span v-else class="grade-cell is-none">未评估</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="买卖点价格" width="120" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ formatPrice(row.bsp_price) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="当前价格" width="100" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ formatPrice(row.current_price) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="买卖点时间" width="140">
                    <template #default="{ row }">
                      <span class="num">{{ formatBspTime(row) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="周期" width="90">
                    <template #default="{ row }">
                      <span class="num">{{ klLabel(row.kl_type) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="150" align="right">
                    <template #default="{ row }">
                      <button class="row-action" @click="openNesting(row)">区间套</button>
                      <button class="row-action" @click="openMonitorDialog(row)">加入监控</button>
                    </template>
                  </el-table-column>
                  <template #empty>
                    <EmptyState description="暂无买卖点记录，请调整查询条件" />
                  </template>
                </el-table>
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
            </el-tab-pane>

            <el-tab-pane label="板块聚合" name="sector">
              <div class="tbl-wrap" v-loading="aggLoading">
                <el-table :data="aggregate" empty-text="暂无聚合数据">
                  <el-table-column label="行业" min-width="160">
                    <template #default="{ row }">
                      <span class="badge badge--default">{{ row.industry }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="买点股票数" width="140" align="right">
                    <template #default="{ row }">
                      <span class="num text-rise">{{ row.buy_count }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="卖点股票数" width="140" align="right">
                    <template #default="{ row }">
                      <span class="num text-fall">{{ row.sell_count }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="合计" width="120" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ row.total }}</span>
                    </template>
                  </el-table-column>
                  <template #empty>
                    <EmptyState description="暂无板块聚合数据" />
                  </template>
                </el-table>
              </div>
            </el-tab-pane>

            <!-- 形态信号独立 Tab（chan-pattern-buy-signal 任务 5.4，方案 B）：
                 独立数据源与独立查询条件，不与缠论买卖点列表共用行与去重口径 -->
            <el-tab-pane label="形态信号" name="pattern">
              <div class="pattern-toolbar">
                <el-select
                  v-model="patternDirection"
                  style="width: 100px"
                  @change="onPatternQueryChange"
                >
                  <el-option label="买+卖" value="" />
                  <el-option label="买点形态" value="buy" />
                  <el-option label="卖点形态" value="sell" />
                </el-select>
                <el-select
                  v-model="patternQuery.pattern_type"
                  placeholder="全部形态"
                  clearable
                  style="width: 160px"
                  @change="onPatternQueryChange"
                >
                  <el-option
                    v-for="t in filteredPatternTypes"
                    :key="t.value"
                    :label="t.label"
                    :value="t.value"
                  />
                </el-select>
                <el-select
                  v-model="patternQuery.kl_type"
                  placeholder="全部周期"
                  clearable
                  style="width: 110px"
                  @change="onPatternQueryChange"
                >
                  <el-option label="日线" value="D" />
                  <el-option label="周线" value="W" />
                  <el-option label="月线" value="M" />
                  <el-option label="30分钟" value="30m" />
                  <el-option label="60分钟" value="60m" />
                </el-select>
                <el-date-picker
                  v-model="patternDateRange"
                  type="daterange"
                  range-separator="至"
                  start-placeholder="确认日期起"
                  end-placeholder="确认日期止"
                  value-format="YYYY-MM-DD"
                  style="width: 240px"
                  @change="onPatternQueryChange"
                />
                <el-select
                  v-model="patternInvalid"
                  style="width: 110px"
                  @change="onPatternQueryChange"
                >
                  <el-option label="全部状态" value="" />
                  <el-option label="仅有效" value="false" />
                  <el-option label="仅失效" value="true" />
                </el-select>
                <el-input-number
                  v-model="patternScoreMin"
                  :min="0"
                  :max="100"
                  placeholder="最低分"
                  controls-position="right"
                  style="width: 110px"
                  @change="onPatternQueryChange"
                />
                <button class="btn btn--ghost" @click="onPatternReset">重置</button>
                <span class="pattern-total">共 {{ patternTotal }} 条</span>
              </div>
              <div class="tbl-wrap" v-loading="patternLoading">
                <el-table
                  :data="patternRecords"
                  empty-text="暂无形态信号（需先在 K 线页或补算任务生成）"
                  @row-dblclick="onPatternRowDblClick"
                  row-key="rowKey"
                >
                  <el-table-column label="方向" width="70">
                    <template #default="{ row }">
                      <el-tag :type="row.direction === 'sell' ? 'danger' : 'success'" size="small">
                        {{ row.direction === 'sell' ? '卖' : '买' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="编码" width="110">
                    <template #default="{ row }">
                      <span class="mono">{{ row.code }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="名称" width="100">
                    <template #default="{ row }">
                      <span>{{ row.name }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="形态" width="150">
                    <template #default="{ row }">
                      <span class="badge badge--rise">{{ row.pattern_name }}</span>
                      <el-tag
                        v-if="row.is_new_signal"
                        :type="row.direction === 'sell' ? 'danger' : 'warning'"
                        size="small"
                        class="pattern-new-badge"
                      >
                        {{ row.direction === 'sell' ? '新卖点' : '新形态' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="周期" width="70">
                    <template #default="{ row }">{{ row.kl_type }}</template>
                  </el-table-column>
                  <el-table-column label="确认时间" width="160">
                    <template #default="{ row }">
                      <span class="mono">{{ row.confirm_time_key }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="确认价" width="100" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ formatPrice(row.price ?? 0) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="置信分" width="120">
                    <template #default="{ row }">
                      <template v-if="row.score !== null">
                        <span class="num" :class="row.score >= 80 ? 'text-rise' : ''">{{ row.score }}</span>
                        <span class="pattern-qual">{{ row.qual }}</span>
                      </template>
                      <span v-else class="pattern-qual">未评估</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="状态" width="90">
                    <template #default="{ row }">
                      <el-tag v-if="row.invalid" type="info" size="small">已失效</el-tag>
                      <el-tag v-else-if="row.veto_text" type="warning" size="small">否决</el-tag>
                      <el-tag v-else type="success" size="small">有效</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="90" fixed="right">
                    <template #default="{ row }">
                      <el-button link type="primary" size="small" @click.stop="openPatternDetail(row)">详情</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-pagination
                  layout="prev, pager, next, total"
                  :total="patternTotal"
                  :page-size="patternQuery.page_size"
                  :current-page="patternQuery.page"
                  @current-change="onPatternPageChange"
                  class="pattern-pagination"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </div>

    <!-- 区间套抽屉 -->
    <NestingDrawer
      v-model:visible="nestingVisible"
      :record="nestingRecord"
    />

    <!-- 形态信号详情弹窗（chan-pattern-buy-signal 任务 5.4）：
         注意事项 + 置信分明细 + 确认数据（spec「弹窗展示注意事项」） -->
    <el-dialog
      v-model="patternDetailVisible"
      :title="patternDetailTitle"
      width="560px"
      append-to-body
    >
      <template v-if="patternDetailRow">
        <div class="pattern-detail">
          <div class="pattern-detail__head">
            <el-tag :type="patternDetailRow.invalid ? 'info' : 'success'" size="small">
              {{ patternDetailRow.invalid ? '已失效' : patternDetailRow.veto_text ? '否决' : '有效' }}
            </el-tag>
            <span class="mono">{{ patternDetailRow.confirm_time_key }}</span>
            <span class="num">{{ formatPrice(patternDetailRow.price ?? 0) }}</span>
            <span class="pattern-detail__score">
              置信分
              <b :class="patternDetailRow.score !== null && patternDetailRow.score >= 80 ? 'text-rise' : ''">
                {{ patternDetailRow.score !== null ? patternDetailRow.score : '未评估' }}
              </b>
              <span v-if="patternDetailRow.qual" class="pattern-qual">· {{ patternDetailRow.qual }}</span>
            </span>
          </div>

          <div v-if="patternDetailRow.veto_text" class="pattern-detail__veto">
            ⚠ {{ patternDetailRow.veto_text }}
          </div>

          <div class="pattern-detail__section">
            <h4>注意事项</h4>
            <ul>
              <li v-for="(c, i) in patternDetailRow.cautions" :key="i">{{ c }}</li>
            </ul>
          </div>

          <div class="pattern-detail__section">
            <h4>置信分构成（市场逻辑 → 评分项）</h4>
            <template v-for="(axis, key) in patternDetailRow.scoring" :key="key">
              <div class="pattern-detail__axis">
                <span class="pattern-detail__axis-name">{{ patternAxisName(String(key)) }}</span>
              </div>
              <ul>
                <li v-for="(s, i) in axis" :key="i">{{ s.item }}（权重 {{ s.weight }}）</li>
              </ul>
            </template>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 批量加入自选弹窗 -->
    <el-dialog v-model="watchlistDialogVisible" title="批量加入自选" width="420px" append-to-body>
      <div class="add-dialog-body">
        <div class="form-row">
          <label>目标文件夹</label>
          <el-select v-model="watchlistFolderId" placeholder="选择文件夹" style="width: 100%">
            <el-option v-for="f in watchFolders" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </div>
        <p class="dialog-hint">
          选中的 {{ selectedCount }} 只股票将按 code 去重后加入目标文件夹。
        </p>
      </div>
      <template #footer>
        <el-button @click="watchlistDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="addingWatch" @click="confirmBatchWatchlist">确认加入</el-button>
      </template>
    </el-dialog>

    <!-- 行级加入监控弹窗（design D8 修订，任务 4.5）：
         只读上下文（股票/周期/买卖点价格）+ 买点时间（默认 = 该行买卖点时间，
         可编辑，「此刻」按钮取当前时间），提交 POST /api/monitor -->
    <el-dialog v-model="monitorDialogVisible" title="加入监控" width="440px" append-to-body>
      <div class="add-dialog-body" v-if="monitorRow">
        <div class="monitor-ctx">
          <div class="form-row">
            <label>股票</label>
            <span class="ctx-value">
              {{ monitorRow.name }}
              <span class="mono ctx-code">{{ monitorRow.code }}</span>
            </span>
          </div>
          <div class="form-row">
            <label>周期</label>
            <span class="ctx-value">{{ klLabel(monitorRow.kl_type) }}</span>
          </div>
          <div class="form-row">
            <label>买卖点价格</label>
            <span class="ctx-value num" :class="{ 'price-stale': priceLoading }">
              {{ formatPrice(monitorPrice) }}
            </span>
          </div>
        </div>
        <div class="form-row">
          <label>买点时间</label>
          <div class="monitor-time-row">
            <el-date-picker
              v-model="monitorStartTime"
              type="datetime"
              value-format="YYYY-MM-DD HH:mm:ss"
              format="YYYY-MM-DD HH:mm:ss"
              placeholder="选择买点时间"
              clearable
              style="flex: 1"
              @change="onMonitorTimeChange"
            />
            <el-button @click="setMonitorTimeNow">此刻</el-button>
          </div>
        </div>
        <!-- 分组选择（monitor-group-change D5，任务 5.1）：可选，默认「未分组」；
             下拉尾部「新增分组」行内输入，成功即自动选中新组 -->
        <div class="form-row">
          <label>分组</label>
          <el-select
            v-model="monitorGroupId"
            placeholder="未分组"
            style="width: 100%"
            @visible-change="onGroupSelectVisible"
          >
            <el-option label="未分组" :value="null" />
            <el-option v-for="g in monitorGroups" :key="g.id" :label="g.name" :value="g.id" />
            <template #footer>
              <div v-if="!groupCreating" class="group-add-entry" @click="groupCreating = true">
                <el-icon><Plus /></el-icon>
                <span>新增分组</span>
              </div>
              <div v-else class="group-add-form">
                <el-input
                  v-model="newGroupName"
                  size="small"
                  placeholder="输入分组名"
                  maxlength="20"
                  @keyup.enter="onCreateGroup"
                />
                <el-button size="small" :loading="groupSaving" @click="onCreateGroup">确定</el-button>
              </div>
            </template>
          </el-select>
        </div>
        <p class="dialog-hint">
          提交后将以所选买点时间对应的股票价格作为入场价，自买点时间起对该股票进行监控。
        </p>
      </div>
      <template #footer>
        <el-button @click="monitorDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="addingMonitor" @click="confirmAddMonitor">确认加入</el-button>
      </template>
    </el-dialog>

    <!-- 批量加入监控弹窗（bsp-page-level-filter-and-batch-monitor D7）：
         分组（本次提交的唯一统一参数，含下拉尾部行内新建）+ 只读目标清单。
         与行级弹窗分叉而非复用：行级有可编辑买点时间与价格联动，批量是只读清单，
         字段与状态差异较大，按 mode 合并反而更难读（design D7）。
         清单含方向列，让「不拦截卖点行」这一决定可自查 -->
    <el-dialog
      v-model="batchMonitorVisible"
      :title="batchMonitorTitle"
      width="760px"
      append-to-body
    >
      <div class="add-dialog-body" v-loading="batchSubmitting">
        <!-- 分组选择：复用行级弹窗的设施（getMonitorGroups / createMonitorGroup + 行内新建） -->
        <div class="form-row">
          <label>分组</label>
          <el-select
            v-model="monitorGroupId"
            placeholder="未分组"
            style="width: 100%"
            @visible-change="onGroupSelectVisible"
          >
            <el-option label="未分组" :value="null" />
            <el-option v-for="g in monitorGroups" :key="g.id" :label="g.name" :value="g.id" />
            <template #footer>
              <div v-if="!groupCreating" class="group-add-entry" @click="groupCreating = true">
                <el-icon><Plus /></el-icon>
                <span>新增分组</span>
              </div>
              <div v-else class="group-add-form">
                <el-input
                  v-model="newGroupName"
                  size="small"
                  placeholder="输入分组名"
                  maxlength="20"
                  @keyup.enter="onCreateGroup"
                />
                <el-button size="small" :loading="groupSaving" @click="onCreateGroup">确定</el-button>
              </div>
            </template>
          </el-select>
        </div>
        <p class="dialog-hint">{{ batchDedupeHint }}</p>
        <!-- 只读目标清单：无任何可编辑控件，仅用于提交前核对 -->
        <el-table :data="batchTargets" size="small" max-height="320" empty-text="无可提交记录">
          <el-table-column label="编码" width="106">
            <template #default="{ row }"><span class="mono">{{ row.code }}</span></template>
          </el-table-column>
          <el-table-column label="名称" width="92" prop="name" />
          <el-table-column label="周期" width="72">
            <template #default="{ row }">{{ klLabel(row.kl_type) }}</template>
          </el-table-column>
          <el-table-column label="买卖点时间" min-width="164">
            <template #default="{ row }">
              <span class="mono">{{ toDateTimeStr(row.bsp_date) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="买卖点价格" width="102" align="right">
            <template #default="{ row }">
              <span class="num">{{ formatPrice(row.bsp_price) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="方向" width="72">
            <template #default="{ row }">
              <span class="badge" :class="row.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
                {{ row.direction === 'buy' ? '买点' : '卖点' }}
              </span>
            </template>
          </el-table-column>
        </el-table>
        <p class="dialog-hint">
          每条以其自身周期与买卖点时间创建监控，入场价取该时间点的收盘价（取不到时回退买卖点价格并计入失败）。
        </p>
      </div>
      <template #footer>
        <el-button :disabled="batchSubmitting" @click="batchMonitorVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="batchSubmitting"
          :disabled="batchSubmitting || !batchTargets.length"
          @click="confirmBatchMonitor"
        >
          确认加入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 买卖点页。
 * 页面缓存（design.md D10，2026-10-20 修订）：纳入 AppShell KeepAlive 白名单——
 * 切走再切回保留筛选条件 / 分页 / 滚动位置与列表内容，不重挂载。
 * 缓存复活经 onActivated 静默刷新数据（列表与板块聚合），保留「回到页面看到最新买卖点」
 * 的原有语义，但不重置查询条件、不置 loading（避免缓存内容被骨架替换而闪烁）。
 */
defineOptions({ name: 'BspView' })

import { ref, reactive, computed, onMounted, onActivated, onBeforeUnmount, watch } from 'vue'
import type { AutocompleteInstance, TableInstance } from 'element-plus'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { TrendCharts, Top, Bottom, Calendar, Search, Plus } from '@element-plus/icons-vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import ChangeBadge from '@/components/ui/ChangeBadge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import NestingDrawer from './NestingDrawer.vue'
import { getBspList, getBspAggregate, getPriceAt, type BspQuery } from '@/api/modules/bsp'
import { getPatternList, getPatternTypes, type PatternRecord, type PatternTypeItem } from '@/api/modules/pattern'
import { getFolders, addStock, type WatchFolder } from '@/api/modules/watchlist'
import { createMonitor, getMonitorGroups, createMonitorGroup, type MonitorGroup } from '@/api/modules/monitor'
import { searchStocks } from '@/api/modules/stock'
import { ALL_BSP_LABELS, bspLabel, ENTRY_PSEUDO_OPTIONS } from '@/utils/bsp'
import { ladderInfos, ladderPosition, gradeTone, parseLadder, type LadderInfo } from '@/utils/bspLadder'
import type { BspRecord, BspAggregate } from '@/api/types'

// 周期词表（design D1）：30分 → 60分 → 日线 → 周线 → 月线，无 1/5/15 分钟
// 单一数组同时驱动左侧周期列表与工具栏下拉，改一处两边同步
const klOptions = [
  { label: '30分', value: '30m' },
  { label: '60分', value: '60m' },
  { label: '日线', value: 'D' },
  { label: '周线', value: 'W' },
  { label: '月线', value: 'M' },
]

function klLabel(v: string) {
  return klOptions.find((k) => k.value === v)?.label || v
}

// ---- 级别筛选下拉（bsp-page-level-filter-and-batch-monitor D2/D3）----
// 选项按确认阶梯的判定顺序 L4 > L3 > L1 > L2（与表格级别列语义排序一致，非数值序）；
// 文案用短标签以适配 130px 下拉宽度（对齐「买卖点类型」），全称与仓位指引仍在级别列 tooltip。
// 无「未定级」选项：存量行经 is_sure 兜底映射后必为 L4 或 L2，不存在未定级桶（design D2）。
const ladderOptions = [
  { value: 'L4', label: 'L4 确认买卖点' },
  { value: 'L3', label: 'L3 背驰预警' },
  { value: 'L1', label: 'L1 区间套' },
  { value: 'L2', label: 'L2 虚笔候选' },
]

// ---- 级别列（bsp-ladder-change 4.2）：徽章色 + hover 说明文案 ----
/** 徽章样式：L4 实色 badge--rise / L3 warning / L1 info / L2（及缺省）弱化 default */
function ladderBadgeClass(info: LadderInfo): string {
  // 按轴分色系（chan-bsp-ladder-change）：确认实色、进度 info、佐证 success、分型 warning
  switch (info.kind) {
    case 'confirmed': return 'badge--rise'
    case 'progress': return 'badge--info'
    case 'corroboration': return 'badge--success'
    case 'fractal': return 'badge--warning'
    default: return 'badge--default'
  }
}
/** 级别定义查询：组合串逐档展开（非法值返回空数组，模板兜底「未定级」） */
function ladderInfosOf(row: BspRecord): LadderInfo[] {
  return ladderInfos(row.ladder)
}
/** hover 说明：已由模板内逐徽章描述取代（三轴各自说明），保留供其他调用方复用 */
function ladderTooltip(row: BspRecord): string {
  const infos = ladderInfosOf(row)
  if (!infos.length) return ''
  const pos = ladderPosition(parseLadder(row.ladder), row.direction === 'buy')
  return `${infos.map((i) => `${i.axis}:${i.name}`).join(' · ')} · ${pos}`
}

/**
 * 证据强度列的 hover 说明（chan-bsp-grading）。
 *
 * 表格里只有「85 较强」这种缩写，用户需要知道**为什么**是这个分、
 * 以及未成立时**卡在哪一步**。这些文案全部来自后端 `grade`，前端不重复推导。
 */
function gradeTooltip(row: BspRecord): string {
  const g = row.grade
  if (!g) return '未评估'
  const lines = [`${g.score} 分 · ${g.grade}`, g.advice]
  // 「卡在」只配被判据拦下的点；判据全过只欠确认的点，那句话本身就是进度说明
  if (g.blocked_by) lines.push(g.score >= 60 ? g.blocked_by : `卡在：${g.blocked_by}`)
  if (g.disclaimer) lines.push(g.disclaimer)
  return lines.join('\n')
}

// ---- 查询 ----
// 日期范围默认值 = 最近三个交易日（design D9）：前端跳周末近似（节假日不跳，范围过滤语义下可接受）
// date_to = 今天，date_from = 自今天向前数第 3 个工作日（周内）
function recentThreeWorkdays(): [string, string] {
  const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const to = new Date()
  let n = 0
  let cur = new Date(to)
  // 向前找 2 个更早的工作日（含今天共 3 个工作日）
  while (n < 2) {
    cur = new Date(cur.getFullYear(), cur.getMonth(), cur.getDate() - 1)
    if (cur.getDay() !== 0 && cur.getDay() !== 6) n++
  }
  return [fmt(cur), fmt(to)]
}

const query = reactive<BspQuery>({
  page: 1,
  page_size: 20,
  keyword: '',
  bsp_type: '',
  direction: '',
  kl_type: '',
  date_from: '',
  date_to: '',
  // 确认状态（bsp-sure-annotation D4）：'' = 全部（不传参数），confirmed/preview 透传后端 sure 过滤
  sure: '',
  // 级别条件（bsp-page-level-filter-and-batch-monitor D1）：'' = 全部级别（不传参数）
  ladder: '',
})

// 日期范围控件本地状态（daterange 绑定 [start, end]，空为 null）
const dateRange = ref<[string, string] | null>(recentThreeWorkdays())

// 发请求前把 dateRange 同步进 query（null/空时两端都置 ''，即不过滤）
function syncDateRangeToQuery() {
  query.date_from = dateRange.value?.[0] || ''
  query.date_to = dateRange.value?.[1] || ''
}
syncDateRangeToQuery()

const activeTab = ref<'list' | 'sector' | 'pattern'>('list')

// 形态 Tab 懒加载：首次切入时拉数据（onMounted 已预拉，这里兜底）
watch(activeTab, (t) => {
  if (t === 'pattern' && patternRecords.value.length === 0 && !patternLoading.value) {
    loadPatternList()
  }
})

// ---------------------------------------------------------------------------
// 形态信号 Tab（chan-pattern-buy-signal 任务 5.4）：独立数据源与独立查询条件
// ---------------------------------------------------------------------------

const patternTypes = ref<PatternTypeItem[]>([])
const patternRecords = ref<(PatternRecord & { rowKey: string; pattern_name: string })[]>([])
const patternTotal = ref(0)
const patternLoading = ref(false)
const patternDateRange = ref<[string, string] | null>(null)
const patternInvalid = ref('')
const patternScoreMin = ref<number | undefined>(undefined)
const patternQuery = reactive({
  page: 1,
  page_size: 50,
  pattern_type: '',
  kl_type: '',
})
/** 方向筛选（sell-signal 任务 3.4）：'' 买+卖 / 'buy' / 'sell'；
 *  卖向由后端默认收敛到关注范围（自选 ∪ 监控），前端无需再过滤 */
const patternDirection = ref('')
/** 「新信号」时效窗口（与后端 PATTERN_NEW_BARS 同步的展示判定）：
 *  确认时间在最近 M 个自然日内（日线近似）即视为新信号 */
const PATTERN_NEW_DAYS = 7

/** 形态详情弹窗状态 */
const patternDetailVisible = ref(false)
const patternDetailRow = ref<(PatternRecord & { pattern_name: string }) | null>(null)
const patternDetailTitle = computed(() =>
  patternDetailRow.value
    ? `${patternDetailRow.value.pattern_name} — ${patternDetailRow.value.name}（${patternDetailRow.value.code}）`
    : '形态信号详情',
)

/** 三轴名白话（评分项分组标题） */
function patternAxisName(key: string): string {
  return key === 'struct' ? '结构轴' : key === 'vol' ? '量能轴' : key === 'position' ? '位置轴' : '确认轴'
}

/** 形态下拉按当前方向过滤（'' 时全量） */
const filteredPatternTypes = computed(() =>
  patternDirection.value
    ? patternTypes.value.filter((t) => (t.direction ?? 'buy') === patternDirection.value)
    : patternTypes.value,
)

async function loadPatternTypes() {
  try {
    patternTypes.value = await getPatternTypes()
  } catch {
    // 失败已由拦截器提示；下拉已选类型不在当前方向时一并清空
    if (
      patternQuery.pattern_type &&
      !filteredPatternTypes.value.some((t) => t.value === patternQuery.pattern_type)
    ) {
      patternQuery.pattern_type = ''
    }
  }
}

async function loadPatternList() {
  patternLoading.value = true
  try {
    const res = await getPatternList({
      page: patternQuery.page,
      page_size: patternQuery.page_size,
      pattern_type: patternQuery.pattern_type,
      kl_type: patternQuery.kl_type,
      date_from: patternDateRange.value?.[0] ?? null,
      date_to: patternDateRange.value?.[1] ?? null,
      invalid: patternInvalid.value,
      score_min: patternScoreMin.value ?? null,
      direction: patternDirection.value,
    })
    patternRecords.value = res.list.map((it) => ({
      ...it,
      rowKey: `${it.code}|${it.kl_type}|${it.autype}|${it.pattern_type}|${it.confirm_time_key}`,
      pattern_name: it.name || it.pattern_type,
      // 新信号徽标：确认时间在最近 M 日内且未失效（展示判定，后端 is_new 仅 K 线页用）
      is_new_signal:
        !it.invalid &&
        !!it.confirm_time_key &&
        (Date.now() - new Date(it.confirm_time_key.replace(' ', 'T')).getTime()) /
          86400000 <=
          PATTERN_NEW_DAYS,
    }))
    patternTotal.value = res.total
  } catch {
    // 失败已由拦截器提示
  } finally {
    patternLoading.value = false
  }
}

function onPatternQueryChange() {
  patternQuery.page = 1
  loadPatternList()
}

function onPatternPageChange(page: number) {
  patternQuery.page = page
  loadPatternList()
}

function onPatternReset() {
  patternQuery.pattern_type = ''
  patternQuery.kl_type = ''
  patternDirection.value = ''
  patternDateRange.value = null
  patternInvalid.value = ''
  patternScoreMin.value = undefined
  onPatternQueryChange()
}

/** 行点击 → 详情弹窗（注意事项 + 置信分明细） */
function openPatternDetail(row: PatternRecord & { pattern_name: string }) {
  patternDetailRow.value = row
  patternDetailVisible.value = true
}

/** 双击行 → 跳 K 线页（与买卖点列表同模式，KL_TO_KLINE_PERIOD 映射周期） */
function onPatternRowDblClick(row: PatternRecord & { pattern_name: string }) {
  const q: { code: string; period?: string } = { code: row.code }
  const m: Record<string, string> = { D: '1d', W: '1w', M: '1M', '30m': '30m', '60m': '60m' }
  const period = row.kl_type ? m[row.kl_type] : undefined
  if (period) q.period = period
  router.push({ name: 'kline', query: q })
}
const loading = ref(false)
const records = ref<BspRecord[]>([])
const total = ref(0)

// 统计（侧栏 count）
const stats = reactive({ total: 0, buy: 0, sell: 0 })

/**
 * 拉取列表 + 侧栏统计。
 * @param silent 静默刷新（页面缓存切回时用）：不置 loading、失败保留现有内容，
 *   避免缓存列表被骨架或清空替换。
 */
async function loadList(silent = false) {
  if (!silent) loading.value = true
  // 每次请求前同步日期范围（控件可能被用户改写/清空）
  syncDateRangeToQuery()
  try {
    const res = await getBspList(query)
    records.value = res.list
    total.value = res.total
    // 统计（侧栏 count）：buy/sell = 同一条件下（不含方向）按方向拆分的总数
    // total = buy + sell，确保三个统计值口径一致（不受当前 direction 筛选影响）
    const [buyRes, sellRes] = await Promise.all([
      getBspList({ ...query, page: 1, page_size: 1, direction: 'buy' }),
      getBspList({ ...query, page: 1, page_size: 1, direction: 'sell' }),
    ])
    stats.buy = buyRes.total
    stats.sell = sellRes.total
    stats.total = buyRes.total + sellRes.total
  } catch {
    // 静默刷新失败：保留缓存内容（下一轮激活或手动查询再重试）
    if (silent) return
    records.value = []
    total.value = 0
    stats.total = 0
    stats.buy = 0
    stats.sell = 0
  } finally {
    if (!silent) loading.value = false
  }
}

// 板块聚合
const aggLoading = ref(false)
const aggregate = ref<BspAggregate[]>([])
async function loadAggregate(silent = false) {
  if (!silent) aggLoading.value = true
  try {
    aggregate.value = await getBspAggregate()
  } catch {
    if (silent) return
    aggregate.value = []
  } finally {
    if (!silent) aggLoading.value = false
  }
}

// ---- 股票搜索（el-autocomplete：模糊下拉选 code，点「查询」才触发请求）----
interface StockSuggestion {
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与查询 */
  placeholder?: boolean
}
const acRef = ref<AutocompleteInstance | null>(null)
/** 输入框绑定值（自由文本）；选中候选后回填为精确 code */
const keywordInput = ref('')
/** 选中候选后的精确查询 code（'' = 未选中，查询退化为关键词模糊匹配） */
const selectedCode = ref('')

/** 远程模糊搜索候选（searchStocks 已含防抖语义，此处仅做空输入短路） */
async function queryStocks(q: string, cb: (items: StockSuggestion[]) => void) {
  const query = q.trim()
  if (!query) {
    cb([])
    return
  }
  try {
    const list = await searchStocks(query)
    if (!list.length) {
      cb([{ value: query, code: '', name: '无匹配候选', placeholder: true }])
      return
    }
    cb(list.map((s) => ({ value: s.code, code: s.code, name: s.name })))
  } catch {
    cb([])
  }
}

/** 点选候选：输入框回填精确 code，锁定 selectedCode（不触发查询） */
function onSelectSuggestion(item: StockSuggestion) {
  if (item.placeholder) return
  selectedCode.value = item.code
  keywordInput.value = item.code
  acRef.value?.close()
}

/** 手动清空/修改输入后，解除已锁定的精确 code（退回模糊语义） */
function onKeywordClear() {
  selectedCode.value = ''
}

// 点「查询」时才把搜索框内容同步进 query：
// 选中过候选 → 精确 code；否则用输入文本做关键词模糊匹配
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
  query.bsp_type = ''
  query.direction = ''
  query.kl_type = ''
  // 确认状态恢复默认：全部（不传参数）
  query.sure = ''
  // 级别恢复默认：全部级别（不传参数）
  query.ladder = ''
  // 日期范围恢复默认：最近三个交易日（spec「默认日期范围为最近三个交易日」）
  dateRange.value = recentThreeWorkdays()
  syncDateRangeToQuery()
  query.page = 1
  loadList()
}

function setDirection(d: 'buy' | 'sell' | '') {
  query.direction = d
  onQueryChange()
}
function setKlType(v: string) {
  query.kl_type = v
  onQueryChange()
}

// ---- 双击行跳转 K 线页（任务 4.3）----
// bsp 周期词表（D1：D/W/M/30m/60m）→ K 线页词表（1d/1w/1M/30m/60m），
// 30m/60m 两页同值；空周期（全部）不带 period，K 线页保持其默认日线
const KL_TO_KLINE_PERIOD: Record<string, string> = {
  D: '1d',
  W: '1w',
  M: '1M',
  '30m': '30m',
  '60m': '60m',
}
const router = useRouter()

function onRowDblClick(row: BspRecord) {
  const q: { code: string; period?: string } = { code: row.code }
  const period = row.kl_type ? KL_TO_KLINE_PERIOD[row.kl_type] : undefined
  if (period) q.period = period
  router.push({ name: 'kline', query: q })
}

// ---- 多选 ----
const selected = ref<BspRecord[]>([])
const selectedCount = ref(0)
const hasSelected = ref(false)
function onSelectionChange(rows: BspRecord[]) {
  selected.value = rows
  selectedCount.value = rows.length
  hasSelected.value = rows.length > 0
}

// ---- 区间套 ----
const nestingVisible = ref(false)
const nestingRecord = ref<BspRecord | null>(null)
function openNesting(row: BspRecord) {
  nestingRecord.value = row
  nestingVisible.value = true
}

// ---- 批量加入自选 ----
const watchlistDialogVisible = ref(false)
const watchlistFolderId = ref<number | null>(null)
const watchFolders = ref<WatchFolder[]>([])
const addingWatch = ref(false)

async function onBatchWatchlist() {
  if (!hasSelected.value) return
  try {
    watchFolders.value = await getFolders()
    watchlistFolderId.value = watchFolders.value[0]?.id ?? null
    watchlistDialogVisible.value = true
  } catch {
    // 失败已处理
  }
}

async function confirmBatchWatchlist() {
  if (!watchlistFolderId.value) {
    ElMessage.warning('请选择目标文件夹')
    return
  }
  addingWatch.value = true
  try {
    // 按 code 去重
    const codes = Array.from(new Set(selected.value.map((r) => r.code)))
    await Promise.all(codes.map((c) => addStock(watchlistFolderId.value!, c)))
    ElMessage.success(`已加入 ${codes.length} 只到自选`)
    watchlistDialogVisible.value = false
  } catch {
    // 失败已处理
  } finally {
    addingWatch.value = false
  }
}

// ---- 批量加入监控（bsp-page-level-filter-and-batch-monitor 任务组 4）----
// 按行参数提交（D5）：每条以自身 kl_type / bsp_date / 该时间点收盘价创建监控，
// 分组是唯一统一参数；按 (code, kl_type) 去重（D6）；串行提交、部分失败不中断、
// 成功后清空选择集（D8）。
const bspTableRef = ref<TableInstance | null>(null)
const batchMonitorVisible = ref(false)
const batchSubmitting = ref(false)
/** 去重后的待提交清单（弹窗只读清单的数据源） */
const batchTargets = ref<BspRecord[]>([])
/** 去重前的选中条数（用于「去重前 X → 去重后 Y」提示） */
const batchRawCount = ref(0)

/** 级别强度序（D6 次级裁决）：与判定顺序一致 L4 > L3 > L1 > L2；缺失/未定级最低 */
const LADDER_STRENGTH: Record<string, number> = { L4: 3, L3: 2, L1: 1, L2: 0 }

/**
 * 同 (code, kl_type) 两条记录谁更该保留（D6）：
 * 先比买卖点时间（新者胜），打平比级别强度，仍打平返回 false 保留先遇者
 * （bsp_date 由 time_key 转出，时间为 ms 级，故打平即 time_key 打平，取首即可）
 */
function preferTarget(a: BspRecord, b: BspRecord): boolean {
  if (a.bsp_date !== b.bsp_date) return a.bsp_date > b.bsp_date
  const sa = LADDER_STRENGTH[a.ladder ?? ''] ?? -1
  const sb = LADDER_STRENGTH[b.ladder ?? ''] ?? -1
  return sa > sb
}

/** 按（股票编码, 周期）去重（D6）：同一组合只保留一条 */
function dedupeTargets(rows: BspRecord[]): BspRecord[] {
  const best = new Map<string, BspRecord>()
  for (const r of rows) {
    const key = `${r.code}|${r.kl_type}`
    const cur = best.get(key)
    if (!cur || preferTarget(r, cur)) best.set(key, r)
  }
  return Array.from(best.values())
}

const batchMonitorTitle = computed(() => `批量加入监控（${batchTargets.value.length} 条）`)

/** 提交前告知去重前后数量（spec「同股同周期去重保留最新」） */
const batchDedupeHint = computed(() => {
  const before = batchRawCount.value
  const after = batchTargets.value.length
  if (before === after) {
    return `已选 ${before} 条，按（编码, 周期）去重后 ${after} 条 —— 无重复，全部提交。`
  }
  return `已选 ${before} 条，按（编码, 周期）去重后 ${after} 条（去重 ${before - after} 条，同一股票同一周期保留买卖点时间最新的一条）。`
})

/** 打开批量弹窗：选中集 → 去重清单；分组重置为「未分组」 */
function onBatchMonitor() {
  if (!hasSelected.value) return
  batchRawCount.value = selected.value.length
  batchTargets.value = dedupeTargets(selected.value)
  // 分组为本次提交的统一参数，每次打开都重置（与行级弹窗共用同一状态，两者不会同时打开）
  monitorGroupId.value = null
  groupCreating.value = false
  newGroupName.value = ''
  batchMonitorVisible.value = true
}

/**
 * 确认批量提交（D8）：逐条串行，单条失败不中断后续。
 * 每条按其自身周期与买卖点时间取价（D5），取价失败回退该行买卖点价格并计入失败。
 * 成功 = 建监控成功且取价成功；失败口径分为「取价失败（已回退价格）」「创建失败」。
 */
async function confirmBatchMonitor() {
  if (!batchTargets.value.length || batchSubmitting.value) return
  batchSubmitting.value = true
  let ok = 0
  let priceFallback = 0
  let createFail = 0
  try {
    for (const row of batchTargets.value) {
      const time = toDateTimeStr(row.bsp_date)
      // 取价：该股票在该行周期上不晚于买卖点时间的最近一根收盘价
      let entry = row.bsp_price
      let fellBack = false
      try {
        const r = await getPriceAt(row.code, row.kl_type, time)
        entry = r.price
      } catch {
        fellBack = true
      }
      try {
        await createMonitor({
          code: row.code,
          kl_type: row.kl_type,
          entry_price: entry,
          monitor_start_time: time,
          // 分组为统一参数；未分组（null）不传，后端写 NULL
          group_id: monitorGroupId.value ?? undefined,
          // 不传 source_type：沿用缺省来源 'chan'（与行级按钮一致）
        })
        if (fellBack) priceFallback++
        else ok++
      } catch {
        // 单条创建失败不中断后续（失败提示由 axios 拦截器逐条给出）
        createFail++
      }
    }
    const total = batchTargets.value.length
    const failed = priceFallback + createFail
    if (failed === 0) {
      ElMessage.success(`已加入监控 ${ok} 条`)
    } else {
      const reasons = [
        priceFallback ? `取价失败回退买卖点价格 ${priceFallback} 条` : '',
        createFail ? `创建失败 ${createFail} 条` : '',
      ]
        .filter(Boolean)
        .join('、')
      ElMessage.warning(`批量加入监控完成：成功 ${ok} 条，失败 ${failed} 条（${reasons}，共 ${total} 条）`)
    }
    batchMonitorVisible.value = false
    // 提交成功后清空选择集（D8）；clearSelection 会触发 selection-change，已选计数随之归零
    bspTableRef.value?.clearSelection()
  } finally {
    batchSubmitting.value = false
  }
}

// ---- 行级加入监控（design D8 修订 + D12 价格联动，任务 4.5/4.9）----
// 弹窗：股票/周期只读 + 买点时间（默认 = 该行买卖点时间，可编辑，「此刻」置当前时间）
// + 买卖点价格随买点时间联动（GET /bsp/price-at：所选时间点监控周期最近收盘价）；
// 提交 POST /api/monitor（entry_price = 联动后价格）。
// monitor_start_time 传 'YYYY-MM-DD HH:mm:ss'：monitor 表存 VARCHAR，
// 消费方（DuckDB time_key 字符串比较 / LLM prompt 文本）均兼容该格式。
const monitorDialogVisible = ref(false)
const monitorRow = ref<BspRecord | null>(null)
const monitorStartTime = ref<string>('')
const addingMonitor = ref(false)

// ---- 弹窗分组选择（monitor-group-change D5，任务 5.1）----
// 可选分组：默认「未分组」（null）；下拉尾部「新增分组」行内输入，
// 创建成功即自动选中新组；重名/非法由后端返回 detail（拦截器提示）
const monitorGroups = ref<MonitorGroup[]>([])
const monitorGroupId = ref<number | null>(null)
const groupCreating = ref(false)
const newGroupName = ref('')
const groupSaving = ref(false)

/** 下拉展开时拉分组列表（每次展开都刷新，与左侧栏管理入口保持数据一致） */
async function onGroupSelectVisible(visible: boolean) {
  if (!visible) return
  try {
    monitorGroups.value = await getMonitorGroups()
  } catch {
    // 失败已由拦截器提示；保留现有选项
  }
}

/** 行内新建分组：成功即自动选中新组（spec「弹窗内快速新建分组」） */
async function onCreateGroup() {
  const name = newGroupName.value.trim()
  if (!name) {
    ElMessage.warning('请输入分组名')
    return
  }
  groupSaving.value = true
  try {
    const g = await createMonitorGroup(name)
    monitorGroups.value = await getMonitorGroups()
    monitorGroupId.value = g.id
    newGroupName.value = ''
    groupCreating.value = false
  } catch {
    // 重名/非法：后端 detail 已由拦截器提示，保留输入供修改重试
  } finally {
    groupSaving.value = false
  }
}
// D12 价格联动：弹窗内显示与提交用的价格（初始 = 行买卖点价格，随时间变化更新）
const monitorPrice = ref<number>(0)
const priceLoading = ref(false)
let priceSeq = 0
let priceTimer: ReturnType<typeof setTimeout> | null = null

/** ms 时间戳 → 'YYYY-MM-DD HH:mm:ss'（含秒，与提交格式一致） */
function toDateTimeStr(ts: number) {
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 按买点时间取价（design D12）：失败/404 保留原价格并提示 */
async function fetchMonitorPrice(time: string) {
  const row = monitorRow.value
  if (!row || !time) return
  const seq = ++priceSeq
  priceLoading.value = true
  try {
    const r = await getPriceAt(row.code, row.kl_type, time)
    if (seq !== priceSeq) return // 过期响应丢弃
    monitorPrice.value = r.price
  } catch {
    if (seq !== priceSeq) return
    ElMessage.warning('所选时间无 K 线数据，保留原买卖点价格')
  } finally {
    if (seq === priceSeq) priceLoading.value = false
  }
}

/** 买点时间变化 → 300ms 防抖取价（design D12） */
function onMonitorTimeChange() {
  if (priceTimer) clearTimeout(priceTimer)
  if (!monitorStartTime.value) return
  priceTimer = setTimeout(() => fetchMonitorPrice(monitorStartTime.value), 300)
}

function openMonitorDialog(row: BspRecord) {
  monitorRow.value = row
  // 默认值 = 该行买卖点时间（bsp_date 为 ms 时间戳，已含时分秒）
  monitorStartTime.value = toDateTimeStr(row.bsp_date)
  monitorPrice.value = row.bsp_price
  // 分组选择重置为「未分组」（null）
  monitorGroupId.value = null
  groupCreating.value = false
  newGroupName.value = ''
  monitorDialogVisible.value = true
  // 默认时间也触发一次联动（语义统一：价格 = 所选时间点收盘价）
  fetchMonitorPrice(monitorStartTime.value)
}

/** 「此刻」按钮：买点时间置为当前时间（经 date-picker change 事件触发联动） */
function setMonitorTimeNow() {
  monitorStartTime.value = toDateTimeStr(Date.now())
  onMonitorTimeChange()
}

async function confirmAddMonitor() {
  const row = monitorRow.value
  if (!row) {
    console.warn('[confirmAddMonitor] 无上下文行，忽略提交', { dialogVisible: monitorDialogVisible.value })
    return
  }
  if (!monitorStartTime.value) {
    ElMessage.warning('请设置买点时间')
    return
  }
  addingMonitor.value = true
  try {
    await createMonitor({
      code: row.code,
      kl_type: row.kl_type,
      entry_price: monitorPrice.value, // D12：联动后的所选时间点价格
      monitor_start_time: monitorStartTime.value,
      // 分组归属（monitor-group-change D5）：未分组（null）不传，后端写 NULL
      group_id: monitorGroupId.value ?? undefined,
    })
    ElMessage.success(`已将「${row.name}」加入监控`)
    monitorDialogVisible.value = false
  } catch {
    // 失败已由 axios 拦截器统一 ElMessage.error（含后端 detail），此处仅保留弹窗供重试
  } finally {
    addingMonitor.value = false
  }
}

// ---- 工具 ----
function formatPrice(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function formatDate(ts: number) {
  const d = new Date(ts)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// ---- 买卖点时间格式化（design D10，任务 4.4）----
// bsp_date 是 ms 时间戳（后端已按 time_key 转出，携带时分秒）。
// 按行周期区分：分钟级（30m/60m）显示日期+时分；日线及以上（D/W/M）只显示日期
// （time_key 为 00:00，显示时分是冗余噪音）。与 NestingDrawer 共用同一语义。
const MINUTE_KL_TYPES = new Set(['30m', '60m'])
function formatBspTime(row: { bsp_date: number; kl_type: string }) {
  const d = new Date(row.bsp_date)
  const date = formatDate(row.bsp_date)
  if (!MINUTE_KL_TYPES.has(row.kl_type)) return date
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${date} ${hh}:${mm}`
}

// 首次挂载后首次 activated 与 onMounted 重复，跳过（见下方 onActivated）
let activatedOnce = false

onMounted(() => {
  loadList()
  loadAggregate()
  loadPatternTypes()
  loadPatternList()
})

// 页面缓存（design.md D10，2026-10-20 修订）：首次挂载走 onMounted；切走后再切回只触发
// onActivated（onMounted 不再执行）。此时静默刷新列表与板块聚合——保留筛选条件/分页与
// 已渲染内容，只把数据更新到最新（与未缓存时「切回重拉」语义一致，但无骨架闪烁）。
onActivated(() => {
  // 仅缓存复活触发（首次挂载后紧跟的 activated 由 onMounted 已覆盖，不重复拉）
  if (!activatedOnce) {
    activatedOnce = true
    return
  }
  loadList(true)
  loadAggregate(true)
})

// 卸载清理防抖定时器（缓存页亦可能在 AppShell 卸载时销毁，如登出）
onBeforeUnmount(() => {
  if (priceTimer) {
    clearTimeout(priceTimer)
    priceTimer = null
  }
})
</script>

<style scoped>
/* 形态信号 Tab（chan-pattern-buy-signal 任务 5.4） */
.pattern-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 0 10px;
  flex-wrap: wrap;
}
.pattern-total {
  color: var(--text-secondary, #9ca3af);
  font-size: 12px;
  margin-left: auto;
}
.pattern-qual {
  color: var(--text-secondary, #9ca3af);
  font-size: 12px;
  margin-left: 6px;
}
.pattern-new-badge {
  margin-left: 6px;
}
.pattern-pagination {
  margin-top: 10px;
  justify-content: flex-end;
}
.pattern-detail__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.pattern-detail__score b {
  font-size: 16px;
}
.pattern-detail__veto {
  background: rgba(246, 70, 93, 0.08);
  border: 1px solid rgba(246, 70, 93, 0.3);
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 13px;
  color: var(--rise, #F6465D);
  margin-bottom: 10px;
}
.pattern-detail__section {
  margin-top: 12px;
}
.pattern-detail__section h4 {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--text-secondary, #9ca3af);
}
.pattern-detail__section ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.7;
}
.pattern-detail__axis-name {
  font-size: 12px;
  color: var(--accent, #60A5FA);
  font-weight: 600;
}
.bsp-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  flex: 1;
}

/* ---- 证据强度列（chan-bsp-grading）------------------------------------
   表格里给「85 较强」这种两段式缩写：数字供横向比较，定性供快速分档。
   颜色按分数分五档（与 gradeTone() 对应），与级别列的徽章色系区分开、
   不抢注意力 —— 它是**评估**，级别才是**结构事实**。 */
.grade-cell {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 1px 7px;
  border-radius: 3px;
  border-left: 2px solid var(--border-strong);
  background: var(--bg-surface-hover);
  cursor: help;
}
.grade-cell__num {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.grade-cell__qual {
  font-size: 10.5px;
  color: var(--text-secondary);
}
.grade-cell.is-strong { border-left-color: var(--rise); }
.grade-cell.is-good   { border-left-color: color-mix(in srgb, var(--rise) 62%, var(--warning)); }
.grade-cell.is-mid    { border-left-color: var(--warning); }
.grade-cell.is-weak   { border-left-color: color-mix(in srgb, var(--warning) 55%, var(--fall)); }
.grade-cell.is-poor   { border-left-color: var(--fall); }
.grade-cell.is-none {
  border-left-color: var(--border-base);
  color: var(--text-disabled);
  font-size: 11px;
  cursor: default;
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
.bsp-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 var(--sp-md);
}
/* 买卖点类型单元格（bsp-sure-annotation D4）：类型徽章与「未确认」灰 tag 垂直堆叠，避免 110px 列宽内横向挤压 */
.bsp-type-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  line-height: 1.3;
}
.sure-tag {
  /* 灰色弱化标注，height 压缩以适配行高 */
  height: 18px;
  padding: 0 6px;
  font-size: 11px;
}
.bsp-tabs :deep(.el-tabs__nav-wrap::after) {
  background: var(--border-base);
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-md) var(--sp-lg);
  border-top: 1px solid var(--border-base);
}
.add-dialog-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
}
.monitor-ctx {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
  padding: var(--sp-md);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
}
.monitor-ctx .form-row {
  flex-direction: row;
  align-items: center;
  gap: var(--sp-md);
}
.monitor-ctx .form-row label {
  width: 90px;
  flex-shrink: 0;
}
.ctx-value {
  font-size: 13px;
  color: var(--text-primary);
}
/* D12 价格联动取价中的弱化显示 */
.ctx-value.price-stale {
  opacity: 0.5;
}
.ctx-code {
  margin-left: 6px;
  font-size: 12px;
  color: var(--text-disabled);
}
.monitor-time-row {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
}
/* 下拉尾部「新增分组」行内入口（monitor-group-change D5） */
.group-add-entry {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  font-size: 13px;
  color: var(--accent-hover);
  cursor: pointer;
  border-top: 1px solid var(--border-base);
}
.group-add-entry:hover {
  background: var(--accent-dim);
}
.group-add-form {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  padding: 6px 8px;
  border-top: 1px solid var(--border-base);
}
.dialog-hint {
  font-size: 12px;
  color: var(--text-disabled);
  margin: 0;
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
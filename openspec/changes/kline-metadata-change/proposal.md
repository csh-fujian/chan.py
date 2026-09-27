## Why

`stock-metadata-sync` 已将股票的公司档案（16 列）、估值快照（8 列）、身份信息、股东户数等元数据全量落库 PG，但目前**没有任何 API 与界面出口**：`GET /stocks/{code}` 仅返回身份+用户列，`GET /stocks/{code}/profile` 仅返回板块+价格。K 线页用户在看图分析时无法就地看到上市日期、估值、主营业务等决策上下文，这些信息只躺在数据库里。此外，K 线页顶栏搜索框只接受完整代码手输回车，用户知道名称或拼音首字母时无法检索到目标股票，而 PG `stock` 表与 `GET /api/stocks?q=` 的模糊查询能力（且不含拼音）未被该页面利用。

## What Changes

- **K 线页左侧面板新增「股票信息」tab**（位于「标的」旁），分四组从上到下展示：
  1. **A 公司档案**：公司全称/英文名称/曾用简称、交易所、上市板块、上市日期、成立日期、法人代表、注册资本
  2. **D 行情快照**：总市值、流通市值、PE(TTM)、PB、换手率、主力净流入、数据时间（snapshot_at 时效标注）
  3. **C 经营概况**：主营业务、经营范围、公司简介（长文本折叠展开）
  4. **B 联系方式**：官网（可点击）、邮箱（可点击）、电话、传真、注册地址、办公地址、邮编
  - 附加小节：**股东户数**近 1 年 sparkline、**用户标签/备注**（tags/notes 只读）
- **新增后端接口 `GET /api/stocks/{code}/meta`**：一次性返回档案 16 列 + 快照 8 列 + 身份补充列 + 股东户数近 1 年序列 + tags/notes（所有字段可空，返回默认值/空数组）。
- **与「标的」tab 严格去重**：不重复展示 name/code/price/change_pct（标的头部）、行业 badge（板块信息）；`industry_l1` 因与行业 badge 语义重复且上交所数据缺失，不展示。
- **不含**：财务三表展示（数据量大，留待独立变更）；region/concepts（本变更不生产该数据）。
- **K 线页股票搜索增强**：顶栏搜索框支持输入时远程搜索下拉——按股票**编号模糊**、**名称模糊**、**名称拼音首字母模糊**（PG `stock` 表新增 `name_py` 列，由 pypinyin 从 name 生成，仅存首字母；在 name 的三条写入口统一维护并回填存量）匹配出多条候选，用户在下拉中点选后以该 code 精确加载 K 线；**保留**手动输入完整代码回车/点搜索按钮的既有精确加载行为。复用既有 `GET /api/stocks?q=`，其匹配条件扩为 `code OR name OR name_py` 三列子串匹配（受益方含 watchlist/alerts）；无候选时下拉空态但不阻断手动加载；PG 不可用时降级为编号匹配、不报错。
- **前端配套**：`KLineView.vue` 搜索框改造（防抖远程下拉，模式参照 watchlist 已有的 remote select）、mock 搜索 handler 同步支持 `name_py` 匹配。
- 前端配套（元数据 tab）：`stock.ts` API 模块、`types.ts` 类型、`StockMetaPanel` 组件、MSW mock handler。

## Capabilities

### New Capabilities

- `kline-stock-metadata`: K 线页「股票信息」tab 展示能力。覆盖 tab 切换与分组顺序（A→D→C→B）、元数据接口契约、字段与「标的」tab 的去重边界、空态与长文本折叠、快照时效标注、股东户数趋势、用户标签只读展示。

- `kline-stock-search`: K 线页股票搜索能力。覆盖三列模糊匹配契约（编号/名称/拼音首字母，复用 `GET /api/stocks?q=`）、`name_py` 数据维护（生成时机与存量回填）、搜索下拉与选中后精确查 K 线、手动精确输入保留、无候选与无 PG 时的降级行为。

### Modified Capabilities

<!-- 无：`openspec/specs/` 下仅 `kline-persistence`，其需求（K 线数据持久化）不因本变更改变；
     `stock-metadata-sync`（未归档）定义的是同步/落库需求，本变更只消费数据不改其需求。 -->

## Impact

- **新增后端文件**：无（在既有 `WebAPI/routers/stocks.py` 内新增路由）。
- **修改后端**：`WebAPI/routers/stocks.py`（新增 `GET /{code}/meta`；`GET /stocks` 的 `q` 匹配扩列）；`WebAPI/stock_store.py`（新增读取函数：档案+快照列、股东户数近 1 年序列；`name` 三条写入口同步生成 `name_py`；存量回填）；`WebAPI/init.sql`（`stock` 表加 `name_py` 列）。
- **新增依赖**：`pypinyin`（`Script/requirements.txt`），用于从 name 生成拼音首字母。
- **修改前端**：`Front/src/api/modules/stock.ts`（`getStockMeta`；`searchStocks` 无需改签名）、`Front/src/api/types.ts`（`StockMeta` 类型）、`Front/src/views/kline/KLineView.vue`（新增 tab 按钮与面板切换；顶栏搜索框改造为远程下拉）、`Front/src/mock/handlers/stock.ts`（搜索匹配支持 `name_py`；meta handler + 数据）。
- **新增前端文件**：`Front/src/components/kline/StockMetaPanel.vue`。
- **数据依赖**：`stock-metadata-sync` 的 profile/identity/snapshot/holders 域已落库（profile 全量进行中，展示层需空态兜底）；不修改 `CChan` 计算流水线与 DuckDB K 线存储。
- **交叉说明**：`name_py` 的写入口与 `stock-metadata-sync`（进行中）同处 `WebAPI/stock_store.py`，身份域 name 更新（BaoStock 名单同步）也需同步刷新 `name_py`；两变更在同一文件上工作，实施时需对齐。
- **不依赖**：财务三表、行业 M2M 完整性（行业不重复展示）。

## 1. 搜索数据层（`name_py` 列与匹配）

- [x] 1.1 `Script/requirements.txt` 添加 `pypinyin` 并 `.venv/bin/pip install`，验证 `pip show pypinyin` 成功
- [x] 1.2 `WebAPI/init.sql` 幂等补列 `name_py VARCHAR NOT NULL DEFAULT ''`，`stock_store._ensure_tables` 同步对齐补列，验证重启后 PG 中 `stock` 表含 `name_py` 列
- [x] 1.3 实现 `gen_name_py(name)`（pypinyin FIRST_LETTER、小写、非中文原样拼入），在 `upsert_stock`、身份域同步写入、`import_stocks` 三个 name 写入口统一调用，验证手动新增股票后 `SELECT name_py FROM stock WHERE code=...` 有值
- [x] 1.4 `_ensure_tables` 内实现进程级一次性回填（`name_py = '' AND name <> ''`，flag 防重复），验证存量股票 `name_py=''` 行数为 0，且第二次重启不重复执行
- [x] 1.5 `list_stocks` 的 `q` 匹配扩为 `code ILIKE OR name ILIKE OR name_py ILIKE`（同一参数绑定三次），验证 `curl '/api/stocks?q=payh'` 命中「平安银行」、`q=0000` 命中编号含 0000 的股票、`q=PAYH` 与 `payh` 结果一致

## 2. 元数据接口（`GET /stocks/{code}/meta`）

- [x] 2.1 `stock_store` 新增 meta 读取函数：档案+快照+身份补充+tags/notes（`stock` 单行）与股东户数近 1 年序列（按日期升序），所有字段无值时返回约定空值形态，验证直接调用返回恒定键集合
- [x] 2.2 `WebAPI/routers/stocks.py` 新增 `GET /stocks/{code}/meta`（与既有参数化路由并列声明），验证：库内 code 返回 200 全字段，库外 code 返回 404
- [x] 2.3 `Front/src/mock/handlers/stock.ts` 新增 meta handler，mock 数据覆盖「字段齐全 + 稀疏字段为空 + holders 空序列」三种形态，验证 mock 模式下三种响应形态均正确

## 3. 元数据前端（「股票信息」tab）

- [x] 3.1 `Front/src/api/types.ts` 新增 `StockMeta` 类型、`stock.ts` 新增 `getStockMeta(code)`，验证 `vue-tsc -b` 通过
- [x] 3.2 实现 `Front/src/components/kline/StockMetaPanel.vue`：按 spec 顺序渲染 A/D/C/B 四组 + 股东户数 + 用户标签/备注；空值 `--` 占位、长文本折叠、snapshot_at 时效标注、404 面板级空态、加载态，验证 `npm run dev` 下三种 mock 形态展示正确
- [x] 3.3 `KLineView.vue` 左侧 tab 栏加「股票信息」入口并接 `StockMetaPanel`（互斥切换、默认仍为「标的」），验证三 tab 切换与默认行为符合 spec
- [x] 3.4 与「标的」tab 去重核对：名称/代码/现价/涨跌幅/行业 badge 不出现在元数据面板，`industry_l1` 不展示，验证两 tab 来回切换无重复信息

## 4. K 线页搜索下拉

- [x] 4.1 mock 搜索 handler 匹配条件加 `name_py` 第三列（mock 数据手工标 `name_py`），验证 mock 模式下 `q=payh` 返回「平安银行」
- [x] 4.2 `KLineView.vue` 顶栏输入框改造为 `el-autocomplete`：`:fetch-suggestions` 接 `searchStocks`、300ms 本地防抖、空输入不请求、过期响应丢弃（后发覆盖），验证输入「平安」约 300ms 后出现候选下拉
- [x] 4.3 实现 Enter 语义：未用 ↑↓ 浏览候选时 Enter 按输入框原值走既有 `handleSearch()`；浏览过（flag）或鼠标 `@select` 时选中候选并同步输入框为该 code，验证「输入 `sz.000001` 回车」与「输 `payh` → 方向键选中回车」两条路径分别落在预期行为上
- [x] 4.4 无匹配候选时下拉空态且不阻断手动加载，验证输入乱字符后下拉显示空态、回车仍按输入值加载
- [x] 4.5 无 PG 降级验证：停掉 PG（或断开连接）后输入名称/拼音查询词，接口返回 code 匹配结果或空列表、页面不报错

## 5. 整体验证

- [ ] 5.1 对照 `specs/kline-stock-search/spec.md` 13 个 Scenario 与 `specs/kline-stock-metadata/spec.md` 各 Scenario 逐条手验（mock 模式 + 真实 PG 模式各过一遍），记录偏差
- [x] 5.2 回归既有调用方：自选页添加股票弹窗、预警规则弹窗的 `searchStocks` 正常；`openspec validate kline-metadata-change` 通过

## 6. 存量缺陷修复：PG 连接失败不兜底（实施中排查发现）

> 背景：`_get_pg_conn` 在「DSN 已配置但 PG 不可达」时抛 `OperationalError`（而非按契约返回 None），
> 导致 4 个 store 模块级 `_ensure_tables()` 阻断应用启动、运行期全端点 500。
> HEAD 存量问题，非本变更引入；修复后 spec 4.5「PG 不可用降级」在所有不可用形态下成立。

- [x] 6.1 4 个 store（stock/bsp/watchlist/monitor）的 `_get_pg_conn` 捕获 `OperationalError` → 返回 None + 状态翻转日志；`auth._get_pg_conn` 连接失败转 HTTPException 503；验证坏 DSN 下 `import WebAPI.main` / `import WebAPI.app` 均不崩
- [x] 6.2 降级与回归验证：坏 DSN 实例搜索 200 降级 / meta 404 / auth 503；正常 DSN 实例功能回归；连接失败→恢复的状态翻转日志各记一条

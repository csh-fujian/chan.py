## Purpose

在 K 线分析页左侧面板提供「股票信息」tab，将 `stock-metadata-sync` 已落库的公司档案、估值快照、经营概况、联系方式、股东户数与用户标签以只读形式就地展示，且与「标的」tab 的既有信息严格去重。

## ADDED Requirements

### Requirement: 股票信息 tab 切换
K 线页左侧 tab 栏 SHALL 包含「标的 / 股票信息 / 问答」三个入口；点击「股票信息」SHALL 切换为元数据面板，且切换行为 SHALL 与既有「标的 / 问答」切换一致（互斥显示，默认仍为「标的」）。

#### Scenario: 切换到股票信息
- **WHEN** 用户在 K 线页点击「股票信息」tab
- **THEN** 左侧面板显示当前 code 的元数据内容，「标的」面板隐藏，tab 高亮态移至「股票信息」

#### Scenario: 默认 tab 不变
- **WHEN** 用户首次进入 K 线页或切换股票代码
- **THEN** 左侧面板默认仍显示「标的」tab，不因本变更改变默认行为

### Requirement: 分组展示与顺序
元数据面板 SHALL 按以下从上到下的固定顺序分组展示：**A 公司档案 → D 行情快照 → C 经营概况 → B 联系方式**，其后依次为**股东户数**与**用户标签/备注**小节。字段明细：A 组含公司全称、英文名称、曾用简称、交易所、上市板块、上市日期、成立日期、法人代表、注册资本；D 组含总市值、流通市值、市盈率(TTM)、市净率、换手率、主力净流入、数据时间；C 组含主营业务、经营范围、公司简介；B 组含官网、邮箱、电话、传真、注册地址、办公地址、邮编。

#### Scenario: 分组顺序
- **WHEN** 用户打开「股票信息」tab 且数据可用
- **THEN** 面板自上而下依次呈现 公司档案、行情快照、经营概况、联系方式、股东户数、用户标签/备注 六个区块

#### Scenario: 官网与邮箱可交互
- **WHEN** 档案中官网或邮箱有值
- **THEN** 官网渲染为可点击链接（新窗口打开），邮箱渲染为 mailto 链接

### Requirement: 与「标的」tab 去重
元数据面板 SHALL NOT 展示「标的」tab 已有的信息：股票名称、代码、现价、涨跌幅、行业 badge 列表；亦 SHALL NOT 展示 `industry_l1`（与行业 badge 语义重复且上交所来源缺失）。区域/概念不在本能力范围。

#### Scenario: 头部信息不重复
- **WHEN** 用户在「标的」与「股票信息」两个 tab 间来回切换
- **THEN** 名称/代码/现价/涨跌幅仅出现在「标的」头部，行业 badge 列表仅出现在「标的」板块信息区，「股票信息」中均不出现

### Requirement: 元数据接口契约
系统 SHALL 提供 `GET /api/stocks/{code}/meta`，一次性返回该股票的档案字段、快照字段、身份补充字段、tags/notes 以及股东户数近 1 年序列。所有字段 SHALL 恒定存在：无值时字符串字段为空串、数值字段为 null、序列为数组（可为空）；股票不在库时 SHALL 返回 404。快照数值 SHALL 来自同步落库的估值快照，而非 K 线收盘价推导。

#### Scenario: 已知股票返回全量字段
- **WHEN** 对库内存在的 code 请求 `GET /api/stocks/{code}/meta`
- **THEN** 返回 200，JSON 同时包含档案 16 列（full_name、en_name、former_names、legal_person、reg_capital、found_date、website、email、phone、fax、reg_addr、office_addr、postal_code、main_business、business_scope、intro）、快照 8 列（price、total_mv、float_mv、pe_ttm、pb、turnover_rate、main_net_inflow、snapshot_at）、身份补充（exchange、ipo_date、board）、tags、notes、holders 序列

#### Scenario: 未同步字段不缺键
- **WHEN** 库内股票的某档案字段尚未同步（值为空）
- **THEN** 响应中该键仍存在且为约定的空值形态，前端无需判断键是否存在

#### Scenario: 库外代码
- **WHEN** 请求的 code 不在 stock 表
- **THEN** 返回 404，前端展示「暂无元数据」空态而非崩溃

### Requirement: 空态与长文本折叠
字段值为空时面板 SHALL 显示统一占位符（如 `--`）而非空白或键名；经营范围与公司简介 SHALL 默认折叠并可展开查看全文；面板 SHALL 具备加载态。档案稀疏字段（曾用简称、简介、传真等）出现空值 SHALL 视为正常展示而非错误。

#### Scenario: 档案未同步时的展示
- **WHEN** profile 域尚未同步到该股票（如全量任务进行中），用户打开「股票信息」tab
- **THEN** A/C/B 组字段显示占位符，页面无报错，D 组已同步的快照字段正常显示

#### Scenario: 长文本折叠
- **WHEN** 经营范围或公司简介文本超过展示行数
- **THEN** 默认折叠显示截断内容并提供展开控件，点击后显示全文

### Requirement: 快照时效标注
D 组 SHALL 展示快照数据时间（snapshot_at）；快照缺失时该组数值显示占位符且不显示数据时间。

#### Scenario: 展示数据时间
- **WHEN** 该股票存在估值快照
- **THEN** 行情快照组内展示格式化的 snapshot_at 时间，标明数据时效

### Requirement: 股东户数趋势
面板 SHALL 展示该股票近 1 年股东户数序列（按日期升序）的轻量趋势图；序列为空时 SHALL 显示区块级空态。

#### Scenario: 有户数数据
- **WHEN** stock_holder_num 中该股票近 1 年存在记录
- **THEN** 股东户数小节渲染趋势图，数据点按日期升序

#### Scenario: 无户数数据
- **WHEN** 该股票近 1 年无股东户数记录
- **THEN** 股东户数小节显示「暂无数据」占位，不影响其他区块渲染

### Requirement: 用户标签与备注只读
面板 SHALL 以只读形式展示该股票的 tags（徽标样式）与 notes 文本；本能力 SHALL NOT 提供编辑入口（编辑仍属既有股票管理能力）。

#### Scenario: 展示标签与备注
- **WHEN** 股票带有用户设置的 tags 或 notes
- **THEN** 「用户标签/备注」小节展示徽标与备注文本；两者均为空时显示占位符

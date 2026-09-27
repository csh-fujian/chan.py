# -*- coding: utf-8 -*-
"""
元数据同步服务（stock-metadata-sync）——AKShare 多数据源分域同步到 PG 四表。

被 Data/sync_stock_meta.py 批量脚本与 WebAPI/routers/stocks.py 手动刷新共用的
唯一核心路径（design D5）。

域与频率矩阵（D8）：
    identity  每天    交易所三所名单（唯一权威身份源）
    snapshot  每天    腾讯全市场估值快照
    industry  7 天    东财板块成分 M2M（探测失败降级巨潮单值）
    holders   15 天   股东户数（近 1 年）
    profile   30 天   巨潮公司档案 16 列
    financial 30 天   东财财务三表 JSONB（年报全历史 + 近 10 年中报季报）

静态字段（D8）：ipo_date / found_date 首次写入后永不覆盖（落库侧 IS NULL 保护）。

代码归一（D1）：全域写入前统一归一为 `<sh|sz|bj>.<6位>`（与 DuckDB kline.code 一致），
无法归一 → 拒绝落库并计入 failed 明细。

代理陷阱（D6）：all_proxy=socks5://... 且未装 pysocks 时 requests 直连报错，
请求前清空代理环境变量；东财 push2 域做 2-3 次退避重试（直连/代理交替），
探测失败按设计降级（行业域）。
"""

import logging
import math
import os
import re
import time
from contextlib import contextmanager, suppress
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

from . import stock_store

log = logging.getLogger("meta_sync")

# ---------------------------------------------------------------------------
# 域定义与频率矩阵（D8）
# ---------------------------------------------------------------------------

# 执行顺序：快的市场级域在前，逐股慢域在后；identity 必须最先（新码建档供后续域入池）
DOMAIN_ORDER: tuple[str, ...] = (
    "identity",
    "profile",
    "industry",
    "snapshot",
    "financial",
    "holders",
)
DOMAINS: tuple[str, ...] = DOMAIN_ORDER  # 脚本 --domain choices 用

DOMAIN_INTERVALS: dict[str, int] = {
    "identity": 86400,
    "snapshot": 86400,
    "industry": 7 * 86400,
    "holders": 15 * 86400,
    "profile": 30 * 86400,
    "financial": 30 * 86400,
}

# 静态字段集合：首次全量写入后不再覆盖（列级保护在 stock_store.apply_*）
STATIC_IDENTITY_FIELDS: set[str] = {"ipo_date"}
STATIC_PROFILE_FIELDS: set[str] = {"found_date"}

# 交易所 -> exchange 落库值
EXCHANGE_SH = "上交所"
EXCHANGE_SZ = "深交所"
EXCHANGE_BJ = "北交所"


# ---------------------------------------------------------------------------
# 代码归一（D1，全域共用）
# ---------------------------------------------------------------------------

_CODE_NORMALIZED = re.compile(r"^(sh|sz|bj)\.(\d{6})$")
_CODE_DOT_SUFFIX = re.compile(r"^(\d{6})\.(sh|sz|bj)$", re.IGNORECASE)
_CODE_PREFIXED = re.compile(r"^(sh|sz|bj)(\d{6})$", re.IGNORECASE)
_CODE_BARE = re.compile(r"^(\d{6})$")

_BARE_PREFIX_BY_FIRST_DIGIT = {"6": "sh", "0": "sz", "3": "sz", "4": "bj", "8": "bj", "9": "bj"}


def normalize_code(raw: Any) -> Optional[str]:
    """把异构源格式归一为 `<sh|sz|bj>.<6位>`；无法归一返回 None（计入 failed）。

    支持：`sh688808` / `SZ000001`（前缀大写映射）、`000001.SZ`（剥 .XX 后缀）、
    裸 6 位首位推断（`6`→sh、`0`/`3`→sz、`4`/`8`/`9`→bj）、已归一 `sz.000001`。
    """
    if raw is None:
        return None
    if isinstance(raw, float):
        if math.isnan(raw):
            return None
        if raw.is_integer():
            raw = int(raw)
    s = str(raw).strip().lower()
    if not s or s in ("nan", "none", "null"):
        return None

    m = _CODE_NORMALIZED.match(s)
    if m:
        return f"{m.group(1)}.{m.group(2)}"

    m = _CODE_DOT_SUFFIX.match(s)
    if m:
        return f"{m.group(2).lower()}.{m.group(1)}"

    m = _CODE_PREFIXED.match(s)
    if m:
        return f"{m.group(1).lower()}.{m.group(2)}"

    m = _CODE_BARE.match(s)
    if m:
        digits = m.group(1)
        prefix = _BARE_PREFIX_BY_FIRST_DIGIT.get(digits[0])
        if prefix is None:
            return None
        return f"{prefix}.{digits}"

    return None


def code_to_ak_symbol(code: str) -> str:
    """`sz.000001` -> `SZ000001`（东财 datacenter symbol 参数格式）。"""
    pref, digits = code.split(".", 1)
    return f"{pref.upper()}{digits}"


def code_to_bare(code: str) -> str:
    """`sz.000001` -> `000001`（巨潮 symbol 参数格式）。"""
    return code.split(".", 1)[1]


# ---------------------------------------------------------------------------
# 代理陷阱（D6）
# ---------------------------------------------------------------------------

_PROXY_CLEANED = False
_FORCE_DIRECT = False
_ORIG_MERGE_ENV = None


def _clean_proxy_env() -> None:
    """进程内清理 socks 代理陷阱。

    all_proxy/ALL_PROXY 含 socks 且未装 pysocks 时，requests 会因缺 pysocks 而
    连接失败；此时清除 http_proxy/https_proxy/all_proxy/HTTP(S)_PROXY/ALL_PROXY
    环境变量，使 akshare 底层 requests 不再尝试 SOCKS。

    实测补充：macOS 下清环境变量后 urllib.getproxies() 仍会回退到系统代理配置，
    对东财 push2 域的请求仍可能被本地代理掐断——重试路径用 _direct_transport()
    临时中和 getproxies 走真直连（proxies={} 在 requests 里并不能禁用代理）。
    """
    global _PROXY_CLEANED
    if _PROXY_CLEANED:
        return
    _PROXY_CLEANED = True

    socks_val = os.environ.get("all_proxy") or os.environ.get("ALL_PROXY") or ""
    if "socks" not in socks_val.lower():
        return
    try:
        import socks  # noqa: F401  # type: ignore

        return  # pysocks 已装，socks 代理可用
    except ImportError:
        pass

    for key in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        os.environ.pop(key, None)
    log.debug("proxy env cleared (socks trap without pysocks)")


def _install_direct_patch() -> None:
    """给 requests.Session.merge_environment_settings 打补丁，支持强制直连。"""
    global _ORIG_MERGE_ENV
    if _ORIG_MERGE_ENV is not None:
        return
    import requests.sessions

    _ORIG_MERGE_ENV = requests.sessions.Session.merge_environment_settings

    def _patched(self, url, proxies, stream, verify, cert):
        if _FORCE_DIRECT:
            was = self.trust_env
            self.trust_env = False
            try:
                return _ORIG_MERGE_ENV(
                    self, url, {"http": None, "https": None}, stream, verify, cert
                )
            finally:
                self.trust_env = was
        return _ORIG_MERGE_ENV(self, url, proxies, stream, verify, cert)

    requests.sessions.Session.merge_environment_settings = _patched


@contextmanager
def _direct_transport():
    """临时让 requests（含 akshare 内部调用）绕过环境/系统代理走直连。"""
    global _FORCE_DIRECT
    _install_direct_patch()
    prev = _FORCE_DIRECT
    _FORCE_DIRECT = True
    try:
        yield
    finally:
        _FORCE_DIRECT = prev


def _fetch_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    retries: int = 3,
    backoff: float = 1.5,
    alternate_direct: bool = True,
    **kwargs: Any,
) -> Any:
    """带退避重试的数据源调用；东财域在重试间交替 直连/系统代理 两种传输。

    2-3 次退避重试后仍失败则抛出（由调用方决定降级或记 failed）。
    """
    last: Optional[BaseException] = None
    for i in range(max(1, retries)):
        try:
            if alternate_direct and i % 2 == 1:
                with _direct_transport():
                    return fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            # 中断契约（spec 2.7）：Ctrl+C/kill -INT 不得被重试循环吞掉或拖延——
            # 直接上抛，让 sync() 把 sync_job 置 interrupted 后退出。
            raise
        except BaseException as e:  # 失败隔离，重试耗尽后统一上抛
            last = e
            log.warning("fetch retry %d/%d for %s: %s", i + 1, retries, getattr(fn, "__name__", fn), e)
            if i < retries - 1:
                time.sleep(backoff * (i + 1))
    assert last is not None
    raise last


# ---------------------------------------------------------------------------
# 运行时列探针 + 取值工具（akshare 列名版本漂移防护）
# ---------------------------------------------------------------------------


def _pick_col(columns: Iterable[str], *candidates: str) -> Optional[str]:
    """按候选名取实际列（大小写不敏感兜底），全部缺失返回 None。"""
    cols = list(columns)
    col_set = set(cols)
    for c in candidates:
        if c in col_set:
            return c
    lower_map = {str(c).lower(): c for c in cols}
    for c in candidates:
        hit = lower_map.get(c.lower())
        if hit is not None:
            return hit
    return None


def _cell(row: dict, col: Optional[str], default: Any = None) -> Any:
    if col is None:
        return default
    v = row.get(col, default)
    return default if v is None else v


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _to_num(v: Any) -> Optional[float]:
    """源列数值化；'-' / '' / NaN → None（不编造）。"""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", "nan", "None", "null"):
        return None
    if s.endswith("%"):
        s = s.removesuffix("%")
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(v: Any) -> Optional[int]:
    n = _to_num(v)
    return None if n is None else int(n)


def _to_date(v: Any) -> Optional[date]:
    """日期解析：'2026-06-30' / '20260630' / '2026-06-30 00:00:00' / pandas Timestamp。"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "null", "nat"):
        return None
    s = s.replace("/", "-")
    for fmt, cut in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(s[:cut], fmt).date()
        except ValueError:
            continue
    try:
        import pandas as pd

        ts = pd.to_datetime(v, errors="coerce")
        if ts is not None and not pd.isna(ts):
            return ts.date()
    except Exception:
        return None
    return None


def _json_val(v: Any) -> Any:
    """pandas/numpy 值转 JSON 安全值；NaN/NaT → None。"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "item"):
        with suppress(Exception):
            return _json_val(v.item())  # numpy 标量 → python 标量
    with suppress(Exception):
        import pandas as pd

        if v is pd.NaT or (not isinstance(v, (list, dict, str, bytes)) and pd.isna(v)):
            return None
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


# ---------------------------------------------------------------------------
# 财务三表列白名单（约 86 科目：元数据 9+ + 资产负债 36 + 利润 24 + 现金流 19）
# 运行时与返回列求交；data JSONB 只存白名单键。银行保险专属与 *_YOY 重复披露列剔除。
# ---------------------------------------------------------------------------

_FIN_META_COLS: tuple[str, ...] = (
    "SECUCODE",
    "SECURITY_CODE",
    "SECURITY_NAME_ABBR",
    "ORG_TYPE",
    "REPORT_DATE",
    "REPORT_TYPE",
    "REPORT_DATE_NAME",
    "NOTICE_DATE",
    "CURRENCY_NAME",
    "CURRENCY",  # akshare 1.18.97 实测列名为 CURRENCY（非 CURRENCY_NAME）
)

_FIN_BALANCE_COLS: tuple[str, ...] = (
    # 流动资产
    "TRADE_FINASSET",
    "DERIVE_FINASSET",
    "ACCOUNTS_RECE",
    "NOTE_RECE",
    "INVEST_RECE",
    "HOLDSALE_ASSET",
    "OTHER_ASSET",
    "DEFER_TAX_ASSET",
    # 非流动资产
    "LONG_EQUITY_INVEST",
    "INVEST_SUBSIDIARY",
    "INVEST_JOINT",
    "INVEST_REALESTATE",
    "FIXED_ASSET",
    "CIP",
    "USERIGHT_ASSET",
    "INTANGIBLE_ASSET",
    "GOODWILL",
    "LONG_PREPAID_EXPENSE",
    "TOTAL_ASSETS",
    # 负债
    "TRADE_FINLIAB",
    "DERIVE_FINLIAB",
    "ACCOUNTS_PAYABLE",
    "NOTE_PAYABLE",
    "STAFF_SALARY_PAYABLE",
    "TAX_PAYABLE",
    "DIVIDEND_PAYABLE",
    "PREDICT_LIAB",
    "DEFER_TAX_LIAB",
    "HOLDSALE_LIAB",
    "BOND_PAYABLE",
    "LEASE_LIAB",
    "OTHER_LIAB",
    "TOTAL_LIABILITIES",
    # 权益
    "SHARE_CAPITAL",
    "CAPITAL_RESERVE",
    "SURPLUS_RESERVE",
    "UNASSIGN_RPOFIT",
    "OTHER_COMPRE_INCOME",
    "CONVERT_DIFF",
    "TOTAL_PARENT_EQUITY",
    "MINORITY_EQUITY",
    "TOTAL_EQUITY",
    "TOTAL_LIAB_EQUITY",
)

_FIN_INCOME_COLS: tuple[str, ...] = (
    "OPERATE_INCOME",
    "OPERATE_EXPENSE",
    "OPERATE_TAX_ADD",
    "BUSINESS_MANAGE_EXPENSE",
    "ASSET_IMPAIRMENT_LOSS",
    "CREDIT_IMPAIRMENT_LOSS",
    "OTHER_BUSINESS_INCOME",
    "OTHER_BUSINESS_COST",
    "FAIRVALUE_CHANGE_INCOME",
    "INVEST_INCOME",
    "OPERATE_PROFIT",
    "NONBUSINESS_INCOME",
    "NONBUSINESS_EXPENSE",
    "NONCURRENT_DISPOSAL_INCOME",
    "TOTAL_PROFIT",
    "INCOME_TAX",
    "NETPROFIT",
    "CONTINUED_NETPROFIT",
    "DISCONTINUED_NETPROFIT",
    "PARENT_NETPROFIT",
    "MINORITY_INTEREST",
    "DEDUCT_PARENT_NETPROFIT",
    "BASIC_EPS",
    "DILUTED_EPS",
)

_FIN_CASHFLOW_COLS: tuple[str, ...] = (
    "TOTAL_OPERATE_INFLOW",
    "TOTAL_OPERATE_OUTFLOW",
    "NETCASH_OPERATE",
    "TOTAL_INVEST_INFLOW",
    "TOTAL_INVEST_OUTFLOW",
    "NETCASH_INVEST",
    "TOTAL_FINANCE_INFLOW",
    "TOTAL_FINANCE_OUTFLOW",
    "NETCASH_FINANCE",
    "CONSTRUCT_LONG_ASSET",
    "PAY_STAFF_CASH",
    "PAY_ALL_TAX",
    "RECEIVE_DIVIDEND_PROFIT",
    "DISPOSAL_LONG_ASSET",
    "ASSIGN_DIVIDEND_PORFIT",
    "PAY_DEBT_CASH",
    "RATE_CHANGE_EFFECT",
    "CCE_ADD",
    "END_CCE",
)

# 全部白名单键（东财主源）
FINANCIAL_WHITELIST: frozenset[str] = frozenset(
    _FIN_META_COLS + _FIN_BALANCE_COLS + _FIN_INCOME_COLS + _FIN_CASHFLOW_COLS
)

# 财务域 statement_type
STMT_BALANCE = "balance"
STMT_INCOME = "income"
STMT_CASHFLOW = "cashflow"

# 新浪备源（东财三接口都抛异常时兜底，列名映射尽力而为）
_SINA_STMT_SYMBOLS: dict[str, str] = {
    STMT_BALANCE: "资产负债表",
    STMT_INCOME: "利润表",
    STMT_CASHFLOW: "现金流量表",
}

_SINA_COL_MAP: dict[str, str] = {
    # 元数据
    "报告日": "REPORT_DATE",
    "公告日期": "NOTICE_DATE",
    "类型": "REPORT_TYPE",
    "币种": "CURRENCY",
    # 资产负债
    "交易性金融资产": "TRADE_FINASSET",
    "衍生金融工具资产": "DERIVE_FINASSET",
    "应收账款": "ACCOUNTS_RECE",
    "应收票据": "NOTE_RECE",
    "其他应收款": "INVEST_RECE",
    "划分为持有待售的资产": "HOLDSALE_ASSET",
    "其他资产": "OTHER_ASSET",
    "递延税款借项": "DEFER_TAX_ASSET",
    "长期股权投资": "LONG_EQUITY_INVEST",
    "固定资产净额": "FIXED_ASSET",
    "在建工程": "CIP",
    "使用权资产": "USERIGHT_ASSET",
    "无形资产": "INTANGIBLE_ASSET",
    "商誉": "GOODWILL",
    "长期待摊费用": "LONG_PREPAID_EXPENSE",
    "资产总计": "TOTAL_ASSETS",
    "交易性金融负债": "TRADE_FINLIAB",
    "衍生金融工具负债": "DERIVE_FINLIAB",
    "应付账款": "ACCOUNTS_PAYABLE",
    "应付票据": "NOTE_PAYABLE",
    "应付职工薪酬": "STAFF_SALARY_PAYABLE",
    "应交税费": "TAX_PAYABLE",
    "应付股利": "DIVIDEND_PAYABLE",
    "预计负债": "PREDICT_LIAB",
    "递延所得税负债": "DEFER_TAX_LIAB",
    "应付债券": "BOND_PAYABLE",
    "租赁负债": "LEASE_LIAB",
    "其他负债": "OTHER_LIAB",
    "负债合计": "TOTAL_LIABILITIES",
    "股本": "SHARE_CAPITAL",
    "资本公积": "CAPITAL_RESERVE",
    "盈余公积": "SURPLUS_RESERVE",
    "未分配利润": "UNASSIGN_RPOFIT",
    "其他综合收益": "OTHER_COMPRE_INCOME",
    "外币报表折算差额": "CONVERT_DIFF",
    "归属于母公司股东的权益": "TOTAL_PARENT_EQUITY",
    "少数股东权益": "MINORITY_EQUITY",
    "负债及股东权益总计": "TOTAL_LIAB_EQUITY",
    # 利润
    "营业收入": "OPERATE_INCOME",
    "营业总收入": "OPERATE_INCOME",
    "营业成本": "OPERATE_EXPENSE",
    "营业总成本": "OPERATE_EXPENSE",
    "营业税金及附加": "OPERATE_TAX_ADD",
    "管理费用": "BUSINESS_MANAGE_EXPENSE",
    "资产减值损失": "ASSET_IMPAIRMENT_LOSS",
    "信用减值损失": "CREDIT_IMPAIRMENT_LOSS",
    "其他业务收入": "OTHER_BUSINESS_INCOME",
    "其他业务成本": "OTHER_BUSINESS_COST",
    "公允价值变动收益": "FAIRVALUE_CHANGE_INCOME",
    "投资收益": "INVEST_INCOME",
    "营业利润": "OPERATE_PROFIT",
    "营业外收入": "NONBUSINESS_INCOME",
    "营业外支出": "NONBUSINESS_EXPENSE",
    "处置非流动资产收益": "NONCURRENT_DISPOSAL_INCOME",
    "利润总额": "TOTAL_PROFIT",
    "所得税": "INCOME_TAX",
    "净利润": "NETPROFIT",
    "持续经营净利润": "CONTINUED_NETPROFIT",
    "终止经营净利润": "DISCONTINUED_NETPROFIT",
    "归属于母公司股东的净利润": "PARENT_NETPROFIT",
    "少数股东损益": "MINORITY_INTEREST",
    "扣除非经常性损益后的净利润": "DEDUCT_PARENT_NETPROFIT",
    "基本每股收益": "BASIC_EPS",
    "稀释每股收益": "DILUTED_EPS",
    # 现金流
    "销售商品、提供劳务收到的现金": "TOTAL_OPERATE_INFLOW",
    "经营活动现金流入小计": "TOTAL_OPERATE_INFLOW",
    "购买商品、接受劳务支付的现金": "TOTAL_OPERATE_OUTFLOW",
    "经营活动现金流出小计": "TOTAL_OPERATE_OUTFLOW",
    "经营活动产生的现金流量净额": "NETCASH_OPERATE",
    "投资活动现金流入小计": "TOTAL_INVEST_INFLOW",
    "投资活动现金流出小计": "TOTAL_INVEST_OUTFLOW",
    "投资活动产生的现金流量净额": "NETCASH_INVEST",
    "筹资活动现金流入小计": "TOTAL_FINANCE_INFLOW",
    "筹资活动现金流出小计": "TOTAL_FINANCE_OUTFLOW",
    "筹资活动产生的现金流量净额": "NETCASH_FINANCE",
    "购建固定资产、无形资产和其他长期资产支付的现金": "CONSTRUCT_LONG_ASSET",
    "支付给职工以及为职工支付的现金": "PAY_STAFF_CASH",
    "支付的各项税费": "PAY_ALL_TAX",
    "取得投资收益收到的现金": "RECEIVE_DIVIDEND_PROFIT",
    "处置固定资产、无形资产和其他长期资产收回的现金净额": "DISPOSAL_LONG_ASSET",
    "分配股利、利润或偿付利息支付的现金": "ASSIGN_DIVIDEND_PORFIT",
    "偿还债务支付的现金": "PAY_DEBT_CASH",
    "汇率变动对现金及现金等价物的影响": "RATE_CHANGE_EFFECT",
    "现金及现金等价物净增加额": "CCE_ADD",
    "期末现金及现金等价物余额": "END_CCE",
}

# 档案 16 列：stock 列 -> 巨潮候选列
_PROFILE_COL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "full_name": ("公司名称", "公司全称"),
    "en_name": ("英文名称",),
    "former_names": ("曾用简称",),
    "legal_person": ("法人代表", "法人"),
    "reg_capital": ("注册资金", "注册资本"),
    "found_date": ("成立日期",),
    "website": ("官方网站", "官网"),
    "email": ("电子邮箱", "邮箱"),
    "phone": ("联系电话", "电话"),
    "fax": ("传真",),
    "reg_addr": ("注册地址",),
    "office_addr": ("办公地址",),
    "postal_code": ("邮政编码", "邮编"),
    "main_business": ("主营业务",),
    "business_scope": ("经营范围",),
    "intro": ("机构简介", "简介"),
}

# 快照 8 列（不含 snapshot_at）：stock 列 -> 腾讯实测列（akshare 1.18.97 stock_zh_a_spot_tx）
# 源单位原样落库：price=元、total_mv/float_mv=亿元、turnover_rate=%、main_net_inflow=万元
_SNAPSHOT_COL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "price": ("zxj", "最新价"),
    "total_mv": ("zsz", "总市值"),
    "float_mv": ("ltsz", "流通市值"),
    "pe_ttm": ("pe_ttm", "市盈率-动态", "市盈率TTM"),
    "pb": ("pn", "市净率"),
    "turnover_rate": ("hsl", "换手率"),
    "main_net_inflow": ("zljlr", "主力净流入"),
}

# 股东户数：stock_holder_num 列 -> 巨潮候选列（价量列 最新价/涨跌幅/区间涨跌幅/总市值/名称 不入库）
_HOLDERS_COL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "stat_date": ("股东户数统计截止日-本次", "END_DATE", "统计截止日"),
    "notice_date": ("公告日期", "HOLD_NOTICE_DATE"),
    "holder_num": ("股东户数-本次", "HOLDER_NUM"),
    "prev_holder_num": ("股东户数-上次", "PRE_HOLDER_NUM"),
    "holder_num_change": ("股东户数-增减", "HOLDER_NUM_CHANGE"),
    "holder_num_change_pct": ("股东户数-增减比例", "HOLDER_NUM_RATIO"),
    "avg_hold_mv": ("户均持股市值", "AVG_MARKET_CAP"),
    "avg_hold_shares": ("户均持股数量", "AVG_HOLD_NUM"),
    "total_share": ("总股本", "TOTAL_A_SHARES"),
}


# ---------------------------------------------------------------------------
# 同步汇总
# ---------------------------------------------------------------------------


def _new_summary(domains_run: list[str]) -> dict:
    return {
        "created": 0,
        "updated": 0,
        "disabled": 0,
        "skipped": 0,
        "degraded": False,
        "failed": [],  # [(code, domain, error), ...]
        "domains_run": list(domains_run),
    }


class _SyncCtx:
    """单次 sync 运行的共享上下文：单元门限、水位、汇总。"""

    def __init__(
        self,
        *,
        now: datetime,
        force: bool,
        cutoff: datetime,
        sleep: float,
        targets: Optional[list[str]],
        summary: dict,
    ):
        self.now = now
        self.force = force
        self.cutoff = cutoff
        self.sleep = sleep
        self.targets = targets  # None = 全市场
        self.summary = summary
        self._wm_cache: dict[str, dict[str, datetime]] = {}
        self._push2_ok: Optional[bool] = None  # 本运行内缓存的 push2 探测结果
        self._push2_boards: Optional[list[str]] = None

    # ---- 汇总计数 ----
    def count(self, outcome: str) -> None:
        if outcome == "created":
            self.summary["created"] += 1
        elif outcome == "disabled":
            self.summary["disabled"] += 1
        elif outcome == "skipped":
            self.summary["skipped"] += 1
        else:  # updated / unchanged
            self.summary["updated"] += 1

    def skip(self) -> None:
        self.summary["skipped"] += 1

    def fail(self, code: str, domain: str, error: Any) -> None:
        self.summary["failed"].append((code, domain, str(error)))
        log.warning("[%s][%s] failed: %s", code, domain, error)

    # ---- 水位 ----
    def watermarks(self, domain: str, codes: list[str]) -> dict[str, datetime]:
        if domain not in self._wm_cache:
            self._wm_cache[domain] = {}
        cache = self._wm_cache[domain]
        missing = [c for c in codes if c not in cache]
        if missing:
            cache.update(stock_store.get_watermarks(missing, domain))
        return cache

    def unit_due(self, code: str, domain: str) -> bool:
        """到期判定（D8/D9）：

        - force=True：跳过间隔，但 synced_at >= cutoff（续传保护）的单元跳过；
        - force=False：水位缺失或超间隔 = 到期；已有水位且在有效期内 = 跳过（续传即其副产品）。
        """
        wm = self.watermarks(domain, [code]).get(code)
        if wm is not None and wm.tzinfo is None:
            wm = wm.replace(tzinfo=timezone.utc)
        if self.force:
            return not (wm is not None and wm >= self.cutoff)
        if wm is None:
            return True
        return (self.now - wm).total_seconds() >= DOMAIN_INTERVALS[domain]

    def mark_done(self, code: str, domain: str) -> None:
        """单元成功：先写数据事务成功、再写水位（R 风险条目约定顺序）。"""
        stock_store.set_watermark(code, domain)
        cache = self._wm_cache.setdefault(domain, {})
        cache[code] = self.now

    def pool_codes(self, enabled_only: bool) -> list[str]:
        """单元目标池：给定 targets 则为其，否则 identity=全部行 / 其余=enabled=true。"""
        if self.targets is not None:
            return list(self.targets)
        return stock_store.list_pool_codes(enabled=enabled_only)


# ---------------------------------------------------------------------------
# 身份域（D1/D3）
# ---------------------------------------------------------------------------

# 交易所名单板块逐一（A 股）：akshare 实测 symbol 参数（1.18.97）
_SH_BOARD_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("主板A股", "主板"),
    ("科创板", "科创板"),
)
_SZ_LIST_SYMBOL = "A股列表"  # 一次返回 主板/创业板（板块列区分）


def _parse_list_rows(
    df,
    exchange: str,
    default_board: str,
    bad_codes: list,
) -> dict[str, dict]:
    """交易所名单 DataFrame -> {归一code: 身份字段}；无法归一的代码入 bad_codes。"""
    cols = list(df.columns)
    code_col = _pick_col(cols, "证券代码", "A股代码", "公司代码", "code", "CODE")
    name_col = _pick_col(cols, "证券简称", "A股简称", "公司简称", "证券简称", "name")
    ipo_col = _pick_col(cols, "上市日期", "A股上市日期")
    ind_col = _pick_col(cols, "所属行业", "行业")
    board_col = _pick_col(cols, "板块", "板块名称")
    if code_col is None:
        raise ValueError(f"identity({exchange}): 代码列缺失，实际列={cols}")

    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        raw_code = row.get(code_col)
        code = normalize_code(raw_code)
        if code is None:
            bad_codes.append((str(raw_code), "identity", f"un-normalizable code from {exchange}"))
            continue
        board = _to_str(row.get(board_col)) if board_col else ""
        out[code] = {
            "name": _to_str(row.get(name_col)) if name_col else "",
            "exchange": exchange,
            "ipo_date": _to_date(row.get(ipo_col)) if ipo_col else None,
            "board": board or default_board,
            "industry_l1": _to_str(row.get(ind_col)) if ind_col else "",
        }
    return out


def _fetch_identity_lists(ak) -> tuple[dict[str, dict], list[tuple[str, Any]], list[tuple]]:
    """三所名单并集 -> (known, fetch_errors, bad_codes)。

    任一所抛异常即该所入 fetch_errors（本域 fail-closed 由上层执行）。
    """
    known: dict[str, dict] = {}
    errors: list[tuple[str, Any]] = []
    bad_codes: list[tuple] = []

    # 上交所：主板A股 / 科创板 逐一
    try:
        for symbol, board in _SH_BOARD_SYMBOLS:
            df = _fetch_with_retry(ak.stock_info_sh_name_code, symbol=symbol, retries=3)
            known.update(_parse_list_rows(df, EXCHANGE_SH, board, bad_codes))
    except Exception as e:
        errors.append((EXCHANGE_SH, e))

    # 深交所：A股列表（板块列区分主板/创业板）
    try:
        df = _fetch_with_retry(ak.stock_info_sz_name_code, symbol=_SZ_LIST_SYMBOL, retries=3)
        known.update(_parse_list_rows(df, EXCHANGE_SZ, "主板", bad_codes))
    except Exception as e:
        errors.append((EXCHANGE_SZ, e))

    # 北交所
    try:
        df = _fetch_with_retry(ak.stock_info_bj_name_code, retries=3)
        known.update(_parse_list_rows(df, EXCHANGE_BJ, EXCHANGE_BJ, bad_codes))
    except Exception as e:
        errors.append((EXCHANGE_BJ, e))

    return known, errors, bad_codes


def _sync_identity(ctx: _SyncCtx, ak) -> None:
    known, errors, bad_codes = _fetch_identity_lists(ak)
    for item in bad_codes:
        ctx.fail(item[0], item[1], item[2])
    fail_closed = bool(errors)
    for ex_name, err in errors:
        # 任一所失败：本域 fail-closed —— 只写成功名单里已知行，完全跳过 enabled=false 判定
        ctx.fail("*", "identity", f"{ex_name} 名单拉取失败（fail-closed，跳过名单缺失禁用判定）: {err}")

    if ctx.targets is not None:
        candidates = list(ctx.targets)
    else:
        # identity 域池 = 全部库内行 ∪ 名单并集（新码建档）
        candidates = sorted(set(stock_store.list_pool_codes(enabled=None)) | set(known.keys()))

    for code in candidates:
        if not ctx.unit_due(code, "identity"):
            ctx.skip()
            continue
        try:
            if code in known:
                row = known[code]
                outcome = stock_store.apply_identity(
                    code,
                    row["name"],
                    row["exchange"],
                    row["ipo_date"],
                    row["board"],
                    row["industry_l1"],
                    in_list=True,
                )
                ctx.count(outcome)
                ctx.mark_done(code, "identity")
            elif fail_closed:
                # 拿不全名单就不做禁用判定（R 风险条目：fail-closed）
                ctx.skip()
            else:
                outcome = stock_store.apply_identity(
                    code, "", "", None, "", "", in_list=False
                )
                ctx.count(outcome)
                ctx.mark_done(code, "identity")
        except Exception as e:
            ctx.fail(code, "identity", e)


# ---------------------------------------------------------------------------
# 档案域（巨潮 16 列）
# ---------------------------------------------------------------------------


def _fetch_profile(ak, code: str) -> dict:
    """巨潮个股档案 -> {stock 列: 值}（缺列置默认值）+ _industry 原始行业值。"""
    df = _fetch_with_retry(
        ak.stock_profile_cninfo, symbol=code_to_bare(code), retries=2, alternate_direct=False
    )
    if df is None or len(df) == 0:
        raise ValueError("cninfo profile empty")
    row = df.iloc[0].to_dict()
    cols = list(df.columns)
    out: dict[str, Any] = {}
    for field, candidates in _PROFILE_COL_CANDIDATES.items():
        col = _pick_col(cols, *candidates)
        if field == "found_date":
            out[field] = _to_date(_cell(row, col)) if col else None
        else:
            out[field] = _to_str(_cell(row, col, ""))
    # 身份字段（代码/简称/上市日期/交易所/板块）一律不写；行业列留给行业降级域用
    ind_col = _pick_col(cols, "所属行业", "行业")
    out["_industry"] = _to_str(_cell(row, ind_col, ""))
    return out


def _sync_profile(ctx: _SyncCtx, ak) -> None:
    for code in ctx.pool_codes(enabled_only=True):
        if not ctx.unit_due(code, "profile"):
            ctx.skip()
            continue
        try:
            data = _fetch_profile(ak, code)
            ok = stock_store.apply_profile(code, **{k: v for k, v in data.items() if k != "_industry"})
            if not ok:
                ctx.skip()  # 股票池边界：行不存在不写
            else:
                ctx.count("updated")
                ctx.mark_done(code, "profile")
        except Exception as e:
            ctx.fail(code, "profile", e)
        if ctx.sleep > 0:
            time.sleep(ctx.sleep)


# ---------------------------------------------------------------------------
# 行业域（M2M 探测 + 单值降级，D4）
# ---------------------------------------------------------------------------


def _probe_push2(ctx: _SyncCtx, ak) -> tuple[bool, list[str]]:
    """每次 sync 运行探测一次东财行情网关（stock_board_industry_name_em）。

    成功缓存 push2_ok=True 与板块稳定序；失败返回 (False, [])，由调用方降级。
    """
    if ctx._push2_ok is not None:
        return ctx._push2_ok, ctx._push2_boards or []
    try:
        df = _fetch_with_retry(ak.stock_board_industry_name_em, retries=3)
        cols = list(df.columns)
        name_col = _pick_col(cols, "板块名称", "名称")
        code_col = _pick_col(cols, "板块代码", "代码")
        if name_col is None:
            raise ValueError(f"industry boards: 板块名称列缺失，实际列={cols}")
        # 板块遍历稳定序：优先按板块代码排序，无代码列则按名称
        if code_col is not None:
            df = df.sort_values(by=code_col, kind="mergesort")
        else:
            df = df.sort_values(by=name_col, kind="mergesort")
        boards = [_to_str(v) for v in df[name_col].tolist() if _to_str(v)]
        ctx._push2_ok = True
        ctx._push2_boards = boards
        return True, boards
    except Exception as e:
        log.warning("push2 probe failed: %s", e)
        ctx._push2_ok = False
        ctx._push2_boards = []
        return False, []


def _fetch_board_cons(ak, board_name: str) -> list[str]:
    """单板块成分 -> 归一 code 列表。"""
    df = _fetch_with_retry(
        ak.stock_board_industry_cons_em, symbol=board_name, retries=3
    )
    cols = list(df.columns)
    code_col = _pick_col(cols, "代码", "证券代码", "code", "CODE")
    if code_col is None:
        raise ValueError(f"industry cons({board_name}): 代码列缺失，实际列={cols}")
    codes = []
    for v in df[code_col].tolist():
        nc = normalize_code(v)
        if nc is not None:
            codes.append(nc)
    return codes


def _sync_industry(ctx: _SyncCtx, ak) -> None:
    pool = ctx.pool_codes(enabled_only=True)
    targets_due = [c for c in pool if ctx.unit_due(c, "industry")]
    for _ in range(len(pool) - len(targets_due)):
        ctx.skip()
    if not targets_due:
        return  # 未到期：不发起任何数据源请求（含 push2 探测）

    ok, boards = _probe_push2(ctx, ak)

    if ok:
        # M2M：code -> [行业名]（板块遍历稳定序，rank=0 起，首行主行业）
        code_industries: dict[str, list[str]] = {}
        for board_name in boards:
            try:
                cons_codes = _fetch_board_cons(ak, board_name)
            except Exception as e:
                ctx.fail("*", "industry", f"板块 {board_name} 成分拉取失败: {e}")
                continue
            for code in cons_codes:
                lst = code_industries.setdefault(code, [])
                if board_name not in lst:
                    lst.append(board_name)
            if ctx.sleep > 0:
                time.sleep(ctx.sleep)

        for code in targets_due:
            industries = code_industries.get(code)
            if not industries:
                # 板块成分中无此码：本单元处理完毕（无数据不写行）
                ctx.skip()
                ctx.mark_done(code, "industry")
                continue
            rows = [
                {"name": n, "rank": i, "is_primary": i == 0}
                for i, n in enumerate(industries)
            ]
            try:
                ok_write = stock_store.apply_industries(code, rows)
                if not ok_write:
                    ctx.skip()
                else:
                    ctx.count("updated")
                    ctx.mark_done(code, "industry")
            except Exception as e:
                ctx.fail(code, "industry", e)
        return

    # 降级：逐股巨潮档案行业列单值（rank=0、主行业）
    ctx.summary["degraded"] = True
    log.warning("push2 unavailable, industry degraded to cninfo single value")
    for code in targets_due:
        try:
            data = _fetch_profile(ak, code)
            ind = data.get("_industry", "")
            rows = [{"name": ind, "rank": 0, "is_primary": True}] if ind else []
            ok_write = stock_store.apply_industries(code, rows)
            if not ok_write:
                ctx.skip()
            else:
                ctx.count("updated")
                ctx.mark_done(code, "industry")
        except Exception as e:
            ctx.fail(code, "industry", e)
        if ctx.sleep > 0:
            time.sleep(ctx.sleep)


# ---------------------------------------------------------------------------
# 快照域（腾讯全市场，8 列）
# ---------------------------------------------------------------------------


def _sync_snapshot(ctx: _SyncCtx, ak) -> None:
    pool = ctx.pool_codes(enabled_only=True)
    if not any(ctx.unit_due(c, "snapshot") for c in pool):
        for _ in pool:
            ctx.skip()
        return

    snapshot_at = datetime.now(timezone.utc)
    df = _fetch_with_retry(ak.stock_zh_a_spot_tx, retries=3)
    cols = list(df.columns)
    code_col = _pick_col(cols, "code", "代码", "证券代码")
    if code_col is None:
        raise ValueError(f"snapshot: 代码列缺失，实际列={cols}")
    picked = {k: _pick_col(cols, *cands) for k, cands in _SNAPSHOT_COL_CANDIDATES.items()}

    pool_set = set(pool)
    seen: set[str] = set()
    for _, row in df.iterrows():
        code = normalize_code(row.get(code_col))
        if code is None:
            raw = row.get(code_col)
            if raw is not None and _to_str(raw):
                ctx.fail(str(raw), "snapshot", "un-normalizable code")
            continue
        if code not in pool_set or code in seen:
            continue
        seen.add(code)
        if not ctx.unit_due(code, "snapshot"):
            ctx.skip()
            continue
        try:
            # 源列缺失的字段写 NULL，不得编造
            values = {k: (_to_num(row.get(col)) if col else None) for k, col in picked.items()}
            ok = stock_store.apply_snapshot(code, snapshot_at=snapshot_at, **values)
            if not ok:
                ctx.skip()
            else:
                ctx.count("updated")
                ctx.mark_done(code, "snapshot")
        except Exception as e:
            ctx.fail(code, "snapshot", e)


# ---------------------------------------------------------------------------
# 财务域（东财三表 JSONB，D4）
# ---------------------------------------------------------------------------


def _keep_report_period(report_date: Optional[date]) -> bool:
    """期数策略：年报（12 月）全历史保留；非年报仅保留近 10 年。"""
    if report_date is None:
        return False
    if report_date.month == 12:
        return True
    today = date.today()
    try:
        cutoff = today.replace(year=today.year - 10)
    except ValueError:  # 2 月 29
        cutoff = today.replace(year=today.year - 10, day=28)
    return report_date >= cutoff


def _rows_to_financial(
    df, statement_type: str, whitelist: frozenset[str]
) -> list[dict]:
    """东财报表 DataFrame -> [{report_date, notice_date, report_type, report_name, data}]。"""
    cols = list(df.columns)
    rd_col = _pick_col(cols, "REPORT_DATE", "报告日")
    if rd_col is None:
        raise ValueError(f"financial({statement_type}): REPORT_DATE 列缺失，实际列={cols}")
    nt_col = _pick_col(cols, "NOTICE_DATE", "公告日期")
    rt_col = _pick_col(cols, "REPORT_TYPE", "类型")
    rn_col = _pick_col(cols, "REPORT_DATE_NAME", "报告名称")
    # data 只存白名单键 ∩ 返回列
    data_cols = [c for c in cols if c in whitelist]

    out = []
    for _, row in df.iterrows():
        report_date = _to_date(row.get(rd_col))
        if report_date is None or not _keep_report_period(report_date):
            continue
        data = {c: _json_val(row.get(c)) for c in data_cols}
        out.append(
            {
                "statement_type": statement_type,
                "report_date": report_date,
                "notice_date": _to_date(row.get(nt_col)) if nt_col else None,
                "report_type": _to_str(row.get(rt_col)) if rt_col else "",
                "report_name": _to_str(row.get(rn_col)) if rn_col else "",
                "data": data,
            }
        )
    return out


def _fetch_financial_em(ak, code: str) -> tuple[dict[str, list[dict]], list[tuple[str, Any]]]:
    """东财 datacenter 三表逐股（主源）-> (成功表 {stmt: rows}, 失败表 [(stmt, err)])。

    三表全部抛异常时 result 为空，由调用方决定是否走新浪备源（仅全失败才备源）。
    """
    symbol = code_to_ak_symbol(code)
    result: dict[str, list[dict]] = {}
    errors: list[tuple[str, Any]] = []
    fetchers = (
        (STMT_BALANCE, ak.stock_balance_sheet_by_report_em),
        (STMT_INCOME, ak.stock_profit_sheet_by_report_em),
        (STMT_CASHFLOW, ak.stock_cash_flow_sheet_by_report_em),
    )
    for stmt_type, fn in fetchers:
        try:
            df = _fetch_with_retry(fn, symbol=symbol, retries=2, alternate_direct=True)
            result[stmt_type] = _rows_to_financial(df, stmt_type, FINANCIAL_WHITELIST)
        except Exception as e:
            errors.append((stmt_type, e))
    return result, errors


def _fetch_financial_sina(ak, code: str) -> dict[str, list[dict]]:
    """新浪备源（东财三接口都抛异常时兜底），列名映射尽力而为。"""
    bare = code_to_bare(code)
    result: dict[str, list[dict]] = {}
    for stmt_type, sina_symbol in _SINA_STMT_SYMBOLS.items():
        df = _fetch_with_retry(
            ak.stock_financial_report_sina,
            stock=bare,
            symbol=sina_symbol,
            retries=2,
            alternate_direct=False,
        )
        cols = list(df.columns)
        rd_col = _pick_col(cols, "报告日", "REPORT_DATE")
        if rd_col is None:
            raise ValueError(f"sina financial({stmt_type}): 报告日列缺失，实际列={cols}")
        out = []
        for _, row in df.iterrows():
            report_date = _to_date(row.get(rd_col))
            if report_date is None or not _keep_report_period(report_date):
                continue
            data = {}
            notice_date = None
            report_type = ""
            for col in cols:
                key = _SINA_COL_MAP.get(str(col))
                if key is None or key not in FINANCIAL_WHITELIST:
                    continue
                val = _json_val(row.get(col))
                if key == "NOTICE_DATE":
                    notice_date = _to_date(row.get(col))
                    data[key] = val
                elif key == "REPORT_TYPE":
                    report_type = _to_str(row.get(col))
                    data[key] = val
                else:
                    data[key] = val
            out.append(
                {
                    "statement_type": stmt_type,
                    "report_date": report_date,
                    "notice_date": notice_date,
                    "report_type": report_type,
                    "report_name": "",
                    "data": data,
                }
            )
        result[stmt_type] = out
    return result


def _sync_financial(ctx: _SyncCtx, ak) -> None:
    for code in ctx.pool_codes(enabled_only=True):
        if not ctx.unit_due(code, "financial"):
            ctx.skip()
            continue
        try:
            stmts, em_errors = _fetch_financial_em(ak, code)
            if em_errors and not stmts:
                # 东财三接口都抛异常 → 新浪备源（列名映射兜底，尽力而为）
                log.info("[%s] em financial all failed (%s), fallback to sina", code, em_errors)
                stmts = _fetch_financial_sina(ak, code)
                em_errors = []
            in_pool = True
            for rows in stmts.values():
                for row in rows:
                    ok = stock_store.upsert_financial(
                        code,
                        row["statement_type"],
                        row["report_date"],
                        notice_date=row["notice_date"],
                        report_type=row["report_type"],
                        report_name=row["report_name"],
                        data=row["data"],
                    )
                    if not ok:
                        in_pool = False
            if not in_pool:
                ctx.skip()  # 股票池边界
                continue
            if em_errors:
                # 部分表失败：已成功表的行保留，单元水位不写（下轮补拉），失败计入明细
                for stmt_type, err in em_errors:
                    ctx.fail(code, "financial", f"{stmt_type}: {err}")
                continue
            ctx.count("updated")
            ctx.mark_done(code, "financial")
        except Exception as e:
            ctx.fail(code, "financial", e)
        if ctx.sleep > 0:
            time.sleep(ctx.sleep)


# ---------------------------------------------------------------------------
# 股东户数域（近 1 年，D6）
# ---------------------------------------------------------------------------


def _sync_holders(ctx: _SyncCtx, ak) -> None:
    pool = ctx.pool_codes(enabled_only=True)
    if not any(ctx.unit_due(c, "holders") for c in pool):
        for _ in pool:
            ctx.skip()
        return

    # 单次全市场抓取。注意：akshare stock_zh_a_gdhs() 默认 symbol 硬编码为某一历史季度
    # （实测 "20230930"），直接调用会被近 1 年过滤清空；symbol="最新" 为全市场最新披露切片。
    df = _fetch_with_retry(
        ak.stock_zh_a_gdhs, symbol="最新", retries=3, alternate_direct=True
    )
    cols = list(df.columns)
    code_col = _pick_col(cols, "代码", "证券代码", "code", "CODE")
    if code_col is None:
        raise ValueError(f"holders: 代码列缺失，实际列={cols}")
    picked = {k: _pick_col(cols, *cands) for k, cands in _HOLDERS_COL_CANDIDATES.items()}
    stat_col = picked.get("stat_date")

    cutoff_date = date.today() - timedelta(days=365)
    pool_set = set(pool)
    seen: set[str] = set()
    for _, row in df.iterrows():
        code = normalize_code(row.get(code_col))
        if code is None:
            raw = row.get(code_col)
            if raw is not None and _to_str(raw):
                ctx.fail(str(raw), "holders", "un-normalizable code")
            continue
        if code not in pool_set or code in seen:
            continue
        seen.add(code)
        if not ctx.unit_due(code, "holders"):
            ctx.skip()
            continue
        try:
            stat_date = _to_date(row.get(stat_col)) if stat_col else None
            if stat_date is None or stat_date < cutoff_date:
                # 仅写入近 1 年报告期数据：窗口外/无统计截止日不写行
                ctx.mark_done(code, "holders")
                ctx.skip()
                continue
            ok = stock_store.upsert_holder_num(
                code,
                stat_date,
                notice_date=_to_date(row.get(picked["notice_date"])) if picked.get("notice_date") else None,
                holder_num=_to_int(row.get(picked["holder_num"])) if picked.get("holder_num") else None,
                prev_holder_num=_to_int(row.get(picked["prev_holder_num"])) if picked.get("prev_holder_num") else None,
                holder_num_change=_to_int(row.get(picked["holder_num_change"])) if picked.get("holder_num_change") else None,
                holder_num_change_pct=_to_num(row.get(picked["holder_num_change_pct"])) if picked.get("holder_num_change_pct") else None,
                avg_hold_mv=_to_num(row.get(picked["avg_hold_mv"])) if picked.get("avg_hold_mv") else None,
                avg_hold_shares=_to_num(row.get(picked["avg_hold_shares"])) if picked.get("avg_hold_shares") else None,
                total_share=_to_num(row.get(picked["total_share"])) if picked.get("total_share") else None,
            )
            if not ok:
                ctx.skip()
            else:
                ctx.count("updated")
                ctx.mark_done(code, "holders")
        except Exception as e:
            ctx.fail(code, "holders", e)


# ---------------------------------------------------------------------------
# 编排（D5/D9）
# ---------------------------------------------------------------------------

_DOMAIN_RUNNERS: dict[str, Callable[[_SyncCtx, Any], None]] = {
    "identity": _sync_identity,
    "profile": _sync_profile,
    "industry": _sync_industry,
    "snapshot": _sync_snapshot,
    "financial": _sync_financial,
    "holders": _sync_holders,
}


def sync(
    codes: Optional[list[str]] = None,
    domains: Optional[list[str]] = None,
    force: bool = True,
    sleep: float = 0.4,
    verbose: bool = False,
    job_id: Optional[int] = None,
) -> dict:
    """同步入口（脚本与 Web 共用）。

    返回 {created, updated, disabled, skipped, degraded, failed: [(code, domain, error)], domains_run}。
    单元 = (code, domain)；域间互不阻塞；逐单元失败隔离。
    KeyboardInterrupt / 异常：sync_job 置 interrupted / failed（部分汇总持久化）后上抛。
    """
    _clean_proxy_env()
    import akshare as ak  # 延迟导入：先清代理环境

    if verbose:
        logging.getLogger("meta_sync").setLevel(logging.DEBUG)

    if domains is None:
        run_domains = list(DOMAIN_ORDER)
    else:
        wanted = set(domains)
        unknown = wanted - set(DOMAIN_ORDER)
        if unknown:
            raise ValueError(f"unknown domains: {sorted(unknown)}")
        run_domains = [d for d in DOMAIN_ORDER if d in wanted]

    scope = "market" if codes is None else "single"
    now = datetime.now(timezone.utc)
    summary = _new_summary(run_domains)

    # 目标代码归一（用户输入与源数据同规则；无法归一计入 failed）
    targets: Optional[list[str]] = None
    if codes is not None:
        targets = []
        for raw in codes:
            nc = normalize_code(raw)
            if nc is None:
                summary["failed"].append((str(raw), "*", f"un-normalizable code: {raw!r}"))
            else:
                targets.append(nc)

    # 孤儿 running 任务 → interrupted（重启遗留）
    stock_store.mark_orphan_jobs_interrupted(keep_id=job_id)

    # 续传 cutoff（D9）：force=True 且最近同域任务为 interrupted → 从其 started_at 续传
    cutoff = now
    if force:
        last = stock_store.get_last_sync_job(domains=run_domains)
        if last and last.get("status") == "interrupted" and last.get("started_at"):
            cutoff = last["started_at"]
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            log.info("resume mode: cutoff = %s (interrupted job #%s)", cutoff, last.get("id"))

    if job_id is None:
        job_id = stock_store.create_sync_job(run_domains, scope, force)

    if targets is not None and not targets:
        # 全部 code 无法归一：无单元可执行，不再发起任何网络请求
        stock_store.finish_sync_job(job_id, "done", summary)
        return summary

    ctx = _SyncCtx(
        now=now, force=force, cutoff=cutoff, sleep=sleep, targets=targets, summary=summary
    )

    try:
        for domain in run_domains:
            runner = _DOMAIN_RUNNERS[domain]
            try:
                runner(ctx, ak)
            except Exception as e:  # 市场级抓取失败：该域整体入 failed
                summary["failed"].append(("*", domain, f"domain fetch failed: {e}"))
                log.exception("domain %s failed", domain)
        stock_store.finish_sync_job(job_id, "done", summary)
    except KeyboardInterrupt:
        stock_store.finish_sync_job(job_id, "interrupted", summary)
        raise
    except Exception:
        stock_store.finish_sync_job(job_id, "failed", summary)
        raise

    return summary


def due_domains(domains: Optional[list[str]] = None, now: Optional[datetime] = None) -> list[str]:
    """任一池内单元到期即算该域到期（供调度用）。

    池 = stock 表 enabled=true 的 code（identity 域用全部行）。
    """
    now = now or datetime.now(timezone.utc)
    check_list = list(domains) if domains else list(DOMAIN_ORDER)
    result = []
    for domain in check_list:
        if domain not in DOMAIN_INTERVALS:
            continue
        codes = stock_store.list_pool_codes(enabled=None if domain == "identity" else True)
        if not codes:
            continue
        wms = stock_store.get_watermarks(codes, domain)
        interval = DOMAIN_INTERVALS[domain]
        for code in codes:
            wm = wms.get(code)
            if wm is None:
                result.append(domain)
                break
            if wm.tzinfo is None:
                wm = wm.replace(tzinfo=timezone.utc)
            if (now - wm).total_seconds() >= interval:
                result.append(domain)
                break
    return result

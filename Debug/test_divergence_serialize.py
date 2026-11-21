# -*- coding: utf-8 -*-
"""chan-recent-divergence-mark 任务 1.2 验证：/api/klines 序列化冒烟（DuckDB 离线）。

断言：
  - bi[-1].is_divergence 存在且为 True/False/None 之一
  - bi[:-1] 无该键
  - seg[-1].is_divergence 存在且合法
  - 中间反向笔不参与比较（口径由 cal_last_divergence 单测覆盖，此处只验契约）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ChanAnalyse.Chan import CChan                    # noqa: E402
from ChanAnalyse.ChanConfig import CChanConfig        # noqa: E402
from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE  # noqa: E402
from WebAPI.serializer import serialize_chan          # noqa: E402


def main():
    conf = CChanConfig({"trigger_step": False, "kl_data_check": False})
    chan = CChan(code="sz.000001", data_src="custom:DuckDBAPI.CDuckDB",
                 lv_list=[KL_TYPE.K_DAY], config=conf,
                 autype=AUTYPE.QFQ, begin_time="2024-01-01")
    result = serialize_chan(chan, KL_TYPE.K_DAY)

    bi = result["bi"]
    seg = result["seg"]
    assert len(bi) >= 3, f"笔数不足: {len(bi)}"
    assert "is_divergence" in bi[-1], "末尾笔缺 is_divergence 键"
    assert bi[-1]["is_divergence"] in (True, False, None), \
        f"非法取值: {bi[-1]['is_divergence']!r}"
    for i, item in enumerate(bi[:-1]):
        assert "is_divergence" not in item, f"中间笔 #{i} 不应携带 is_divergence"

    if len(seg) >= 3:
        assert "is_divergence" in seg[-1], "末尾段缺 is_divergence 键"
        assert seg[-1]["is_divergence"] in (True, False, None)
        for i, item in enumerate(seg[:-1]):
            assert "is_divergence" not in item, f"中间段 #{i} 不应携带 is_divergence"
    else:
        print(f"（线段数 {len(seg)} < 3，段级断言跳过，字段应为不存在）")
        for i, item in enumerate(seg[:-1]):
            assert "is_divergence" not in item

    print(f"bi[-1].is_divergence  = {bi[-1]['is_divergence']!r}")
    if len(seg) >= 3:
        print(f"seg[-1].is_divergence = {seg[-1]['is_divergence']!r}")
    print(f"笔数 {len(bi)}  段数 {len(seg)}")
    print("[OK] 序列化契约冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

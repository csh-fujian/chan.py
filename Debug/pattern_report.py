# 从批量分析汇总 JSON + PG 生成「按形态类型分组、每类最多 3 个样本」的报告
import json
import sys

sys.path.insert(0, '.')
import psycopg2

META_NAMES = {
    'dark_cloud_cover': '乌云盖顶',
    'shooting_star': '射击之星',
    'hanging_man': '高位吊颈线',
    'high_engulfing': '高位阴包阳',
    'high_engulfing_gap': '高位穿头破脚阴线',
    'w_bottom': 'W底（双重底）',
    'head_shoulders': '头肩底',
    'box_breakout': '箱体突破',
    'ascending_triangle': '上升三角形',
    'low_flag': '低位旗形',
    'v_reversal': 'V形反转',
    'rounding_bottom': '圆弧底',
    'cup_handle': '杯柄形态',
}

conn = psycopg2.connect(host='127.0.0.1', port=5432, dbname='chan', user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("""
    SELECT pattern_type, direction, pattern_date, code, score, qual, invalid, veto
    FROM pattern_signal
    WHERE kl_type='D'
    ORDER BY pattern_type, pattern_date DESC, score DESC
""")
rows = cur.fetchall()
cur.close()
conn.close()

# 按类型分组统计
groups: dict = {}
for pt, direction, date, code, score, qual, invalid, veto in rows:
    groups.setdefault((pt, direction), []).append((date, code, score, qual, invalid, veto))

print(f"总计 {len(rows)} 行，{len(groups)} 个（类型×方向）组合\n")
for (pt, direction), items in sorted(groups.items(), key=lambda kv: (kv[0][1], -len(kv[1]))):
    name = META_NAMES.get(pt, pt)
    dir_label = '买向' if direction == 'buy' else '卖向'
    valid = [x for x in items if not x[4]]
    # 优先取未被否决的样本，其次按日期取最近的
    top = sorted(valid, key=lambda x: (x[5] is not None, -(x[2] or 0)))[:3] if valid else []
    top = sorted(valid, key=lambda x: x[0], reverse=True)[:3]
    print(f"## {dir_label} · {name}（{pt}）— 全库 {len(items)} 次"
          + (f"，有效 {len(valid)} 次" if len(valid) != len(items) else ""))
    for date, code, score, qual, invalid, veto in top:
        veto_note = f"【{veto}】" if veto else ''
        print(f"   - {code}  {date}  分数 {score} {qual or ''} {veto_note}")
    if not top:
        print("   - （全部失效/无有效样本）")
    print()

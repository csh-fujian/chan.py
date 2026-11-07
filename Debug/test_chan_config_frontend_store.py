# -*- coding: utf-8 -*-
"""chan-config-panel —— 前端 store 草稿/档位/overrides 逻辑的离线验证。

`Front/src/stores/chanConfig.ts` 的纯逻辑（`dirtyCount` / `switchPreset` /
`resetToDefaults` / `computeOverrides`）无法在 Python 侧断言，前端又没装
测试框架（package.json 无 vitest）。本脚本用 esbuild 把改写了导入路径的
store 副本打成单文件，在 Node 里跑一组固定场景。

做法：
    1. 后端侧 `build_schema()` 导出真实元数据到临时目录（`schema.json`）
    2. 把 `Front/src/stores/chanConfig.ts` 复制一份，把 `pinia` / `@/api/...`
       的导入改指到 stub（`pinia` 用真的，避免 ref/computed 行为失真）
    3. esbuild bundle → node 运行断言

断言的场景都是**真实踩过或差点踩到的坑**：
    A. `effective` 带后端派生键（`macd_algo-seg`）时，未改动不应被算成脏
    B. `saved.overrides` 里的非 schema 键（分侧后缀）保存时不能被挤掉
    C. 切档位后未改项跟随新档位，且不被写进 overrides
    D. 改一项 → overrides 只含那一项
    E. 恢复默认 = 当前档位基线，档位本身不变
    F. `"inf"` 与 `Infinity` 判为同值
    G. legacy 档下只提交用户真正改过的那一项

运行：
    .venv/Scripts/python.exe Debug/test_chan_config_frontend_store.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

# Windows 控制台默认 GBK，esbuild/node 的错误输出含制表符号时会炸
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from WebAPI.chan_config_schema import build_schema  # noqa: E402
from WebAPI import chan_config_store as store      # noqa: E402

FRONT = os.path.join(ROOT, "Front")
STORE_SRC = os.path.join(FRONT, "src", "stores", "chanConfig.ts")
ESBUILD = os.path.join(FRONT, "node_modules", ".bin", "esbuild.cmd"
                       if os.name == "nt" else "esbuild")

_PASS = 0
_FAIL = 0


def check(label, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK]   {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


STUB_API = """\
export let savedState: any = null
export function __setSaved(v: any) { savedState = v }
export async function getChanConfig() { return savedState }
export async function getChanConfigSchema() { return (globalThis as any).__schema }
export async function saveChanConfig(payload: any) {
  ;(globalThis as any).__lastPayload = payload
  return { version: 1 }
}
"""

STUB_TYPES = """\
export type ChanConfigSchema = any
export type ChanConfigState = any
"""

VERIFY = r"""
import { createPinia, setActivePinia } from 'pinia'
setActivePinia(createPinia())
import { useChanConfigStore } from './store-copy.js'

const schema = (globalThis as any).__schema
let fails = 0
function check(name: string, cond: boolean, extra = '') {
  if (cond) console.log('  [OK]   ' + name)
  else { fails++; console.log('  [FAIL] ' + name + '  ' + extra) }
}

const store = useChanConfigStore()
store.schema = schema
const kb = schema.kernel_defaults

function seed(effective: any, overrides: any, preset = 'standard') {
  store.saved = { effective, overrides, preset, version: 1, initialized: true }
  store.discardDraft()
}

// A. 量能类：effective 只有 schema 键（派生键 macd_algo-seg 由后端在计算出口补，
//    不出现在 effective / overrides 里）。未改动时不应被算成脏。
seed({ ...kb, macd_algo: 'volumn' }, { macd_algo: 'volumn' })
check('A1 量能类：未改动 dirtyCount=0', store.dirtyCount === 0, 'dirty=' + store.dirtyCount)
let ov = store.computeOverrides()
check('A2 未改动时 overrides 保留 macd_algo', ov.macd_algo === 'volumn', JSON.stringify(ov))
check('A3 未改动时 overrides 不含派生键 macd_algo-seg', !('macd_algo-seg' in ov), JSON.stringify(ov))

// B. 非 schema 键保留
seed({ ...kb }, { 'divergence_rate-buy': 0.5 })
ov = store.computeOverrides()
check('B1 非 schema 键在保存时不被挤掉', ov['divergence_rate-buy'] === 0.5, JSON.stringify(ov))
check('B2 未改动时 dirtyCount=0', store.dirtyCount === 0, 'dirty=' + store.dirtyCount)

// C. 切档位
seed({ ...kb }, {}, 'standard')
store.switchPreset('legacy')
const legacy = schema.preset_baselines.legacy
check('C1 切到 legacy 后 draft 等于 legacy 基线', schema.params.every(
  (p: any) => JSON.stringify((store.draft as any)[p.key]) === JSON.stringify(legacy[p.key])),
  'min_zs_cnt draft=' + (store.draft as any).min_zs_cnt + ' want=' + legacy.min_zs_cnt)
ov = store.computeOverrides()
check('C2 切档位后 overrides 为空', Object.keys(ov).length === 0, JSON.stringify(ov))

// D. 改一项
store.setDraftValue('min_zs_cnt', 3)
const only = store.computeOverrides()
check('D1 改一项后 overrides 只含该项',
  JSON.stringify(Object.keys(only)) === '["min_zs_cnt"]', JSON.stringify(only))

// E. 恢复默认
store.resetToDefaults()
check('E1 恢复默认后 draft 等于 legacy 基线', schema.params.every(
  (p: any) => JSON.stringify((store.draft as any)[p.key]) === JSON.stringify(legacy[p.key])))
check('E2 恢复默认保留当前档位', (store.draft as any).bsp_preset === 'legacy')
check('E3 恢复默认后 overrides 为空', Object.keys(store.computeOverrides()).length === 0,
  JSON.stringify(store.computeOverrides()))

// F. inf 编码：字符串 "inf" 与数字 Infinity 判为同值
seed({ ...kb }, {})
const dirtyBefore = store.dirtyCount
store.draft = { ...store.draft, divergence_rate: Infinity }
const dirtyNum = store.dirtyCount
store.draft = { ...store.draft, divergence_rate: 'inf' }
check('F1 字符串 inf 与数字 Infinity 判为同值',
  dirtyNum === store.dirtyCount && dirtyNum - dirtyBefore === 1,
  'before=' + dirtyBefore + ' num=' + dirtyNum + ' str=' + store.dirtyCount)

// G. legacy 档下只提交用户真正改过的那一项
seed({ ...kb }, {}, 'standard')
store.switchPreset('legacy')
store.setDraftValue('bsp1_zero_axis', !legacy.bsp1_zero_axis)
ov = store.computeOverrides()
check('G1 legacy 档只提交用户真正改过的那一项',
  JSON.stringify(Object.keys(ov)) === '["bsp1_zero_axis"]', JSON.stringify(ov))

console.log(fails === 0 ? '__PASS__' : '__FAIL__' + fails)
process.exit(fails === 0 ? 0 : 1)
"""


def main():
    print("=" * 46)
    print(">>> 前端 store 草稿/档位/overrides 逻辑")
    print("=" * 46)

    if not shutil.which("node"):
        print("  [SKIP] 未找到 node，跳过")
        return 0
    if not os.path.exists(ESBUILD):
        print(f"  [SKIP] 未找到 esbuild（{ESBUILD}），先在 Front/ 执行 npm install")
        return 0

    # 临时目录必须建在 Front/ 内：bundle 出来的 ESM 以自身路径为基准解析
    # `vue` / `pinia`，放在系统临时目录里 node 找不到 Front/node_modules。
    tmp = tempfile.mkdtemp(prefix=".tmp_cfg_store_", dir=FRONT)
    try:
        # 1. 真实 schema（含 inf 编码，与 GET /schema 同一条路径）
        schema = store.encode_config(build_schema())
        with open(os.path.join(tmp, "schema.json"), "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False)

        # 2. store 副本：只改导入路径，不动逻辑
        with open(STORE_SRC, encoding="utf-8") as f:
            src = f.read()
        src = src.replace("from 'pinia'", "from 'pinia'")
        src = src.replace("from '@/api/modules/chanConfig'", "from './stub-api.js'")
        src = src.replace("from '@/api/types'", "from './stub-types.js'")
        with open(os.path.join(tmp, "store-copy.ts"), "w", encoding="utf-8") as f:
            f.write(src)

        with open(os.path.join(tmp, "stub-api.ts"), "w", encoding="utf-8") as f:
            f.write(STUB_API)
        with open(os.path.join(tmp, "stub-types.ts"), "w", encoding="utf-8") as f:
            f.write(STUB_TYPES)
        with open(os.path.join(tmp, "verify.ts"), "w", encoding="utf-8") as f:
            f.write(VERIFY)
        with open(os.path.join(tmp, "run.mjs"), "w", encoding="utf-8") as f:
            f.write(
                "import fs from 'node:fs'\n"
                "globalThis.__schema = JSON.parse("
                "fs.readFileSync(new URL('./schema.json', import.meta.url), 'utf8'))\n"
                "await import('./out.mjs')\n"
            )

        # 3. bundle（node 内置模块用 --platform=node 交给 node 解析）
        build = subprocess.run(
            [ESBUILD, os.path.join(tmp, "verify.ts"), "--bundle",
             "--platform=node", "--format=esm",
             f"--outfile={os.path.join(tmp, 'out.mjs')}"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=FRONT,
        )
        if build.returncode != 0:
            print(f"  [FAIL] esbuild 打包失败\n{build.stderr[:2000]}")
            return 1

        run = subprocess.run(
            ["node", os.path.join(tmp, "run.mjs")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        out = (run.stdout or "") + (run.stderr or "")
        # Node 侧自己统计的 PASS/FAIL 已足够；这里转成 Python 的计数
        for line in out.splitlines():
            if line.startswith("  [OK]"):
                check(line[7:].strip(), True)
            elif line.startswith("  [FAIL]"):
                check(line[9:].strip().split("  ")[0], False,
                      line[9:].strip().split("  ", 1)[-1])
            elif line.startswith("__FAIL__"):
                print(f"  [FAIL] Node 侧报告失败数 = {line[8:]}")

        if "__PASS__" not in out and "__FAIL__" not in out:
            print(f"  [FAIL] Node 脚本未正常结束\n{out[:2000]}")
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

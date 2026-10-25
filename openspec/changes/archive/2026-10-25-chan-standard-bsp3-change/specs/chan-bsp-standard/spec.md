# Spec Delta: chan-bsp-standard

## ADDED Requirements

### Requirement: strict_bsp3 的双分支语义差异为规格化行为

`strict_bsp3` 开启时，两条分支 SHALL 采用各自独立的「紧邻一买」判定：三买A 分支判定「中枢的进入笔为一买笔的下一笔」；三买B 分支判定「中枢的离开笔即一买笔」。该差异由两分支中枢位置不同（三买A 锚定下一条线段的中枢、三买B 锚定本线段的中枢）结构性决定，系统 SHALL NOT 以统一两分支条件为目标修改任一侧语义。对外文档（参数说明）SHALL 按分支分别描述两种「紧邻」定义，SHALL NOT 以单一「紧挨着一类买卖点」表述覆盖两分支。该开关默认 SHALL 为 False，标准档输出不受其影响。

#### Scenario: README 按分支描述语义

- **WHEN** 用户查阅买卖点参数文档中的 `strict_bsp3` 说明
- **THEN** 文档分别给出三买A 与三买B 两个分支的判定条件，并注明两分支「紧邻」定义不同

#### Scenario: 开启后两分支按各自条件过滤

- **WHEN** 用户显式设置 `strict_bsp3=True`
- **THEN** 三买A 按「中枢进入笔 == 一买笔 + 1」过滤，三买B 按「中枢离开笔 == 一买笔」过滤，两侧条件不互换、不统一

#### Scenario: 默认关闭不影响输出

- **WHEN** 用户未配置 `strict_bsp3`
- **THEN** 标准档六类买卖点输出与该开关取值无关

## Purpose

定义策略信号能力的参数声明类型体系扩展：params_schema 新增 enum 类型（枚举选项集），后端校验与前端声明驱动渲染同步支持。本文件为对 `strategy-signal` 能力的增量修改，基于 strategy-task-redesign 归档后的任务语义版本。

## MODIFIED Requirements

### Requirement: 策略定义注册表
系统 SHALL 维护策略定义注册表，每个策略定义 SHALL 声明：策略标识、显示名称、引擎标识、参数模式（params_schema：每个参数的类型/默认值/范围/说明 desc，类型支持 int/float/**enum——enum 参数声明枚举选项集 options（每项含取值 value 与显示标签 label），校验取值必须在选项集内**）、状态集合（states：该策略信号生命周期中可能出现的状态列表）、表格列声明（columns：信号列表页的私有列）、任务详情声明（detail_schema：任务详情页的展示积木块组合，见 strategy-task 能力）。策略定义 SHALL 由代码注册（随版本发布），用户 SHALL NOT 能增删策略定义。注册新策略定义时 detail_schema 为必填声明。

#### Scenario: 查看策略列表
- **WHEN** 用户打开策略任务页
- **THEN** 侧栏按策略大类分组展示全部已注册策略定义，每个定义下展示其任务节点

#### Scenario: 新策略接入零前端改动
- **WHEN** 后端注册一个新的策略定义（含 params_schema/states/columns/detail_schema 声明）
- **THEN** 前端策略任务页无需代码修改即可展示该策略：参数表单（int/float 输入控件、enum 下拉选择）、状态标签、表格私有列、任务详情均由声明驱动渲染

#### Scenario: 参数说明悬浮
- **WHEN** 用户在任务创建表单中将鼠标悬浮于某参数名旁的说明图标
- **THEN** 展示该参数的说明文案（来自 params_schema 的 desc 声明）

#### Scenario: enum 参数渲染
- **WHEN** 任务创建表单渲染一个 type 为 enum 的参数
- **THEN** 以选项下拉（options 声明的标签集）呈现，缺省选中声明的 default

#### Scenario: enum 参数非法被拒绝
- **WHEN** 用户提交的 enum 参数取值不在声明的选项集内（或绕过前端直接提交任意字符串）
- **THEN** 系统拒绝创建并返回校验错误

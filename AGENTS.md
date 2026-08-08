# 项目 Agent 规范

## 边界

- 本目录是 `subagent-governance` 的开发仓库和唯一开发源。
- 日常开发只能修改本仓库，不得直接修改 `~/plugins/subagent-governance` 或 `~/.codex/plugins/cache/personal/subagent-governance`。
- 只有用户明确要求“发布、安装或更新稳定版”时，才允许写入稳定发布源、Marketplace、运行缓存、Hook 信任状态或 Codex Manager Registry。
- 开发仓库、稳定发布源和运行缓存之间不得创建符号链接。
- 不修改第三方 Skill；相关兼容性只记录在本项目文档中。

## 实现原则

- 保留原生 `spawn_agent`，不引入第二套编排平台。
- Hook 只做用户级协作护栏，不宣称替代沙箱、批准机制或平台内部消息投递。
- 优先修复会导致错误阻断、错误终态或无法恢复的状态机问题。
- 对兼容调用默认降级保护，避免治理组件故障时禁用原生子 Agent。
- 协议、Skill、Hook 和 Schema 应尽量共享同一语义来源，避免重复规则漂移。

## 验证

- 修改运行时代码时，先补能稳定复现问题的测试。
- 至少运行：
  - `python3 -m unittest discover -s tests -v`
  - `python3 -m py_compile scripts/subagent_governance.py`
  - Plugin validator
  - Skill validator（修改 Skill 时）
- 发布前还要验证开发仓库与稳定发布源不是同一路径或符号链接，并检查稳定源与目标运行缓存哈希。

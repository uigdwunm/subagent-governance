# 上下文完备性契约

## 目标

受治理派发必须显式覆盖任务目标、背景、范围、禁止事项、完成条件、证据、当前状态、任务特征、模型、推理强度、对话继承和材料依赖。插件只检查字段与材料事实，不分析自然语言是否正确、充分或可信。

本改进解决的是“派发方声明的必需材料没有真正到达目标基线”，不宣称自动发现所有潜在依赖。

## TaskContract 输入规则

TaskContract 的全部输入字段必须出现：

- `task_features` 在所有治理等级下都是完整对象。显式等级仍不自动升降；`auto` 才使用这些结构化事实解析等级。
- `model`、`reasoning_effort` 必须显式出现，JSON `null` 表示继承原生默认值。
- 允许为空的数组必须显式提供 `[]`；允许为空的文本使用 JSON `null`。
- `relevant_files[]` 只提供定位提示，不建立可达性保证。
- `context_manifest` 必须选择 `none|declared`，不能缺省。

生成器继续独占 `resolved_mode` 和 `resolution_reason`，固定渲染终态通知义务；模型不重复填写这些派生或固定事实。

## Context Manifest

无材料依赖：

```json
{"mode": "none"}
```

有材料依赖：

```json
{
  "mode": "declared",
  "workspace_root": "/absolute/repository/root",
  "baseline": {
    "kind": "git_commit",
    "revision": "40-or-64-character-full-commit-oid"
  },
  "required_paths": [
    {"path": "docs/task.md", "type": "file"},
    {"path": "src/selection", "type": "directory"}
  ]
}
```

`working_tree` baseline 的 `revision` 固定为 `null`。所有 path 使用规范 POSIX 相对路径，禁止绝对路径、反斜杠、空段、`.`、`..`、重复项和控制字符。工作区路径只在声明 root 内解析。

## 验证事实

- `git_commit` 要求工作区是声明的 Git 根目录、revision 是完整 commit OID、当前 HEAD 等于该 commit、每个路径存在于该 commit 且 blob/tree 类型匹配，并且声明路径没有 tracked/untracked 差异；生成器计算 object ID。目录下 ignored 内容不作为 commit 事实，精确依赖优先逐文件声明。
- `working_tree` 要求路径存在且类型匹配；文件生成 SHA-256，目录记录自身 mtime。
- 初始 spawn 和 spawn retry 在 preparation 与 PreToolUse claim 两处验证并比较同一快照。
- business resume 在 communication preparation 与 follow-up claim 两处执行相同校验。
- 确定性缺失、类型错误或快照变化阻止 governed 操作且不消费派发凭证。
- 验证器只读取 manifest 中声明的路径，不扫描 transcript、summary、历史 final、工作区其他路径或业务正文。

内部 Hook 异常继续遵守项目既有 fail-open 边界；显式生成器无法验证声明依赖时返回失败，不调用原生工具。

## 运输边界

原生 `spawn_agent` 自动使用双门禁。`--verify-context-manifest` 提供无 Session、无 PreparedContract、无状态写入的运输中立预检，可在 `create_thread` 等独立任务交接前使用，但它不能拦截这些平台工具，也不治理其等待、恢复或关闭生命周期。

## 非目标

- 不评价 objective、background、scope、completion 或 evidence 的自然语言质量。
- 不检查关键词、长度启发式、固定标题或终态卡。
- 不自动扫描仓库寻找模型可能遗漏的文件。
- 不重新引入 TaskResult、deliverable contract、业务 acceptance 或结果文件。

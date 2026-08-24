# P13：运行缓存双版本滚动保留与安装事务收口

状态：已确认方案，等待独立实现对话执行。

前置：P12-A 开发仓库实现与本地门禁已通过；执行本方案时不得安装、发布或写入稳定源/运行缓存。

执行配置：`gpt-5.6-terra`、推理强度 `high`。

## 目标

修复本地插件更新时原生 `codex plugin add` 删除安装前运行缓存，导致尚未重启的旧对话继续从旧版本 Hook 路径执行时出现 `ENOENT` 的问题。

安装成功后的缓存集合采用最多两个完整 Manifest 版本目录：

- `current`：本次目标版本，必须与稳定测试源 version 和 tree digest 精确一致；
- `retained_previous`：安装前由 `codex plugin list` 确认的 registered/current 完整版本，用于尚未重启的上一代对话继续执行 Skill、Hook 和脚本；
- 更早的 compatibility cache 在下一次受确认的更新中删除。

本方案只改变安装、安装检查和发布文档，不改变插件业务治理状态机、Hook 路由、Skill 协议或正常子 Agent 流程。

## 已核实事实

### 现有路径已经按完整版本隔离

当前 Codex 运行缓存结构已经是：

```text
~/.codex/plugins/cache/<marketplace>/subagent-governance/<full-manifest-version>/
```

因此不再增加诸如 `<version>/<version>/...` 的重复嵌套层。本方案所说“增加版本层”的落地含义，是把现有 `<full-manifest-version>` 目录正式作为不可变缓存代际，并调整保留策略。

### 删除旧版本的主体不是仓库 cleanup

最近一次真实安装事务记录显示：

- 安装前旧 registered/current cache 已进入事务快照；
- 仓库安装器报告 `removed_cache_entries=[]`；
- 原生命令返回后运行目录只剩目标版本；
- 旧版本是在原生 `codex plugin add` 执行期间消失，而不是安装器成功清理阶段删除。

所以仅把安装器 cleanup 从“删除全部旧 cache”改成“不删除 previous”不足以修复问题。安装器必须能够从事务快照恢复原生命令已经删除的精确 previous cache。

### 当前检查器与文档要求单缓存

`scripts/check_installation.py` 当前把目标版本之外的所有条目都记为 `unexpected_extra_cache`，并以 `single_current_cache` 作为健康条件。`docs/architecture.md`、`docs/release-process.md` 和 P10 也写明成功后只保留目标 cache。这些语义必须与实现一起改为双版本滚动模型，不能只改单一脚本。

## 范围

必须修改：

- `scripts/reinstall_plugin.py`
- `scripts/check_installation.py`
- `tests/test_release_tools.py`
- `docs/architecture.md`
- `docs/release-process.md`
- `docs/improvement-plans/P10-authorized-install-and-real-validation.md`
- `docs/platform-validation.md` 中与安装器能力或待验证范围相关的表述

按实际引用同步修改：

- 其他仍声明“成功后只有一个 cache”或把 previous cache 视为异常的仓库文档/测试；
- 安装事务报告字段的测试 fixture。

禁止：

- 安装或更新本机插件；
- 生成 cachebuster；
- 写入稳定测试源、Marketplace、Registry、Hook trust 或运行缓存；
- 修改治理状态机、Hook 事件逻辑、Skill 协议或 P12-A probe 行为；
- 直接修改 plugin-creator 系统 Skill；
- 依赖目录名排序、mtime 或语义版本比较推测 current/previous；
- 为兼容旧事务报告保留含混的单缓存语义。

## 核心模型

### 角色由身份事实决定，不由排序决定

安装前：

- `previous_version` 必须由操作者从 `codex plugin list` 读取并通过 `--previous-version` 精确传入；
- `previous_version` 必须对应安装前缓存集合中的普通目录；
- 如果安装前没有 cache，则不允许传 `--previous-version`，视为 initial install；
- `target_version` 必须来自稳定测试源 Manifest 或显式相同值，且不得等于 `previous_version`。

安装后：

- `current` 固定为 `target_version`；
- `retained_previous` 固定为安装前的 `previous_version`，不存在 previous 时为 `null`；
- 其他安装前或安装过程中出现的 cache 都不是 current/previous 身份来源。

安装检查：

- current 由稳定源 Manifest full version 确定；
- registered/current 身份仍需单独由 `codex plugin list` 验证，不能从两个目录中猜；
- retained previous 只允许零或一个，检查器不得把目录排序后的“另一个”描述为平台 registered previous，只能描述为 `retained_previous_cache`；
- 目标 cache 才与稳定源做 tree digest 相等检查；retained previous 只验证为安全普通目录、Manifest version 等于目录名且 tree 可安全计算。

### 健康缓存集合

允许：

```text
initial install: {target}
first update:    {previous, target}
next update:     {previous, target}  # 上一次 target 成为本次 previous
```

拒绝：

- 缺少 target；
- target 不是普通目录、是 symlink、owner/permissions 不安全；
- target Manifest version 或 digest 与稳定源不一致；
- previous 不是普通目录、是 symlink、Manifest version 与目录名不一致或 tree 不可安全读取；
- target 之外存在两个或更多缓存目录；
- cache parent 中存在非目录、symlink 或其他非缓存条目；
- current 与 previous 身份相同。

## 安装事务设计

### 1. 安装前门禁

保持现有 OS file lock、owner/permission、ordinary-directory、same-filesystem、稳定源 digest 和未完成事务恢复门禁。

新增或明确：

- 快照必须覆盖安装前完整 cache 集合，而不只是 previous；
- snapshot manifest 必须记录每个 cache 的 name/digest、精确 `previous_version` 和 `target_version`；
- previous cache 的 snapshot digest 必须在调用原生命令前复核；
- 安装前已有 retained compatibility cache 时，说明这是第二次或更后的滚动更新。命令必须显式传入 `--confirm-previous-sessions-restarted`，否则在调用原生命令前拒绝；该确认只表示操作者已经重启/关闭依赖最老 cache 的会话，不表示安装器检测到了会话状态；
- initial install 或只有一个安装前 current cache 时不需要该确认参数。

此门槛不阻止用户按滚动策略更新，但避免脚本在无提示情况下删除仍可能被 N-2 对话使用的最老目录。

### 2. 调用原生安装命令

继续调用原生：

```text
codex plugin add subagent-governance@<marketplace>
```

不通过 chmod、symlink、后台复制或修改 Codex cache 行为来阻止原生命令删除旧目录。

### 3. 原生命令返回后优先恢复 previous

如果原生命令返回成功且存在 previous：

1. 从事务 manifest 找到精确 previous snapshot 和 expected digest；
2. 若 previous 目录不存在，立即从 snapshot 恢复到原完整版本路径；
3. 若 previous 目录仍存在，要求其 digest 精确等于 snapshot；不得静默覆盖未知内容；
4. 恢复/复核后再次校验目录类型、Manifest version 和 digest；
5. 把动作记录为 `retained_previous_cache` 和 `previous_cache_restored`。

该步骤应位于较长的 target/stable 完整验证之前，以缩短原生命令删除 previous 后的不可用窗口。不能宣称消除原生命令执行期间的全部瞬时窗口；保证从原生命令返回并成功恢复后开始成立。

如果 previous 恢复或复核失败，整个安装失败并按安装前完整快照回滚，不能留下只有 target 的半成功状态。

### 4. 验证 target 和稳定源

保持并收紧现有检查：

- stable source 在命令前后的 digest 不变；
- target 是安全普通目录；
- target Manifest full version 等于 `target_version`；
- target tree digest 等于安装前绑定的 stable tree digest；
- previous 与 target 是两个不同真实路径且都不是 symlink。

previous 的 digest 必须等于其安装前 snapshot digest，但不要求等于当前 stable digest。

### 5. 成功收敛

成功时保留集合：

```text
keep = {target_version} U {previous_version if present}
```

删除 keep 之外的更早 cache，并记录 `removed_cache_entries`。删除前继续执行 ordinary-directory 和 tree-digest 安全检查。

完成后重新枚举并验证：

- initial install 只剩 target；
- update 精确剩 target + previous；
- 不允许第三个条目；
- transaction snapshot 清理后只保留锁文件和最终事务报告。

### 6. 失败与中断回滚

以下任一失败都恢复安装前完整 cache 集合及原 digest：

- 原生命令失败或抛异常；
- previous 恢复/复核失败；
- stable source 或 target 校验失败；
- 更早 cache 清理失败；
- 最终集合复核失败。

回滚不是“保留 target + previous”，而是精确恢复 pre-install snapshot。回滚失败时保留 transaction snapshot 并输出可定位错误；不得继续清理快照。

中断事务恢复继续以完整 pre-install snapshot 为事实来源，不能把上次目标版本误认成 current。

## 事务报告

成功报告至少包含：

- `previous_version`
- `target_version`
- `pre_install_caches=[{name,digest}]`
- `retained_previous_cache`：完整路径或 `null`
- `previous_cache_restored`：布尔值
- `retained_previous_digest`：previous 存在时为 snapshot digest，否则 `null`
- `removed_cache_entries`
- `actual_target_tree_digest`
- `actual_stable_tree_digest`
- `state=install_succeeded`

失败报告继续包含 `failed_stage`、`restored_caches` 和错误原因。建议新增明确阶段：

- `restore_previous`
- `post_install_verification`
- `cleanup`
- `rollback`

不得用 `removed_cache_entries=[]` 推断 previous 仍存在；最终集合必须单独报告和复核。

## 安装检查器设计

移除 `single_current_cache` 这一含混健康条件，替换为：

- `current_cache_present`
- `current_cache_matches_stable`
- `compatibility_cache_count`（`0|1`）
- `rolling_cache_set_valid`
- `retained_previous_cache`（路径或 `null`）
- `retained_previous_version`（字符串或 `null`）
- `retained_previous_digest`（字符串或 `null`）
- `unexpected_cache_entries`

检查器输出仍明确：

- `codex_registration_checked=false`
- `hook_trust_checked=false`
- registered current 不能由目录集合推断；
- compatibility cache 的存在只证明文件系统保留，不证明任何旧会话仍活跃。

如果存在一个安全的非 target 版本目录，检查器把它视为允许的 compatibility cache，不发 `unexpected_extra_cache` warning。存在第二个非 target 条目或任何非安全条目时失败，并报告 `rolling_cache_set_invalid` / `unexpected_extra_cache`。

## 测试矩阵

至少增加或修改以下测试；测试先稳定复现旧行为，再验证新语义：

### 成功路径

1. empty → A：只保留 A，previous 字段为 null。
2. A current → B，原生命令保留 A：最终 A+B，A digest 不变，`previous_cache_restored=false`。
3. A current → B，原生命令删除 A：从 snapshot 恢复 A，最终 A+B，`previous_cache_restored=true`。
4. A compatibility + B current → C，带确认参数：原生命令删除全部旧 cache 后恢复 B，最终 B+C，A 被删除。
5. 检查器接受只有 target。
6. 检查器接受 target + 一个 retained previous，且只比较 target/stable digest。

### 门禁与身份

7. 有 cache 但缺少 `--previous-version`：命令不运行。
8. `previous_version` 不存在或等于 target：命令不运行。
9. 已有两个安装前 cache 但缺少 `--confirm-previous-sessions-restarted`：命令不运行且不创建安装副作用。
10. previous 选择不依赖目录名、mtime 或语义版本顺序。
11. initial install 错误传 previous：拒绝。

### 失败与回滚

12. previous snapshot digest 损坏：原生命令不运行或恢复阶段失败，保留可恢复事务事实。
13. 原生命令删除 previous，恢复 copy 失败：精确回滚 A 或 A+B。
14. 原生命令保留 previous 但内容变化：拒绝并精确回滚。
15. target 缺文件、增文件、mode 改变、Manifest version 错误：精确回滚。
16. stable source 命令期间变化：精确回滚。
17. 删除最老 cache 失败：精确回滚安装前 A+B。
18. 最终集合出现第三个条目：失败并回滚。
19. symlink、非目录、owner/permission 异常：在对应安全边界拒绝。
20. 中断事务恢复后仍使用 manifest 中 previous 身份，不按目录排序猜测。

### 检查器负向路径

21. 缺少 target：失败。
22. target + 两个其他 cache：失败。
23. retained previous Manifest version 与目录名不一致：失败。
24. retained previous symlink、非目录或 digest 不可读：失败。
25. target/stable digest 不一致：失败；previous 是否健康不掩盖 current 失败。

## 文档更新

必须统一以下表述：

- “只有一个 current cache”改为“恰好一个 current，允许最多一个 retained previous compatibility cache”；
- “成功后只保留目标 cache”改为“成功后保留目标和精确安装前 current，下一次确认更新删除更早版本”；
- previous cache 是 restart compatibility，不是 rollback source；rollback source 仍是 transaction snapshot；
- `codex plugin list` 是 registered/current 身份来源；目录集合永远不是；
- 一次更新只兼容上一代会话。更新 N→N+1 后，在再次更新 N+1→N+2 前，必须重启/关闭仍依赖 N 的会话，并显式确认；
- 安装后仍需用户重启，双版本保留只防止旧会话在重启前因路径消失报错，不让旧会话热加载新版本；
- 原生命令执行期间可能存在短暂删除窗口，安装器保证的是命令返回后的恢复与最终双版本集合，不夸大为零窗口原子切换。

## 实施顺序

1. 在 `tests/test_release_tools.py` 增加原生命令删除 previous 后应恢复、A+B→B+C 滚动、检查器接受双 cache 的失败测试。
2. 实现 snapshot 中精确 previous 的恢复/复核 helper 和事务报告字段。
3. 将成功 cleanup 改为 keep target + previous，并保持失败精确回滚。
4. 加入已有 compatibility cache 时的 `--confirm-previous-sessions-restarted` 门禁。
5. 修改检查器为 current + optional compatibility 模型。
6. 补齐负向、fault injection、symlink/permission 和 interrupted transaction 测试。
7. 更新架构、发布、P10 和平台验证文档。
8. 运行完整本地门禁并提交；不要在本方案执行对话中安装。

## 验收标准

- 原生 add 删除 previous 的测试能从事务快照恢复精确旧版本路径和 digest。
- 更新成功后缓存集合精确为 target + previous；initial install 精确为 target。
- 再次更新在显式确认后精确轮换为新 target + 安装前 current，并删除更早 cache。
- 所有失败路径恢复安装前完整缓存集合；无半成功 target-only 状态。
- 检查器接受健康双版本集合，拒绝第三个 cache 和不安全条目。
- current/previous 身份没有任何目录排序、mtime 或版本比较推断。
- 文档、脚本帮助、事务报告和测试使用一致术语。
- 不生成 cachebuster，不安装、不发布、不写稳定源或运行缓存。
- 以下验证全部通过：

```bash
python3 -m unittest tests.test_release_tools -v
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/reinstall_plugin.py scripts/check_installation.py scripts/subagent_governance.py
python3 scripts/release_preflight.py --development-only
python3 <plugin-creator-skill-root>/scripts/validate_plugin.py .
git diff --check
```

如实现未修改 Skill，不需要 Skill validator；如实际范围触及 Skill，停止并先说明为什么超出本方案预期。

## 停止条件

遇到以下任一情况时停止实现并向父对话报告，不自行安装或扩大范围：

- Codex 实际 cache 路径不再以完整 Manifest version 为直接子目录；
- 原生 add 在测试替身之外要求无法安全恢复的额外 registry/cache 事务；
- previous 恢复必须修改 Hook 配置、trust 或平台内部文件；
- 无法在 same-filesystem transaction snapshot 下恢复精确 digest；
- 为实现滚动保留必须直接修改 plugin-creator 系统 Skill；
- 现有未提交用户改动与本方案文件发生不可安全合并的冲突；
- 本地门禁失败且原因属于 P12-A 或其他治理运行时，而不是安装器/检查器改动。

## 后续真实安装与验证（不在本方案执行对话中）

本方案提交并经父对话复审后，才进入另行授权的安装步骤：

1. 生成唯一 cachebuster并重跑发布前本地门禁；
2. 通过受支持流程同步稳定测试源；
3. 用 `codex plugin list` 读取精确 previous/current；
4. 运行新安装器；
5. 安装后只读确认 target + retained previous、stable=target digest、无第三 cache；
6. 当前旧对话 Stop Hook 应继续从 retained previous 路径运行；
7. 用户重启 Codex；
8. 重启后新建独立 `gpt-5.6-terra` / `high` 对话，验证目标 Skill/Hook 和 P12-A 真实场景；
9. 未完成重启和新对话真实验证前，不宣称完整修复。


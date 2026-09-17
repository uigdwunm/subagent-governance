# 发布与本机开发部署

开发仓库是唯一修改源。Codex 可加载的 runtime 使用
`.codex-plugin/runtime-bundle.json` 的机器 allowlist 构造；稳定源与运行缓存只保存这份精确 projection，不再投影完整 tracked tree。

## Runtime bundle

allowlist 只包含插件 Manifest、Hook manifest、当前 Skill 与必要 references、核心 runtime scripts、运行时读取的 governance semantics Schema 和 `LICENSE`。仓库说明 `README.md` 与对外提供的 TaskContract v2 输入 Schema 仍进入源码和 release archive，但不进入本机 runtime。以下内容也明确不进入 runtime：

- tests、CI、improvement plans 与 validation reports；
- `AGENTS.md`、贡献/安全文档、开发依赖与 release preflight；
- `runtime_bundle.py`、`dev_deploy.py` 和其他安装、检查、同步或 cache 管理工具。

`scripts/runtime_bundle.py` 对 allowlist 做排序、唯一性、普通文件和无符号链接校验。`bundle_digest` 只覆盖 allowlisted path、mode 与 bytes；普通测试或开发文档变化不会改变 runtime digest。`verify_runtime_bundle` 还要求目标树没有任何额外文件。runtime facade 在导入治理模块前禁用 Python bytecode 写入，避免执行过程向 current 或 retained previous bundle 注入 `__pycache__`。

## 本地门禁

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
git diff --check
```

支持的其他 Python 版本、ruff 与 coverage 可用时也应运行。archive/release preflight、cachebuster、tag 与 Marketplace ref 仍属于正式发布门禁，不属于本机开发部署入口。

## GitHub 稳定发布

当前稳定版为 `v0.5.0`。正式版本在插件 Manifest 使用纯版本号，公开 Marketplace ref 固定为同名 `v<version>` 标签；本机 cachebuster 不作为公开稳定版号。

发布前完成本地门禁，确认开发仓库与稳定发布源是独立的非符号链接目录，推送 main 并等待六个 CI 矩阵任务通过。再给同一提交创建不可变标签，运行 `release_preflight.py --mode release --tag v<version>`，确认标签 CI 通过后创建 GitHub Release。发布说明应列出变更、升级边界和实际验证范围。

仓库通过 `.gitattributes` 固定文本 checkout 为 LF，避免 Windows 自动 CRLF 转换破坏原始提交字节一致性。CI 不因一个矩阵任务失败而取消其他任务。公开发布不执行本机安装，也不声称稳定源与运行缓存已同步到新标签。

## 唯一开发部署入口

`scripts/dev_deploy.py` 是唯一的本机开发测试部署入口。它不会写全局 `AGENTS.md`、Marketplace 配置、Registry 或 Hook trust，也不会检查这些外部状态。省略 `--execute` 时是严格零写入 dry-run：

```bash
python3 scripts/dev_deploy.py \
  --source-root <clean-development-worktree> \
  --stable-root <marketplace-stable-plugin-root> \
  --cache-parent <codex-plugin-cache-parent> \
  --transaction-parent <development-deploy-transaction-parent> \
  --expected-head <full-commit-oid> \
  --expected-version <full-manifest-version> \
  --marketplace <marketplace-name> \
  [--previous-version <exact-installed-current-version>]
```

任何 stable、cache 或 Codex 写入都必须另行取得当前任务的明确授权。获准后使用相同参数追加 `--execute`。安装前已有两个 cache 时，显式 `previous-version` 仍绑定当前安装版；成功后直接按双版本规则从 `A+B` 轮换为 `B+C`，不要求第二次人工确认。

执行入口只接受：

1. 干净且 HEAD 精确匹配的 Git 根目录；
2. 与 Manifest 完整版本一致、可构造的 allowlisted source bundle；
3. 普通、非符号链接、owner/permission 安全且互不重叠的 source/stable/cache/transaction roots；
4. 操作者从原生状态机械取得的 exact previous version；不按目录时间、版本语义或唯一候选推断；被选中的 previous 必须在调用原生安装前通过精确 runtime bundle 校验。

来源证明直接读取 `expected-head` 的原始 Git tree/blob，禁用 replacement objects，不依赖 index 的 `skip-worktree`、`assume-unchanged` 或再次检查 `git status` 来证明内容。allowlist 自身及全部发布文件必须属于该提交，且实际字节逐项一致；提交中的符号链接和 submodule 不能作为发布文件。准入、锁内恢复之后、staging 激活之前及安装后分别核对相应 source/staging 内容。

此入口采用原始提交字节语义：CRLF、smudge filter 等 checkout 转换导致字节不同，即使 Git 认为工作区干净也拒绝，不自动转换或执行 filter。POSIX 上另核对 Git 记录的 owner executable bit；Windows 不据此声称 POSIX 执行权限已验证。Git 提交身份与 `bundle_digest` 是两类证据：前者绑定原始字节与 Git 文件模式，后者继续比较安装投影的完整文件权限位与字节。此校验不能观察两次检查之间发生又被撤销的全部工作区编辑，也不提供针对同一用户并发篡改文件系统的隔离保证。

入口在同一 operation lock 内恢复精确绑定的未完成 transaction，然后：

1. 快照 stable 和完整安装前 cache 集合及 digest；
2. stage 并验证精确 allowlisted bundle；
3. 用同一 stable parent 内的 rename 原子激活 stable；
4. 调用原生 `codex plugin add <plugin>@<marketplace>`；
5. 恢复或复核 exact previous，并再次验证其精确文件集合与原 digest；同时验证 stable/target runtime digest 与 source digest 一致；
6. 精确保留 target 与可选 previous，只有在全部检查通过后删除更早 compatibility cache 和 transaction。

部署、最终校验、成功清理及失败回滚连续持有同一 operation lock；回滚完成或失败退出后才释放锁。竞争进程拿锁失败时不执行恢复或安装，也不解锁。

原生命令失败、target 缺失或摘要不匹配、source/stable 变化、retention 失败都会尝试恢复部署前 stable 与完整 cache 集合。cache 快照仍须通过完整校验；清理对象仅限 transaction 中的目标版本与部署前 cache 名称，允许空目录或部分安装残留。删除任何 cache 前先检查整组对象及其后代的普通文件/目录类型、所有权和权限，拒绝未知版本目录、符号链接与特殊文件。恢复复制失败后留下的部分目录也按同一规则在下次执行时处理。

进程在原子切换中断时，下次有写权限的执行只按 transaction manifest 绑定的 staging/backup/recovery path 恢复；存在多个 transaction 或孤立 switch path 时拒绝猜测。恢复失败保留 transaction 快照及原错误和恢复错误，不报告已回滚；只有恢复后的 cache 集合和摘要精确匹配才完成回滚。

直接管理 Codex 内部 cache 是本机开发测试能力，不是通用产品 API。部署命令无论成功或失败，当前任务都应立即报告并停止，等待用户重启 Codex；真实验证必须在重启后的新任务进行。

## 真实平台验证

获准部署并重启后，在独立新任务按测试目的分别冻结并显式指定父子模型、推理强度和继承配置，分别核实实际值；配置未确定前不启动，用户明确配置优先。主要使用组合可为强主模型与低成本子模型，不要求同模型。无法确认的项目标为未验证；历史结果只证明当时组合。以下运行正确性门槛不由成本收益评测替代：

- unmanaged spawn fail-open 且零状态；
- prepare → Pre claim → native spawn → explicit exact-target confirm；
- wait 与 exact bound-target observation；
- normal message success/failed 无必需额外记账，一条终态证据只登记一次，minimal interrupt 与 parent close；
- 实际 unknown 后出现确定状态时，终态可登记，历史 unknown 仍保留；未实际出现该回执则标为未验证；
- exact-session SessionStart/status 以及用户触发的 restart/compact。

身份契约回归至少覆盖 standard 只读任务和 strict 通信收尾任务。测试者先读新版 Skill，不额外提示应选择哪个返回字段；逐项记录同次 spawn 的原生返回、confirm target 与最终状态。完整 canonical task_name 与输入短名称必须区分，嵌套路径不得重建或截断；其他接口只有实际可用时才验证，不可用标为未验证。若需要自行纠正文档或额外提示才能完成，即使最终 closed 也不能将说明一致性判为通过。文档样例本地检查不能替代这项真实验证。

异构协作验收另外核对正常交付、真实 compact 后恢复原始验收要求，以及具体缺陷下的纠偏/接管。后续消息修订不自动进入契约快照，恢复证据需区分原始要求和后续约定；无法恢复则如实标记。收益比较按 [F 方案](improvement-plans/F-rework-cost-pilot.md) 单独冻结批次，流程通过不等于成本下降。

Hook trust、Codex registration、桌面 UI 和 exact session identity 分别记录；文件存在、`installed/enabled` 或本地测试不能替代真实证据。未经授权或尚未重启时一律记为 `not_checked`。

state-v12 与旧 state-v11 隔离，不自动恢复、迁移或删除旧未关闭任务。部署交接说明此边界，不把新 namespace 为空当作旧任务完成。新 runtime 不读取保留的上一版本逻辑或状态。

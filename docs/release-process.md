# 发布与本机开发部署

开发仓库是唯一修改源。Codex 可加载的 runtime 使用
`.codex-plugin/runtime-bundle.json` 的机器 allowlist 构造；稳定源与运行缓存只保存这份精确 projection，不再投影完整 tracked tree。

## Runtime bundle

allowlist 只包含插件 Manifest、Hook manifest、当前 Skill 与必要 references、核心 runtime scripts、当前 Schema、`README.md` 和 `LICENSE`。以下内容明确不进入 runtime：

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

入口在同一 operation lock 内恢复精确绑定的未完成 transaction，然后：

1. 快照 stable 和完整安装前 cache 集合及 digest；
2. stage 并验证精确 allowlisted bundle；
3. 用同一 stable parent 内的 rename 原子激活 stable；
4. 调用原生 `codex plugin add <plugin>@<marketplace>`；
5. 恢复或复核 exact previous，并再次验证其精确文件集合与原 digest；同时验证 stable/target runtime digest 与 source digest 一致；
6. 精确保留 target 与可选 previous，只有在全部检查通过后删除更早 compatibility cache 和 transaction。

原生命令失败、target 缺失或摘要不匹配、source/stable 变化、retention 失败都会恢复部署前 stable 与完整 cache 集合。进程在原子切换中断时，下次有写权限的执行只按 transaction manifest 绑定的 staging/backup/recovery path 恢复；存在多个 transaction 或孤立 switch path 时拒绝猜测。

直接管理 Codex 内部 cache 是本机开发测试能力，不是通用产品 API。部署命令成功后当前任务应立即停止，等待用户重启 Codex；真实验证必须在重启后的新任务进行。

## 真实平台验证

获准部署并重启后，在独立任务按以下顺序验证：

- unmanaged spawn fail-open 且零状态；
- prepare → Pre claim → native spawn → explicit exact-target confirm；
- wait 与 exact bound-target observation；
- normal message、terminal notification、minimal interrupt 与 parent close；
- exact-session SessionStart/status 以及用户触发的 restart/compact。

Hook trust、Codex registration、桌面 UI 和 exact session identity 分别记录；文件存在、`installed/enabled` 或本地测试不能替代真实证据。未经授权或尚未重启时一律记为 `not_checked`。

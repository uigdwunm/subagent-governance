# 发布流程

发布操作只使用当前协议、当前插件版本和恰好一个 current 运行缓存；为尚未重启的上一代会话，可额外保留一个 retained previous compatibility cache。开发仓库是唯一修改源；稳定发布源和运行缓存不是开发源。

## 发布门禁

发布前必须满足：

1. Git 工作树干净，目标提交已推送。
2. Python 3.11 与 3.12 单元测试全部通过。
3. 所有 Python 脚本编译通过。
4. development 与 archive release preflight 通过。
5. Plugin validator 与 Skill validator 通过。
6. Manifest 公共版本、Git tag 和 Marketplace ref 一致。
7. 开发仓库、稳定发布源和运行缓存是三个不同的普通目录，且不是符号链接。
8. 运行缓存父目录中有目标 current，并且至多有一个安全的 retained previous compatibility cache。
9. Hook trust、真实事件投递和 Codex 注册状态没有被本地测试冒充为已验证。

未获得明确授权时，流程只执行开发仓库中的只读验证，不替换稳定源、不安装插件、不更新 Marketplace、不应用全局规则、不修改 Hook trust。

## 开发仓库验证

```bash
python3.11 -m pip install -r requirements-dev.txt
python3.11 -m unittest discover -s tests -v
python3.12 -m unittest discover -s tests -v
python3.11 -m py_compile scripts/*.py
python3.12 -m py_compile scripts/*.py
ruff check scripts tests
coverage run -m unittest discover -s tests -v
coverage report
python3 scripts/release_preflight.py --mode development
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/subagent-governance
```

归档验证使用目标提交：

```bash
archive_root="$(mktemp -d)"
git archive --format=tar HEAD | tar -xf - -C "$archive_root"
python3 "$archive_root/scripts/release_preflight.py" \
  --root "$archive_root" \
  --mode archive
```

## 版本与 tag

正式发布前生成唯一 cachebuster，重新运行全部门禁，然后提交并创建 tag：

```bash
python3 ~/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py .
python3 scripts/release_preflight.py --mode release --tag "v<public-version>"
```

`.codex-plugin/plugin.json` 的公共版本、tag 和 `.agents/plugins/marketplace.json` 的 ref 必须一致。cachebuster 只属于完整 Manifest version。

## 安装事务

取得安装授权前，先在开发仓库完成 cachebuster 提交和本地门禁，再从该干净 commit 同步稳定测试源：

```bash
python3 scripts/sync_stable_plugin.py \
  --source-root <clean-development-worktree> \
  --stable-root <marketplace-stable-plugin-root> \
  --transaction-parent <plugin-install-transaction-parent> \
  --expected-head <full-commit-oid> \
  --expected-version <full-manifest-version>
```

读取 `last-stable-sync.json`，确认 source/stable path、HEAD、version 和 source projection/new stable digest 一致后，才从稳定发布源运行：

```bash
python3 <stable-plugin-root>/scripts/reinstall_plugin.py \
  --previous-version <exact-installed-current-version> \
  --target-version <full-manifest-version>
```

安装工具执行以下事务：

1. 验证缓存与快照目录的所有权、权限、文件类型和文件系统边界。
2. 有 cache 时要求传入从 `codex plugin list` 读取的准确 installed/current 版本；禁止按目录名、mtime 或版本语义推测。
3. 在调用原生命令前，从运行该脚本的稳定测试源绑定完整 tree digest，并在锁保护且同一文件系统内快照安装前完整 cache 集合及摘要。
4. 调用原生 `codex plugin add`；命令返回后优先从事务快照恢复或复核精确 `--previous-version` 路径和 digest，再确认稳定测试源未变化，且目标 cache 是安全普通目录、Manifest 完整版本精确匹配 `--target-version`、tree digest 精确匹配已绑定的稳定源摘要。
5. 命令失败、来源或目标验证失败、目标缓存缺失、清理失败或进程中断时恢复安装前完整 cache 集合。
6. 只有上述摘要校验成功时才删除更早缓存和事务快照，精确保留目标 current 与安装前 current 作为 retained previous。若安装前已有 compatibility cache，必须额外传入 `--confirm-previous-sessions-restarted`，确认依赖最老 cache 的会话已重启或关闭。

事务快照只服务当前安装，并在事务成功或回滚完成后删除。
安装锁使用操作系统文件锁；锁文件稳定保留，锁本身随进程退出自动释放。
稳定源同步的 backup 只服务 stable root 的 rename 切换；它不是安装回滚快照，也不是 retained previous compatibility cache。同步与安装使用同一个 transaction parent 和 `.install.lock`，禁止并发执行。

## 安装后检查

```bash
python3 <stable-plugin-root>/scripts/check_installation.py \
  --require-development-sync
```

检查必须证明：

- 稳定发布源与 current target 缓存哈希一致。
- 全局受管理规则与稳定资产一致。
- 开发、稳定和缓存路径相互独立。
- 只有 current target 与零或一个安全 retained previous compatibility cache；目录集合不用于推断 Codex registered/current。

## 真实平台验证

运行时代码、Hook 或 Skill 发生变化后，在取得本地测试安装授权后新建 Codex 任务验证：

- governed spawn 和 PreToolUse claim；
- wait 与 exact `list_agents`；
- 原生终态通知记录；
- parent close；
- SessionStart/Stop/SessionEnd；
- 失败安装回滚。

真实平台验证没有执行时必须标记 `not_checked`。不能复用开发或调试当前问题的原任务代替新任务验收。

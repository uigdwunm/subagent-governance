# J：部署恢复与来源一致性本地验收

基线：`8ba349ef3cc5d59f695654b670f2463d5c9fef89`。范围仅为独立开发 worktree；用户确认采用原始 Git 提交字节语义后实施。

## 问题与修复

- 空目标 cache 残留：旧实现对清理对象调用要求非空的插件树摘要，导致安装失败后回滚失败，再次执行也不能恢复。现在完整快照校验与残留清理校验分离，只清理事务目标版本和部署前版本名称下的安全普通目录；先检查全部对象，再删除和恢复，最后复核完整 cache 集合与摘要。
- 来源一致性：旧实现只检查 HEAD 与 Git status，隐藏在 `skip-worktree` 或 `assume-unchanged` 后的未提交修改能通过 dry-run 和模拟安装。现在直接读取原始 commit tree/blob，禁用 replacement objects，逐项核对 allowlist 自身、发布文件字节和 POSIX owner executable bit；staging 激活前另行核对提交内容和精确投影。
- 保留 H 的同锁部署、回滚、验证和清理，保留双版本策略及失败证据；不改变事务格式、Skill、治理规则或子 Agent 生命周期。

代码在 [dev_deploy.py](../../scripts/dev_deploy.py)，行为测试在 [test_dev_deploy.py](../../tests/test_dev_deploy.py)，操作语义见[发布与本机开发部署](../release-process.md)。

## 回归证据

先添加首批 5 个测试方法并在旧代码上运行，得到 14 个 failure 和 1 个 error（包括子用例），确认测试能暴露问题。随后实现修复并扩展到 10 个新增测试方法。

覆盖空 cache／已有 previous、空和部分安装残留、中断安装后恢复、恢复复制失败后的下一次部署、未知目录、根与后代符号链接、特殊文件、不安全权限、模拟错误所有权、两种隐藏标记下的 dry-run／execute、插件 Manifest 与 allowlist 的隐藏修改、staging 字节被篡改、部署前后源变化、Git 认为干净的 CRLF 转换、忽略 filemode 时的执行位变化、replacement blob。

全部安装与恢复用例只使用临时合成插件树及假 runner，没有运行真实 `codex plugin add`。既有测试继续覆盖正常提交安装、精确 previous 恢复、双版本轮换、竞争进程及锁保持。

## 本地门禁结果

首次 220 项通过（78.176 秒）发生在新增本文之前，不能代表包含本文的最终工作树。来源任务随后以 Python 3.11 独立检查得到 219 项通过、1 项失败（96.659 秒）：本文尚未加入文档白名单。现按正式验收记录保留本文，并精确加入 `tests/test_current_only_repository.py` 的 `VALIDATION_DOCUMENTS`；保留完整集合相等检查及未知文档拒绝测试，不调整运行时代码。修正后的最终验证如下。

| 检查 | 结果 |
| --- | --- |
| `python3.11 -m unittest tests.test_current_only_repository -v` | 5 项通过，包含文档集合与未知文档拒绝检查 |
| `python3.11 -m unittest discover -s tests -v` | 包含本文及白名单修正的工作树：220 项通过，91.979 秒 |
| `python3 -m compileall -q scripts` | 通过 |
| Plugin validator | 通过 |
| Ruff 0.16.7 `check .` | 通过，使用已有本机二进制 |
| `python3 scripts/release_preflight.py --mode development` | 通过 |
| `git diff --check`、本记录相对链接检查 | 通过 |

Skill 未修改，未重复运行 Skill validator。未执行安装或发布模式预检来补齐外部部署证据。

文档收录修正轮未修改运行时代码；重新运行上述 5 项相关测试、全量 220 项测试、修改文件的 Ruff、差异与相对链接检查，均通过。编译、Plugin validator 和 development release-preflight 沿用前轮及来源任务独立检查的通过结果。本轮全量日志位于本机 `/tmp/j-final-document-review.log`，该临时日志不作为发布文件。

## 限制与未验证项

- Git 提交身份不等于安装投影摘要：Git 记录文件类型和执行属性，投影摘要保留完整文件权限位及字节。
- 不自动应用 checkout 换行转换、smudge 或 textconv；实际字节不等于原始提交即拒绝。
- 不能观察检查间发生又被撤销的所有编辑，也不提供针对同一用户并发篡改文件系统的隔离保证。
- 本地验证平台为 macOS；Windows、其他平台 CI、真实 Codex 安装行为、稳定源与运行缓存一致性及重启后真实测试未验证。Windows 不声称验证了 POSIX 执行权限。
- 未提交、合并、推送、安装或部署；未修改实际插件目录、稳定发布源、Marketplace、Hook trust、Registry 或第三方 Skill。待来源任务独立验收。

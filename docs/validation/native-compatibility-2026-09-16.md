# E 原生接口兼容验证：开发 worktree 验收

日期：2026-09-16；基线 `e7bb27e`。范围为隔离开发 worktree；未提交、合并、推送、安装或部署。

## 修改

- 新增[兼容矩阵](../native-compatibility-matrix.md)，按接口、Hook envelope、环境与回执区分声明、本地和历史真实证据。当前客户端精确版本未知，state-v12 真实链路未验证。
- PreToolUse 外层兜底仅返回安全 systemMessage、exit 0，移除官方不支持的 continue；D 的故障分类、claim 证据与 fail-open 策略不变。
- adapter 的有限继承轮数字符集收紧到 ASCII，与已有 TaskContract/Schema 一致；未扩大原生支持范围。
- 增加默认值、null、混合形状、冻结参数、重放优先级、身份类型和 Hook 输出检查；旧历史文档保留并标明版本边界。机器事件 fixture 保留 2026-08-14 历史日期，另记录 2026-09-16 已注册事件的文档核对范围。

## 验证

先修改回归测试，旧实现稳定出现 9 个失败子案例（4 个 Unicode 数字和 5 个不兼容兜底输出）；修复后相关 39 项测试通过。全量首次发现新增文档缺少白名单，补齐后重新验收。最终检查如下。

临时 StateStore/runtime bundle 均为本地 fixture，不是当前安装实例或真实 native/Hook 投递。运行缓存一致性、当前 trust/Registry、远端跨平台 CI 和独立重启真实测试未验证。F 应使用矩阵中的已证实条件和未验证项，不能从本轮推导返工成本或业务质量改善。

| 检查 | 实际结果 |
| --- | --- |
| Python 3.9.6 全量 unittest | 180 项通过 |
| Python 3.11.15 全量 unittest，coverage branch=true | 180 项通过，总覆盖率 77%，超过 70% 门槛 |
| 修改模块覆盖率（含分支） | native_adapter 87%；CLI 78% |
| Ruff check scripts tests | 通过 |
| compileall scripts | 通过 |
| 系统 Plugin validator / Skill quick_validate | 均通过 |
| release_preflight --mode development | 通过 |
| git diff --check、文档相对文件链接检查、事件 fixture JSON 解析 | 通过 |

覆盖率数据与测试日志保存在临时目录，未写入仓库或插件运行缓存。新增 6 项测试方法包含参数化子案例，174 → 180；不将测试数量或覆盖率当作真实平台兼容率。状态格式和 runtime 文件清单没有变化。

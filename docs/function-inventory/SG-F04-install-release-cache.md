# SG-F04 稳定发布、安装与兼容缓存治理盘点

## 文档边界

- 当前状态：盘点完成；第 1～8 项业务功能及第 9 项收口、覆盖审查和修改方案输入均已确认。
- 一句话职责：把已验证的开发版本安全交付到稳定发布源、Personal Marketplace 和版本化运行缓存，并在发布、重装和回滚期间保留当前版本与升级前一个版本的明确兼容窗口。
- 本文只记录 SG-F04；SG-F01 的治理规则内容、SG-F02 的插件发现与 Hook 注册、SG-F03 的通信和恢复指令不在本文重复盘点。
- 本任务最初只维护本文；用户随后明确授权实施第 4 至第 8 项中边界清楚的局部改进，因此本轮同时修改发布工具、规则资产、Skill、定向测试和发布说明。Manifest、稳定发布源、Marketplace、真实运行缓存、Codex 配置和用户真实全局 `AGENTS.md` 仍未修改。

## 已确认功能点

1. 发布版本与缓存身份。
2. 发布验证与干净副本生成。
3. Marketplace 与插件重装。
4. 单版本兼容缓存保护与重装恢复。
5. 安装健康、部署同步与发布就绪诊断。
6. 全局 `AGENTS.md` 治理规则分发。
7. 真实 Codex 加载与 Hook trust 验收。
8. 回滚、旧缓存与 legacy 资产退役。

八个功能点已经完成逐项确认，共用发布事务身份、安装证据和回滚边界，因此保留为一个大功能，不再拆分。

## 1. 发布版本与缓存身份（已确认）

### 1.1 功能结论

- 建议名称：发布版本与缓存身份。
- 一句话职责：使用 Manifest `version` 同时表达可读的基础发布版本和唯一的 Codex 安装缓存身份，并保证它与 Git tag、稳定发布副本及当前运行缓存可追溯对应。
- 本功能点必须保留，但不需要建设独立版本数据库或第二套版本系统；Git tag、Manifest 完整版本和发布内容哈希应继续作为身份与追溯基础。

### 1.2 当前事实

- `.codex-plugin/plugin.json` 当前开发版本为 `0.4.0-rc.10`，尚未包含 `+codex.<cachebuster>` 后缀；当前 Git HEAD 仍是 `v0.4.0-rc.9` 对应提交，工作树包含未提交修改，因此这是开发中的下一基础版本，不是完整发布身份。
- 已有 `v0.4.0-rc.1` 至 `v0.4.0-rc.9` tag。每个 tag 中的 Manifest 基础版本与 tag 一致，并带有一个唯一的 `+codex.<UTC 时间戳>` 后缀，例如 `v0.4.0-rc.9` 对应 `0.4.0-rc.9+codex.20260808155909`。
- 内置 `plugin-creator` 的更新规则把版本规范化为 `<base-version>+codex.<cachebuster>`：保留第一个 `+` 之前的基础版本，替换而不是追加已有缓存后缀；默认 token 是精确到秒的 UTC 时间戳。
- 内置更新规则明确：不得仅为了让 Codex 重新加载本地插件而递增数值版本；基础版本表达业务发布身份，`codex` 后缀表达安装缓存身份。
- `docs/release-process.md` 已要求在提交和 tag 前生成唯一 cachebuster，生成后重新运行校验，再提交、推送并创建 tag；发布副本必须来自该 tag。
- `scripts/check_installation.py` 从稳定发布源 Manifest 读取完整 `version`，并用它定位当前缓存目录；它不验证版本格式、基础版本与 tag 的关系、cachebuster 唯一性、tag 指向的提交或稳定源是否来自该 tag。
- `tests/test_release_tools.py` 当前只在安装检查 fixture 中提供简单版本字符串，用于定位缓存；`tests/test_plugin_structure.py` 也没有建立项目发布版本策略测试。
- OpenAI 官方插件文档确认 `name`、`version` 和 `description` 用于标识插件，Marketplace 指向插件来源，安装后由缓存副本加载；`+codex.<cachebuster>` 的具体约定来自当前 Codex 内置 `plugin-creator` 的本地更新流程，而不是公开 Manifest 字段规范。

### 1.3 上下游交接

- 上游内容输入：SG-F01、SG-F02 和其他运行功能完成待发布的规则、Skill、Hook、Schema、脚本和文档修改；它们提供发布内容，但不决定发布事务。
- 与 SG-F02 的边界：SG-F02 负责 Manifest 结构、插件名称、Skill/Hook 发现和 UI 元数据；SG-F04 只负责 `version` 在发布、安装和缓存选择中的身份语义。
- 上游发布决策：发布任务先确定基础版本，例如 `0.4.0-rc.10`，再在最终提交前生成完整缓存版本。
- 下游第 2 项消费：发布验证与干净副本生成必须取得已经确定的基础版本、cachebuster、目标提交和 Git tag。
- 下游第 3 项消费：Marketplace 和原生插件重装从稳定发布源读取完整 Manifest 版本，并生成对应安装缓存。
- 下游第 4 项消费：兼容缓存保护把完整 Manifest 版本作为缓存目录身份，并在安装成功后只保留当前版本和升级前实际版本。
- 下游第 5 项消费：安装诊断需要分别报告开发基础版本、稳定完整版本和当前缓存版本，不能把“开发版领先稳定版”误判为运行安装损坏。
- 下游第 7 项消费：真实 Codex 验收需要证明新任务实际加载了目标完整版本，而不只是确认开发仓库包含新代码。
- 明确排除：本功能点不导出或替换稳定源，不执行 `codex plugin add`，不清理缓存，不审核 Hook trust，也不判断业务改动是否达到发布质量。

### 1.4 已确认的目标规则

1. Git tag 只表达基础版本，格式为 `v<base-version>`，例如 `v0.4.0-rc.10`。
2. Manifest 的发布版本使用 `<base-version>+codex.<cachebuster>`，例如 `0.4.0-rc.10+codex.20260810...`。
3. cachebuster 是缓存身份，不是新的业务版本；不得为了刷新 Codex 缓存而无依据增加 `rc`、patch 或其他基础版本组件。
4. 开发期间允许 Manifest 暂时只有基础版本；进入发布就绪验收时必须有且只有一个合法的 `+codex.<token>` 后缀。
5. cachebuster 应作为发布前最后一项源文件修改；生成后必须重新校验，再提交、推送并创建 tag。
6. 发布门禁应机械验证 Manifest 基础版本与目标 tag 一致、完整版本只有一个合法 cachebuster、tag 指向目标提交、tag 中已包含该完整版本，并检查完整版本没有与稳定源或已有缓存发生意外身份冲突。
7. 不新增长期维护的发布版本数据库或重复版本文件；需要的发布证据优先从 Git、Manifest 和内容哈希计算或输出。

### 1.5 可以局部直接实施的改进

以下改进不需要重新设计整个安装发布链路，可在最终统一方案授权实施时作为低风险局部修改处理：

- 在发布说明中明确区分“基础版本”和“完整缓存版本”。
- 明确 Git tag 不包含 `+codex.*` 后缀。
- 明确开发状态允许暂时缺少 cachebuster，而发布就绪状态必须要求 cachebuster。
- 明确不得单纯为了刷新安装缓存而递增基础版本。
- 明确 cachebuster 在最终提交和 tag 前生成，生成后重新运行所有发布校验。
- 为项目自有的版本解析或门禁逻辑增加纯函数测试，覆盖无后缀、合法单后缀、重复后缀、非法空 token 和 tag 不匹配。

盘点阶段不直接修改 `README.md`、`docs/release-process.md`、测试或 Manifest；上述内容只作为后续实施输入。

### 1.6 必须留待统一方案的决策

- `SG-F04-PLAN-01`：决定新建只读 release preflight 工具，还是扩展 `scripts/check_installation.py`；该选择同时影响第 2 项的发布门禁和第 5 项的诊断状态分层。
- `SG-F04-PLAN-02`：定义开发 Manifest 没有 cachebuster 时的机器可读状态，例如 `development` 或 `not_release_ready`，并避免影响 `runtime_healthy`。
- `SG-F04-PLAN-03`：决定 cachebuster 唯一性检查范围是当前稳定源、当前缓存和保留的上一版本缓存，还是包含清理前发现的更早缓存；需要与缓存保留和恢复规则共同设计。
- `SG-F04-PLAN-04`：决定发布门禁是否机械验证目标提交已经推送；该检查涉及本地 Git、远程状态和离线发布边界。
- `SG-F04-PLAN-05`：决定项目发布入口是显式调用内置 `update_plugin_cachebuster.py`，还是由项目自有发布工具包装调用；不得复制并形成第二套 cachebuster 生成语义。
- tag、稳定源替换、原生重装和失败回滚的事务边界不在本功能点单独决定，转交第 2、3、4、8 项统一确认。

### 1.7 不再作为目标的内容

- 不创建独立版本数据库、发布 Registry 或重复版本清单。
- 不要求 Git tag 带 `+codex.<cachebuster>`；tag 保持稳定、可读的基础版本即可。
- 不为每次普通代码编辑生成 cachebuster；只有需要形成新的安装缓存或进入正式发布流程时才生成。
- 不使用手工指定 cachebuster 作为默认流程；只有外部工作流确实依赖特定 token 时才使用显式覆盖。
- 不把“开发基础版本尚未生成 cachebuster”直接定义为当前运行安装故障。

### 1.8 证据与当前验证范围

- 仓库证据：`.codex-plugin/plugin.json`、`docs/release-process.md`、`README.md`、`scripts/check_installation.py`、`tests/test_release_tools.py`、`tests/test_plugin_structure.py`、Git tag 和 Manifest 历史。
- 内置工具证据：`plugin-creator/references/installing-and-updating.md` 与 `plugin-creator/scripts/update_plugin_cachebuster.py`。
- 官方文档证据：[Package your plugin](https://developers.openai.com/plugins/build/plugins)。
- 本项仅执行只读文件、Git 历史和官方文档核对；未生成 cachebuster，未创建提交或 tag，未修改稳定发布源、Marketplace、缓存或 Hook trust。

## 2. 发布门禁与稳定副本生成（已确认）

### 2.1 功能结论

- 建议名称：发布门禁与稳定副本生成。
- 一句话职责：确认待发布提交满足质量和身份要求，从确定的 Git tag 生成可验证的候选副本，并在保留恢复路径的前提下安全替换稳定发布源。
- 本功能点必须保留；当前 `git archive` 的完整 tag 导出路线正确，不需要把稳定发布源改造成第二个 Git 工作树，也不需要维护另一份人工发布文件白名单。
- 当前稳定发布结果已经证明可达到正确状态，但发布流程主要依赖人工操作，尚未由项目自有工具保证可重复性、并发安全和失败恢复。

### 2.2 当前事实

- `docs/release-process.md` 是当前主要发布入口，要求工作树干净、目标提交已推送、单元测试与 Python 编译通过、Plugin/Skill validator 通过、可执行代码完成安全审查、Manifest 已更新正式版本和 cachebuster、已记录回滚目标，并确认全局治理规则一致。
- 文档要求在开发仓库完成验证后生成 cachebuster，再重新运行校验、提交、推送和创建 tag；随后使用 `git archive --format=tar <tag>` 导出到临时目录，校验后替换 `~/plugins/subagent-governance`。
- “工作树干净”与“随后生成 cachebuster”目前处于同一发布门禁列表，状态顺序不够精确；生成 cachebuster 本身会修改 Manifest，只有完成最终验证和发布提交后才可能重新达到干净状态。
- 文档只说明候选副本“校验后”替换稳定源，没有列出候选目录必须执行的完整检查，也没有机械验证 `HEAD`、目标 tag、Manifest 基础版本、完整版本和导出内容之间的对应关系。
- 当前没有项目自有的 tag 导出、候选验证或稳定源替换脚本；`scripts/check_installation.py` 只在发布之后检查目录隔离以及稳定源与当前运行缓存的一致性。
- `.github/workflows/ci.yml` 当前只在 Python 3.11 和 3.12 上运行 `py_compile scripts/subagent_governance.py` 与完整单元测试；Plugin validator、Skill validator、发布身份检查、tag 导出和稳定源替换不在 CI 中。
- `tests/test_release_tools.py` 当前覆盖全局规则同步、安装检查和缓存保留重装，但没有创建临时 Git 仓库或覆盖 tag、`git archive`、候选验证、稳定源替换、替换失败和回滚。
- 本地 tag 类型不一致：`v0.4.0-rc.1`、`v0.4.0-rc.8` 和 `v0.4.0-rc.9` 是 annotated tag，`v0.4.0-rc.2` 至 `v0.4.0-rc.7` 是 lightweight tag；当前发布说明只要求创建 tag，没有规定 tag 类型。
- 2026-08-10 只读核对确认：当前稳定发布源 `$HOME/plugins/subagent-governance` 是当前用户拥有的普通目录、不是符号链接、权限为 `0700`，且不包含 `.git` 元数据。
- 从 `v0.4.0-rc.9` 重新执行 `git archive` 得到的候选树与当前稳定发布源树哈希均为 `fed424cb225c8293d74abf2b442a99a25b3025567fb2f5476943ae1a95d2b74c`，文件级比较也没有差异；这证明当前稳定源确实是该 tag 的干净副本。
- 当前存在 `subagent-governance.backup-rc7-20260808142500` 和 `subagent-governance.pre-v0.4.0-rc.9` 两份稳定源备份，分别包含 `rc.7` 和 `rc.8`；备份命名格式不一致，其中 `rc.7` 备份权限为 `0755`，其余当前稳定源和 `rc.8` 备份为 `0700`，说明备份仍由人工管理且安全属性没有统一门禁。
- 当前发布文档没有规定候选目录必须与稳定源位于同一文件系统。如果候选先生成在系统临时目录，后续移动可能退化为跨文件系统复制，无法直接获得同文件系统 rename 的边界。
- 当前发布文档要求保留上一稳定备份，但没有发布锁、统一备份名称、替换状态记录或第二次移动失败后的恢复步骤；并发发布、进程崩溃、磁盘不足和稳定路径短暂缺失均未被项目测试证明安全。

### 2.3 上下游交接

- 上游第 1 项输入：已经确定的基础版本、完整 Manifest 版本、目标提交和目标 Git tag。
- 上游内容输入：SG-F01、SG-F02 和其他功能提供待发布规则、Skill、Hook、Schema、脚本、文档和测试；本项不重新判断这些功能的业务边界。
- 上游质量证据：单元测试、Python 编译、Plugin validator、Skill validator 和安全审查结论；安全审查属于人工或独立审查证据，发布脚本不得凭空生成“已完成”结论。
- 本项输出：已验证的 tag 候选副本、候选内容哈希、替换后的稳定发布源、上一稳定备份路径以及足以支持下游判断的发布结果。
- 下游第 3 项消费：只有稳定发布源替换并完成内容验证后，才允许执行 Marketplace 插件重装；候选生成完成但稳定源替换失败时不得继续重装。
- 下游第 5 项消费：安装诊断验证稳定发布源是普通隔离目录，并与重装后当前运行缓存一致；它不是 tag 导出真实性的替代证明。
- 下游第 6 项消费：全局规则同步必须使用稳定发布源内的 `assets/agents-governance.md`，不能使用仍在变化的开发仓库资产。
- 下游第 7 项消费：真实 Codex 验收验证新任务实际加载了该稳定发布内容。
- 下游第 8 项消费：稳定源替换失败、插件重装失败或真实验收失败时，使用本项保留的上一稳定副本和发布证据执行完整回滚。
- 明确排除：本功能点不生成或恢复运行缓存，不修改 Marketplace，不审核 Hook trust，不自动清理稳定备份，也不替代人工安全审查。

### 2.4 已确认的目标规则

1. 发布流程应明确分成“开发候选”“cachebuster 生成并重新验证”“发布提交和 tag 已确定”“tag 候选副本验证通过”“稳定发布源替换完成”五个阶段。
2. 在 tag 导出前要求最终工作树干净，并机械验证 `HEAD == <tag>^{}`；不能从带未提交修改的开发工作树复制发布。
3. 后续 tag 统一使用 annotated tag；当前没有证据要求强制签名 tag，但不应继续混用 annotated 和 lightweight tag。
4. 候选目录应创建为稳定发布源父目录下的隐藏、唯一、权限受控的普通目录，确保与稳定源处于同一文件系统并避免符号链接。
5. 候选副本必须从目标 tag 使用 `git archive` 生成，不把稳定发布源变成 Git checkout，也不维护第二份发布文件清单。
6. 替换前应验证候选 Manifest 身份符合第 1 项规则、候选树没有不安全符号链接或条目、Plugin/Skill validator 通过、候选内容哈希可以从 tag 重现，并确认目标稳定路径和备份路径均为当前用户拥有的普通目录。
7. 稳定源替换过程必须保留上一版本副本，并在替换完成后重新计算稳定源哈希；只有稳定源与候选副本完全一致，才允许进入插件重装。
8. 发布过程应提供发布锁或等价并发保护，并为候选、旧稳定源和新稳定源的状态变化保留明确恢复依据。
9. 发布可以输出一次性的机器可读报告，记录 tag、commit、完整版本、候选哈希、上一稳定版本和备份路径；当前不需要建立长期发布数据库。

### 2.5 可以局部直接实施的改进

以下改进不需要先确定完整发布事务实现，可在最终统一方案授权实施时作为低风险局部修改处理：

- 在发布说明中明确五个发布阶段，解决“工作树干净”和“生成 cachebuster”的顺序歧义。
- 明确后续发布统一使用 annotated tag。
- 明确候选目录必须是稳定发布源父目录下的同文件系统兄弟目录，而不是未约束位置的系统临时目录。
- 补充候选副本必须执行的 Manifest 身份、目录安全、Plugin validator、Skill validator 和树哈希检查。
- 明确替换完成后必须再次证明稳定源与候选副本内容完全一致，才能进入重装。
- 统一稳定备份的建议命名格式、所有者和权限要求。
- 明确继续使用完整 Git tag 导出，不建设人工文件包含清单或第二个稳定 Git 工作树。

盘点阶段不直接修改 `docs/release-process.md`、`README.md`、CI、脚本或测试；上述内容只作为后续实施输入。

### 2.6 必须留待统一方案的决策

- `SG-F04-PLAN-06`：决定发布实现是单一受控工具，还是拆成只读 release preflight 与有副作用的稳定源替换工具；需要与第 1、5 项共同确定职责边界。
- `SG-F04-PLAN-07`：确定发布锁的位置、所有者、安全检查和异常遗留处理，避免并发发布或遗留锁导致假阻塞。
- `SG-F04-PLAN-08`：设计稳定源替换的最小事务状态和恢复步骤，覆盖第二次 rename 失败、进程崩溃、磁盘不足、候选损坏和目标路径意外变化。
- `SG-F04-PLAN-09`：决定机器可读发布报告是否持久保存、保存位置和保留期，并避免形成新的长期版本事实源。
- `SG-F04-PLAN-10`：统一现有及未来稳定备份的命名、权限、内容验证和退出策略；实际旧备份清理转交第 8 项。
- `SG-F04-PLAN-11`：决定“目标提交已推送”是强制机械门禁，还是允许显式离线本地发布；该决策与第 1 项远程状态检查共同处理。
- `SG-F04-PLAN-12`：决定 Plugin/Skill validator 继续只作为本机发布门禁，还是增加可在 CI 稳定获得的验证方式；不得复制或修改第三方 Skill validator 形成漂移实现。
- `SG-F04-PLAN-13`：定义安全审查证据如何进入发布门禁；脚本可以要求明确输入或证明文件，但不能自行判断复杂代码已经通过安全审查。
- 完整回滚的稳定源、缓存、全局规则和 Hook trust 顺序转交第 8 项，不能在本功能点只处理目录回退后就宣称发布已经恢复。

### 2.7 不再作为目标的内容

- 不从当前开发工作树直接复制发布，也不允许未提交修改混入稳定源。
- 不把开发仓库直接配置为 Marketplace 安装源。
- 不用符号链接连接开发仓库、稳定发布源或运行缓存。
- 不把稳定发布源改造成第二个长期维护的 Git 工作树。
- 不为发布包维护另一份人工文件白名单；完整 tag 导出更直接，也不容易遗漏运行资产。
- 不让 CI 自动替换本机稳定发布源、执行插件安装或修改其他本机 Codex 状态。
- 不因为当前 `rc.9` 稳定源已经与 tag 完全一致，就把人工发布步骤视为已经具备可重复和失败安全保证。

### 2.8 证据与当前验证范围

- 仓库证据：`docs/release-process.md`、`README.md`、`.github/workflows/ci.yml`、`scripts/check_installation.py`、`tests/test_release_tools.py`、`tests/test_plugin_structure.py`、Git tag 类型和提交关系。
- 真实环境只读证据：当前稳定发布源及两份备份的目录类型、权限、Manifest 版本和树哈希；从 `v0.4.0-rc.9` 临时执行 `git archive` 后与稳定发布源进行树哈希和文件级比较。
- 已确认结果：当前稳定源是 `v0.4.0-rc.9` 的干净普通目录副本，且没有 `.git` 元数据或内容漂移。
- 本项没有替换稳定源，没有修改或删除现有备份，没有生成提交或 tag，也没有执行插件重装、缓存修改、Marketplace 修改或 Hook trust 操作。

## 3. Marketplace 选择与插件重装编排（已确认）

### 3.1 功能结论

- 建议名称：Marketplace 选择与插件重装编排。
- 一句话职责：确认 Marketplace 指向正确的稳定发布源，调用 Codex 官方插件安装命令生成新安装缓存，并把旧缓存保护和安装后验收交给对应下游功能。
- 本功能点必须保留；继续调用官方 `codex plugin add` 并由项目包装器保护升级前实际缓存的职责边界正确。包装器现已收敛为只保护显式 N-1，但仍不应自行实现第二套 Marketplace、插件复制或缓存安装机制。
- 当前真实 Marketplace 配置和插件安装状态正确；包装器已经取得显式上一版本、目标 Manifest 版本并检查目标缓存存在，但尚未机械证明安装前 Marketplace 来源以及安装后的 installed/enabled、来源路径和稳定源/缓存哈希。

### 3.2 当前事实

- 默认 Personal Marketplace 文件为 `$HOME/.agents/plugins/marketplace.json`，顶层名称是 `personal`，只包含一个 `subagent-governance` 条目。
- Marketplace 条目的 `source` 是本地来源，`path` 为 `./plugins/subagent-governance`；Codex 以 Marketplace 根目录 `$HOME` 解析该路径，实际来源为 `$HOME/plugins/subagent-governance`，与当前稳定发布源一致。
- Marketplace 条目的 `policy.installation` 为 `AVAILABLE`，`policy.authentication` 为 `ON_INSTALL`，分类为 `Productivity`；当前配置符合 OpenAI 官方插件 Marketplace 字段要求和内置 `plugin-creator` 的默认结构。
- 2026-08-10 只读执行 `codex plugin list --marketplace personal --json` 确认：`subagent-governance@personal` 为 installed、enabled，版本为 `0.4.0-rc.9+codex.20260808155909`，来源为稳定发布目录。
- `codex plugin marketplace list` 把 `personal` 的 Marketplace 根目录报告为 `$HOME`；默认 Personal Marketplace 已被隐式发现，不需要执行 `codex plugin marketplace add`。
- 当前 `~/.codex/config.toml` 显式保存 `[plugins."subagent-governance@personal"] enabled = true`；插件 installed 与 enabled 是两个不同状态，不能仅凭存在缓存或 `codex plugin add` 返回 0 推断二者都满足。
- 历史本机流程使用 `subagent-governance@personal`。公开安装改造后，`scripts/reinstall_preserving_caches.py` 默认使用公开 Marketplace `subagent-governance`，即选择器 `subagent-governance@subagent-governance`；维护者可通过 `--marketplace personal` 使用原 Personal Marketplace，也可通过 `--plugin-spec` 显式覆盖。命令仍使用参数数组调用而不是 shell 拼接。
- 包装器在调用原生命令前恢复完整遗留快照、检查缓存目录安全，并只复制 `--previous-version` 指定的升级前实际缓存；原生命令结束或异常后尝试恢复该 N-1，并输出命令、目标/上一版本、返回码、失败阶段、恢复结果和清理候选等 JSON 事务记录。
- 包装器没有读取 Marketplace 文件或 `codex plugin list`，因此重装前不证明 `personal` 仍是正确 Marketplace、条目仍唯一或来源仍指向稳定发布源。
- CLI 默认从稳定脚本所在插件目录读取 Manifest 形成目标版本，并在原生命令返回 0 后确认目标版本缓存目录已经生成；它仍没有证明插件 installed/enabled、来源路径未变化或稳定源与新缓存内容一致。
- 包装器当前不捕获 `subprocess.run()` 的 stdout/stderr；普通非零返回码只出现在报告的 `returncode` 中，诊断信息依赖 Codex 子进程直接输出，`OSError` 才作为 `command_error` 写入报告。
- 原生命令返回非零时包装器仍恢复缓存，这是正确的兼容保护；但 Codex 配置、enabled 状态或 Marketplace 快照若发生部分变化，包装器不会也不应直接手工回写 Codex-owned 配置。
- 包装器已使用 `.reinstall.lock` 阻止并发或遗留锁重入，并把最后事务状态原子写入 `last-transaction.json`；进程硬崩溃后的锁确认和人工恢复命令仍未实现。
- `tests/test_release_tools.py` 已使用伪 runner 覆盖显式 N-1、命令非零/异常、目标缓存缺失、事务锁、遗留快照和清理候选；它仍不覆盖 Marketplace 选择、稳定源来源、原生命令 stdout/stderr、installed/enabled、来源路径和稳定源/缓存哈希后置条件。
- OpenAI 官方文档确认 Marketplace 是插件目录，`source.path` 相对于 Marketplace 根目录解析，默认 Personal Marketplace 位于 `~/.agents/plugins/marketplace.json`，非默认 Marketplace 才需要显式添加；内置 `plugin-creator` 进一步要求更新已有插件时先确认 Marketplace 名称和来源，不手工修改 Marketplace 或 `config.toml`。
- OpenAI 官方文档对本地插件缓存版本目录使用了通用 `local` 描述，而当前 Codex CLI 和本机环境实际使用 Manifest 完整版本作为缓存目录；本项目应明确区分官方通用说明和当前已验证的 Codex 行为，不能用文档示例覆盖真实运行证据。

### 3.3 上下游交接

- 上游第 1 项输入：稳定发布源 Manifest 中已经确定的完整版本和 cachebuster 身份。
- 上游第 2 项输入：已完成候选验证、稳定源替换和替换后哈希确认的普通目录发布副本。
- Marketplace 输入：Marketplace 文件提供 Marketplace 名称、插件名称、来源类型、相对来源路径和安装策略。
- 本项输出：选择的 Marketplace 和插件标识、预期来源与版本、原生安装命令结果，以及足以让下游继续判断的重装阶段报告。
- 下游第 4 项消费：负责旧版本缓存快照、遗留快照恢复、内容冲突、崩溃恢复和缓存并发安全；本项只编排并消费该能力。
- 下游第 5 项消费：验证安装后的 installed/enabled、来源路径、稳定源与当前缓存哈希、目录安全和运行健康；原生命令返回码不能替代该诊断。
- 下游第 6 项消费：只有稳定安装路径确认后，才使用稳定发布源资产同步全局 `AGENTS.md`。
- 下游第 7 项消费：在新 Codex 任务中确认新版本被加载，并完成 Hook enabled/trusted 和代表性事件真实触发验收。
- 下游第 8 项消费：处理原生命令部分成功、配置状态不确定、缓存恢复失败或安装后验收失败时的稳定源与缓存回滚。
- 明确排除：本功能点不生成初始 Marketplace 文件，不手工编辑 `marketplace.json` 或 `config.toml`，不修改 Hook trust，不直接删除旧缓存，也不自行实现 Codex 插件安装逻辑。

### 3.4 已确认的目标规则

1. 重装前必须确认 Marketplace 文件、顶层名称、目标插件条目、来源类型和 `source.path`；解析后的真实来源必须等于已验证的稳定发布源。
2. 默认 Personal Marketplace 使用 `~/.agents/plugins/marketplace.json` 的隐式发现能力，不额外执行 `codex plugin marketplace add`；非默认 Marketplace 才进入显式配置分支。
3. 重装前读取稳定发布源 Manifest 的完整版本，把它作为预期安装版本和后续检查输入。
4. 继续使用官方 `codex plugin add <plugin>@<marketplace>`；项目包装器只增加前置检查、缓存保护、结果报告和后置验证，不复制安装逻辑。
5. 保留 `--plugin-spec` 或等价显式覆盖能力；默认流程不能在未验证 Marketplace 来源的情况下盲目依赖硬编码名称。
6. 原生命令的非敏感 stdout/stderr、返回码和执行阶段应进入诊断报告，区分命令无法启动、原生命令非零、缓存恢复失败和安装后置条件失败。
7. 原生命令返回 0 只是安装动作完成信号，不是完整成功证据；后续至少确认插件 installed、enabled 状态明确、来源路径仍为稳定发布源、目标版本缓存存在，并由第 5 项验证稳定源与当前缓存一致。
8. 包装器不得直接编辑 Codex-owned `config.toml`、Marketplace 快照或 Hook trust；原生命令部分成功导致配置状态不确定时，应明确报告并转交回滚或人工验收。
9. Marketplace 预检查、缓存快照、原生命令和后置验证需要共享明确的重装身份或锁，避免并发重装互相干扰；具体锁与恢复由第 4、8 项共同决定。

### 3.5 可以局部直接实施的改进

以下改进可在最终统一方案授权实施时作为相对局部的包装器、测试或文档修改处理：

- 在重装前增加 Marketplace 文件、插件条目和来源路径的只读预检查。
- 在 JSON 报告中增加 Marketplace 名称、插件 ID、解析后的来源路径、稳定源预期版本和当前执行阶段。
- 保留并明确 `--plugin-spec` 覆盖能力，同时避免默认流程在来源未经确认时只依赖硬编码 `personal`。
- 捕获并报告原生命令的非敏感 stdout/stderr，为非零返回提供可定位上下文。
- 在原生命令后执行只读插件列表检查，报告 installed、enabled、来源和版本；是否直接作为硬门禁留待统一状态设计。
- 为 Marketplace 路径解析、重复或缺失插件条目、来源错误、版本不一致、命令无法启动和原生命令非零补充单元测试。
- 在发布说明中明确默认 Personal Marketplace 不需要 `codex plugin marketplace add`，且不允许更新流程手工修改 Marketplace 或 `config.toml`。

盘点阶段不直接修改 Marketplace、包装器、测试、发布文档或 Codex 配置；上述内容只作为后续实施输入。

### 3.6 必须留待统一方案的决策

- `SG-F04-PLAN-14`：决定 Marketplace 预检查放在重装包装器、第 5 项安装诊断，还是第 1、2 项共享的 release preflight；应避免三个入口重复解析同一配置。
- `SG-F04-PLAN-15`：决定默认 Marketplace 名称是从 Personal Marketplace 文件读取，还是保留项目限定的 `personal` 默认并只增加严格验证；不得依赖稳定插件包中不存在的外部 helper。
- `SG-F04-PLAN-16`：决定安装后 installed、enabled、来源和版本检查由包装器直接作为硬门禁，还是由统一安装诊断输出分层状态。
- `SG-F04-PLAN-17`：评估 `codex plugin list --json` 当前字段的稳定性和兼容失败策略；不能未经边界测试就把易变 CLI JSON 变成无法降级的发布阻断点。
- `SG-F04-PLAN-18`：定义 enabled 状态变化的处理方式；初步倾向只报告并要求明确决策，不由包装器直接修改 Codex-owned 配置。
- `SG-F04-PLAN-19`：定义原生命令部分成功后配置状态不确定的回滚和验收边界；缓存恢复不能被描述为完整插件状态回滚。
- `SG-F04-PLAN-20`：决定重装锁与第 4 项缓存锁是否使用同一事务身份、状态文件和恢复入口，避免发布锁、重装锁和缓存锁互相独立漂移。
- Marketplace、稳定源、Codex 配置和运行缓存是否需要不同层次的备份，由第 8 项统一回滚方案决定；本项不单独创建配置快照机制。

### 3.7 不再作为目标的内容

- 不为默认 Personal Marketplace 额外执行 `codex plugin marketplace add`。
- 不在更新或重装流程中手工编辑 `marketplace.json` 或 `config.toml`。
- 不自行实现插件下载、目录复制、缓存命名或 installed/enabled 状态存储。
- 不把 `codex plugin add` 返回码单独当成完整安装成功证据。
- 不在原生命令完成前修改 Hook trust、处理真实 UI 验收或删除旧缓存；安装成功后的 N-2 及更早缓存清理由第 4 项负责。
- 不为了消除当前硬编码而直接依赖稳定插件中不存在的 `plugin-creator` helper；需要的 Marketplace 解析能力应有明确项目边界。
- 不把 OpenAI 文档中的通用本地缓存示例强行解释为当前 Codex CLI 的实际版本化缓存目录语义。

### 3.8 证据与当前验证范围

- 仓库证据：`scripts/reinstall_preserving_caches.py`、`tests/test_release_tools.py`、`docs/release-process.md`、`README.md` 和 `.codex-plugin/plugin.json`。
- 内置工具证据：`plugin-creator/SKILL.md` 与 `plugin-creator/references/installing-and-updating.md`。
- 官方文档证据：[Package your plugin](https://developers.openai.com/plugins/build/plugins)。
- 真实环境只读证据：Personal Marketplace 文件、`codex plugin list`、`codex plugin list --marketplace personal --json`、`codex plugin marketplace list`、稳定源路径、当前配置中的 enabled 状态以及版本化缓存目录清单。
- 已确认结果：当前 Marketplace 正确指向稳定源，插件为 installed/enabled，当前稳定版和加载来源均为 `0.4.0-rc.9+codex.20260808155909`；当前没有遗留的缓存 rollover 子目录。
- 本项未执行 `codex plugin add`，未修改 Marketplace、`config.toml`、稳定源、运行缓存、全局规则或 Hook trust。

## 4. 单版本兼容缓存保护与重装恢复（已确认）

### 4.1 功能结论

- 建议名称：单版本兼容缓存保护与重装恢复。
- 一句话职责：在插件升级前保存实际运行版本，升级成功后恢复该版本作为唯一回退缓存，并在完成安装验证后删除 N-2 及更早缓存。
- 本功能点必须保留，但现有“永久保留全部历史缓存”的策略已经不再需要。用户确认当前仍处于插件开发阶段，现有更早缓存可以清理；面向用户电脑的目标兼容窗口只包含当前版本 N 和升级前实际版本 N-1。
- 这个策略明确放弃对 N-2 及更早任务的运行路径保证。发布文档必须如实说明只支持一个版本的滚动回退窗口，不能继续宣称所有已打开历史任务都可无限期使用原缓存。

### 4.2 当前事实

- `scripts/reinstall_preserving_caches.py` 当前会在重装前恢复可确认完整的遗留快照，枚举缓存父目录中的全部普通目录，拒绝符号链接和非目录条目，并调用 `tree_digest()` 拒绝缓存树中的符号链接。
- 包装器要求通过 `--previous-version` 显式指定升级前实际版本，只把该目录复制到 `rollover-<pid>-<uuid>/cache`，写入完成 manifest 后执行官方 `codex plugin add`，再恢复被原生命令删除的 N-1。
- 原生命令返回非零或抛出 `OSError` 时仍会进入恢复路径；当前还通过 `finally` 保证 runner 抛出的其他正常 Python 异常在向上继续传播前先恢复缓存。进程被强制终止、机器崩溃或恢复自身失败仍依赖遗留快照路径。
- 同名缓存内容相同则保留重装后目录并跳过；同名内容不同则停止且不覆盖任何一方。冲突错误现已同时报告实际保留的快照目录和目标缓存路径。
- 快照完成后写入 `snapshot-manifest.json`；结构化快照缺少 manifest 时拒绝自动恢复。正常恢复后删除事务快照，最后阶段记录保存在 `last-transaction.json`。
- 当前使用 `.reinstall.lock` 阻止并发或未确认的遗留事务重入；硬崩溃后的锁清理必须人工确认，尚无自动恢复命令。
- 默认缓存父目录与快照父目录当前位于同一文件系统，且都是当前用户拥有的普通目录；包装器现已机械拒绝跨文件系统的自定义路径。
- `ordinary_directory()` 现已检查缓存父目录、每个版本化缓存、快照目录和恢复目标不是符号链接、属于当前用户且不允许组用户或其他用户写入；新建快照父目录和事务快照使用 `0700` 请求权限。父路径中的符号链接和可信根边界仍未建立完整机械检查。
- `tree_digest()` 包含相对文件路径、文件权限和内容，拒绝符号链接并忽略 `__pycache__`，但不包含目录本身和空目录差异。当前没有证据证明空目录差异会影响插件运行，先作为哈希边界记录，不单独修改。
- 当前真实缓存父目录包含 9 个版本目录，单目录规模约 84K 至 256K；快照父目录为空。当前只复制一份 N-1，快照成本不再随全部历史缓存数量线性增长。
- `tests/test_release_tools.py` 现有 13 项重装相关测试，覆盖显式 N-1、成功恢复、命令非零、命令启动 `OSError`、其他 runner 异常、目标缓存缺失、完整和不完整遗留快照、同名冲突、首次安装、事务锁、清理候选以及目录/文件系统安全。
- 当前测试仍未覆盖真实 `codex plugin add`、快照复制和清理失败注入、磁盘不足、进程硬崩溃后的人工恢复以及真实验收后的 N-2 删除提交。
- `README.md`、`docs/release-process.md` 和 `docs/optimization-plan.md` 已与当前显式 N-1、事务锁、完成 manifest、dry-run 清理候选和后置验收门禁保持一致。
- `docs/project-function-inventory.md` 的 SG-F02 交接和文件覆盖表仍把全部旧缓存描述为已打开任务的兼容层；该主盘点文档由其他任务维护，本任务不修改，只把这项跨文档冲突留给最终合并审查。SG-F05 只要求发布切换考虑旧运行代码读取共享状态的兼容性，在 N/N-1 窗口内仍成立，不要求无限保留历史缓存。

### 4.3 上下游交接

- 上游第 1 项输入：稳定发布源 Manifest 的目标完整版本 N，用于识别新缓存目录；升级前实际安装版本必须作为 N-1 记录，不能仅按目录名或语义版本排序推断。
- 上游第 3 项输入：已经验证 Marketplace 来源、稳定源目标版本和原生安装命令；第 3 项发起重装，本项提供缓存事务保护。
- 本项输出：重装前实际版本、快照身份、原生命令后的当前版本、恢复的 N-1、清理的更早缓存、失败阶段以及剩余快照状态。
- 下游第 5 项消费：先证明目标版本 N 已安装且当前缓存与稳定源一致，并确认 N-1 恢复正确；只有该健康检查成功后，才能提交 N-2 及更早缓存的删除。
- 下游第 7 项消费：真实新任务应加载 N；N-1 仅用于一个版本的回退和升级期间兼容，不作为新任务的默认加载版本。
- 下游第 8 项消费：若安装或真实验收失败，回滚到 N-1；本项只保证缓存文件存在，不代表 Marketplace、enabled、Hook trust、全局规则和稳定发布源已经整体回滚。
- 与 SG-F05 的边界：SG-F04 只管理 N/N-1 运行代码目录。N 与 N-1 是否都能读取共享治理状态、状态 Schema 如何迁移或拒绝，归 SG-F05 和最终统一方案；缓存恢复不得自行修改治理状态文件。
- 明确排除：本项不判断业务版本号，不修改 Marketplace 或 `config.toml`，不更新 Hook trust，不定义治理状态迁移，也不尝试发现或保留 N-2 及更早活跃任务。

### 4.4 已确认的目标规则

1. 升级完成后的稳定缓存集合只包含目标版本 N 和升级前实际安装版本 N-1；如果是首次安装，则只包含 N。
2. N-1 必须来自重装前的实际 installed/current 版本记录，不能通过缓存目录名称排序、文件时间或“最大版本号”猜测。
3. 重装前只快照 N-1，不再复制所有历史缓存；发现 N-2 及更早目录时先报告，不能在原生命令执行前删除。
4. 原生命令非零、无法启动或后置验证失败时，必须恢复 N-1，并保留足够证据判断当前缓存状态；失败路径不执行历史缓存清理。
5. 只有目标版本 N 的安装身份、installed/enabled、来源、当前缓存与稳定源哈希以及 N-1 恢复结果满足既定门禁后，才允许删除 N-2 及更早缓存。
6. 同名不同内容继续作为硬冲突，禁止自动覆盖；同名相同内容允许幂等跳过。
7. 部分快照不能作为完整遗留快照自动恢复。快照至少需要明确的预期版本、复制完成状态和阶段证据，未完成快照应隔离并报告。
8. Marketplace 预检查、N-1 快照、原生命令、后置验证和历史缓存清理应共用一个重装事务身份及并发锁。
9. 缓存与快照必须位于同一文件系统；当前实现明确拒绝跨文件系统自定义路径，不把 `shutil.move()` 的复制降级行为纳入支持范围。
10. 不增加可配置的无限保留数量，也不建设活跃任务扫描器。当前产品策略固定为一个上一版本回退窗口。

### 4.5 可以局部直接实施的改进

本轮已在用户明确授权后直接实施以下低风险内容：

- 修正同名冲突错误，使其报告真实保留的 snapshot 路径和冲突目标路径。
- 在成功或可恢复失败报告中增加 snapshot ID/path 和 `failed_stage=codex_command`；升级前实际版本和目标版本仍等待统一身份来源。
- 使用 `finally` 保证 runner 的非 `OSError` 异常在传播前也尝试恢复缓存，并为快照复制、缓存恢复和快照清理失败增加阶段化错误上下文。
- 增加原生命令非零、命令启动 `OSError`、其他 runner 异常、完整遗留快照、同名冲突、首次安装及目录/文件系统安全测试；原成功测试收敛为一个上一版本缓存，不再用测试固化多历史缓存保留。
- 补充缓存父目录、版本化缓存、快照和恢复目标的所有者及组/其他用户可写权限检查，新建快照目录请求 `0700`；父路径可信根和符号链接组件检查仍留给统一目录安全策略。
- 明确拒绝 snapshot parent 与 cache parent 的 `st_dev` 不一致，不在当前实现中支持跨文件系统快照。
- 更新发布说明，明确兼容窗口只有当前版本和上一版本，并删除“所有历史任务缓存无限保留”的目标表述；第 8 项随后把包装器收敛为只复制显式 N-1。

仍不能局部完成的内容是 N/N-1 真实版本识别、安装后健康门禁和清理提交。这三者需要第 3、5、8 项共享事务后才能补相应策略测试，不能用目录排序或“只留任意一个旧目录”替代。

本轮未清理本机真实缓存。缓存删除属于实际运行环境的破坏性操作，需要单独明确执行并先只读核对目标。

### 4.6 必须留待统一方案的决策

- `SG-F04-PLAN-21`：定义“升级前实际版本”的权威读取来源和失败边界，优先复用第 3、5 项的插件列表/Manifest 身份检查，避免包装器另建版本推断逻辑。
- `SG-F04-PLAN-22`：把第 3 项 Marketplace 预检查、缓存快照、原生命令、安装后健康检查和历史缓存清理合并为同一重装事务；锁和事务身份应与 `SG-F04-PLAN-20` 合并实现，不建立第二把独立缓存锁。
- `SG-F04-PLAN-23`：设计最小快照 manifest、复制完成标志、阶段记录和遗留快照恢复协议；部分快照必须隔离，不能自动恢复。
- `SG-F04-PLAN-24`：确定安装成功和允许清理 N-2 的精确门禁，以及“目标版本成功但 N-1 恢复失败”“恢复成功但清理失败”等部分成功状态的机器可读表达。
- `SG-F04-PLAN-26`：定义快照前磁盘空间检查和空间不足行为。当前数据量很小，不需要复杂配额系统，但不能在复制中断后把部分快照当成有效恢复点。
- `SG-F04-PLAN-27`：统一缓存父目录、快照父目录、锁和 manifest 的所有者、权限、父路径及符号链接安全策略，与第 2 项稳定源发布目录策略保持一致。
- `SG-F04-PLAN-28`：与 SG-F05 确认 N/N-1 同时存在时的共享治理状态兼容门禁；SG-F04 只消费“兼容、需要迁移或不可回退”的结论，不实现状态 Schema 迁移。
- 本机现有 N-2 及更早缓存是否现在清理、具体删除哪些目录和是否保留一次性备份，不属于盘点文档修改；如需执行必须由用户单独明确授权并先做只读目标核对。

### 4.7 不再作为目标的内容

- 不永久保留全部历史版本缓存。
- 不根据缓存目录数量、修改时间或语义版本排序猜测 N-1。
- 不在目标版本安装和验证成功前清理任何已有缓存。
- 不承诺仍引用 N-2 及更早缓存的历史任务继续运行。
- 不通过符号链接把旧版本映射到新版本，也不使用未证明安全的硬链接快照替代普通目录复制。
- 不建设缓存引用数据库、进程扫描器或自动识别所有已打开 Codex 任务的复杂系统。
- 不把缓存恢复描述为完整插件回滚；稳定源、Marketplace、enabled、Hook trust 和全局规则仍需第 8 项统一处理。

### 4.8 证据与当前验证范围

- 仓库证据：`scripts/reinstall_preserving_caches.py`、`tests/test_release_tools.py`、`docs/release-process.md`、`README.md`、`docs/optimization-plan.md` 和 `scripts/check_installation.py`。
- 跨功能证据：主盘点文档的 SG-F02/SG-F03 安装与状态交界，以及 `SG-F05-lifecycle-wait-recovery.md` 的状态版本与跨缓存兼容边界。
- 真实环境只读证据：当前缓存父目录中的 9 个普通版本目录、空的 rollover 快照父目录、目录所有者/权限和相同文件系统设备号。
- 用户确认的目标策略：当前开发阶段的更早缓存可以清理；面向用户电脑只保留当前版本和升级前一个版本。
- 本项未执行插件重装，未创建或恢复快照，未清理真实缓存，未修改 Marketplace、`config.toml`、稳定源、全局规则或 Hook trust。

### 4.9 本轮直接实施与验证记录

- 修改文件：`scripts/reinstall_preserving_caches.py`、`tests/test_release_tools.py`、`README.md`、`docs/release-process.md`、`docs/optimization-plan.md` 和本文。
- `SG-F04-PLAN-25` 已关闭：当前明确禁止跨文件系统快照，包装器通过 `st_dev` 检查提前拒绝；未来如确有支持需求，应作为新的显式设计决策处理。
- `SG-F04-PLAN-27` 已部分完成：最终目录所有者、组/其他用户写权限和新建快照权限已有门禁；父路径可信根、路径组件符号链接和与其他发布目录的统一策略仍保留。
- 第 4 项首次实施时有 8 项重装测试；经第 8 项事务收敛后，当前共有 13 项重装相关测试，进一步覆盖显式 N-1、目标缓存、事务锁、完成 manifest 和 dry-run 清理候选。
- 最新完整验证为 147 项单元测试通过；`scripts/subagent_governance.py`、`reinstall_preserving_caches.py`、`check_installation.py` 和 `apply_agents_block.py` 编译通过；Plugin validator 与 Skill validator 通过。
- 显式 N-1 选择、保护和清理候选已经实现；真实验收后的 N-2 删除提交尚未实现，因此仍不宣称缓存保留策略已经端到端完成。

## 5. 安装健康、部署同步与发布就绪诊断（已确认）

### 5.1 功能结论

- 建议名称：安装健康、部署同步与发布就绪诊断。
- 一句话职责：只读区分当前安装是否健康、稳定资产是否已经同步到运行缓存与全局规则、开发治理规则是否已部署，以及发布候选是否经过完整 preflight。
- 本功能点必须保留，但原单一 `clean` 状态已经删除。运行健康、部署同步、开发规则同步、缓存保留策略和发布就绪分别输出，不再让正常的未发布开发状态伪装成安装损坏。
- `scripts/check_installation.py` 继续只负责本机安装状态。Git 工作树、基础版本/cachebuster、提交/tag、候选副本、测试、validator 和安全审查应由独立 release preflight 负责，不把安装检查扩展成第二套发布编排器。

### 5.2 当前事实

- 当前脚本输出 `runtime_healthy`：检查开发仓库、稳定发布源、缓存父目录和当前缓存是当前用户拥有、不可被组用户或其他用户写入的普通目录；检查开发/稳定/缓存三层路径隔离、稳定源与当前缓存哈希、全局治理区间、全部缓存目录安全以及 legacy Hook 未挂载。
- `deployment_in_sync` 当前只表达稳定发布源、当前缓存和全局治理规则三层已同步，不表达开发工作树或 Git tag 已经发布。
- `development_rules_in_sync` 单独比较开发仓库与稳定发布源中的受管理治理规则区间。它为 false 时默认检查仍可成功，只在使用 `--require-development-sync` 时影响退出码。
- `retention_policy_satisfied` 机械要求当前版本之外最多存在一份普通安全缓存；传入 `--expected-previous-version` 时还要求该目录正是发布前记录的 N-1。未传入该参数时仍只能确认数量窗口。
- `release_ready` 当前固定为 JSON `null`，`release_readiness_status=not_evaluated`。脚本没有伪造尚未执行的 Git、tag、测试、validator 或候选发布结论。
- `codex_registration_checked=false` 和 `hook_trust_checked=false` 明确记录范围限制；Marketplace 来源、installed/enabled 和当前版本虽已通过外部只读 CLI 核对，但尚未由该脚本机械消费。
- `cache_inventory()` 现已对所有保留缓存检查最终目录类型、所有者、组/其他用户写权限和内部符号链接；不安全条目分别输出路径及错误详情。
- 稳定 Manifest 无法读取、JSON 非法、根节点错误或 `version` 不是非空字符串时，脚本返回结构化 JSON 错误，不再输出 Python traceback。
- `instruction_block()` 现已把标记缺失、重复和结束标记位于开始标记之前统一视为非法布局，不再因反向标记抛出未处理异常。
- 默认退出码只由 `runtime_healthy` 决定；`--require-development-sync` 和 `--require-retention-policy` 是两个独立的附加门禁。原 `--require-clean` 已删除。
- `clean`、通用 `issues`、重复别名 `agents_matches_asset`、`legacy_hook_absent` 和正常报告中恒真的 `separated` 已删除，替换为分层状态、问题数组和警告。
- `docs/project-function-inventory.md` 仍记录旧 `clean`/`--require-clean` 行为和“旧缓存需等待所有任务结束”的原结论；该共享主文档不属于本任务写入范围，已作为最终合并审查必须修正的跨文档冲突保留。

### 5.3 当前真实环境结果

- 2026-08-10 只读执行默认检查：退出码 0，`runtime_healthy=true`、`deployment_in_sync=true`，稳定源与当前 `rc.9` 缓存哈希一致，全局规则一致，legacy Hook 存在但未挂载。
- `development_rules_in_sync=false`：开发规则资产领先当前稳定发布源，表示开发修改尚未部署，不是当前安装故障。
- `retained_cache_count=8`、`retention_policy_satisfied=false`：当前历史缓存数量超过用户确认的 N/N-1 目标窗口，但目录本身均通过现有安全检查。
- `release_ready=null`：当前检查没有证明开发候选已经满足版本、tag、测试、validator、安全审查和候选副本门禁。
- 同时使用 `--require-development-sync --require-retention-policy` 时退出码为 1，原因是开发规则尚未部署且旧缓存超过一份；运行健康仍保持 true。
- 外部只读 CLI 证据仍确认插件 installed/enabled、Marketplace 为 `personal`、来源为 `$HOME/plugins/subagent-governance`、版本为 `0.4.0-rc.9+codex.20260808155909`。这些结果尚未合并进脚本的 `runtime_healthy`。

### 5.4 上下游交接

- 上游第 2 项提供已经替换并验证的稳定发布源；本项只验证当前稳定源与运行缓存和全局规则的已部署关系，不证明稳定源确实来自目标 tag。
- 上游第 3 项提供 Marketplace、installed/enabled、来源和预期版本；本项未来可消费稳定适配结果，但不执行 `codex plugin add` 或修改 Codex 配置。
- 上游第 4 项提供重装前记录的真实 N-1、快照结果和清理结果；本项通过 `--expected-previous-version` 消费其身份，不自行猜测 N-1。
- 下游第 6 项负责应用全局治理规则；本项只报告 `agents_matches_stable_asset`，不写入全局 `AGENTS.md`。
- 下游第 7 项负责交互式 `/hooks` trust、真实新任务加载和代表性事件触发；本项必须把这些状态标记为未检查，而不是根据配置文件存在推断成功。
- 下游第 8 项消费运行不健康、部署不同步和发布后验收失败结果决定是否回滚；本项不执行恢复或删除。
- 与 SG-F05 的边界：本项可消费 N/N-1 状态兼容结论形成发布门禁，但不迁移、修改或删除治理状态文件。

### 5.5 已确认的目标规则

1. 默认安装检查只对当前机械运行健康负责；开发内容尚未发布和历史缓存待清理不能再混入同一个失败状态。
2. `runtime_healthy` 的检查范围必须在报告中显式声明；当前范围是文件系统、稳定源/缓存、全局规则和 legacy 挂载，不包含 Codex 注册和 Hook trust。
3. 稳定源、缓存和全局规则同步使用 `deployment_in_sync`；开发规则是否已进入稳定源使用 `development_rules_in_sync`。
4. N/N-1 数量和身份共同使用 `retention_policy_satisfied`；真实 N-1 必须来自重装事务记录并通过 `--expected-previous-version` 输入。
5. 发布就绪未被实际检查时必须返回 `null/not_evaluated`，不能把 `runtime_healthy` 或 `deployment_in_sync` 当作 `release_ready`。
6. 预期的路径、Manifest、缓存或治理标记错误必须输出结构化 JSON，并返回非零；不得把普通诊断错误泄漏成 traceback。
7. installed/enabled、Marketplace 来源、版本和 Hook trust 应使用明确适配层及 unknown 状态，不能因 CLI 字段漂移使本地文件系统检查整体不可用。
8. 默认退出码只表达运行健康；附加策略使用独立参数，不恢复含义不清的 `--require-clean`。

### 5.6 本轮直接实施的改进

- 删除单一 `clean` 和 `--require-clean`，新增 `runtime_healthy`、`deployment_in_sync`、`development_rules_in_sync`、`retention_policy_satisfied`、`release_ready` 及分层 issues/warnings。
- 默认退出码改为所有运行健康检查失败时返回 1，不再只对稳定源/缓存哈希不一致硬失败。
- 增加 `--require-development-sync` 和 `--require-retention-policy` 两个精确门禁。
- 对开发、稳定、缓存父目录、当前缓存和兼容缓存增加所有者及组/其他用户写权限检查，并验证全部兼容缓存树中的符号链接。
- 增加三层路径隔离、Manifest version、治理标记顺序和预期错误结构化报告。
- 删除重复或误导性的输出字段，并通过 warnings 明确 Codex 注册、Hook trust 和 release preflight 尚未检查。
- 更新 `README.md` 和 `docs/release-process.md` 的命令、退出语义、N/N-1 和发布就绪边界。

### 5.7 必须留待统一方案的决策

- `SG-F04-PLAN-29`：确定 release preflight 是独立脚本还是统一发布工具的只读子命令，并复用第 1、2 项的版本、tag、候选和验证规则。
- `SG-F04-PLAN-30`：为 `codex plugin list --json` 建立受支持字段适配器和 unknown 降级，决定 installed、enabled、来源和版本如何进入运行健康或发布后验收。
- `SG-F04-PLAN-31`：明确 Hook trust 只能由交互式 `/hooks` 验收的部分，以及是否存在稳定的机械只读证据；配置中的 `trusted_hash` 记录存在不能直接视为当前定义已信任。
- `SG-F04-PLAN-32` 已完成局部基础：安装诊断支持 `--expected-previous-version` 并验证唯一旧缓存身份；统一发布事务仍需自动传递该参数和证据引用。
- `SG-F04-PLAN-33`：决定 SG-F05 的跨版本状态兼容结论如何进入 release preflight 和回滚门禁，不让安装检查自行解释状态 Schema。
- `SG-F04-PLAN-34`：确认 `config_references_hook()` 的 legacy 路径检查是否需要从文本包含升级为受支持配置结构适配，避免注释、备份文本或字段漂移产生误判。
- `SG-F04-PLAN-35`：定义 release preflight 的机器可读证据模型、退出码和“未检查/不适用/失败”状态，不能重复引入一个新的含糊 `clean`。

### 5.8 不再作为目标的内容

- 不恢复单一 `clean` 或 `--require-clean`。
- 不把开发规则领先稳定版描述为安装损坏。
- 不把稳定源/缓存一致或 `codex plugin add` 返回 0 描述为发布就绪。
- 不仅凭缓存目录是普通目录就判断其内部安全。
- 不仅凭 legacy Hook 文件存在就判断当前安装失败；真正的运行门禁是是否仍被活动配置挂载。
- 不从缓存目录名猜测 N-1，也不在诊断脚本中执行缓存清理。
- 不从 `trusted_hash` 记录存在推断当前 Hook 定义已经 trusted。

### 5.9 测试与验证证据

- `tests/test_release_tools.py` 当前有 4 项安装诊断测试，覆盖运行健康与开发同步分层、默认/附加退出码、一个及多个兼容缓存、非法缓存条目、legacy Hook 挂载、Manifest 错误、反向治理标记、缓存权限和嵌套符号链接。
- 发布工具测试当前共 26 项通过。
- 完整验证：147 项单元测试通过；相关 Python 脚本编译、Plugin validator 和 Skill validator 通过。
- 本项使用真实本机路径执行默认检查和两个附加门禁，结果与 5.3 记录一致。
- 尚未覆盖：真实 Codex CLI JSON 适配、Hook trust、release preflight、升级前版本的自动权威读取、状态跨版本门禁、legacy 配置精确解析和完整回滚触发。
- 本项没有执行发布、重装、Marketplace/config 修改、Hook trust 修改、缓存删除或全局规则写入。

## 6. 全局 `AGENTS.md` 最小入口分发（已确认）

### 6.1 功能结论

- 最终名称调整为“全局 `AGENTS.md` 最小入口分发”，不再称为完整治理规则分发。
- 一句话职责：在新版稳定源和运行缓存就位后，把指向 `$subagent-governance` Skill 的短入口安全同步到全局受管理区间，使完整协作规则只在真正使用子 Agent 时按需加载。
- 本功能点必须保留，但全局区间不应继续复制派发模板、通信格式、20 分钟等待、恢复状态和终态卡等大段协议。子 Agent 不是普通任务的常用入口，长期把完整规则放入每个任务上下文会产生不必要占用和规则漂移。
- 当前不建议完全取消全局入口。Skill description 可以帮助按任务触发，但普通父 Agent 也可能在用户没有明确提到“子 Agent”时自主决定调用 `spawn_agent`；如果它没有先加载 Skill，当前 Hook 会因缺失合法治理名称而拒绝首次调用。保留几行入口可以把“先加载 Skill”变成稳定前置条件，而完整细节仍按需加载。

### 6.2 当前事实

- `assets/agents-governance.md` 已收敛为 732 字节、单一标记区间内的四条短规则：普通任务不加载、涉及派发/通信/等待/恢复/中断/验收时先使用 `$subagent-governance`、完整协议只在 Skill 中维护，以及 Skill/Hook 不替代平台安全边界。
- 原全局资产中的治理等级、用户可见派发说明、通信字段、等待巡检、有限恢复和终态格式已经迁入 `skills/subagent-governance/SKILL.md`；相关运行时一致性测试改为验证 Skill，不再要求全局资产复制完整协议。
- Skill frontmatter 触发范围已经补充 `spawn_agent`、`send_message`、`followup_task`、`interrupt_agent` 以及等待、恢复、中断和终态验收，使按需加载边界不只覆盖“创建 Agent”。
- 本机用户真实全局 `AGENTS.md` 仍与当前 `rc.9` 稳定资产哈希一致；它与开发仓库的新最小入口不同。这是尚未发布的预期版本差异，本轮没有写入全局文件。
- `scripts/apply_agents_block.py` 继续要求全局文件和资产各自只有一对合法标记，只替换受管理区间并保留区间外用户内容；`--check --diff` 输出目标路径、资产路径、受管理区间哈希和 unified diff。
- 分发脚本现已检查全局文件、资产文件及各自直接父目录属于当前用户、不是符号链接且不允许组用户或其他用户写入；写入前后还会确认目标父目录的设备号和 inode 未变化。
- 原子写入保留目标 Unix mode，写入临时文件后执行文件与目录 `fsync`，并在读取后内容变化时停止覆盖。
- 退出码语义已经明确：`0` 表示一致或执行成功，`1` 只表示 `--check` 发现内容差异，`2` 表示路径、权限、标记、读取或写入错误。
- 当前稳定版脚本还没有 `--diff`，开发版已经具备；发布说明中的新命令只有在目标版本进入稳定源后才完整可用，不能把开发文档反向当作当前稳定脚本能力。
- 当前工具要求全局文件和唯一标记区间已经存在；缺少文件、没有标记或存在多对标记都会返回错误，不会自动创建或追加。
- 最新 SG-F05 文档仍把 provider 错误分类同时归因于开发规则资产和 Skill；规则资产精简后，该语义只保留在 Skill、运行边界和运行时代码中。最新 SG-F06 已建立独立终态功能，终态格式的内容归属也应从 SG-F05 交界进一步移交给 SG-F06。两项均属于最终合并时需要修正的跨文档版本差异，本任务不修改其他盘点文档。

### 6.3 主要归属与前后文交接

- `assets/agents-governance.md` 的“按需加载入口”及其稳定分发机制主要归 SG-F04；Skill 中治理等级和派发契约语义主要归 SG-F01，通信语义归 SG-F03，等待、恢复、中断和生命周期语义归 SG-F05，结构化终态和父任务闭环语义归 SG-F06。
- 上游第 2 项必须提供来自目标 tag 的稳定资产；上游第 3、5 项必须先确认目标稳定源和运行缓存已经就位。本项不能从仍在变化的开发仓库提前覆盖全局入口。
- 下游第 7 项在新任务中验证最小入口能够触发目标版本 Skill，并确认新版 Hook 与 Skill 使用同一协议版本。
- 下游第 8 项回滚时必须恢复上一稳定源和缓存，再使用恢复后的稳定脚本重新应用上一版入口；只回滚代码而保留新版全局入口会形成版本漂移。
- 与 SG-F05 的边界：已经打开的任务可能保留启动时读取的旧全局规则快照。本项只保证新任务加载当前稳定入口，不能改写已打开任务上下文，也不负责治理状态 Schema 迁移。

### 6.4 已确认的目标规则

1. 全局受管理区间只保留按需加载入口和最小能力边界，不复制完整协作协议。
2. 完整父 Agent 软指导以目标版本 Skill 为来源；Hook 和 Schema 只表达可机械执行或校验的约束。
3. 普通任务不加载子 Agent Skill；只有实际涉及派发、通信、等待、恢复、中断或终态验收时才加载。
4. 当前仍保留最小全局入口，直到真实证据证明 Skill 能在所有自主派发路径中可靠地先于 Hook 自动加载。
5. 全局入口只能来自已经就位的稳定发布源，不能直接使用开发工作树资产。
6. 发布前只验证目标入口资产合法；安装后才要求全局区间与目标稳定资产一致。
7. 分发只能修改唯一受管理区间；区间外用户内容、文件权限和并发修改必须受到保护。
8. 检查差异、执行错误和一致状态使用不同退出码，发布编排器不能把“有差异”和“工具故障”合并处理。

### 6.5 本轮直接实施的改进

- 将全局规则资产缩减为最小 Skill 入口，把完整派发、通信、等待、恢复和终态规则迁入 Skill。
- 扩展 Skill 触发描述和正文，使其覆盖创建之外的通信、等待、恢复、中断和终态场景。
- 更新结构与运行时一致性测试：限制全局资产体积，禁止重新塞入 `timeout_ms`、严格终态卡和治理名称等详细协议；完整语义改由 Skill 测试保护。
- 为全局文件、资产文件和直接父目录增加所有者、类型、符号链接和组/其他用户写权限检查，并检查写入期间父目录身份未变化。
- 更新 `README.md`、发布流程和优化计划，明确全局入口的安装时序、退出码和回滚交接。

### 6.6 必须留待统一方案的决策

- `SG-F04-PLAN-36` 已关闭：`--execute` 会在文件不存在时创建最小入口、在文件存在但无标记时保留原文并追加；重复、残缺或反向标记继续拒绝。`--remove` 只移除受管理区间。
- `SG-F04-PLAN-37`：把旧受管理区间摘要、上一稳定资产和恢复动作纳入统一发布事务，定义“代码已回滚但全局入口恢复失败”等部分成功状态。
- `SG-F04-PLAN-38`：把分发资产绑定目标版本、tag、稳定源路径和发布事务身份，机械阻止误用开发仓库脚本提前发布入口。
- `SG-F04-PLAN-39`：确认 macOS ACL、扩展属性和其他平台元数据是否必须跨原子替换保留；当前只明确保留 Unix mode。
- `SG-F04-PLAN-40`：统一 `apply_agents_block.py` 与 `check_installation.py` 的标记解析、文件权限和可信父路径逻辑，避免两个发布工具继续漂移。
- `SG-F04-PLAN-41`：与 SG-F05 定义新旧 Skill、N/N-1 运行代码、全局入口和已打开任务规则快照的兼容门禁。
- `SG-F04-PLAN-42`：在真实 Codex 中验证所有自主 `spawn_agent` 路径是否都会可靠触发 Skill；只有存在稳定证据且 Hook 能提供无首次失败的引导时，才重新评估是否可以完全取消全局入口。
- `SG-F04-PLAN-43`：最终合并时同步修正主盘点、SG-F05 和 SG-F06 对完整规则资产的旧归属描述；全局资产只拥有入口，完整语义按 SG-F01、SG-F03、SG-F05 和 SG-F06 分区归属。

### 6.7 不再作为目标的内容

- 不把完整子 Agent 协作手册常驻写入用户全局 `AGENTS.md`。
- 不让全局资产与 Skill 各自维护一份完整且容易漂移的协议。
- 不在开发仓库规则领先稳定版时提前更新用户全局入口。
- 不因为存在 Skill 就未经真实触发验证直接删除全部全局入口。
- 不在普通执行模式下自动创建用户全局文件或猜测治理区间插入位置。
- 不修改或覆盖受管理区间之外的用户规则。

### 6.8 测试与当前验证范围

- 新增不安全文件和直接父目录权限测试；写入器会在任何覆盖发生前拒绝组用户或其他用户可写的目标。
- 插件结构测试限制全局资产不超过 1200 字节，并确认它只包含 `$subagent-governance` 按需入口而不复制详细协议。
- 运行时契约和等待恢复一致性测试已经改为读取 Skill，证明完整规则仍受测试保护。
- 五项新增或调整的定向测试已通过；最新完整回归共 147 项通过，相关 Python 编译、Plugin validator 和 Skill validator 均通过。
- 本机只读检查确认：开发版全局入口与用户当前全局规则不同并返回差异退出码 1；当前稳定版规则仍与用户全局区间一致并返回 0；安装检查继续报告 `runtime_healthy=true`、`deployment_in_sync=true`，证明本轮开发修改没有污染当前稳定运行环境。
- 本项没有执行稳定发布、插件重装、Marketplace/config 修改、Hook trust 修改、缓存删除或用户真实全局 `AGENTS.md` 写入。

## 7. 目标版本真实加载、Hook trust 与端到端验收（已确认）

### 7.1 功能结论

- 一句话职责：在目标稳定源、运行缓存和最小全局入口部署后，通过机械注册检查、真实 `/hooks` trust、新任务 Skill 加载和代表性生命周期 smoke 证明 Codex 实际运行的是目标版本。
- 本功能点必须保留，并与第 5 项安装诊断分开。第 5 项证明本机文件系统、稳定源、缓存和全局入口处于一致健康状态；本项证明 Codex 产品层真正发现、信任并执行了目标插件。
- 这一项主要是发布验收协议和证据闭环，不需要增加第八类 Hook、第二套模拟平台或仓库内 trust hash 实现。

### 7.2 三层证据边界

| 证据层 | 能确认的事实 | 不能据此确认的事实 |
| --- | --- | --- |
| 仓库结构和测试 | Manifest、Skill 路径、七类 Hook、matcher、命令、超时、上下文限制和 handler 行为合法 | Codex 当前是否加载、信任或触发这些定义 |
| CLI 与配置只读检查 | 插件 installed/enabled、Marketplace、来源、版本、`features.hooks` 和历史 trust 记录存在 | trust 记录是否仍匹配当前定义、事件是否实际执行 |
| 真实 Codex 新任务 | `/hooks` 中当前定义的 enabled/trusted、目标 Skill 实际加载、最小入口按需触发和生命周期事件真实经过 Hook | 不代表所有 provider、平台版本和并发边界都已完成端到端覆盖 |

fixture、直接调用 `handle()`、Plugin validator、Skill validator、稳定源/缓存哈希和 `codex plugin add` 返回 0 都属于前两层证据，不能替代第三层。

### 7.3 当前真实环境只读证据

- 2026-08-10 执行 `codex plugin list --marketplace personal --json` 返回 `subagent-governance@personal`：`installed=true`、`enabled=true`、Marketplace 为 `personal`、来源为 `$HOME/plugins/subagent-governance`、版本为 `0.4.0-rc.9+codex.20260808155909`。
- 当前 `~/.codex/config.toml` 中 `features.hooks=true`，并存在插件 `pre_tool_use`、`post_tool_use`、`session_start`、`session_end`、`subagent_start`、`subagent_stop` 和 `stop` 七条 trust hash 记录。
- trust hash 记录只证明 Codex 曾为对应 Hook 身份保存过信任信息。仓库没有受支持的 hash 算法，也没有证据证明这些值与当前稳定缓存中的定义仍完全匹配。
- 当前任务公开的 `$subagent-governance` Skill 来自 `rc.9` 版本缓存，证明当前稳定版至少完成了 Skill 发现；它不能证明七类 Hook 全部执行，也不能验证尚未发布的开发版 `rc.10`。
- `hooks/hooks.json` 和结构测试确认开发仓库仍定义七类事件；fixture 覆盖成功生命周期、平台错误、恢复上限和中断，但都直接调用 handler，不是 Codex 真实事件证据。
- 本轮未打开交互式 `/hooks`、未创建新验收任务、未调用子 Agent smoke、未修改 trust，也未使用 `--dangerously-bypass-hook-trust`。

### 7.4 前后文交接

- SG-F02 拥有 Manifest、Skill 发现、七类 Hook 注册和运行时路由的预期结构；SG-F04 只消费这些预期，在发布后证明目标版本被真实加载。
- 上游第 3、5 项提供 installed/enabled、来源、版本、稳定源/缓存哈希和运行健康；这些只是本项 registration 层输入。
- 上游第 6 项提供最小全局入口；本项必须验证用户没有显式点名 Skill、但任务确实需要子 Agent 时，父 Agent 会先加载 `$subagent-governance`。
- SG-F05 提供等待、对账、恢复、中断、Stop 和 SessionStart/End 的预期状态链；SG-F06 提供终态结果和父任务闭环预期。本项只选择代表性安全场景验证这些链路真实进入 Hook，不重新定义状态语义。
- 下游第 8 项消费每个验收项的 `passed`、`failed` 或 `not_checked` 结果；任何必需项失败或未检查时都不能清理 N-2，也不能宣称发布完成。

### 7.5 目标验收矩阵

| 验收项 | 最低证据 | 是否允许机械检查 | 发布完成要求 |
| --- | --- | --- | --- |
| `registration_verified` | plugin ID、installed/enabled、Marketplace、来源和目标完整版本 | 是，CLI Schema 不识别时降级为 `not_checked` | 必须 `passed` |
| `deployment_verified` | 稳定源、目标缓存、最小全局入口和目录安全一致 | 是，复用第 5、6 项 | 必须 `passed` |
| `hook_trust_verified` | 真实 `/hooks` 中七类目标定义均 enabled/trusted | 当前必须交互式确认 | 必须 `passed` |
| `skill_loaded_from_target` | 新任务发现目标版本 Skill，而不是旧缓存 Skill | 需要新任务证据 | 必须 `passed` |
| `global_entry_verified` | 未显式点名 Skill 的安全子 Agent 场景会先按最小入口加载 Skill | 需要新任务行为证据 | 必须 `passed` |
| `lifecycle_smoke_verified` | 一条轻量只读子 Agent 完整生命周期真实触发主要 Hook，父任务正常闭环 | 需要真实 Agent 调用 | 必须 `passed` |
| `release_acceptance_complete` | 所有必需项均通过且记录目标版本、缓存路径、时间和证据 | 汇总状态 | 只有此项通过才允许收口 |

每个原子验收项只允许 `passed`、`failed`、`not_checked`。不能把 trust 记录存在、fixture 通过或插件安装成功折算为真实验收通过。

### 7.6 真实验收的最小安全场景

1. 在目标版本发布完成后新建 Codex 任务，记录任务时间、目标完整版本和目标缓存路径；不能复用发布前已经打开的任务。
2. 在 `/hooks` 中逐项确认目标插件的七类 Hook 当前定义均 enabled/trusted；如果定义变化需要重新 review，按产品交互完成，不编辑 `config.toml`。
3. 使用一个不显式写 `$subagent-governance`、但明确适合只读子 Agent 的请求，验证最小全局入口会先引导父 Agent 加载 Skill。
4. 派发一个 `light` 只读 smoke Agent，例如读取一个固定非敏感文件并返回简短结果；记录用户可见派发说明、目标 Agent 标识和终态通知。
5. 通过该链路验证至少 PreToolUse、PostToolUse、SubagentStart、SubagentStop 和父任务 Stop；新任务启动同时提供 SessionStart 证据。SessionEnd 是否实际触发需要在任务结束后的受支持诊断或后续状态检查中确认，不能从任务关闭动作本身推定。
6. 任一必需证据缺失时记录 `not_checked`；任一明确不一致、未信任、未加载目标版本或生命周期失败时记录 `failed` 并转交回滚。

### 7.7 本轮可以直接实施的内容

- 在本文建立三层证据边界、目标验收矩阵、最小安全 smoke 场景和三态结果语义。
- 更新 `docs/release-process.md`，要求发布者记录目标版本、缓存路径、七类 `/hooks` 状态、新任务 Skill/入口证据、生命周期 smoke 和最终汇总结论。
- 明确禁止使用 `--dangerously-bypass-hook-trust` 作为发布验收；该选项会绕过本项要证明的核心门禁。
- 记录当前 `rc.9` 的 installed/enabled、来源和七条 trust 记录只读事实，同时保持 `hook_trust_verified=not_checked`，不把记录存在升级为信任成功。
- 保留既有结构测试和 fixture，不再为每个真实事件建设重复的平台模拟器。

### 7.8 必须留待统一方案的决策

- `SG-F04-PLAN-44`：为 `codex plugin list --json` 建立稳定字段适配器、Schema 漂移测试和 unknown 降级；与 `SG-F04-PLAN-30` 合并，不建立两套注册检查。
- `SG-F04-PLAN-45`：确认 Codex 是否会提供受支持的 Hook 状态只读接口；在此之前 `/hooks` 仍是 trust 权威证据，禁止反向实现 hash 算法。
- `SG-F04-PLAN-46`：定义机器可读 release acceptance 证据对象、三态枚举、目标版本/缓存/时间字段和退出码，并与第 5 项 release preflight 状态模型合并。
- `SG-F04-PLAN-47`：定义真实生命周期 smoke 的脱敏证据、任务清理和失败恢复边界，避免保存完整 prompt、敏感输出或内部平台响应。
- `SG-F04-PLAN-48`：为第 6 项最小全局入口建立真实隐式触发验收；如果无法可靠先加载 Skill，决定增强入口、改进 Skill discovery 还是调整 Hook 首次失败反馈。
- `SG-F04-PLAN-49`：把验收失败状态与第 8 项回滚事务连接，明确哪些失败需要恢复稳定源、缓存、全局入口或重新完成 Hook review。

### 7.9 不再作为目标的内容

- 不通过 trust hash 记录存在推断当前 Hook 已 trusted。
- 不自行计算、编辑或迁移 Codex-owned trust hash。
- 不使用 `--dangerously-bypass-hook-trust` 绕过验收。
- 不把 handler 单元测试、fixture 或 validator 描述成真实 Codex 端到端通过。
- 不在已经打开且固定旧缓存的任务中验收目标新版本。
- 不为七类 Hook 建设第二套 Codex 平台模拟器；仓库测试保护内部行为，真实 smoke 保护产品接入。
- 不因一次派发成功就推断 SessionStart、SessionEnd、恢复、错误和并发边界全部通过。

### 7.10 当前测试与验证范围

- `tests/test_plugin_structure.py` 保护七类 Hook 配置、matcher、命令、超时、状态提示、上下文限制、Manifest 和 Skill 入口。
- `tests/test_hook_fixtures.py` 保护成功生命周期、平台错误、恢复上限和中断的既定 payload 行为。
- 当前完整回归共 147 项通过，Plugin validator 和 Skill validator 也已通过，但这些证据只属于仓库层。
- CLI 与配置只读证据已经记录；`hook_trust_verified`、目标 `rc.10` 新任务加载、最小入口触发和真实生命周期 smoke 均保持 `not_checked`。
- 本项没有执行发布、重装、Marketplace/config 写入、Hook trust 修改、子 Agent 派发或新任务创建。

## 8. 回滚、旧缓存与 legacy 资产退役（已确认）

### 8.1 功能结论

- 一句话职责：在目标版本发布或真实验收失败时恢复上一稳定版本，并在成功验收后只保留当前版本和紧邻的上一版本缓存，安全退役更旧缓存、稳定备份和 legacy 资产。
- 本功能点必须保留。它是第 2～7 项失败路径和历史资产生命周期的统一收口，不应拆成独立的永久备份系统或全历史缓存管理功能。
- 当前运行版本 N 的缓存是运行必需资产；“只保留上个最新版本的缓存”是指历史兼容缓存只保留升级前实际版本 N-1。N-2 及更早缓存不再保留。
- 缓存重装恢复已经可以局部直接收敛；稳定源、Marketplace、全局入口、Hook trust 和真实验收之间的完整回滚仍不是一个原子事务，必须留给统一发布编排方案。

### 8.2 当前环境与退役候选

- 2026-08-10 只读检查确认当前稳定发布源 `$HOME/plugins/subagent-governance` 为 `0.4.0-rc.9+codex.20260808155909`。
- 上一稳定备份 `$HOME/plugins/subagent-governance.pre-v0.4.0-rc.9` 为 `0.4.0-rc.8+codex.20260808142230`，是当前可辨认的上一稳定候选；该身份目前来自人工发布历史，不是机器事务记录。
- 更旧备份 `$HOME/plugins/subagent-governance.backup-rc7-20260808142500` 为 `0.4.0-rc.7+codex.20260808140430`，已经是退役候选，但本轮没有删除。
- 当前运行缓存目录包含 `0.1.0`、`rc.1`、`rc.3`、`rc.4`、`rc.5`、`rc.6`、`rc.7`、`rc.8` 和当前 `rc.9` 共九份。按照最终策略，在下一版本成功安装和验收后，历史缓存只保留实际升级前版本 `rc.9`；更早目录均可清理。
- 当前滚动快照目录 `$HOME/.codex/plugin-cache-rollover/subagent-governance` 为空，没有待恢复快照。
- legacy Hook `$HOME/.codex/hooks/subagent_policy.py` 是符号链接，指向 `.cc-switch` 的迁移备份；当前 `~/.codex/hooks.json` 和 `config.toml` 均未引用它，安装检查报告为“存在但未挂载”。
- “未挂载”只证明当前配置不再使用 legacy Hook，不能证明所有已打开任务都没有固定该绝对路径。用户已明确授权清理旧版本缓存，但没有授权删除 legacy Hook、迁移备份或旧稳定发布备份，因此三类资产必须分别处理。

### 8.3 前后文交接

- 第 2 项提供可恢复的上一稳定副本和目标发布事务身份；没有这两个输入时，本项不能靠备份目录排序猜测回滚目标。
- 第 3、4 项提供升级前实际 installed/current 版本、N-1 快照和原生重装结果；本项只允许恢复这一份权威 N-1，不再恢复所有历史缓存。
- 第 5 项提供恢复后的文件系统、稳定源、当前缓存、全局入口和保留策略检查；`runtime_healthy=true` 不能替代产品层重新验收。
- 第 6 项要求回滚稳定源后使用上一稳定版脚本恢复上一版最小全局入口，不能让新版入口继续指向已经回滚的运行资产。
- 第 7 项把 registration、deployment、Hook trust、目标 Skill、最小入口和生命周期 smoke 结果交给本项。只有所有必需项为 `passed`，才允许提交 N-2 清理；任何 `failed` 或 `not_checked` 都必须保留回滚能力。
- SG-F05 已确认新旧缓存可能具有不同的 SessionEnd 状态保留语义。SG-F04 只管理运行代码目录的 N/N-1 保留，不能自行迁移或清除跨版本共享治理状态；该兼容门禁必须与 SG-F05 的状态版本策略一起验收。
- SG-F06 最终提供结构化终态与父任务闭环兼容要求；SG-F04 只消费协议兼容结论，不修改业务结果或状态语义。

### 8.4 已确认的回滚与保留规则

1. 发布开始前必须记录升级前实际 installed/current 完整版本、稳定源、Marketplace、N-1 缓存、全局入口摘要和验收状态。
2. 上一版本身份必须来自发布前记录，不能按目录名、版本字符串、修改时间或备份名称排序推断。
3. 重装时只快照升级前实际版本 N-1；首次安装没有旧缓存时允许没有 N-1。
4. 原生命令失败、无法启动、目标缓存未生成或缓存恢复冲突都属于未完成事务，不能进入历史缓存清理。
5. 安装成功只进入“待真实验收”，不能因为命令返回 0 就允许删除 N-2。
6. 真实验收全部通过后，稳定状态保留当前 N 和唯一 N-1；N-2 及更早缓存均可清理，不建立全历史缓存档案。
7. 回滚顺序固定为：恢复上一稳定源；从原 Marketplace 恢复或重新安装 N-1；确认稳定源与缓存一致；恢复上一版最小全局入口；重新确认 Hook trust；在新任务中重新完成真实验收。
8. trust 是 Codex-owned 产品状态。回滚工具只能要求重新 review 和记录结果，不能反向计算、编辑或恢复 trust hash。
9. 旧稳定备份只需保留当前版的一个明确回滚目标；更旧备份可以退役，但必须与对应发布事务和 N-1 身份一起决定，不能只看目录名称。
10. legacy Hook 只有在当前配置未挂载且确认没有仍打开任务固定引用其路径后才可删除；其 `.cc-switch` 迁移备份是否保留是独立外部资产决策。

### 8.5 本轮直接实施的改进

- `scripts/reinstall_preserving_caches.py` 新增显式 `--previous-version` 和目标版本校验。已有缓存时不提供升级前实际版本会停止，工具不再按目录顺序推断 N-1。
- 重装快照从“复制全部缓存”改为只复制显式 N-1；原生命令失败、无法启动、异常或目标缓存缺失时先恢复这一版本。
- 每个完整快照写入 `snapshot-manifest.json`；结构化快照缺少完成 manifest 时拒绝自动恢复，避免把进程崩溃留下的不完整复制当作可用回滚资产。
- 快照父目录新增 `.reinstall.lock`，并发执行或崩溃遗留锁会停止新事务并要求人工确认，不再让两个重装流程同时改写同一缓存树。
- 最后事务状态原子写入 `last-transaction.json`，记录事务 ID、目标版本、N-1、命令结果、失败阶段、恢复结果和清理候选。成功状态为 `reinstall_succeeded_pending_acceptance`，仍明确设置 `retention_cleanup_allowed=false`。
- 工具新增 N-2 dry-run 清单 `cleanup_candidates`，但本轮没有增加或执行自动删除；真实验收完成后如何提交清理由统一发布入口调用。
- `scripts/check_installation.py` 新增 `--expected-previous-version`，可以同时验证历史缓存数量最多一份且该目录确实是发布前记录的 N-1；任意其他单份旧缓存不再能够冒充正确保留状态。
- `docs/release-process.md` 已更新显式 N-1 参数、事务文件、并发锁、待验收状态、保留策略、检查命令和完整回滚顺序。
- 新增或调整测试覆盖显式 N-1、只恢复上一版本、首次安装、命令失败、命令异常、目标缓存缺失、遗留快照、同名冲突、并发锁、事务记录、清理候选 dry-run 和预期 N-1 身份检查。

### 8.6 必须留待统一方案的决策

- `SG-F04-PLAN-50`：把稳定源替换、Marketplace 重装、缓存事务、最小入口、Hook trust 和真实验收纳入统一发布事务，定义每一步的 `pending/passed/failed/rolled_back` 与部分成功状态。
- `SG-F04-PLAN-51`：为 `last-transaction.json` 定义正式 Schema、版本、保留周期、敏感字段边界和事务历史策略；当前只保留最后一次缓存重装状态，不建设永久发布数据库。
- `SG-F04-PLAN-52`：增加真实验收后的显式 retention finalize 动作，只删除事务中列出的 N-2 候选，并在删除前重新确认目标版本、N-1、验收事务和缓存树没有变化。
- `SG-F04-PLAN-53`：设计崩溃遗留锁与不完整快照的人工恢复命令。当前工具宁可停止并保留证据，不会根据 PID、时间或目录内容自动判定锁已经失效。
- `SG-F04-PLAN-54`：确定稳定发布备份只保留当前回滚目标的提交门禁，以及当前 `rc.7` 备份何时可以删除；不得把用户对旧缓存的授权扩展为稳定备份删除授权。
- `SG-F04-PLAN-55`：与 SG-F05 建立 N/N-1 共享状态兼容门禁，避免旧缓存代码使用旧 SessionEnd 语义破坏新版仍可恢复状态。
- `SG-F04-PLAN-56`：确定 legacy Hook 符号链接和 `.cc-switch` 迁移备份的引用检查与最终删除责任；当前安装检查只证明它未被现行配置挂载。
- `SG-F04-PLAN-57`：确定回滚后的 Hook trust、新任务加载和生命周期 smoke 如何写回同一验收事务；不能把文件恢复成功当作回滚完成。
- `SG-F04-PLAN-58`：最终合并时更新主盘点文档仍保留的旧事实，包括“快照全部缓存”、单一 `clean/--require-clean`、完整全局规则资产和旧测试数量；SG-F04 已确认的最新实现与边界优先，当前任务不修改共享主文档。

### 8.7 不再作为目标的内容

- 不保留 N-2 及更早运行缓存，不建设全部历史任务引用数据库。
- 不保留无限数量的稳定源备份；只需要当前版和一个明确的上一稳定回滚目标。
- 不按目录名、时间或语义版本排序猜测 N-1。
- 不自动清理仍处于 `pending`、`failed` 或 `not_checked` 发布事务的历史缓存。
- 不实现 trust hash 的反向计算、复制或直接编辑工具。
- 不把 legacy Hook 文件存在本身视为运行故障；当前配置仍挂载它才是严格健康问题。
- 不把缓存恢复包装器描述成完整发布回滚事务，它目前只保护缓存和记录局部安装状态。

### 8.8 当前测试与验证范围

- `tests/test_release_tools.py` 已覆盖缓存目录类型、所有者、权限、同文件系统、显式 N-1、只保留上一缓存快照、失败恢复、异常恢复、目标缓存存在性、遗留快照、冲突保留、首次安装、事务锁、事务记录和 dry-run 清理候选。
- 安装检查测试已覆盖最多一份历史缓存以及“保留目录必须等于预期 N-1”的身份检查。
- 本轮定向 `tests.test_release_tools` 共 26 项通过；最新完整回归共 147 项通过，相关 Python 编译、Plugin validator 和 Skill validator 均通过。
- 当前工具测试仍使用临时目录和伪造的原生命令，不能证明真实 Marketplace 重装、稳定源回滚、Hook trust 或新任务验收已经成功。
- 本项没有执行真实插件重装、缓存删除、稳定源替换、Marketplace/config 写入、Hook trust 修改、legacy Hook 删除或稳定备份删除。

## 9. 功能收口、覆盖审查与修改方案输入

### 9.1 最终功能身份

- 最终编号：`SG-F04`。
- 最终名称：稳定发布、安装与兼容缓存治理。
- 一句话职责：把已经验证的开发版本以可追溯、可诊断、可回滚的方式交付到稳定发布源、Personal Marketplace、当前运行缓存和最小全局入口，并只保留升级前实际版本作为唯一兼容缓存。
- 不拆分原因：发布身份、稳定副本、Marketplace 重装、缓存保护、安装诊断、全局入口、真实验收和失败回滚必须共享目标版本、上一版本、事务状态和验收结果；拆成两个大功能会重新产生两套版本事实和部分成功状态。

#### 上游输入

- SG-F01 提供待发布的治理等级、派发契约和 Skill 业务规则；SG-F04 不修改其语义。
- SG-F02 提供 Manifest、Skill、Hook 配置和统一运行时的预期发现结构；SG-F04 负责版本身份、稳定交付和真实加载验收。
- SG-F03 提供通信与有限恢复协议的发布内容；SG-F04 不处理消息参数或任务关联。
- SG-F05 提供状态版本、会话生命周期和 N/N-1 共享状态兼容结论；SG-F04 只把结论作为发布与回滚门禁。
- SG-F06 提供终态结果协议和跨版本兼容结论；SG-F04 不定义结果字段或验收语义。
- Git 提交、tag、测试、validator 和安全审查提供发布候选证据；没有完整证据时只能记录 `not_checked`，不能进入正式发布。

#### 下游运行依赖

- Personal Marketplace 必须继续指向与开发仓库隔离的稳定发布源。
- 新 Codex 任务从 Manifest 完整版本对应的当前缓存加载 Skill 和 Hook；已打开任务最多依赖唯一 N-1 缓存。
- 全局 `AGENTS.md` 只消费稳定资产中的最小 Skill 入口，完整协作规则按需从目标版本 Skill 加载。
- Hook trust、目标 Skill 加载和生命周期 smoke 由真实 Codex 验收，仓库测试不能替代。
- 回滚流程消费上一稳定源、N-1、上一入口和真实验收结果，并在新任务中重新闭环。

#### 明确排除

- 不拥有 SG-F01～SG-F03、SG-F05、SG-F06 的业务协议、状态机或结果模型。
- 不建立第二套插件管理器、Marketplace 格式、版本数据库、Agent 编排器或 trust hash 实现。
- 不永久保留全历史缓存、稳定备份或全部已打开任务引用数据库。
- 不从目录排序推断上一版本，不用符号链接连接开发、稳定源和缓存。
- 不把文件系统健康、命令返回 0、trust 记录存在或 fixture 通过描述成真实发布完成。
- 不在盘点任务中执行发布、重装、缓存删除、稳定源替换、Marketplace/config 写入、Hook review 或用户全局文件写入。

### 9.2 仓库文件覆盖

| 文件 | SG-F04 关系 | 覆盖结论 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | 次要发布门禁 | 在 Python 3.11/3.12 上编译运行时并执行完整单元测试；尚不运行发布工具编译、Plugin/Skill validator 或 release preflight。 |
| `.gitignore` | 仓库配置 | 排除缓存、构建、临时和日志产物，避免进入 tag；不是发布验证工具，也不证明工作树干净。 |
| `AGENTS.md` | 工作边界 | 规定开发仓库与稳定运行环境隔离、发布写入必须显式授权；不是插件发布资产。 |
| `.codex-plugin/plugin.json` | 共享；版本字段直接相关 | SG-F02 主要拥有 Manifest 发现和 UI 元数据；SG-F04 拥有 `version`、cachebuster、tag 和缓存身份交界。 |
| `assets/agents-governance.md` | 主要 | 稳定发布时分发到全局受管理区间的最小 Skill 入口；完整业务语义归其他功能。 |
| `docs/release-process.md` | 主要 | 当前人工发布、重装、验收和回滚操作入口。 |
| `docs/optimization-plan.md` | 次要 | 记录 legacy 退役、N/N-1 缓存和发布完成标准；已修正“复制全部缓存”的过时描述。 |
| `README.md` | 次要 | 说明三层目录、发布原则、显式 N-1 和安装检查入口。 |
| `docs/function-inventory/SG-F04-install-release-cache.md` | 主要 | SG-F04 唯一盘点事实、证据、交界和修改方案输入来源。 |
| `docs/project-function-inventory.md` | 只读交界 | 保存 SG-F01～SG-F03 和早期安装候选事实；仍含已登记待最终合并修正的旧实现描述。 |
| `docs/function-inventory/SG-F05-lifecycle-wait-recovery.md` | 只读交界 | 提供状态版本、SessionEnd 和跨缓存共享状态兼容要求。 |
| `docs/function-inventory/SG-F06-terminal-result-acceptance.md` | 只读交界 | 提供结果协议、终态和 N/N-1 兼容要求。 |
| `scripts/apply_agents_block.py` | 主要 | 检查或原子替换全局最小入口，保护标记、路径、权限、用户内容和并发修改。 |
| `scripts/check_installation.py` | 主要 | 只读输出运行健康、部署同步、开发规则同步、N-1 保留和未评估发布就绪状态。 |
| `scripts/reinstall_preserving_caches.py` | 主要 | 显式保护升级前实际 N-1，包装原生重装并记录局部事务和 N-2 清理候选。 |
| `scripts/subagent_governance.py` | 发布载荷与兼容输入 | 主要归运行时功能；SG-F04 只验证目标版本加载，并消费状态/结果跨版本兼容结论。 |
| `hooks/hooks.json` | 发布载荷与真实验收目标 | SG-F02 主要拥有注册；SG-F04 验证目标稳定版本七类 Hook 的 enabled/trusted 和真实触发。 |
| `skills/subagent-governance/SKILL.md` | 发布载荷与入口目标 | 完整协作规则归对应业务功能；SG-F04 负责稳定分发和最小入口触发验收。 |
| `skills/subagent-governance/agents/openai.yaml` | 发布载荷 | SG-F02 主要拥有 Skill UI 元数据；SG-F04 只保证目标 tag 和缓存包含一致文件。 |
| `skills/subagent-governance/references/governance-levels.md` | 发布载荷 | SG-F01 主要拥有；SG-F04 只要求随目标版本原样发布。 |
| `skills/subagent-governance/references/runtime-boundaries.md` | 发布载荷与兼容输入 | SG-F01、SG-F03、SG-F05 主要拥有；SG-F04 消费其中平台与跨版本边界。 |
| `schemas/task-contract-v1.schema.json` | 发布载荷与兼容输入 | SG-F01 主要拥有；SG-F04 只消费协议版本兼容结论。 |
| `schemas/task-result-v1.schema.json` | 发布载荷与兼容输入 | SG-F06 主要拥有；SG-F04 只消费结果协议兼容结论。 |
| `tests/test_release_tools.py` | 主要 | 保护安装检查、N-1 重装事务、最小入口分发及其安全边界。 |
| `tests/test_plugin_structure.py` | 共享 | 保护 Manifest、Skill/Hook 结构和最小全局资产；其中发布内容合法性属于 SG-F04 次要证据。 |
| `tests/test_governance.py` | 发布载荷回归 | 主要归运行时功能；完整回归用于发布门禁，不能替代真实 Codex 验收。 |
| `tests/test_concurrency.py` | 发布载荷回归 | 主要归 SG-F05；为发布安全审查提供状态并发回归，不测试发布事务。 |
| `tests/test_hook_fixtures.py` | 发布载荷回归与 smoke 前置 | 主要归 SG-F03、SG-F05、SG-F06；证明仓库 payload 行为，不证明真实 Hook trust。 |
| `tests/fixtures/opaque-spawn-v1.json` | 发布载荷 | SG-F01 主要拥有；SG-F04 只保证进入目标发布副本。 |
| `tests/fixtures/agent-status-error-v1.json` | 发布载荷 | SG-F03/SG-F05 主要拥有；SG-F04 不重新解释平台状态。 |
| `tests/fixtures/recovery-limit-v1.json` | 发布载荷 | SG-F03/SG-F05 主要拥有；SG-F04 不重新定义恢复次数。 |
| `tests/fixtures/interrupt-v1.json` | 发布载荷 | SG-F05 主要拥有；SG-F04 只把真实中断 smoke 纳入更高层发布证据。 |
| `tests/fixtures/lifecycle-v1.json` | 发布载荷 | SG-F05/SG-F06 主要拥有；SG-F04 不把 fixture 当成真实生命周期验收。 |

结论：仓库全部当前有效文件均已在 SG-F04 中标明主要、次要、发布载荷或明确排除关系；没有未解释的仓库文件。

### 9.3 核心代码区段覆盖

| 文件与区段 | SG-F04 职责 | 当前证据与剩余边界 |
| --- | --- | --- |
| `.codex-plugin/plugin.json` 的 `version` | 基础版本与唯一缓存身份 | 当前开发版为 `0.4.0-rc.10`，发布前仍需生成单一 cachebuster 并绑定 tag。 |
| `assets/agents-governance.md` 全文件 | 最小全局入口资产 | 结构测试限制体积、标记和按需 Skill 入口；真实隐式触发仍未验收。 |
| `apply_agents_block.managed_span()`、`_managed_block()` | 唯一合法标记区间解析 | 已覆盖缺失、重复、反向和资产区间外内容。 |
| `apply_agents_block._owned_directory()`、`_owned_regular_file()` | 全局文件、资产及父目录安全 | 已覆盖所有者、符号链接和危险权限；ACL/扩展属性仍待决定。 |
| `apply_agents_block.atomic_write()` | 并发保护的原子替换 | 已覆盖 mode 保留、内容读取后变化、父目录身份变化和 `fsync`。 |
| `apply_agents_block.main()` | `--check/--execute/--remove/--diff` 与退出码 | 支持首次创建、无标记追加、唯一标记替换和受管理区间卸载；非法标记布局继续拒绝。 |
| `check_installation.tree_digest()`、`ordinary_directory()` | 稳定源和缓存树完整性、安全与隔离 | 拒绝内部符号链接、所有者错误和危险权限；不是签名或远程来源证明。 |
| `check_installation.cache_inventory()`、`version_directory_name()` | 当前缓存外的 N-1 清单及身份边界 | 已检查全部缓存树并支持预期 N-1；不执行删除。 |
| `check_installation.manifest_version()`、`instruction_block()` | 当前完整版本和全局入口解析 | 错误进入结构化报告；未验证 tag 或 cachebuster 合法性。 |
| `check_installation.config_references_hook()` | legacy Hook 当前挂载检查 | 当前使用文本包含匹配，仍需受支持配置结构适配。 |
| `check_installation.main()` | 五类分层状态和退出码 | `release_ready` 保持 `null/not_evaluated`；CLI 注册和 trust 明确未检查。 |
| `reinstall_preserving_caches.validate_version_name()`、`select_previous_cache()` | 显式权威 N-1 | 已禁止目录排序猜测；CLI 权威版本读取仍由统一适配器提供。 |
| `reinstall_preserving_caches.write_json_atomic()`、`operation_lock()` | 最后事务记录和并发互斥 | 已覆盖普通成功和遗留锁；正式 Schema、历史保留和恢复命令仍未实现。 |
| `reinstall_preserving_caches.snapshot_cache_root()`、`restore_snapshot()`、`recover_stale_snapshots()` | 完整快照识别、冲突保护和遗留恢复 | 结构化部分快照拒绝恢复，同名不同内容不覆盖。 |
| `reinstall_preserving_caches.retention_candidates()` | N-2 dry-run | 只列出候选，不代表已经通过真实验收或允许删除。 |
| `reinstall_preserving_caches.reinstall()` | N-1 快照、原生命令、目标缓存检查、恢复和局部事务状态 | 只覆盖缓存与命令层；稳定源、Marketplace 状态、入口和 trust 不在同一事务。 |
| `reinstall_preserving_caches.main()` | 稳定版 CLI 入口 | 已有缓存时要求 `--previous-version`；不手工修改 Marketplace。 |
| `tests/test_release_tools.py` 的安装诊断测试 | 分层状态、错误 JSON、缓存安全和 N-1 身份 | 临时目录测试，不证明真实 CLI 或运行环境。 |
| `tests/test_release_tools.py` 的重装测试 | 快照、失败恢复、锁、事务记录和清理候选 | 使用伪造 runner，不执行真实 `codex plugin add`。 |
| `tests/test_release_tools.py` 的入口分发测试 | 标记、路径、权限、并发和原子写入 | 不写用户真实全局文件。 |
| `tests/test_plugin_structure.py` 的 Manifest/Skill/资产测试 | 发布载荷结构和最小入口 | 不能证明 Marketplace、Hook trust 或新任务加载。 |

### 9.4 测试证据与缺口

#### 已有证据

- `tests.test_release_tools` 当前 26 项全部通过。
- 全仓 147 项单元测试全部通过。
- `scripts/subagent_governance.py`、`scripts/check_installation.py`、`scripts/reinstall_preserving_caches.py` 和 `scripts/apply_agents_block.py` 编译通过。
- Plugin validator 与 Skill validator 通过。
- `git diff --check` 和本文尾随空白检查通过。
- 本机只读证据已覆盖当前 rc.9 注册来源、稳定源/缓存哈希、全局区间、缓存清单和 legacy Hook 未挂载状态。

#### 仍缺少的证据

- 没有确定性 release preflight 覆盖版本/cachebuster、提交、tag、候选副本、测试、validator 和安全审查。
- 没有原子稳定源替换、磁盘空间门禁、跨步骤崩溃恢复或完整发布回滚测试。
- 没有稳定的 `codex plugin list --json` Schema 适配与字段漂移测试。
- 没有受支持的 Hook trust 只读接口；真实 `/hooks` review 仍为权威证据。
- 没有目标 rc.10 的新任务 Skill 加载、最小入口隐式触发和真实生命周期 smoke。
- 没有真实验收完成后的 retention finalize 命令及删除前重校验测试。
- Windows 分支已加入实现与 CI 矩阵，但在公开仓库运行 GitHub Actions 前仍缺少真实 Windows runner 证据。
- 没有 SG-F05/SG-F06 状态与结果协议的 N/N-1 跨版本兼容验收。

### 9.5 疑似无用内容与退役边界

#### 仓库内

- 没有确认可以直接删除的有效源码、测试、Schema、Skill、Hook 配置或文档文件。
- `apply_agents_block.py`、`check_installation.py` 和 `reinstall_preserving_caches.py` 存在标记解析、目录安全和原子写入的重复实现，但它们当前均有调用和测试；属于未来共享基础逻辑候选，不是无用代码。
- `--plugin-spec`、`--target-version`、`--development-root` 等参数均承担测试、非默认路径或显式发布边界，不判定为无用扩展点。
- `docs/project-function-inventory.md`、SG-F05 和 SG-F06 中的旧事实属于并行盘点版本差异，不是可直接删除内容；最终合并时修正。

#### 真实安装环境

- N-2 及更早缓存是已授权的清理候选，但只能在目标版本真实验收通过并重新核对事务候选后删除；本轮未执行。
- 当前 rc.7 稳定备份是退役候选，但用户没有把缓存清理授权扩展到稳定备份；本轮未删除。
- 未挂载的 legacy Hook 符号链接是退役候选，但必须先确认没有已打开任务固定引用；其 `.cc-switch` 迁移备份是独立外部资产。
- Codex-owned 历史 trust 记录不是仓库可管理的无用文件，不手工编辑或反向清理。

### 9.6 八个统一修改包

| 修改包 | 合并的原始输入 | 已完成基础 | 最终统一方案仍需完成 |
| --- | --- | --- | --- |
| 1. 发布身份与 release preflight | `PLAN-01～05`、`11～13`、`29`、`35` | 已确认基础版本/cachebuster/tag 边界和分层状态原则 | 建立只读机器门禁、证据 Schema、离线/远程策略和安全审查输入。 |
| 2. 稳定副本与发布事务 | `PLAN-06～10`、`38`、`50～51` | 已确认干净 tag 导出、隔离目录、备份和局部事务记录 | 实现原子稳定源替换、统一锁、部分成功恢复及事务记录正式 Schema。 |
| 3. Marketplace 与注册适配 | `PLAN-14～20`、`30`、`34`、`44` | 已固定 Personal Marketplace 和原生 `codex plugin add` 边界 | 建立 CLI JSON 适配、unknown 降级、enabled 决策和配置精确解析。 |
| 4. N/N-1 重装、保留与 finalize | `PLAN-21～28`、`32`、`52～53` | 显式 N-1、快照 manifest、同文件系统、事务锁、目标缓存检查和 dry-run 已实现；`PLAN-25` 已关闭 | 增加磁盘门禁、真实验收后的删除提交、崩溃恢复命令和跨版本状态门禁。 |
| 5. 安装诊断与共享安全基础 | `PLAN-33`、`40` | 已拆分运行健康、部署同步、开发同步、保留策略和未评估发布就绪 | 统一三个工具的路径、权限、标记解析，并消费 SG-F05 兼容结论。 |
| 6. 最小全局入口生命周期 | `PLAN-36～39`、`41～43` | 入口已精简；首次创建、追加、替换、移除、原子写入和安全检查已实现，`PLAN-36` 已关闭 | 增加事务回滚、目标版本绑定、平台元数据策略和跨文档归属修正。 |
| 7. Hook trust 与真实发布验收 | `PLAN-31`、`45～49`、`57` | 三层证据、三态验收矩阵和发布记录模板已确认 | 完成 `/hooks`、目标新任务、隐式 Skill 触发、生命周期 smoke 和失败回滚联动。 |
| 8. 备份、legacy 与最终合并退役 | `PLAN-54～56`、`58` | 已区分缓存、稳定备份、legacy Hook 和 trust 记录的不同门禁 | 定义稳定备份退出、legacy 引用确认、迁移备份责任，并修正共享盘点旧事实。 |

这些修改包是后续统一修改方案的输入，不等于已经获得发布、删除或外部写入权限。原始 `PLAN-01～58` 保留在各功能点下作为证据和追溯编号，后续实现以本表八个修改包组织，不再创建 58 个平级任务。

### 9.7 最终完成结论

- SG-F04 的八个业务功能点、文件归属、核心代码区段、测试证据、真实环境证据、退役候选和跨功能交界均已完成盘点。
- 当前没有新的 SG-F04 业务功能需要继续逐项拆分；后续只进入全部功能文档的统一合并审查和修改方案设计。
- 已直接完成的局部改进包括 N-1 重装保护、事务记录与锁、安装状态分层、预期 N-1 检查、最小全局入口、分发安全和发布/回滚文档更新。
- 未完成内容均已归并到八个统一修改包，没有把真实 Hook trust、目标版本加载、跨版本状态兼容或完整发布事务误报为已完成。
- 本任务未修改共享主盘点或其他功能文档，未执行发布、安装、重装、缓存删除、稳定源替换、Marketplace/config 写入、Hook trust 修改、全局 `AGENTS.md` 写入、tag、提交或推送。

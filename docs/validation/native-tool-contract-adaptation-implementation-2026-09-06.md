# 原生工具契约适配：本地实施验收

- 日期：2026-09-06
- 实现基线：`d570e527b247ed41642d604a8937e800399b3f38`
- 候选：当前工作树未提交改动（供集中审查）
- 范围：开发仓库实现与隔离本地验证；未部署、未安装、未真实派发。

## E1–E4 结果

- E1：新增纯 `governance_native_adapter`，固定 `collaboration_turns` 与 `fork_context` 两种输出/归一化形态；手写 fixture 覆盖有限轮数、默认值、覆盖冲突、已知不匹配与不可验证输入。
- E2：升级为 `state-v10`，每个 phase 持久保存 `native_interface`；prepare、claim、异常写后回读、confirm 与 dispatch-result 转移均保留冻结字段。v9 及更早 namespace 未读取、迁移或删除。
- E3：PreToolUse 精确匹配新增 collaboration 工具名；可验证冲突拒绝，输入不可验证或内部故障 fail-open 且不 claim。成功/降级输出均不写回原生输入。
- E4：Skill、运行边界、架构与中英文 README 已调整；新模块已加入 runtime bundle。

## 实际检查

```text
python3 -m unittest tests.test_native_adapter -v                 PASS (5 tests)
python3 -m unittest discover -s tests -v                        PASS (109 tests)
python3 -m compileall -q scripts                                PASS
git diff --check                                                PASS
```

尚未执行部署、运行缓存哈希比对、真实 Hook 字段可见性、真实 native spawn、消息/等待/中断回执或重启后平台验收。因此本记录不证明任一原生接口的端到端可用性。终态后受管恢复和资源释放仍不在本轮能力范围内。

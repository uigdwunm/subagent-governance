# P2：统一 CLI/Hook UTF-8 字节边界

状态：已确认，待独立对话实施。

## 目标

所有 stdin JSON 模式统一按 UTF-8 bytes 限制输入。禁止以 Python 字符数代替字节数，也禁止先无界读取再编码检查。

## 已确认问题

当前 `_read_json` 使用：

```python
sys.stdin.read(MAX_HOOK_INPUT_BYTES + 1)
```

这是字符限制。实测 750,015 个多字节字符、2,250,015 bytes 的 JSON 可越过 2 MiB 上限。

## 统一 reader

建立一个 binary JSON reader：

1. 接收 `BinaryIO`。
2. 最多读取 `limit + 1` bytes。
3. 超限立即失败。
4. 严格 UTF-8 decode。
5. `json.loads`。
6. 按调用模式要求验证根是 object。

正式入口使用 `sys.stdin.buffer`。测试使用 `BytesIO` 或 `TextIOWrapper`，不要为了旧 `StringIO` 测试增加字符 fallback。

## 应用范围

- Hook mode
- prepare dispatch
- prepare spawn retry
- verify context manifest
- prepare communication
- prepare interrupt
- reconcile interrupted attempt
- record terminal notification
- parent disposition
- upsert group

Diagnose 和 read group 不消费 stdin。

## Hook 失败边界

解析前失败，包括超限、非法 UTF-8、非法 JSON、非对象根，此时 event 不可信：

- 不扫描前缀猜 Hook event。
- fail-open，返回 continue + system message。

只有已经成功解析 dict 且 `hook_event_name == "PreToolUse"` 后，handler/领域错误才可转换为 deny。

## 测试矩阵

- ASCII：limit、limit+1。
- 2-byte、3-byte、4-byte Unicode：按真实 encoded bytes 检查。
- 非法 UTF-8。
- 合法 UTF-8 非法 JSON。
- JSON array/null。
- reader 只请求 `limit+1`，不无界读取。
- 每个 CLI mode 共用同一 reader。
- 超限时业务函数和 store constructor 均未调用。
- 解析前 PreToolUse 字样不能改变 fail-open。
- 解析后真实 PreToolUse handler error 才 deny。

## 验收标准

- 不存在 `sys.stdin.read(MAX_* + 1)` 字符限制。
- 不存在读完整输入后才 `encode` 检查的路径。
- 所有 JSON stdin 模式走同一 binary reader。
- 大小错误消息包含 byte limit，不回显正文。
- Hook/CLI 回归、py_compile 和 Plugin validator 通过。

## 停止条件

- 为兼容测试需要同时维护 text/binary 两套 reader。
- 某个模式绕过统一 reader。
- 为判断 event 扫描未解析原始字节。

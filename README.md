# 版本化 + 幂等写入示例 API（Python / FastAPI）

一个最小但完整的写入服务，演示三件事：

1. **写入幂等**：重复提交相同内容只生效一次，同键异内容被明确拒绝，并发重复也不会重复/部分生效；
2. **资源版本与乐观并发控制（OCC）**：每次读带版本号，写入必须带版本，过期拒绝而非静默覆盖；
3. **对外 API 版本演进**：旧版本 `v1` 弃用但仍可用，`v2` 为当前版本，两者共享同一份状态，未知版本显式报错。

## 运行

```bash
uv sync --group dev
uv run python main.py          # 启动服务（随机端口）
uv run pytest                  # 运行全部场景测试（带场景化实时日志）
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/items/{id}` | 旧版读取（**已弃用**，响应带弃用头），形态 `{id,value,version}` |
| PUT/POST | `/api/v1/items/{id}` | 旧版写入（**已弃用**），请求体 `{value?, data?, expected_version?}` |
| GET | `/api/v2/items/{id}` | 当前版本读取，形态 `{id,name,data,version}` |
| PUT/POST | `/api/v2/items/{id}` | 当前版本写入，请求体 `{name?, data?, expected_version?}` |
| GET/PUT/POST | `/api/{非v1/v2}/...` | **不回落**任何默认版本，返回 `400 unsupported_api_version` |

所有读写响应都带头 `X-Resource-Version: <当前版本号>`。

## 一、幂等语义

### 请求标识

客户端在写请求上带头：

```
Idempotency-Key: <客户端生成的唯一字符串，建议 UUID>
```

服务端把 **方法 + 路径 + 规范化 JSON 请求体** 做 SHA-256 指纹（键序、空白差异归一），
与幂等键绑定，登记表保存在内存中（`app/idempotency.py`）。

### 规则

| 情况 | 行为 |
| --- | --- |
| 首次使用该键 | 执行写入，缓存完整终态（状态码、响应体、响应头） |
| 同键 + **相同内容**重复提交 | **不再执行写入**，直接重放首次的状态码与响应体；响应加 `Idempotency-Replayed: true` |
| 同键 + **不同内容** | 拒绝：`409 idempotency_conflict`，错误体 `details.idempotency_key` 指明冲突键 |
| 不带键 | 不做幂等保护，按普通请求处理（因此重试可能重复生效，请始终带头） |

**终态一致性**：不仅成功结果被缓存，业务错误（如版本冲突）同样被缓存为重放终态——
客户端无论重试多少次、资源此后是否被其他请求推进，都拿到与首次完全一致的结果。

### 并发重复请求

`acquire` 在一把全局可重入锁内登记“进行中”占位：

- 并发的相同请求里只有一个能成为“首个请求”真正写库；
- 其余相同请求在事件上阻塞等待，首个请求完成后**重放同一结果**；
- 因此至多生效一次，不会出现重复生效或部分生效；
- 并发期间到达的**不同内容**请求立即收到 `409 idempotency_conflict`，无需排队。
- 注意：若不同内容的请求先抢到了某个新键，则后到的同内容请求会被拒——
  幂等键的“内容契约”由**第一个登记该键的请求**确定，客户端应保证一键一用途。

## 二、并发冲突处理（乐观并发控制）

- 资源创建（不存在、且不带版本）：返回 `201`，版本初始化为 **1**。
- 之后每次成功更新，版本严格 **+1**。
- 更新已存在资源的规则：

| 情况 | 状态码 | 错误码 | 说明 |
| --- | --- | --- | --- |
| 未带 `expected_version` | `428` | `version_required` | 错误体回传 `current_version` |
| 版本与当前不一致（过期） | `409` | `version_conflict` | 回传 `expected_version` 与 `current_version`，**绝不静默覆盖** |
| 资源不存在（读，或带版本写不存在的资源） | `404` | `resource_not_found` | `current_version` 为 `null` |

典型重试循环：读取得到 `version=N` → 带 `expected_version=N` 写入 →
若收到 `409`，用错误体里的 `current_version` 重新读取、合并后再试。

整个「检查版本 → 修改 → 版本推进」在同一把锁内完成（`app/service.py`），
并发写被串行化，不会丢失更新。

## 三、对外版本兼容策略

- **v1 弃用但不下线**：功能完全可用；OpenAPI 中路由标记 `deprecated: true`，
  每个响应带 RFC 弃用草案头 `Deprecation`、`Sunset`（暂定 2026-12-31）与
  `Warning: 299 - "API version v1 is deprecated; please migrate to /api/v2"`。
- **同一状态，不同投影**：v1/v2 共享底层资源与版本号。v1 的 `value` 映射到规范字段
  `name`；v1 不输出 `data`，v2 输出完整 `{id,name,data,version}`。
  在任一版本写入，另一版本立即可见、版本号一致。
- **旧读取结果保持兼容**：版本推进不会改变既有响应的字段集合；
  通过幂等键重放还能拿到首次调用时冻结的旧快照，最新读取则返回新状态，两者互不污染。
- **未知版本显式失败**：`/api/v3/...`、拼写错误、大小写差异（如 `V2`）都返回
  `400 unsupported_api_version`，错误体列出 `supported: ["v1","v2"]`，
  不会默认落到任一版本。

## 错误响应统一形态

```json
{
  "error": "ResourceVersionConflict",
  "code": "version_conflict",
  "message": "版本 1 已过期，当前版本为 2",
  "details": {"resource_id": "doc", "expected_version": 1, "current_version": 2}
}
```

错误码集合：`idempotency_conflict` / `version_required` / `version_conflict`
/ `resource_not_found` / `unsupported_api_version`。

## 测试场景

`uv run pytest` 的实时日志按「场景 → 用例 → 结果」输出，结束时打印覆盖汇总：

- **场景1 写入幂等与并发重复提交**（`tests/test_idempotency.py`）
  - 同键同内容只生效一次、重放结果逐字节一致；
  - 同键异内容被拒且资源不被改动；
  - 8 线程真实并发相同请求：仅 1 次生效，其余全部重放；
  - 并发混入异内容：相同方一致重放、异内容方被拒；
  - 资源被其他请求推进后，旧键重放仍返回首次冻结结果。
- **场景2 资源版本与乐观并发控制**（`tests/test_versioning.py`）
  - 读取携带版本（响应体与 `X-Resource-Version`）；
  - 版本严格递增；过期版本被拒且不覆盖；版本缺失（428）/不存在（404）可区分；
  - 版本推进后旧快照形态与值保持兼容。
- **场景3 对外版本演进与跨版本一致性**（`tests/test_api_versions.py`）
  - v1 可用且带弃用标记（头 + OpenAPI）；v2 完整形态无弃用标记；
  - v1/v2 交叉读写同一状态、版本联动；未知版本（含大小写错误）显式报错。

## 代码结构

```
app/
  errors.py       # 统一错误类型（状态码 + 稳定错误码）
  fingerprint.py  # 请求内容规范化指纹
  store.py        # 带锁的版本化内存存储
  idempotency.py  # 幂等键登记 + 进行中请求等待/重放协议
  service.py      # OCC 判定、版本推进、幂等终态登记
  versioning.py   # 对外版本定义与严格解析
  api.py          # v1/v2 路由、投影、弃用头、未知版本兜底
tests/            # 三类场景共 15 个用例（含真实线程并发）
```

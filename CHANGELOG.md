# CHANGELOG

## 1.5.0 (2026-08-05)

### 修复
- **K/D 计算**：由错误的 `kills/rounds`（场均击杀）改为 `kills/deaths`；文字输出同步展示死亡数
- **LLM 工具**：改用 `@filter.llm_tool`，签名正确接收 `event`，从根源避免 `player_name` 被绑成事件对象
- **空战绩图片**：无模式数据时显示「暂无战绩数据」，与文字模式一致

### 变更
- 对局详情请求限制并发（默认 3），降低 PUBG API 429 风险
- 命令查询增加每用户冷却（默认 8 秒）
- 字体加载结果按字号缓存，避免重复 `fc-list` / 磁盘扫描
- 移除已关停的 `stadia` 平台；命令别名由泛化的「查询」改为「查pubg」
- 补充 MIT LICENSE；统一版本号至 1.5.0

## 1.4.2 (2026-05-18)

### 修复
- **崩溃修复**：`_pubg_lookup_tool` 在 LLM Function Calling 模式下，`player_name` 被错误绑定为 `AiocqhttpMessageEvent` 对象，导致 `_api_request` → aiohttp/yarl 拼接 URL 参数时抛出 `TypeError: Invalid variable type`

### 变更
- `_pubg_lookup_tool`：增加 `player_name` 非字符串类型检测与事件对象恢复逻辑
- `_fetch_all`：增加 `player_name`/`platform` 类型防御和自动转换
- `_api_request`：增加 `params` 参数清洗，自动过滤非法类型值

## 1.4.1 (2026-05-17)

### 修复
- 账号状态 `Innocent`（PUBG API 对正常账号的返回值）不再被误标为封禁，正确显示 `✓ 账号状态: 正常`

## 1.4.0 (2026-05-17)

### 新增
- 注册 `pubg_query` LLM function-calling 工具，agent 模式下可直接调用官方 API 查询战绩，避免 Web 抓取
- 新增 `_pubg_lookup_tool` 方法供 LLM 工具调用
- 新增诊断日志：插件加载状态、命令调用跟踪、API 请求进度

### 修复
- **命令注册 bug**：合并三个堆叠的 `@filter.command()` 装饰器为单指令 + alias，修复 handler 因 AND 语义无法激活的问题
- **`asyncio.gather` 容错**：`return_exceptions=True`，单场对局查询失败不再导致全部崩溃
- **请求超时**：移除 session 级 15s 共享超时，改为每请求独立 10s 超时
- **CJK 字体显示**：
  - 扫描本地 `fonts/` 目录加载自定义字体
  - 新增 NotoSerifCJK、fc-match 指定字体族、fc-list 穷举等多级回退
  - 加载字体时指定 `encoding="unic"`
- **仓库引用**：从失效的 `RainySY` 更新为 `sakuradairong`

### 变更
- 支持 `stadia` 平台
- 长玩家名在图片渲染时自动截断

## 1.3.0 (2026-05-17)

- 重构 PUBG 插件，添加玩家信息类，优化 API 请求和渲染逻辑
- 新增命令 "查ID" 和 "查询"

## 1.2.0 (2026-05-17)

- 添加图像渲染功能和文字回退

## 1.1.0

- 初始版本

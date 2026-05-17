# astrbot_plugin_pubg

AstrBot 插件 —— 查询 PUBG（绝地求生）玩家战绩。

通过官方 [PUBG API](https://developer.pubg.com/) 获取玩家终身战绩与最近对局数据，支持图片渲染（Pillow）与文字回退两种输出模式。

## 功能

- 查询玩家终身战绩（按模式展示：单排/双排/四排 × TPP/FPP）
- 最近对局列表（击杀、伤害、助攻、爆头、最远击杀、存活时间）
- 自动检测账号封禁状态
- 跨平台支持：steam、psn、xbox、kakao、stadia
- 图片输出（检测到吃鸡时高亮卡片）/ 文字回退

## 安装

在 AstrBot 的 `plugins` 目录下添加本仓库：

```bash
cd astrbot/plugins
git clone https://github.com/RainySY/astrbot_plugin_pubg.git
```

或下载压缩包解压到 `plugins/astrbot_plugin_pubg/` 目录。

### 依赖

插件会自动加载依赖，但建议手动安装以保证环境完整：

```bash
pip install -r requirements.txt
```

依赖：
- `astrbot>=3.0` — AstrBot 框架
- `aiohttp>=3.9` — 异步 HTTP 客户端
- `Pillow>=10.0` — 图片渲染（可选，缺失时自动回退文字输出）

## 配置

在 AstrBot 管理面板中为插件填写配置：

### `_conf_schema.json` 字段

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `api_key` | string | `""` | PUBG API Key（**必须**） |
| `default_platform` | string | `"steam"` | 默认查询平台 |

### 获取 API Key

1. 访问 [PUBG Developer Portal](https://developer.pubg.com/)
2. 注册账号并创建应用
3. 复制生成的 API Key
4. 在插件配置中填写 `api_key`

## 使用

### 命令

```
/pubg <玩家名> [平台]
/查ID <玩家名> [平台]
/查询 <玩家名> [平台]
```

- `<玩家名>` — PUBG 游戏内昵称（必需）
- `[平台]` — 可选，默认 `steam`。支持：`steam`、`psn`、`xbox`、`kakao`、`stadia`

### 示例

```
/pubg shroud steam
/查ID Shroud
/pubg player_name psn
```

### 输出说明

#### 图片模式（已安装 Pillow）

- 头部：玩家名、平台、查询时间
- 封禁状态栏（如有）：红色/黄色警示
- 终身战绩卡片：各模式的场次、胜率、Top10 率、K/D、场均伤害、场均存活时间
- 最近对局卡片：排名（吃鸡高亮绿色）、击杀、伤害等详情

#### 文字模式（未安装 Pillow）

内容同图片模式，纯文字排版，适用于不支持图片的平台。

## 数据来源

本插件使用 [PUBG API](https://developer.pubg.com/) 官方接口，数据来源于 PUBG 游戏服务器。

## LICENSE

本项目代码仅供学习参考，使用请遵守相关法律法规及 PUBG API 使用条款。

# 视频生成 Skill 使用指南

两个 skill，通过 MCP server 调用视频模型。可用于 Tencent WorkBuddy、Codex CLI、
Claude Desktop。

| Skill | 模型 | 网关分组 |
|---|---|---|
| `seedance-video` | 豆包 Seedance，8 个模型 | 如 `CM-Pro-Seedance` |
| `wan-video` | 通义万相 Wan，10 个模型 | 需含 `wan*` 通道的分组 |

两者都只需 Python 3.9+，无第三方依赖。

## 一、安装

```bash
git clone https://github.com/fore4stwOw2/naoshengyun-video-skills.git
cd naoshengyun-video-skills
cp -R seedance-video ~/.codex/skills/
cp -R wan-video ~/.codex/skills/
```

Codex 从 `~/.codex/skills/` 加载 skill。Claude Desktop 和 WorkBuddy 不限目录，
放在稳定的绝对路径下即可。

## 二、准备 API Key

Key 决定能用哪些模型。网关按分组授权，**分组里没有的模型无法调用**，会返回
`503 model_not_found`。先确认 key 的分组内容：

```bash
curl -s https://token.naoshengyun.com/v1/models \
  -H "Authorization: Bearer sk-你的key" | python3 -m json.tool
```

返回的 `data[].id` 就是这个 key 可用的模型。要用 Wan 就得看到 `wan3.0-video` 之类，
要用 Seedance 就得看到 `doubao-seedance-*`。

## 三、预检

跑一次诊断，确认环境和权限都没问题：

```bash
SEEDANCE_API_KEY=sk-你的key python3 ~/.codex/skills/seedance-video/scripts/verify_setup.py
WAN_API_KEY=sk-你的key      python3 ~/.codex/skills/wan-video/scripts/verify_setup.py
```

全绿即可用。它会分别区分这几类问题：Python 版本、TLS 证书、网关可达性、key 是否
有效、分组有没有对应模型、视频路由是否部署。出问题先看它的输出，别猜。

## 四、在宿主中配置

先取到绝对路径，GUI 宿主不会展开 `~`，也不一定能解析 `python3`：

```bash
python3 -c "import sys; print(sys.executable)"
echo ~/.codex/skills/wan-video/scripts/mcp_server.py
```

### Codex CLI

写入 `~/.codex/config.toml`：

```toml
[mcp_servers.seedance]
command = "/绝对路径/python3"
args = ["/Users/你/.codex/skills/seedance-video/scripts/mcp_server.py"]
env = { SEEDANCE_API_KEY = "sk-..." }

[mcp_servers.wan]
command = "/绝对路径/python3"
args = ["/Users/你/.codex/skills/wan-video/scripts/mcp_server.py"]
env = { WAN_API_KEY = "sk-..." }
```

### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`，然后重启：

```json
{
  "mcpServers": {
    "wan": {
      "command": "/绝对路径/python3",
      "args": ["/Users/你/.codex/skills/wan-video/scripts/mcp_server.py"],
      "env": { "WAN_API_KEY": "sk-..." }
    }
  }
}
```

### Tencent WorkBuddy

连接器只能在界面里添加，完整步骤与截图见
**[WORKBUDDY-SETUP.md](WORKBUDDY-SETUP.md)**。

视频模型**不能**走 设置 → 模型（那是对话协议），必须走 连接器 → 自定义连接器。

### 工具清单

| Seedance | Wan | 作用 |
|---|---|---|
| `seedance_generate_video` | `wan_generate_video` | 生成，默认等待并下载 |
| `seedance_get_video` | `wan_get_video` | 按 task_id 查询或续接 |
| `seedance_download_video` | `wan_download_video` | 下载视频 URL |
| `seedance_list_models` | `wan_list_models` | 查模型能力 |

### 几个实用点

渲染时间长的任务可以传 `wait: false` 先拿 `task_id`，之后用 `*_get_video` 轮询。
超时**不代表失败** —— 任务还在上游跑，用同一个 `task_id` 继续查就行，重新提交会二次计费。

Wan 各代模型能力差异较大，会直接影响请求能否成立：只有 `wan2.7-i2v` 支持音频驱动
口型，只有 wan3.0 系列和 2.7-i2v 支持尾帧，t2v 模型完全拒绝参考图且尺寸必须是
`1920*1080` 这种像素格式。传错组合客户端会在本地拦下，并告诉你哪些模型支持该功能。
不确定就先调 `wan_list_models`。

费用随时长、分辨率、模型档位上升。正式出片前先用 720P 短时长试一版。

## 六、环境变量

| 变量 | 必需 | 说明 |
|---|---|---|
| `SEEDANCE_API_KEY` / `WAN_API_KEY` | 是 | 网关令牌 |
| `SEEDANCE_OUTPUT_DIR` / `WAN_OUTPUT_DIR` | 否 | 视频保存目录 |
| `SEEDANCE_BASE_URL` / `WAN_BASE_URL` | 否 | 网关地址，默认 `https://token.naoshengyun.com` |

Key 只放在宿主配置或环境变量里，不要写进提示词、纳入版本控制或出现在截图中。
server 自身输出会把 `sk-` 开头的串脱敏，但贴进对话的 key 已经暴露了，应当轮换。

## 七、常见问题

**503 `model_not_found`** — 路由和 key 都没问题，是这个分组没有该模型通道。换 key
或让平台给分组加模型。

**401 `INVALID_API_KEY`** — key 无效或额度耗尽。注意一个格式正确的 `sk-` 串也可能被
拒；预检会拿它和一个已知无效的 key 对比来确认。

**404** — 路由在该网关未部署，和 key 无关。确认 base URL 是 `token.naoshengyun.com`
（不是 `api.naoshengyun.com`，后者没有视频路由）。

**server 起不来** — 基本都是解释器路径错误或 `~` 未展开。用绝对路径。

**工具能列出但调用全部 401** — GUI 宿主不读 shell 配置，key 要写在宿主配置里。

**`CERTIFICATE_VERIFY_FAILED`** — python.org 版 Python 的信任库是空的。客户端会自动
回退到 `certifi` 和常见系统证书；仍失败就跑
`/Applications/Python 3.x/Install Certificates.command`。

## 八、离线测试

不需要网络和 key：

```bash
python3 ~/.codex/skills/seedance-video/scripts/test_seedance_client.py   # 20 tests
python3 ~/.codex/skills/wan-video/scripts/test_wan_client.py             # 40 tests
```

## 九、已验证

两个 skill 都跑通了真实视频生成，产物经 MP4 容器解析确认可播：

| Skill | 模型 | 时长 | 规格 | 大小 |
|---|---|---|---|---|
| seedance-video | `doubao-seedance-2-0-260128` | 5.06s | 1280x720 H.264 + AAC | 1.54 MB |
| wan-video | `wan3.0-video` | 5.04s | 1280x720 H.264 + AAC | 10.12 MB |

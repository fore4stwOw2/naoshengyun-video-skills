# Video Generation Skills for MCP

两个 MCP server，让 AI 助手直接生成视频。支持 Codex、Claude Desktop、
Tencent WorkBuddy，以及任何兼容 MCP 的宿主。

只需 Python 3.9+，**零第三方依赖**，无需安装任何包。

| Skill | 模型 | 能力 |
|---|---|---|
| `seedance-video` | 豆包 Seedance，8 个模型 | 文生视频、图生视频、首尾帧、参考视频/音频 |
| `wan-video` | 通义万相 Wan，10 个模型 | 文生视频、图生视频、首尾帧、音频驱动口型 |

## 效果

两个 skill 均已用真实 API 验证，产物经 MP4 容器解析确认可播：

| Skill | 模型 | 产物 |
|---|---|---|
| seedance-video | `doubao-seedance-2-0-260128` | 5.06s / 1280x720 / H.264 + AAC |
| wan-video | `wan3.0-video` | 5.04s / 1280x720 / H.264 + AAC |

## 为什么需要 MCP server

视频生成是异步的：提交任务 → 轮询状态 → 取临时 URL。而各家客户端的"添加模型"
界面走的是 `/chat/completions` 对话协议，撑不起这个流程。

这两个 server 把 提交/轮询/下载 整个循环封装成普通的工具调用。AI 一次调用就能拿到
本地视频文件，不用自己管轮询和超时。

## 快速开始

```bash
git clone https://github.com/fore4stwOw2/mcp-video-skills.git
cd mcp-video-skills
cp -R wan-video ~/.codex/skills/

# 预检：确认环境和 key 分组都没问题
WAN_API_KEY=sk-你的key python3 ~/.codex/skills/wan-video/scripts/verify_setup.py
```

预检全绿后，在宿主里注册 MCP server（见 [USAGE.md](USAGE.md)），然后直接说人话：

> 生成一个 5 秒视频：橘猫在阳光下的窗台上伸懒腰，镜头缓慢推进，电影感

## 需要准备什么

**你自己的 API Key。** 本仓库不含任何凭据。

Key 按分组授权，**分组里没有的模型调不通**，会返回 `503 model_not_found`。这是最常见
的踩坑点，所以先查清楚自己的 key 能用哪些模型：

```bash
curl -s https://token.naoshengyun.com/v1/models -H "Authorization: Bearer sk-你的key"
```

返回的 `data[].id` 就是可用模型清单。用 Wan 需要看到 `wan*`，用 Seedance 需要看到
`doubao-seedance-*`。预检脚本也会把这个清单打印出来。

## 文档

| 文件 | 内容 |
|---|---|
| [USAGE.md](USAGE.md) | 完整使用指南：安装、三个宿主的配置、工具清单、常见问题 |
| [AGENTS.md](AGENTS.md) | 给 AI agent 的操作规范，其他 agent 平台可直接读取 |
| `*/SKILL.md` | 单个 skill 的说明与提示词建议 |
| `*/references/api.md` | 网关端点与参数参考 |
| `*/references/setup.md` | 逐宿主配置细节 |

## 设计要点

**超时不等于失败。** 超时后任务仍在上游运行，用同一个 `task_id` 继续轮询即可，
重新提交会二次计费。

**能力差异在本地校验。** Wan 各代模型差别会直接让请求失效：只有 `wan2.7-i2v` 支持
音频驱动口型，只有 wan3.0 系列和 2.7-i2v 支持尾帧，t2v 模型拒绝参考图且尺寸必须是
`1920*1080` 这类像素格式。传错组合会在本地被拦下，并告知哪些模型支持该功能，而不是
等网关返回一个含糊的 400。

**两种网关响应格式都兼容。** OpenAI 兼容接口和原生接口的状态字段大小写不同、视频 URL
位置不同。客户端做了归一化，并在兼容接口不返回 URL 时自动回落到原生接口或直接从
content 端点取流。

**密钥不外泄。** server 自身输出会对 `sk-` 开头的串脱敏。

## 测试

```bash
python3 seedance-video/scripts/test_seedance_client.py   # 20 tests
python3 wan-video/scripts/test_wan_client.py             # 40 tests
```

60 个离线测试，不需要网络和凭据。覆盖请求构造、模型能力校验、尺寸规则、双接口状态
归一化、轮询终止条件和密钥脱敏。

## 许可与责任

代码按 [MIT](LICENSE) 授权。

许可范围不包括视频模型本身、网关访问权限，以及生成的视频内容。使用者需自备凭据，
遵守网关和模型提供方的使用政策，并自行承担生成费用与内容责任。详见 [LICENSE](LICENSE)。

本项目与任何模型提供方或网关运营方无隶属关系。

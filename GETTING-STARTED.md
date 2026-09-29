# 视频生成 Skill 安装与使用指南

这份文档带你从零完成安装,并在 AI 助手里直接生成视频。

有两条路:**一条命令自动装完**(见下面的快速通道),或者手动一步步来(全程约 15 分钟)。

```
1. 准备 API Key   →  2. 确认 Python  →  3. 下载 Skill
                                            ↓
                  5. 开始生成      ←  4. 配置到你的平台
```

**在开始之前**,先了解两件事:

- 视频生成**按次计费**。每渲染一次都产生费用,并随时长、分辨率、模型档位上升。
  建议先用 720P、5 秒试出效果,再出正式版本。
- 你的 API Key 决定**能用哪些模型**。这是最容易出错的环节,第 1 步会专门处理。

---

## 快速通道:一条命令装完

会用终端的话,不必走下面七步。拿到 API Key 后执行:

```bash
curl -fsSL https://raw.githubusercontent.com/fore4stwOw2/naoshengyun-video-skills/main/install.py | python3 - --key sk-你的key
```

安装器会自动:检查 Python → 下载 skill → 用你的 key 向网关确认可用模型 →
只安装配得上的 skill → 写入检测到的宿主配置(改动前自动备份,不覆盖你已有的内容)。

装完重启 AI 应用,直接说:"生成一个 5 秒视频:橘猫在窗台上伸懒腰,电影感"。

卸载把 `--key sk-...` 换成 `--uninstall` 即可。

如果这条命令报错,或者你想自己控制每一步,继续往下看手动流程。

---

## 第 1 步:准备 API Key

### 1.1 获取 Key

在网关平台注册账号、充值额度,然后创建 API 令牌。令牌形如 `sk-` 开头的一长串字符。

创建令牌时需要选择**分组**。分组决定这个 Key 能调用哪些模型,选错了后面装好也用不了。

| 你想用 | 分组必须包含 |
|---|---|
| 豆包 Seedance 系列 | `doubao-seedance-*` 模型 |
| 通义万相 Wan 系列 | `wan*` 模型 |

### 1.2 验证 Key(重要)

拿到 Key 后先确认它到底能用哪些模型。打开终端(见下方说明),把 `sk-你的key`
替换成实际的 Key 后运行:

```bash
curl -s https://token.naoshengyun.com/v1/models -H "Authorization: Bearer sk-你的key"
```

返回内容里的 `"id"` 就是可用模型清单,例如:

```json
{"data":[{"id":"wan3.0-video",...},{"id":"wan3.0-video-prime",...}]}
```

这个例子说明该 Key 可以用 Wan,但**不能**用 Seedance。

如果返回的是错误信息,例如 `Invalid token` 或 `INVALID_API_KEY`,说明 Key 无效、
已作废或额度不足,先联系网关平台解决,不要继续往下装。

> **怎么打开终端**
> macOS:按 `Command + 空格`,输入 `终端`,回车。
> Windows:按 `Win` 键,输入 `PowerShell`,回车。

### 1.3 保管好 Key

Key 等同于你的账户余额,泄露后可能被人用来消耗你的额度。

不要把它发到聊天群、贴进文档、写进代码,或出现在截图和录屏里。只填在下文要求的
配置文件中。如果不小心泄露,去平台作废重建一个。

---

## 第 2 步:确认 Python

本工具需要 Python 3.9 或更高版本,**不需要安装任何额外的包**。

在终端运行:

```bash
python3 --version
```

看到 `Python 3.9.x` 或更高即可,跳到第 3 步。

如果提示找不到命令:

- **macOS**:运行 `xcode-select --install`,按提示完成安装。
- **Windows**:到 [python.org/downloads](https://www.python.org/downloads/) 下载安装。
  安装时务必勾选 **Add Python to PATH**,否则后续步骤会找不到它。装完重开终端。
  Windows 上命令用 `python` 而不是 `python3`。

---

## 第 3 步:下载 Skill

### 方式一:下载压缩包(推荐,无需额外工具)

1. 打开 https://github.com/fore4stwOw2/naoshengyun-video-skills
2. 点绿色的 **Code** 按钮 → **Download ZIP**
3. 解压到一个**固定不会移动**的位置,例如 `~/Documents/video-skills`

解压后目录里应该能看到 `seedance-video` 和 `wan-video` 两个文件夹。

### 方式二:用 git

```bash
git clone https://github.com/fore4stwOw2/naoshengyun-video-skills.git
```

### 记下绝对路径

后面配置要用到完整路径。在终端进入解压后的目录,运行:

```bash
pwd
```

把输出记下来,例如 `/Users/你的用户名/Documents/video-skills`。

---

## 第 4 步:跑一次预检

这一步会检查所有环节是否就绪,**强烈建议不要跳过**。它能在你配置之前就指出问题,
比装完发现用不了再回头排查省事得多。

在解压目录下运行(把 `sk-你的key` 换成实际 Key):

```bash
WAN_API_KEY=sk-你的key python3 wan-video/scripts/verify_setup.py
```

用 Seedance 的话:

```bash
SEEDANCE_API_KEY=sk-你的key python3 seedance-video/scripts/verify_setup.py
```

Windows PowerShell 里写法不同:

```powershell
$env:WAN_API_KEY="sk-你的key"; python wan-video\scripts\verify_setup.py
```

### 看结果

全部 `ok` 并显示 `All checks passed` 就可以继续:

```
[  ok] python: 3.12.0
[  ok] tls: certificate verification enabled with a usable CA bundle
[note] gateway: https://token.naoshengyun.com
[  ok] credential: present, 51 chars, ends ...ZK1y
[  ok] reachability: gateway responded to GET /v1/models with HTTP 200
[  ok] credential valid: gateway accepted the key
[note] group catalogue: 2 model(s) visible to this key: wan3.0-video, wan3.0-video-prime
[  ok] video route: POST /v1/videos accepted a task; generation is working
------------------------------------------------------------
All checks passed. Video generation is ready.
```

其中 `group catalogue` 那行列出的就是这个 Key 实际能用的模型,可以据此确认买对了分组。

出现 `FAIL` 时对照第 7 步的排查表,它会直接告诉你哪一环出了问题。

---

## 第 5 步:配置到你的平台

配置需要两个绝对路径。先取解释器路径:

```bash
python3 -c "import sys; print(sys.executable)"
```

输出形如 `/usr/bin/python3` 或 `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`。

另一个是第 3 步记下的 skill 目录。**两处都必须写完整路径**,不能用 `~` 或相对路径,
因为图形界面程序不会展开它们。

### Tencent WorkBuddy

WorkBuddy 的连接器只能在界面里添加,步骤和截图另开了一页:

**→ [WORKBUDDY-SETUP.md](WORKBUDDY-SETUP.md)**

一句话版本:视频模型**不能**走 设置 → 模型,必须走 连接器 → 自定义连接器。

### Claude Desktop

编辑配置文件:

- macOS:`~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows:`%APPDATA%\Claude\claude_desktop_config.json`

填入(路径和 Key 替换成你的):

```json
{
  "mcpServers": {
    "wan": {
      "command": "/usr/bin/python3",
      "args": ["/你的路径/wan-video/scripts/mcp_server.py"],
      "env": { "WAN_API_KEY": "sk-你的key" }
    }
  }
}
```

保存后**完全退出并重启** Claude Desktop。工具会出现在连接器图标里。

### Codex CLI

编辑 `~/.codex/config.toml`:

```toml
[mcp_servers.wan]
command = "/usr/bin/python3"
args = ["/你的路径/wan-video/scripts/mcp_server.py"]
env = { WAN_API_KEY = "sk-你的key" }
```

### 其他支持 MCP 的平台

填三项即可:命令为 Python 解释器路径,参数为 `mcp_server.py` 的完整路径,
环境变量为 `WAN_API_KEY` 或 `SEEDANCE_API_KEY`。通信方式是 stdio。

---

## 第 6 步:开始生成

配置好之后,**直接用日常语言提需求**就行,不需要记任何命令:

> 生成一个 5 秒视频:一只橘猫在阳光下的窗台上伸懒腰,镜头缓慢推进,电影感

> 把这张图做成视频,镜头缓慢推进,树叶轻轻飘动
> (附上图片链接)

> 用 wan3.0 生成一段小狗在海边奔跑的视频,720P,逆光日落

AI 会自己调用工具、等待渲染、下载文件,最后告诉你保存位置。

**渲染通常需要 1 到 5 分钟**,期间请耐心等待。视频默认存在:

- `~/Downloads/wan`
- `~/Downloads/seedance`

### 写好提示词

说清楚四件事效果最好:**主体、动作、镜头、光线**。

比较一下:

- 效果一般:`一只狗在海边`
- 效果更好:`金毛在浅海奔跑,低角度跟拍,逆光日落,电影质感`

一个 5 秒片段只安排**一个清晰动作**。想在 5 秒里塞进多次场景切换,画面容易混乱。

### 控制成本

费用随时长、分辨率、模型档位上升。建议:

1. 先用 720P、5 秒试出满意的提示词
2. 确认效果后再提高分辨率或时长

另外注意:如果 AI 提示**超时**,任务其实还在服务器上跑,让它用同一个任务 ID 继续查
就行。**重新生成会再收一次费**。

---

## 第 7 步:遇到问题怎么办

先跑第 4 步的预检,它会直接指出问题所在。下表是常见情况:

| 现象 | 原因 | 怎么办 |
|---|---|---|
| `503 model_not_found` | Key 的分组里没有这个模型 | 回到第 1.2 步确认可用模型,或联系平台调整分组 |
| `401 INVALID_API_KEY` | Key 无效或额度用尽 | 到平台检查余额,或重建令牌 |
| `404` | 网关地址不对 | 确认用的是 `token.naoshengyun.com` |
| 平台里看不到工具 | 服务未启动 | 检查两个路径是否为完整绝对路径 |
| 工具能看到但调用报 401 | 图形程序读不到 Key | Key 必须填在平台配置的环境变量里,不是终端里 |
| `CERTIFICATE_VERIFY_FAILED` | Python 证书未初始化 | macOS 运行 `/Applications/Python 3.x/Install Certificates.command` |
| 提示超时 | 渲染时间较长 | 任务仍在运行,让 AI 用同一任务 ID 继续查询,不要重新生成 |

### 该找谁

| 问题类型 | 找谁 |
|---|---|
| 额度、充值、分组权限、令牌失效 | 网关平台客服 |
| 安装配置、工具报错、功能疑问 | 本项目 [Issues](https://github.com/fore4stwOw2/naoshengyun-video-skills/issues) |
| 视频内容效果不理想 | 调整提示词,参考上文写法建议 |

---

## 附:各模型能力差异

不同模型支持的功能不同,**传错组合请求会直接失败**。工具会在本地拦下并提示哪些模型
支持该功能,不确定时可以直接问 AI「列出可用的视频模型」。

### Wan 系列

| 模型 | 图生视频 | 尾帧 | 音频驱动口型 | 说明 |
|---|---|---|---|---|
| `wan3.0-video` | 支持 | 支持 | 不支持 | 推荐默认 |
| `wan3.0-video-prime` | 支持 | 支持 | 不支持 | 画质最高,较慢 |
| `wan2.7-i2v` | 支持 | 支持 | **支持** | 唯一支持口型同步 |
| `wan2.7-t2v` | 不支持 | 不支持 | 不支持 | 纯文生视频 |
| `wan2.2-i2v-flash` | 支持 | 不支持 | 不支持 | 最快最省 |

### Seedance 系列

| 模型 | 说明 |
|---|---|
| `doubao-seedance-2-0-fast-260128` | 推荐默认,速度与质量平衡 |
| `doubao-seedance-2-5-260628` | 最新,提示词还原度最好 |
| `doubao-seedance-2-0-260128` | 画质最高,较慢 |
| `doubao-seedance-1-0-lite-t2v` | 最省,纯文生视频 |

完整清单和参数说明见 [USAGE.md](USAGE.md) 与各 skill 目录下的 `references/api.md`。

# WorkBuddy 配置视频 Skill

WorkBuddy 的 MCP 连接器只能在界面里添加,没有可以直接写入的配置文件。所以安装器
帮你备好了全部参数,但**最后一步需要你手动粘贴**。

Codex CLI 和 Claude Desktop 不需要看这一页,安装器会直接写好配置。

全程约 3 分钟。

---

## 先记住一件事

> **不要用「设置 → 模型」添加视频模型。**

那个入口走的是对话协议(`/chat/completions`),而视频生成是异步的:提交任务 →
轮询状态 → 取视频地址。对话协议撑不起这个流程,填进去不会报错,但永远出不来视频。

视频必须走**连接器**。这是最容易走错的一步。

| 入口 | 能否生成视频 |
|---|---|
| 设置 → 模型 | 不能 |
| 连接器 → 自定义连接器 | **能,用这个** |

---

## 第 1 步:先跑安装器

如果还没跑过,先执行(把 key 换成你自己的):

```bash
curl -fsSL https://raw.githubusercontent.com/fore4stwOw2/naoshengyun-video-skills/main/install.py | python3 - --key sk-你的key
```

安装器会做三件事:下载 skill、用你的 key 向网关确认能用哪些模型、把参数写进一个
参照文件。留意输出里这一行,它是下一步要打开的文件:

```
✓ Tencent WorkBuddy: /Users/你/.workbuddy/video-skills-connector.json
```

---

## 第 2 步:打开参照文件,拿到三个值

```bash
cat ~/.workbuddy/video-skills-connector.json
```

内容长这样(你的路径和 key 会不同):

```json
{
  "mcpServers": {
    "wan": {
      "command": "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
      "args": [
        "/Users/你/.codex/skills/wan-video/scripts/mcp_server.py"
      ],
      "env": {
        "WAN_API_KEY": "sk-你的key"
      }
    }
  }
}
```

你需要的就是 `command`、`args`、`env` 这三处的值。先别关这个窗口。

> 如果文件里同时有 `wan` 和 `seedance` 两项,说明你的 key 两个都能用。
> 按同样方式各建一个连接器即可,两者互不影响。
>
> 如果只有一项,是正常的:安装器只会配置你的 key 真能调通的那个,避免以后
> 冒出 `503 model_not_found`。

---

## 第 3 步:在 WorkBuddy 里新建连接器

打开 WorkBuddy 的**连接器**管理页,点右上角**自定义连接器**。

> **截图位** · `docs/images/workbuddy-01-connectors.png`
> 连接器管理页,右上角「自定义连接器」按钮。

---

## 第 4 步:填写四个字段

照下表把第 2 步拿到的值填进去。

| 字段 | 填什么 | 示例 |
|---|---|---|
| 名称 | 自己认得出就行 | `wan-video` |
| 命令 | 参照文件里的 `command`,**完整路径** | `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12` |
| 参数 | 参照文件里 `args` 的那一行 | `/Users/你/.codex/skills/wan-video/scripts/mcp_server.py` |
| 环境变量 | 参照文件里 `env` 的键值 | `WAN_API_KEY` = `sk-你的key` |

> **截图位** · `docs/images/workbuddy-02-form.png`
> 自定义连接器表单,四个字段均已填好。

三个容易填错的地方:

- **命令必须是完整路径。** 填 `python3` 或 `~/...` 都不行 —— 图形界面启动的程序
  读不到你终端里的 `PATH`,也不会展开 `~`。直接从参照文件复制。
- **参数只填那一个 .py 路径。** 不要把 `command` 也拼进去。
- **环境变量是键值两栏。** 键是 `WAN_API_KEY`(Seedance 则是 `SEEDANCE_API_KEY`),
  值是 `sk-` 开头那一长串。不要把 `WAN_API_KEY=sk-...` 整句填进「键」那一栏。

---

## 第 5 步:保存并确认连上了

保存后启用连接器。卡片上出现**绿点**表示 WorkBuddy 已经成功启动了这个 server。

> **截图位** · `docs/images/workbuddy-03-connected.png`
> 连接器卡片显示绿点,展开可见 4 个工具。

展开连接器应该能看到 4 个工具:

```
wan_generate_video    提交生成任务并等待完成
wan_get_video         查询任务状态
wan_download_video    把视频存到本地
wan_list_models       列出你的 key 能用的模型
```

Seedance 的是 `seedance_generate_video` 等,同样 4 个。

---

## 第 6 步:说人话生成视频

在对话框里直接描述,不用提工具名:

> 生成一个 5 秒视频:橘猫在阳光下的窗台上伸懒腰,镜头缓慢推进,电影感

WorkBuddy 会自己调 `wan_generate_video`,轮询到完成,再把视频存到本地。

**渲染要 1 到 5 分钟,期间请等待。** 视频**按次计费**,时长、分辨率、模型档位都会
推高费用。建议先用 720P、5 秒把效果试对,再出正式版本。

> 如果等待超时,任务通常还在服务端跑,**不要立刻重新提交** —— 那会重复扣费。
> 先让它用 `wan_get_video` 查一下之前那个任务的状态。

---

## 排查

**卡片一直不变绿**

十有八九是命令路径不对。在终端直接跑一遍参照文件里的 `command` 和 `args`:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}' \
  | WAN_API_KEY=sk-你的key /你的/python3 /你的/wan-video/scripts/mcp_server.py
```

返回一行 JSON 就说明 server 本身没问题,问题在界面里填的值。没返回就看报错。

**报 `503 model_not_found`**

你的 key 分组里没有这个模型。查清楚它到底能用哪些:

```bash
curl -s https://token.naoshengyun.com/v1/models -H "Authorization: Bearer sk-你的key"
```

清单里没有 `wan` 开头的模型,就得找网关平台给这个 key 的分组挂上视频模型。

**报认证失败**

环境变量的键填错了,或者 key 复制得不全。Wan 用 `WAN_API_KEY`,Seedance 用
`SEEDANCE_API_KEY`,两者不能混用。

**想做一次完整自检**

```bash
WAN_API_KEY=sk-你的key python3 ~/.codex/skills/wan-video/scripts/verify_setup.py
```

它会把环境、key、分组、连通性逐项检查一遍并指出问题所在。报问题时请把这个输出
一起贴上。

---

## 换机器或换 key

重跑一次安装器就会刷新参照文件,然后回到第 4 步更新连接器里的值即可。

卸载:

```bash
curl -fsSL https://raw.githubusercontent.com/fore4stwOw2/naoshengyun-video-skills/main/install.py | python3 - --uninstall
```

这条命令会删掉参照文件和 skill 目录,但**不会**动 WorkBuddy 界面里的连接器 ——
那条需要你在界面里自己删。

# Readme

## 目录

- [项目概述](#项目概述)
- [架构设计](#架构设计)
- [环境配置](#环境配置)
- [快速启动](#快速启动)
- [核心模块详解](#核心模块详解)
- [技能系统](#技能系统)
- [内置工具](#内置工具)
- [对话流程](#对话流程)
- [演示场景](#演示场景)
- [扩展指南](#扩展指南)
- [已知限制与注意事项](#已知限制与注意事项)

---

## 项目概述

本项目是一个基于 OpenAI 兼容 API 的智能对话 Agent，以《魔女的夜宴》角色**绫地宁宁**为人设，具备工具调用与技能加载能力。Agent 通过插件化的 Skill 系统扩展知识范围，能在对话中按需加载领域专长，实现从通用对话到专业任务的灵活切换。

**核心特色：**

- 角色扮演：固定人设 + 专属前缀，沉浸式交互
- 工具调用：支持终端命令执行、网页抓取、技能加载三大内置工具
- 技能按需加载：系统提示只含技能描述，回答时才加载完整知识，节省上下文
- 限流重试：自动检测 429 限流并指数退避重试

---

## 架构设计

```
main/
├── agent.py              # 主程序：Agent 核心逻辑
├── .env                  # 环境变量：API Key、Base URL、模型
└── skills/               # 技能目录（自动递归加载）
    ├── github/
    │   └── SKILL.md
    ├── clawhub/
    │   └── SKILL.md
    ├── ddg-web-search-1.0.0/
    │   ├── SKILL.md
    │   └── _meta.json
    ├── skill-creator/
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── init_skill.py
    │       ├── package_skill.py
    │       └── quick_validate.py
    ├── summarize/
    │   └── SKILL.md
    └── weather/
        └── SKILL.md
```

### 工作流程

```
用户输入 → 构建消息历史 → 调用 LLM API（带工具定义）
                                    ↓
                        LLM 返回文本或工具调用
                                    ↓
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
              run_command     web_fetch      load_skill
             (执行Shell命令)  (抓取网页)    (加载技能知识)
                    ↓               ↓               ↓
              工具结果追加到消息历史 → 再次调用 LLM → 最终回复
```

---

## 环境配置

### 依赖安装

```bash
pip install openai pyyaml python-dotenv
```

### 环境变量

在 `main/.env` 中配置以下变量：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `API_KEY` | OpenAI 兼容 API 的密钥 | `nvapi-xxxxx` |
| `BASE_URL` | API 端点地址 | `https://integrate.api.nvidia.com/v1` |
| `MODEL` | 使用的模型名称（可选，有默认值） | `deepseek-ai/deepseek-v4-flash` |

> **注意：** `API_KEY` 和 `BASE_URL` 为必填项，`MODEL` 不设置时默认使用 `zai-org/GLM-5.1-FP8`。

---

## 快速启动

```bash
cd main
python agent.py
```

启动后进入交互式对话，输入问题即可与 Agent 交流，输入 Ctrl+C 退出。

---

## 核心模块详解

### 1. SkillLoader — 技能加载器

**位置：** `agent.py` 第 22-64 行

| 方法 | 功能 |
|------|------|
| `_load_all()` | 递归扫描 `skills/` 目录下所有 `SKILL.md`，解析 YAML frontmatter |
| `_parse_frontmatter(text)` | 分离 YAML 元数据与 Markdown 正文 |
| `get_descriptions()` | 生成技能列表摘要，注入系统提示 |
| `get_content(name)` | 返回指定技能的完整正文（被 `load_skill` 工具调用） |

**按需加载机制：**

系统提示中只包含技能名和描述（轻量），当 LLM 判断需要时调用 `load_skill` 加载完整内容（重量），避免一次性占用过多上下文窗口。

### 2. _TextExtractor — HTML 文本提取器

**位置：** `agent.py` 第 68-89 行

基于 Python 标准库 `HTMLParser` 实现的轻量 HTML 解析器，用于 `web_fetch` 的文本模式：

- 过滤 `<script>` 和 `<style>` 标签内容
- 在段落/换行标签处插入换行符
- 压缩连续空行

### 3. web_fetch — 网页抓取

**位置：** `agent.py` 第 91-106 行

```python
web_fetch(url, extract_mode="text", max_chars=8000)
```

| 参数 | 说明 |
|------|------|
| `url` | 目标 URL |
| `extract_mode` | `"text"` 提取纯文本，`"raw"` 保留原始 HTML |
| `max_chars` | 最大返回字符数，默认 8000 |

### 4. 主循环

**位置：** `agent.py` 第 170-239 行

核心对话循环逻辑：
1. 读取用户输入，追加到消息历史
2. 调用 LLM API（支持工具调用），含限流重试（最多 5 次，指数退避）
3. 若返回工具调用 → 执行对应工具 → 将结果追加到历史 → 回到步骤 2
4. 若返回纯文本 → 打印回复 → 等待下一轮用户输入

---

## 技能系统

### 技能目录结构

每个技能是一个文件夹，核心文件为 `SKILL.md`：

```
my-skill/
├── SKILL.md           # 必需：frontmatter + 指导文档
├── scripts/           # 可选：可执行辅助脚本
├── references/        # 可选：领域参考文档
└── assets/            # 可选：模板、配置等资源
```

### SKILL.md 格式

```yaml
---
name: skill-name                    # 技能名称（hyphen-case）
description: 技能描述与触发条件        # 描述（含何时使用的提示）
metadata: {"nanobot": {"emoji": "🏷️"}}  # 可选元数据
---

# 技能标题

技能正文（使用指南、示例代码等）
```

### 已集成技能一览

| 技能 | Emoji | 功能 | 依赖 | 需要 API Key |
|------|-------|------|------|-------------|
| **github** | 🐙 | 通过 `gh` CLI 操作 GitHub：PR、Issue、CI、API 查询 | `gh` CLI | 需要 GitHub 认证 |
| **clawhub** | 🦞 | 从 ClawHub 公共注册中心搜索和安装技能 | Node.js (`npx`) | 不需要 |
| **ddg-search** | 🔍 | 通过 DuckDuckGo Lite 网页搜索，零依赖 | 无 | 不需要 |
| **skill-creator** | 🛠️ | 创建、验证和打包新技能 | Python | 不需要 |
| **summarize** | 🧾 | 摘要/转录 URL、PDF、YouTube 视频 | `summarize` CLI | 需要 LLM API Key |
| **weather** | 🌤️ | 查询当前天气和预报 | `curl` | 不需要 |

### 各技能详细说明

#### 🐙 github

通过 `gh` CLI 与 GitHub 交互，支持：
- 查看 PR 的 CI 检查状态：`gh pr checks 55 --repo owner/repo`
- 列出工作流运行：`gh run list --repo owner/repo --limit 10`
- 查看失败步骤日志：`gh run view <run-id> --repo owner/repo --log-failed`
- 高级 API 查询：`gh api repos/owner/repo/pulls/55 --jq '.title'`
- JSON 结构化输出：`gh issue list --json number,title --jq '.[] | "\(.number): \(.title)"'`

#### 🦞 clawhub

公共技能注册中心，支持：
- 搜索技能：`npx --yes clawhub@latest search "web scraping" --limit 5`
- 安装技能：`npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace`
- 更新技能：`npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace`
- 列出已安装：`npx --yes clawhub@latest list --workdir ~/.nanobot/workspace`

#### 🔍 ddg-search

通过 DuckDuckGo Lite 搜索网页，无需 API Key：
- 基本搜索：`web_fetch(url="https://lite.duckduckgo.com/lite/?q=QUERY", extractMode="text")`
- 区域过滤：`&kl=us-en`（美国）、`&kl=uk-en`（英国）等
- 精确匹配：`q=%22exact+phrase%22`
- 搜索-抓取模式：先搜索获取 URL 列表，再用 `web_fetch` 抓取完整内容

#### 🛠️ skill-creator

技能创建工具包，包含三个脚本：

| 脚本 | 用途 |
|------|------|
| `init_skill.py` | 初始化技能目录，生成 SKILL.md 模板和资源目录 |
| `package_skill.py` | 验证并打包技能为 `.skill` 分发文件（zip 格式） |
| `quick_validate.py` | 快速验证技能结构：frontmatter 格式、命名规范、目录合规 |

**创建技能示例：**
```bash
python scripts/init_skill.py my-skill --path ./skills --resources scripts,references --examples
```

**打包技能示例：**
```bash
python scripts/package_skill.py ./skills/my-skill ./dist
```

#### 🧾 summarize

摘要与转录工具，支持：
- 网页摘要：`summarize "https://example.com" --model google/gemini-3-flash-preview`
- 文件摘要：`summarize "/path/to/file.pdf" --model google/gemini-3-flash-preview`
- YouTube 转录：`summarize "https://youtu.be/xxx" --youtube auto --extract-only`
- 长度控制：`--length short|medium|long|xl|xxl|<chars>`

#### 🌤️ weather

天气查询，两种方式：
- **wttr.in**（主要）：`curl -s "wttr.in/London?format=3"` → `London: ⛅️ +8°C`
- **Open-Meteo**（备用，JSON）：`curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"`

---

## 内置工具

Agent 注册了三个 Function Calling 工具供 LLM 调用：

| 工具名 | 参数 | 功能 |
|--------|------|------|
| `run_command` | `command: string` | 执行 Shell 命令并返回输出 |
| `web_fetch` | `url: string`, `extract_mode?: string`, `max_chars?: integer` | 抓取网页内容 |
| `load_skill` | `skill_name: string` | 加载指定技能的完整知识 |

---

## 对话流程

以一次完整交互为例：

```
你: 今天伦敦天气怎么样？

[Agent 思考] → 需要天气信息 → 调用 load_skill(skill_name="weather")
[加载技能]: weather

[Agent 思考] → 加载了 weather 技能 → 调用 run_command(command='curl -s "wttr.in/London?format=3"')
[工具返回]: London: ⛅️ +8°C

[Agent 回答]: Ciallo～(∠・ω< )⌒★ 尼桑，伦敦现在的天气是多云，气温大约8°C呢～
```

**关键步骤：**
1. 用户提问 → 消息追加到历史
2. LLM 判断需要技能 → 调用 `load_skill`
3. 技能内容注入对话 → LLM 根据技能指导调用 `run_command`
4. 命令执行结果返回 → LLM 组织最终回复
5. 回复带固定前缀 "Ciallo～(∠・ω< )⌒★"

---

## 演示场景

### 场景 1：查天气

```
你: 东京今天天气如何？

[加载技能]: weather
[Agent 回答]: Ciallo～(∠・ω< )⌒★ 尼桑，让我帮您看看东京的天气～
（调用 curl -s "wttr.in/Tokyo?format=%l:+%c+%t+%h+%w"）
东京: 🌧️ +12°C 85% →15km/h
```

### 场景 2：网页搜索

```
你: 帮我搜索一下 Python 最新版本

[加载技能]: ddg-search
[Agent 回答]: Ciallo～(∠・ω< )⌒★ 尼桑，我来帮您搜索～
（调用 web_fetch 抓取 DuckDuckGo 搜索结果）
根据搜索结果，Python 最新版本是...
```

### 场景 3：GitHub 操作

```
你: 看看 owner/repo 最近的 issue

[加载技能]: github
[Agent 回答]: Ciallo～(∠・ω< )⌒★ 尼桑，我来查看一下～
（调用 gh issue list --repo owner/repo --json number,title）
最近的开 issue 有：#42 修复登录问题、#41 添加暗色模式...
```

### 场景 4：摘要网页

```
你: 帮我总结一下 https://example.com/article 的内容

[加载技能]: summarize
[Agent 回答]: Ciallo～(∠・ω< )⌒★ 尼桑，我来帮您总结～
（调用 summarize "https://example.com/article" --model google/gemini-3-flash-preview）
```

### 场景 5：搜索新技能

```
你: 有没有可以操作数据库的技能？

[加载技能]: clawhub
[Agent 回答]: Ciallo～(∠・ω< )⌒★ 尼桑，我来帮您搜索一下～
（调用 npx --yes clawhub@latest search "database" --limit 5）
找到了以下技能：...
```

### 场景 6：普通对话

```
你: 你好呀宁宁

[Agent 回答]: Ciallo～(∠・ω< )⌒★ 尼桑好呀！今天有什么我可以帮忙的吗？
```

---

## 扩展指南

### 添加新技能

1. 在 `skills/` 目录下创建新文件夹
2. 编写 `SKILL.md`，包含 YAML frontmatter（`name` 和 `description` 必填）和正文
3. 可选添加 `scripts/`、`references/`、`assets/` 子目录
4. 重启 Agent 即可自动加载

**使用 skill-creator 脚本快速初始化：**

```bash
cd skills/skill-creator
python scripts/init_skill.py my-new-skill --path ../../ --resources scripts
```

### 技能验证与打包

```bash
# 验证
python skills/skill-creator/scripts/quick_validate.py skills/my-new-skill

# 打包
python skills/skill-creator/scripts/package_skill.py skills/my-new-skill ./dist
```

### 自定义人设

修改 `agent.py` 中的 `SYSTEM_PROMPT` 变量即可更改角色人设、语气和前缀。

---

## 已知限制与注意事项

1. **Windows 编码**：项目中 `read_text()` 已显式指定 `encoding="utf-8"`，避免 Windows 默认 GBK 编码导致的 `UnicodeDecodeError`
2. **max_tokens**：设置为 4096，避免长回复被截断
3. **限流处理**：自动检测 429 错误并指数退避重试，最多 5 次
4. **DuckDuckGo 搜索限制**：无时间过滤、无图片视频、不支持 Google
5. **Shell 命令安全**：`run_command` 直接执行 Shell 命令，无沙箱隔离，请注意安全
6. **技能描述长度**：frontmatter 中 `description` 最长 1024 字符
7. **技能命名**：必须使用 hyphen-case（小写字母 + 数字 + 连字符），最长 64 字符，且 `name` 须与目录名一致

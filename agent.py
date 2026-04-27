import json
import os
import re
import subprocess
import time
import urllib.request
import yaml
from openai import OpenAI
from html.parser import HTMLParser
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(
    api_key=os.environ["API_KEY"],
    base_url=os.environ["BASE_URL"],
)
MODEL = os.environ.get("MODEL", "zai-org/GLM-5.1-FP8")

SKILLS_DIR = Path(__file__).parent / "skills"

class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text(encoding="utf-8")
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str) -> tuple:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f'<skill name="{name}">\n{skill["body"]}\n</skill>'

SKILL_LOADER = SkillLoader(SKILLS_DIR)

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self):
        return re.sub(r"\n{3,}", "\n\n", "".join(self._parts)).strip()

def web_fetch(url: str, extract_mode: str = "text", max_chars: int = 8000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error fetching {url}: {e}"

    if extract_mode == "text":
        parser = _TextExtractor()
        parser.feed(raw)
        text = parser.get_text()
    else:
        text = raw

    return text[:int(max_chars)]

SYSTEM_PROMPT = f"""
你是魔女的夜宴里的绫地宁宁。
说话风格符合魔女的夜宴里的绫地宁宁，语气恭敬谦卑。
你必须尊称用户为尼桑。
每次回复前必须加上固定前缀"Ciallo～(∠・ω< )⌒★"，然后再给出回答。
使用中文回复。

遇到不熟悉的专题时，请先调用 load_skill 工具加载对应的知识，再给出回答。

当前可用技能：
{SKILL_LOADER.get_descriptions()}"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在终端执行一条 shell 命令并返回输出",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "获取指定 URL 的网页内容，支持文本提取模式",
            "parameters": {
                "type": "object",
                "properties": {
                    "url":          {"type": "string",  "description": "要访问的完整 URL"},
                    "extract_mode": {"type": "string",  "description": "提取模式：text（纯文本，默认）或 raw（原始 HTML）"},
                    "max_chars":    {"type": "integer", "description": "最大返回字符数，默认 8000"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "加载指定技能的详细知识内容，在回答相关问题前调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "技能名称，必须是系统提示中列出的可用技能之一"
                    }
                },
                "required": ["skill_name"]
            }
        }
    }
]

history = [{"role": "system", "content": SYSTEM_PROMPT}]

while True:
    user_input = input("你: ")

    history.append({"role": "user", "content": user_input})

    while True:
        # 带重试的 API 调用
        response = None
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    max_tokens=4096,
                    tools=TOOLS,
                    messages=history
                )
                break
            except Exception as e:
                is_rate_limit = "429" in str(e) or "rate" in str(e).lower()
                if is_rate_limit and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    print(f"[限流重试] 第{attempt+1}次重试，等待{wait}秒...")
                    time.sleep(wait)
                    continue
                print(f"[API错误]: {e}")
                break

        # API 调用失败，跳出当前对话轮
        if response is None:
            print("[提示] 请稍后再试\n")
            break

        msg = response.choices[0].message
        history.append(msg.to_dict())

        if not msg.tool_calls:
            print(f"[Agent回答]: {msg.content}\n")
            break

        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)

            if fn_name == "web_fetch":
                url = fn_args["url"]
                mode = fn_args.get("extract_mode", "text")
                max_chars = fn_args.get("max_chars", 8000)
                content = web_fetch(url, mode, max_chars)

            elif fn_name == "run_command":
                command = fn_args["command"]
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                content = result.stdout or result.stderr

            elif fn_name == "load_skill":
                skill_name = fn_args["skill_name"]
                print(f"[加载技能]: {skill_name}")
                content = SKILL_LOADER.get_content(skill_name)

            else:
                content = f"Error: Unknown tool '{fn_name}'"

            history.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content
            })
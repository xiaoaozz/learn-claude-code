#!/usr/bin/env python3
# Harness: 规划 -- 保持模型在正确轨道上，而不是脚本化路线。
"""
s03_todo_write.py - TodoWrite

模型通过 TodoManager 跟踪自己的进度。当它忘记更新时，
一个唠叨提醒会强制它继续更新。

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> | Tools   |
    |  prompt  |      |       |      | + todo  |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                                |
                    +-----------+-----------+
                    | TodoManager state     |
                    | [ ] 任务 A            |
                    | [>] 任务 B <- 进行中   |
                    | [x] 任务 C            |
                    +-----------------------+
                                |
                    if rounds_since_todo >= 3:
                      注入 <reminder>

核心洞察："Agent 可以跟踪自己的进度 -- 而且我能看到它。"
"""

import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(override=True)

# 如果设置了自定义 API 地址，移除默认的认证令牌
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 初始化工作目录、Anthropic 客户端和模型
WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# 系统提示词：指导 Agent 使用 todo 工具来规划和跟踪任务
# SYSTEM = f"""你是一个位于 {WORKDIR} 的编码 Agent。
# 使用 todo 工具来规划多步骤任务。在开始任务前标记为 in_progress，完成后标记为 completed。
# 优先使用工具，而非冗长的文字描述。"""
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose."""

# -- TodoManager: LLM 写入的结构化状态管理器 --
class TodoManager:
    """
    任务管理器：维护 Agent 的任务列表和状态
    状态标记：[ ] 待处理, [>] 进行中, [x] 已完成
    """
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """更新任务列表并验证状态"""
        # 限制最多 20 个任务
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        
        # 验证每个任务项
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            
            # 检查任务文本是否为空
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            # 检查状态是否合法
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            # 统计进行中的任务数量
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        
        # 确保同时只有一个任务在进行中
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        """渲染任务列表为可读文本"""
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            # 根据状态选择标记符号
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        # 统计完成情况
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


# 全局任务管理器实例
TODO = TodoManager()


# -- 工具实现函数 --
def safe_path(p: str) -> Path:
    """确保路径在工作目录内，防止路径遍历攻击"""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    """执行 shell 命令（带安全检查）"""
    # 阻止危险命令
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    """读取文件内容（可选限制行数）"""
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    """写入文件内容（自动创建父目录）"""
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """在文件中替换文本（精确匹配，只替换第一次出现）"""
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# 工具处理器映射表：将工具名映射到对应的处理函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
}

# 工具定义：描述每个工具的功能和输入模式（供 Claude API 使用）
TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "todo", "description": "Update task list. Track progress on multi-step tasks.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["id", "text", "status"]}}}, "required": ["items"]}},
]


# -- Agent 循环，带有"唠叨提醒"注入机制 --
def agent_loop(messages: list):
    """
    主 Agent 循环：
    1. 调用 Claude API 获取响应
    2. 执行工具调用
    3. 如果连续 3 轮未更新 todo，自动注入提醒
    """
    rounds_since_todo = 0  # 距离上次使用 todo 工具的轮数
    
    while True:
        # 调用 Claude API（提醒会在工具结果中注入）
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        
        # 如果不需要使用工具，结束循环
        if response.stop_reason != "tool_use":
            return
        
        # 执行工具调用
        results = []
        used_todo = False
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                # 打印工具调用信息（前 200 字符）
                print(f"> {block.name}:")
                print(str(output)[:200])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                
                # 检测是否使用了 todo 工具
                if block.name == "todo":
                    used_todo = True
        
        # 更新计数器：如果使用了 todo 则重置为 0，否则递增
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        
        # 核心机制：连续 3 轮未更新 todo，注入提醒
        if rounds_since_todo >= 3:
            results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
        
        messages.append({"role": "user", "content": results})



# -- 主程序入口：交互式命令行界面 --
if __name__ == "__main__":
    history = []  # 对话历史
    while True:
        try:
            # 读取用户输入（青色提示符）
            query = input("\033[36ms03 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        # 退出命令检测
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        # 将用户消息添加到历史
        history.append({"role": "user", "content": query})
        
        # 启动 Agent 循环
        agent_loop(history)
        
        # 打印 Agent 的文本响应
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()

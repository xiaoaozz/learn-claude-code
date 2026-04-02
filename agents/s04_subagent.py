#!/usr/bin/env python3
# 核心机制：上下文隔离 -- 保护模型的思维清晰度
"""
s04_subagent.py - 子代理

创建一个拥有全新 messages=[] 的子代理。子代理在自己的上下文中工作，
与父代理共享文件系统，然后仅返回摘要结果给父代理。

    父代理                           子代理
    +------------------+             +------------------+
    | messages=[...]   |             | messages=[]      |  <-- 全新的
    |                  |  调度       |                  |
    | tool: task       | ---------->| while tool_use:  |
    |   prompt="..."   |            |   call tools     |
    |   description="" |            |   append results |
    |                  |  摘要       |                  |
    |   result = "..." | <--------- | return last text |
    +------------------+             +------------------+
              |
    父代理上下文保持干净。
    子代理上下文被丢弃。

核心洞察："进程隔离免费提供了上下文隔离。"
"""

# ============================================================
# 1. 环境配置和初始化
# ============================================================
import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# 加载环境变量（覆盖已有的）
load_dotenv(override=True)

# 如果设置了自定义的 ANTHROPIC_BASE_URL，则移除 ANTHROPIC_AUTH_TOKEN
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 工作目录：当前目录
WORKDIR = Path.cwd()
# 初始化 Anthropic 客户端
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
# 模型 ID
MODEL = os.environ["MODEL_ID"]

# 父代理的系统提示词：引导它使用 task 工具来委派任务
# SYSTEM = f"你是位于 {WORKDIR} 的编码代理。使用 task 工具来委派探索任务或子任务。"
SYSTEM = f"You are a coding agent at {WORKDIR}. Use the task tool to delegate exploration or subtasks."
# 子代理的系统提示词：引导它完成任务并总结发现
# SUBAGENT_SYSTEM = f"你是位于 {WORKDIR} 的编码子代理。完成给定的任务，然后总结你的发现。"
SUBAGENT_SYSTEM = f"You are a coding subagent at {WORKDIR}. Complete the given task, then summarize your findings."


# ============================================================
# 2. 工具函数实现（父代理和子代理共享）
# ============================================================

def safe_path(p: str) -> Path:
    """安全路径检查：确保路径在工作目录内，防止路径逃逸攻击
    
    Args:
        p: 相对路径字符串
    
    Returns:
        Path: 解析后的绝对路径
    
    Raises:
        ValueError: 如果路径试图逃逸工作目录
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    """执行 Shell 命令（带安全检查和超时限制）
    
    Args:
        command: Shell 命令字符串
    
    Returns:
        str: 命令输出（stdout + stderr），最多 50000 字符
    """
    # 危险命令黑名单
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        # 执行命令，捕获输出，120秒超时
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    """读取文件内容
    
    Args:
        path: 文件路径
        limit: 可选，限制读取的行数
    
    Returns:
        str: 文件内容，最多 50000 字符
    """
    try:
        lines = safe_path(path).read_text().splitlines()
        # 如果设置了行数限制且文件行数超过限制，截断并添加提示
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    """写入文件内容
    
    Args:
        path: 文件路径
        content: 要写入的内容
    
    Returns:
        str: 成功消息或错误信息
    """
    try:
        fp = safe_path(path)
        # 如果父目录不存在，自动创建
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件：查找并替换指定文本（仅替换第一次出现）
    
    Args:
        path: 文件路径
        old_text: 要查找的旧文本
        new_text: 要替换成的新文本
    
    Returns:
        str: 成功消息或错误信息
    """
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        # 仅替换第一次出现
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# 3. 工具处理器映射和工具定义
# ============================================================

# 工具名称到处理函数的映射
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# 子代理的工具集：包含所有基础工具，但不包含 task 工具（防止递归生成子代理）
CHILD_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]


# ============================================================
# 4. 子代理执行函数
# ============================================================

def run_subagent(prompt: str) -> str:
    """运行子代理：使用全新的上下文，仅返回摘要
    
    核心机制：
    - 子代理从空白上下文开始（messages=[]）
    - 可以使用所有基础工具，但不能再生成子代理
    - 执行完成后，仅返回最终的文本摘要给父代理
    - 子代理的完整对话历史被丢弃，不会污染父代理的上下文
    
    Args:
        prompt: 分配给子代理的任务提示
    
    Returns:
        str: 子代理的最终摘要文本
    """
    # 全新的消息上下文，仅包含用户的任务提示
    sub_messages = [{"role": "user", "content": prompt}]
    
    # 最多循环 30 次（安全限制）
    for iteration in range(30):
        print(f"\n{'─'*60}")
        print(f"🤖 子代理循环 #{iteration + 1}")
        print(f"{'─'*60}")
        
        # 调用 Claude API（启用 streaming 和 thinking）
        with client.messages.stream(
            model=MODEL, 
            system=SUBAGENT_SYSTEM, 
            messages=sub_messages,
            tools=CHILD_TOOLS, 
            max_tokens=8000,
            thinking={
                "type": "enabled",
                "budget_tokens": 3000  # 思考预算
            }
        ) as stream:
            # 实时处理流式事件
            current_thinking = False
            current_text = False
            
            for event in stream:
                if event.type == "content_block_start":
                    # 内容块开始
                    if hasattr(event.content_block, 'type'):
                        if event.content_block.type == "thinking":
                            current_thinking = True
                            print(f"\n{'='*60}")
                            print("🤔 模型思考过程:")
                            print(f"{'='*60}")
                        elif event.content_block.type == "text":
                            current_text = True
                            print(f"\n{'='*60}")
                            print("💬 模型回复:")
                            print(f"{'='*60}")
                
                elif event.type == "content_block_delta":
                    delta = event.delta
                    # 实时打印思考内容
                    if delta.type == "thinking_delta":
                        print(delta.thinking, end="", flush=True)
                    # 实时打印文本内容
                    elif delta.type == "text_delta":
                        print(delta.text, end="", flush=True)
                
                elif event.type == "content_block_stop":
                    # 内容块结束，换行
                    if current_thinking or current_text:
                        print(f"\n{'='*60}\n")
                        current_thinking = False
                        current_text = False
            
            # 获取完整的响应对象
            response = stream.get_final_message()
        
        # 将助手的响应添加到子代理的消息历史
        sub_messages.append({"role": "assistant", "content": response.content})
        
        # 如果不是工具调用，说明子代理完成了任务，退出循环
        if response.stop_reason != "tool_use":
            print(f"✅ 子代理任务完成 (stop_reason: {response.stop_reason})")
            break
        
        # 处理工具调用请求
        results = []
        print(f"\n🛠️  执行工具调用:")
        for block in response.content:
            if block.type == "tool_use":
                print(f"  📌 工具: {block.name}")
                print(f"  📝 参数: {str(block.input)[:200]}...")
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                print(f"  ✓ 结果: {str(output)[:200]}...")
                # 收集工具执行结果（限制在 50000 字符以内）
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)[:50000]})
        
        # 将工具执行结果作为用户消息添加到子代理的消息历史
        sub_messages.append({"role": "user", "content": results})
    
    # 关键：仅将最终的文本摘要返回给父代理，子代理的完整上下文被丢弃
    res = "".join(b.text for b in response.content if hasattr(b, "text")) or "(no summary)"
    return res


# ============================================================
# 5. 父代理的工具集
# ============================================================

# 父代理的工具集：基础工具 + task 工具（用于委派任务给子代理）
PARENT_TOOLS = CHILD_TOOLS + [
    {"name": "task", 
     "description": "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
     "input_schema": {
         "type": "object", 
         "properties": {
             "prompt": {"type": "string"}, 
             "description": {"type": "string", "description": "Short description of the task"}
         }, 
         "required": ["prompt"]
     }},
]


# ============================================================
# 6. 父代理的主循环
# ============================================================

def agent_loop(messages: list):
    """父代理的主循环：处理用户请求，执行工具调用
    
    Args:
        messages: 对话历史（会被原地修改）
    """
    iteration = 0
    while True:
        iteration += 1
        print(f"\n{'━'*60}")
        print(f"🎯 父代理循环 #{iteration}")
        print(f"{'━'*60}")
        
        # 调用 Claude API（启用 streaming 和 thinking）
        with client.messages.stream(
            model=MODEL, 
            system=SYSTEM, 
            messages=messages,
            tools=PARENT_TOOLS, 
            max_tokens=8000,
            thinking={
                "type": "enabled",
                "budget_tokens": 3000  # 思考预算
            }
        ) as stream:
            # 实时处理流式事件
            current_thinking = False
            current_text = False
            
            for event in stream:
                if event.type == "content_block_start":
                    # 内容块开始
                    if hasattr(event.content_block, 'type'):
                        if event.content_block.type == "thinking":
                            current_thinking = True
                            print(f"\n{'='*60}")
                            print("🧠 父代理思考过程:")
                            print(f"{'='*60}")
                        elif event.content_block.type == "text":
                            current_text = True
                            print(f"\n{'='*60}")
                            print("💭 父代理回复:")
                            print(f"{'='*60}")
                
                elif event.type == "content_block_delta":
                    delta = event.delta
                    # 实时打印思考内容
                    if delta.type == "thinking_delta":
                        print(delta.thinking, end="", flush=True)
                    # 实时打印文本内容
                    elif delta.type == "text_delta":
                        print(delta.text, end="", flush=True)
                
                elif event.type == "content_block_stop":
                    # 内容块结束，换行
                    if current_thinking or current_text:
                        print(f"\n{'='*60}\n")
                        current_thinking = False
                        current_text = False
            
            # 获取完整的响应对象
            response = stream.get_final_message()
        
        # 将助手的响应添加到对话历史
        messages.append({"role": "assistant", "content": response.content})
        
        # 如果不是工具调用，说明对话完成，退出循环
        if response.stop_reason != "tool_use":
            print(f"✅ 父代理任务完成 (stop_reason: {response.stop_reason})")
            return
        
        # 处理工具调用请求
        results = []
        print(f"\n🔧 执行工具调用:")
        for block in response.content:
            if block.type == "tool_use":
                # 特殊处理 task 工具：调用子代理
                if block.name == "task":
                    desc = block.input.get("description", "subtask")
                    print(f"\n  🎯 委派子任务: {desc}")
                    print(f"  📋 任务提示: {block.input['prompt'][:100]}...")
                    print(f"\n{'▼'*60}")
                    print("  进入子代理...")
                    print(f"{'▼'*60}")
                    output = run_subagent(block.input["prompt"])
                    print(f"{'▲'*60}")
                    print("  子代理返回")
                    print(f"{'▲'*60}")
                    print(f"  📦 子代理摘要: {str(output)[:200]}...")
                # 处理其他基础工具
                else:
                    print(f"  🔨 工具: {block.name}")
                    print(f"  📝 参数: {str(block.input)[:150]}...")
                    handler = TOOL_HANDLERS.get(block.name)
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    print(f"  ✓ 结果: {str(output)[:200]}...")
                
                # 收集工具执行结果
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        
        # 将工具执行结果作为用户消息添加到对话历史
        messages.append({"role": "user", "content": results})


# ============================================================
# 7. 主程序入口：交互式命令行界面
# ============================================================

if __name__ == "__main__":
    # 初始化对话历史
    history = []
    
    # 主循环：接收用户输入并处理
    while True:
        try:
            # 显示提示符并接收用户输入（青色）
            query = input("\033[36ms04 >> \033[0m")
            # 清理可能存在的无效 surrogate 字符
            # 使用 encode 和 decode 配合 surrogateescape/replace 错误处理器
            query = query.encode('utf-8', errors='surrogateescape').decode('utf-8', errors='replace')
        except (EOFError, KeyboardInterrupt):
            # 处理 Ctrl+D 或 Ctrl+C
            break
        
        # 退出命令检查
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        # 将用户输入添加到对话历史
        history.append({"role": "user", "content": query})
        
        # 运行父代理循环
        agent_loop(history)
        
        # 提取并打印最后的响应内容
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()

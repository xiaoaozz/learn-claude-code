#!/usr/bin/env python3
# Harness: 循环 -- 模型与真实世界的第一次连接。
"""
s01_agent_loop.py - Agent 循环

AI 编码代理的全部秘密就在这一个模式中：

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (循环继续)

这是核心循环：将工具结果反馈给模型，直到模型决定停止。
生产级代理会在此基础上添加策略、钩子和生命周期控制。
"""

import os
import subprocess

try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
    readline.parse_and_bind('set enable-meta-keybindings on')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(override=True)

# 如果设置了自定义 BASE_URL，则移除 AUTH_TOKEN（避免冲突）
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 初始化 Anthropic 客户端
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# 系统提示词：定义 AI 代理的角色和行为
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# 工具定义：定义 Agent 可以使用的 bash 工具
TOOLS = [{
    "name": "bash",
    "description": "运行 shell 命令",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]


def run_bash(command: str) -> str:
    """执行 bash 命令并返回输出结果
    
    Args:
        command: 要执行的 shell 命令
        
    Returns:
        命令的输出结果（stdout + stderr），截断至 50000 字符
    """
    # 危险命令黑名单：防止执行可能造成系统损坏的命令
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    
    try:
        # 执行命令：设置超时 120 秒，捕获输出
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


# -- 核心模式：一个 while 循环，持续调用工具直到模型停止 --
def agent_loop(messages: list):
    """Agent 核心循环：LLM 调用 -> 工具执行 -> 结果反馈
    
    这是整个 Agent 系统的核心：
    1. 调用 LLM 生成响应
    2. 如果 LLM 要求使用工具，执行工具
    3. 将工具结果反馈给 LLM
    4. 重复以上步骤，直到 LLM 决定停止
    
    Args:
        messages: 对话历史列表
    """
    while True:
        # 调用 LLM，传入对话历史和可用工具
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        
        # 将助手的响应添加到对话历史
        messages.append({"role": "assistant", "content": response.content})
        
        # 如果模型没有调用工具，说明任务完成，退出循环
        if response.stop_reason != "tool_use":
            return
        
        # 执行每个工具调用，收集结果
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # 打印要执行的命令（黄色）
                print(f"\033[33m$ {block.input['command']}\033[0m")
                # 执行 bash 命令
                output = run_bash(block.input["command"])
                # 打印命令输出（前 200 个字符）
                print(output[:200])
                # 收集工具结果
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
        
        # 将工具执行结果作为用户消息添加到对话历史
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    # 对话历史记录
    history = []
    
    # 主循环：交互式命令行界面
    while True:
        try:
            # 读取用户输入（青色提示符）
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            # 处理 Ctrl+D 或 Ctrl+C
            break
        
        # 退出命令
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        # 将用户输入添加到历史记录
        history.append({"role": "user", "content": query})
        
        # 启动 Agent 循环处理用户请求
        agent_loop(history)
        
        # 打印 Agent 的最终响应
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()

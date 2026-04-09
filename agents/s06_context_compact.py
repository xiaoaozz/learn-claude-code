#!/usr/bin/env python3
# 线束：压缩机制 -- 清理内存以实现无限会话。
"""
s06_context_compact.py - 上下文压缩

三层压缩流水线，让 Agent 可以永久工作：

    每轮对话：
    +------------------+
    | 工具调用结果      |
    +------------------+
            |
            v
    [第一层：micro_compact]        (静默执行，每轮都运行)
      将非 read_file 工具的旧结果（保留最近 3 次）
      替换为 "[Previous: used {tool_name}]"
            |
            v
    [检查：tokens > 50000?]
       |               |
       no              yes
       |               |
       v               v
    继续         [第二层：auto_compact]
                  保存完整对话记录到 .transcripts/
                  让 LLM 总结对话内容。
                  用 [摘要] 替换所有消息。
                        |
                        v
                [第三层：compact 工具]
                  模型调用 compact -> 立即总结。
                  与自动压缩相同，但由模型手动触发。

核心理念："Agent 可以策略性地遗忘，从而永久工作。"
"""

# ============================================================
# 导入必要的库
# ============================================================
import json          # JSON 序列化
import os            # 操作系统接口
import subprocess    # 子进程管理
import time          # 时间操作
from pathlib import Path  # 路径操作

from anthropic import Anthropic  # Anthropic API 客户端
from dotenv import load_dotenv   # 环境变量加载

# ============================================================
# 环境配置
# ============================================================
load_dotenv(override=True)  # 加载 .env 文件，override=True 表示覆盖已存在的环境变量

# 如果设置了自定义的 ANTHROPIC_BASE_URL，则移除 ANTHROPIC_AUTH_TOKEN
# 这通常用于代理或自定义端点场景
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# ============================================================
# 全局常量定义
# ============================================================
WORKDIR = Path.cwd()  # 当前工作目录
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))  # 初始化 Anthropic 客户端
MODEL = os.environ["MODEL_ID"]  # 从环境变量获取模型 ID

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks."

# 压缩相关配置
THRESHOLD = 50000  # token 数量阈值：超过此值触发自动压缩
TRANSCRIPT_DIR = WORKDIR / ".transcripts"  # 对话记录保存目录
KEEP_RECENT = 3  # 微压缩：保留最近 N 次工具调用结果
PRESERVE_RESULT_TOOLS = {"read_file"}  # 保留特定工具的结果不被压缩（因为是参考资料）


# ============================================================
# 辅助函数：Token 估算
# ============================================================

def estimate_tokens(messages: list) -> int:
    """
    粗略估算 token 数量：约 4 个字符 = 1 个 token
    
    这是一个快速估算方法，不需要调用 tokenizer
    用于判断是否需要触发压缩机制
    
    Args:
        messages: 消息列表
        
    Returns:
        估算的 token 数量
    """
    return len(str(messages)) // 4


# ============================================================
# 第一层：micro_compact - 用占位符替换旧的工具结果
# ============================================================

def micro_compact(messages: list) -> list:
    """
    微压缩：静默地清理旧的工具调用结果
    
    工作原理：
    1. 收集所有 tool_result 的位置信息
    2. 只保留最近 KEEP_RECENT 次的工具结果
    3. 将更早的工具结果替换为简短的占位符
    4. 但保留 read_file 的结果（因为是参考资料）
    
    这一层在每轮对话后自动执行，用户无感知。
    
    Args:
        messages: 消息历史列表
        
    Returns:
        压缩后的消息列表
    """
    # 收集所有 tool_result 的信息：(消息索引, 内容块索引, tool_result 字典)
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part_idx, part))
    
    # 如果工具结果数量不超过保留数量，直接返回
    if len(tool_results) <= KEEP_RECENT:
        return messages
    
    # 查找每个工具结果对应的工具名称
    # 方法：在之前的 assistant 消息中查找匹配的 tool_use_id
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_name_map[block.id] = block.name
    
    # 清理旧结果（保留最近 KEEP_RECENT 次）
    # 保留 read_file 的输出，因为它们是参考资料；
    # 压缩它们会强制 agent 重新读取文件
    to_clear = tool_results[:-KEEP_RECENT]
    for _, _, result in to_clear:
        # 跳过内容较短或不是字符串的结果
        if not isinstance(result.get("content"), str) or len(result["content"]) <= 100:
            continue
        
        tool_id = result.get("tool_use_id", "")
        tool_name = tool_name_map.get(tool_id, "unknown")
        
        # 跳过需要保留的工具结果
        if tool_name in PRESERVE_RESULT_TOOLS:
            continue
        
        # 替换为简短的占位符
        result["content"] = f"[Previous: used {tool_name}]"
    
    return messages


# ============================================================
# 第二层：auto_compact - 保存记录、总结对话、替换消息
# ============================================================

def auto_compact(messages: list) -> list:
    """
    自动压缩：当 token 超过阈值时自动触发
    
    工作流程：
    1. 将完整对话记录保存到磁盘（.transcripts/ 目录）
    2. 调用 LLM 对对话进行总结
    3. 用总结内容替换所有消息
    
    这样可以大幅减少 token 使用量，让对话可以继续进行
    
    Args:
        messages: 当前的消息历史列表
        
    Returns:
        压缩后的消息列表（只包含一条总结消息）
    """
    # 1. 保存完整对话记录到磁盘
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            # 使用 default=str 处理不能序列化的对象
            f.write(json.dumps(msg, default=str) + "\n")
    # 提示用户：对话记录已保存到指定路径
    print(f"[transcript saved: {transcript_path}]")
    
    # 2. 让 LLM 总结对话
    # 只取最近 80000 字符（避免输入过长）
    conversation_text = json.dumps(messages, default=str)[-80000:]
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, 2) Current state, 3) Key decisions made. "
            "Be concise but preserve critical details.\n\n" + conversation_text}],
        max_tokens=2000,  # 总结最多 2000 tokens
    )
    summary = response.content[0].text
    
    # 3. 用压缩后的总结替换所有消息
    # 只保留一条消息，包含记录路径和总结内容
    return [
        {"role": "user", "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"},
    ]


# ============================================================
# 工具函数实现
# ============================================================

def safe_path(p: str) -> Path:
    """
    安全路径检查：确保路径不会逃逸到工作目录之外
    
    防止路径遍历攻击（如 ../../etc/passwd）
    
    Args:
        p: 相对路径字符串
        
    Returns:
        解析后的绝对路径
        
    Raises:
        ValueError: 如果路径试图逃逸工作目录
    """
    path = (WORKDIR / p).resolve()  # 将相对路径转换为绝对路径
    if not path.is_relative_to(WORKDIR):
        # 如果解析后的路径不在工作目录内，抛出异常
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    """
    执行 Bash 命令
    
    安全措施：
    1. 阻止危险命令（rm -rf /、sudo、shutdown 等）
    2. 120 秒超时限制
    3. 输出限制在 50000 字符
    
    Args:
        command: 要执行的 shell 命令
        
    Returns:
        命令的标准输出和标准错误合并后的结果
    """
    # 定义危险命令模式列表
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    # 检查命令是否包含危险模式
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        # 执行命令
        r = subprocess.run(
            command,
            shell=True,          # 使用 shell 解释器
            cwd=WORKDIR,         # 在工作目录执行
            capture_output=True, # 捕获输出
            text=True,           # 以文本模式返回
            timeout=120          # 120 秒超时
        )
        out = (r.stdout + r.stderr).strip()  # 合并标准输出和错误输出
        return out[:50000] if out else "(no output)"  # 限制输出长度
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"  # 超时错误

def run_read(path: str, limit: int = None) -> str:
    """
    读取文件内容
    
    Args:
        path: 文件路径（相对于工作目录）
        limit: 可选的行数限制
        
    Returns:
        文件内容（如果设置了 limit，则只返回前 N 行）
    """
    try:
        lines = safe_path(path).read_text().splitlines()  # 读取并按行分割
        if limit and limit < len(lines):
            # 如果设置了行数限制且文件行数超过限制
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]  # 合并行并限制总长度
    except Exception as e:
        return f"Error: {e}"  # 返回错误信息

def run_write(path: str, content: str) -> str:
    """
    写入文件内容
    
    如果目录不存在，会自动创建
    
    Args:
        path: 文件路径（相对于工作目录）
        content: 要写入的内容
        
    Returns:
        成功消息（包含写入字节数）或错误信息
    """
    try:
        fp = safe_path(path)  # 获取安全路径
        fp.parent.mkdir(parents=True, exist_ok=True)  # 确保父目录存在
        fp.write_text(content)  # 写入内容
        return f"Wrote {len(content)} bytes"  # 返回成功消息
    except Exception as e:
        return f"Error: {e}"  # 返回错误信息

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """
    编辑文件：查找并替换文本
    
    只替换第一次出现的匹配项
    
    Args:
        path: 文件路径（相对于工作目录）
        old_text: 要查找的原始文本
        new_text: 替换后的新文本
        
    Returns:
        成功消息或错误信息
    """
    try:
        fp = safe_path(path)  # 获取安全路径
        content = fp.read_text()  # 读取文件内容
        if old_text not in content:
            # 如果找不到要替换的文本
            return f"Error: Text not found in {path}"
        # 替换第一次出现的文本（replace 的第三个参数 1 表示只替换一次）
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"  # 返回成功消息
    except Exception as e:
        return f"Error: {e}"  # 返回错误信息


# ============================================================
# 工具处理器映射表和工具定义
# ============================================================

# 工具处理器字典：将工具名称映射到对应的处理函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),  # 执行 bash 命令
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),  # 读取文件
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),  # 写入文件
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),  # 编辑文件
    "compact":    lambda **kw: "Manual compression requested.",  # 手动压缩（占位符）
}

# 工具定义列表：供 Claude API 使用的工具 schema
TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",  # 运行 shell 命令
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file contents.",  # 读取文件内容
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to file.",  # 写入内容到文件
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in file.",  # 替换文件中的文本
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"}
            },
            "required": ["path", "old_text", "new_text"]
        }
    },
    {
        "name": "compact",
        "description": "Trigger manual conversation compression.",  # 触发手动对话压缩
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "What to preserve in the summary"  # 在总结中保留什么内容
                }
            }
        }
    },
]


# ============================================================
# Agent 主循环
# ============================================================

def agent_loop(messages: list):
    """
    Agent 的主要对话循环（包含三层压缩机制 + 流式输出和思考过程可视化）
    
    工作流程：
    1. 每轮开始时执行微压缩（第一层）
    2. 检查 token 数量，如果超过阈值执行自动压缩（第二层）
    3. 调用 Claude API 生成响应（流式 + 扩展思考）
    4. 实时显示模型的思考过程和回答内容
    5. 检查是否需要使用工具（stop_reason == "tool_use"）
    6. 如果模型调用 compact 工具，执行手动压缩（第三层）
    7. 如果需要其他工具，执行所有工具调用
    8. 将工具结果添加到消息历史
    9. 继续循环，直到模型不再需要工具
    
    压缩机制确保对话可以无限进行，不会因为 token 超限而中断。
    
    Args:
        messages: 对话消息历史列表
    """
    iteration = 0  # 循环迭代计数器
    
    while True:
        iteration += 1
        # 打印循环状态分隔符和迭代次数
        print(f"\n{'━'*60}")
        print(f"🎯 Agent 循环 #{iteration}")
        print(f"{'━'*60}")
        
        # 第一层：每次 LLM 调用前执行微压缩
        micro_compact(messages)
        
        # 第二层：如果 token 估算超过阈值，执行自动压缩
        if estimate_tokens(messages) > THRESHOLD:
            # 提示用户：自动压缩已触发（超过 token 阈值）
            print(f"⚠️  [auto_compact triggered: tokens > {THRESHOLD}]")
            messages[:] = auto_compact(messages)  # 用压缩后的消息替换原消息列表
        
        # 调用 Claude API（启用流式处理和扩展思考）
        with client.messages.stream(
            model=MODEL,           # 使用的模型
            system=SYSTEM,         # 系统提示词
            messages=messages,     # 对话历史
            tools=TOOLS,           # 可用工具列表
            max_tokens=8000,       # 最大生成 token 数
            thinking={
                "type": "enabled",
                "budget_tokens": 3000  # 思考预算：最多 3000 tokens
            }
        ) as stream:
            # 实时处理流式事件
            current_thinking = False  # 标记当前是否在思考块中
            current_text = False      # 标记当前是否在文本块中
            
            for event in stream:
                if event.type == "content_block_start":
                    # 内容块开始事件
                    if hasattr(event.content_block, 'type'):
                        if event.content_block.type == "thinking":
                            # 思考块开始
                            current_thinking = True
                            print(f"\n{'='*60}")
                            print("🤔 模型思考过程:")
                            print(f"{'='*60}")
                        elif event.content_block.type == "text":
                            # 文本块开始
                            current_text = True
                            print(f"\n{'='*60}")
                            print("💬 模型回复:")
                            print(f"{'='*60}")
                
                elif event.type == "content_block_delta":
                    # 内容块增量事件（流式输出的核心）
                    delta = event.delta
                    # 实时打印思考内容（不换行，立即刷新缓冲区）
                    if delta.type == "thinking_delta":
                        print(delta.thinking, end="", flush=True)
                    # 实时打印文本内容（不换行，立即刷新缓冲区）
                    elif delta.type == "text_delta":
                        print(delta.text, end="", flush=True)
                
                elif event.type == "content_block_stop":
                    # 内容块结束事件，打印分隔线
                    if current_thinking or current_text:
                        print(f"\n{'='*60}\n")
                        current_thinking = False
                        current_text = False
            
            # 获取完整的响应对象（流式结束后）
            response = stream.get_final_message()
        
        # 将助手的响应添加到消息历史
        messages.append({"role": "assistant", "content": response.content})
        
        # 如果模型没有要求使用工具，结束循环
        if response.stop_reason != "tool_use":
            print(f"✅ Agent 任务完成 (stop_reason: {response.stop_reason})")
            return
        
        # 处理所有工具调用
        results = []
        manual_compact = False  # 标记是否触发了手动压缩
        print(f"\n🛠️  执行工具调用:")
        
        for block in response.content:
            if block.type == "tool_use":
                # 打印工具名称和参数
                print(f"  📌 工具: {block.name}")
                print(f"  📝 参数: {str(block.input)[:200]}...")
                
                # 检查是否是手动压缩工具
                if block.name == "compact":
                    manual_compact = True  # 设置手动压缩标志
                    output = "Compressing..."  # 提示消息
                else:
                    # 处理其他工具
                    handler = TOOL_HANDLERS.get(block.name)
                    try:
                        # 执行工具（如果处理器存在）
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        # 捕获工具执行中的任何异常
                        output = f"Error: {e}"
                
                # 打印工具执行结果（限制显示长度）
                print(f"  ✓ 结果: {str(output)[:200]}...")
                
                # 将工具结果添加到结果列表
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,  # 对应的工具使用 ID
                    "content": str(output)    # 工具输出结果
                })
        
        # 将所有工具结果作为用户消息添加到历史
        messages.append({"role": "user", "content": results})
        
        # 第三层：如果触发了手动压缩，执行压缩并结束循环
        if manual_compact:
            # 提示用户：手动压缩已触发（模型调用了 compact 工具）
            print("💾 [manual compact]")
            messages[:] = auto_compact(messages)  # 用压缩后的消息替换原消息列表
            return  # 压缩后结束当前循环


# ============================================================
# 主程序入口
# ============================================================

if __name__ == "__main__":
    """
    交互式命令行界面（支持三层压缩机制 + 流式输出和思考过程可视化）
    
    用户可以输入查询，Agent 会：
    1. 自动管理上下文大小（三层压缩）
    2. 实时显示模型的思考过程和回答内容
    3. 使用可用的工具来响应
    4. 在对话变长时自动或手动压缩历史
    
    这样可以实现真正的"无限对话"，并提供完整的思考过程可视化
    """
    history = []  # 初始化对话历史
    
    while True:
        try:
            # 显示提示符并获取用户输入
            # \033[36m 是青色，\033[0m 重置颜色
            query = input("\033[36ms06 >> \033[0m")
            # 清理可能存在的无效 surrogate 字符
            # 使用 encode 和 decode 配合 surrogateescape/replace 错误处理器
            query = query.encode('utf-8', errors='surrogateescape').decode('utf-8', errors='replace')
        except (EOFError, KeyboardInterrupt):
            # 处理 Ctrl+D 或 Ctrl+C
            break
        
        # 检查退出命令
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        # 将用户查询添加到历史
        history.append({"role": "user", "content": query})
        
        # 运行 agent 循环处理查询
        agent_loop(history)
        
        # 注意：由于使用了流式输出，模型的响应已经在 agent_loop 中实时显示了
        # 不需要在这里再次打印响应内容
        
        print()  # 打印空行分隔不同轮次的对话

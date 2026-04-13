#!/usr/bin/env python3
# 线束：持久化任务 -- 超越单次对话的目标管理。
"""
s07_task_system.py - 任务系统

任务以 JSON 文件形式持久化在 .tasks/ 目录，因此可以在上下文压缩后继续存在。
每个任务都有一个依赖图（blockedBy）。

    .tasks/
      task_1.json  {"id":1, "subject":"...", "status":"completed", ...}
      task_2.json  {"id":2, "blockedBy":[1], "status":"pending", ...}
      task_3.json  {"id":3, "blockedBy":[2], ...}

    依赖关系解析：
    +----------+     +----------+     +----------+
    | task 1   | --> | task 2   | --> | task 3   |
    | complete |     | blocked  |     | blocked  |
    +----------+     +----------+     +----------+
         |                ^
         +--- 完成 task 1 后，自动从 task 2 的 blockedBy 中移除

核心理念："状态在压缩后依然存在 -- 因为它保存在对话之外。"
"""

# ============================================================
# 导入必要的库
# ============================================================
import json          # JSON 序列化
import os            # 操作系统接口
import subprocess    # 子进程管理
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
TASKS_DIR = WORKDIR / ".tasks"  # 任务持久化存储目录

SYSTEM = f"You are a coding agent at {WORKDIR}. Use task tools to plan and track work."


# ============================================================
# TaskManager: CRUD 操作 + 依赖图管理，持久化为 JSON 文件
# ============================================================

class TaskManager:
    """
    任务管理器：负责任务的创建、读取、更新、删除，以及依赖关系管理
    
    主要功能：
    1. 任务以独立的 JSON 文件形式存储在 .tasks/ 目录
    2. 每个任务都有唯一的 ID 和状态
    3. 支持任务间的依赖关系（blockedBy）
    4. 当任务完成时，自动从其他任务的依赖列表中移除
    """
    def __init__(self, tasks_dir: Path):
        """
        初始化任务管理器
        
        Args:
            tasks_dir: 任务存储目录的路径
        """
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)  # 确保任务目录存在
        self._next_id = self._max_id() + 1  # 计算下一个可用的任务 ID

    def _max_id(self) -> int:
        """
        查找当前已存在的最大任务 ID
        
        Returns:
            最大任务 ID（如果没有任务则返回 0）
        """
        # 从所有 task_*.json 文件名中提取 ID
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0

    def _load(self, task_id: int) -> dict:
        """
        从磁盘加载指定任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            任务字典
            
        Raises:
            ValueError: 如果任务不存在
        """
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        """
        将任务保存到磁盘
        
        Args:
            task: 任务字典（必须包含 'id' 字段）
        """
        path = self.dir / f"task_{task['id']}.json"
        # 保存为格式化的 JSON，支持中文字符
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False))

    def create(self, subject: str, description: str = "") -> str:
        """
        创建新任务
        
        Args:
            subject: 任务主题（简短描述）
            description: 任务详细描述（可选）
            
        Returns:
            创建的任务的 JSON 字符串
        """
        # 构建任务结构
        task = {
            "id": self._next_id,          # 唯一标识符
            "subject": subject,           # 任务主题
            "description": description,   # 任务描述
            "status": "pending",          # 初始状态：待处理
            "blockedBy": [],              # 依赖的任务列表（初始为空）
            "owner": "",                  # 任务负责人（初始为空）
        }
        self._save(task)  # 持久化到磁盘
        self._next_id += 1  # 递增 ID 计数器
        return json.dumps(task, indent=2, ensure_ascii=False)

    def get(self, task_id: int) -> str:
        """
        获取指定任务的信息
        
        Args:
            task_id: 任务 ID
            
        Returns:
            任务的 JSON 字符串
        """
        return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)

    def update(self, task_id: int, status: str = None,
               add_blocked_by: list = None, remove_blocked_by: list = None) -> str:
        """
        更新任务状态和依赖关系
        
        Args:
            task_id: 要更新的任务 ID
            status: 新状态（可选）："pending"、"in_progress" 或 "completed"
            add_blocked_by: 要添加的依赖任务 ID 列表（可选）
            remove_blocked_by: 要移除的依赖任务 ID 列表（可选）
            
        Returns:
            更新后的任务的 JSON 字符串
            
        Raises:
            ValueError: 如果提供的状态无效
        """
        task = self._load(task_id)
        
        # 更新状态
        if status:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            # 如果任务标记为完成，清理依赖关系
            if status == "completed":
                self._clear_dependency(task_id)
        
        # 添加新依赖（使用 set 去重）
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        
        # 移除依赖
        if remove_blocked_by:
            task["blockedBy"] = [x for x in task["blockedBy"] if x not in remove_blocked_by]
        
        self._save(task)  # 保存更新
        return json.dumps(task, indent=2, ensure_ascii=False)

    def _clear_dependency(self, completed_id: int):
        """
        当任务完成时，从所有其他任务的 blockedBy 列表中移除该任务
        
        这是依赖图管理的核心功能：
        当一个任务完成后，所有依赖它的任务会自动解除该依赖
        
        Args:
            completed_id: 已完成的任务 ID
        """
        # 遍历所有任务文件
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            # 如果该任务依赖已完成的任务
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)  # 移除依赖
                self._save(task)  # 保存更新

    def list_all(self) -> str:
        """
        列出所有任务，按 ID 排序
        
        Returns:
            格式化的任务列表字符串，包含状态标记和依赖信息
            示例:
                [ ] #1: 实现登录功能
                [>] #2: 编写测试用例 (blocked by: [1])
                [x] #3: 代码审查
        """
        tasks = []
        # 按 ID 排序加载所有任务
        files = sorted(
            self.dir.glob("task_*.json"),
            key=lambda f: int(f.stem.split("_")[1])
        )
        for f in files:
            tasks.append(json.loads(f.read_text()))
        
        if not tasks:
            return "No tasks."
        
        # 格式化任务列表
        lines = []
        for t in tasks:
            # 状态标记
            marker = {
                "pending": "[ ]",       # 待处理
                "in_progress": "[>]",   # 进行中
                "completed": "[x]"      # 已完成
            }.get(t["status"], "[?]")   # 未知状态
            
            # 依赖信息（如果有）
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            
            # 组合完整的任务行
            lines.append(f"{marker} #{t['id']}: {t['subject']}{blocked}")
        
        return "\n".join(lines)


# ============================================================
# 初始化全局任务管理器实例
# ============================================================
TASKS = TaskManager(TASKS_DIR)


# ============================================================
# 基础工具函数实现
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
        c = fp.read_text()  # 读取文件内容
        if old_text not in c:
            # 如果找不到要替换的文本
            return f"Error: Text not found in {path}"
        # 替换第一次出现的文本（replace 的第三个参数 1 表示只替换一次）
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"  # 返回成功消息
    except Exception as e:
        return f"Error: {e}"  # 返回错误信息


# ============================================================
# 工具处理器映射表和工具定义
# ============================================================

# 工具处理器字典：将工具名称映射到对应的处理函数
TOOL_HANDLERS = {
    "bash":        lambda **kw: run_bash(kw["command"]),  # 执行 bash 命令
    "read_file":   lambda **kw: run_read(kw["path"], kw.get("limit")),  # 读取文件
    "write_file":  lambda **kw: run_write(kw["path"], kw["content"]),  # 写入文件
    "edit_file":   lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),  # 编辑文件
    # 任务管理工具
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),  # 创建任务
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("addBlockedBy"), kw.get("removeBlockedBy")),  # 更新任务
    "task_list":   lambda **kw: TASKS.list_all(),  # 列出所有任务
    "task_get":    lambda **kw: TASKS.get(kw["task_id"]),  # 获取任务详情
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
        "name": "task_create",
        "description": "Create a new task.",  # 创建新任务
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "description": {"type": "string"}
            },
            "required": ["subject"]
        }
    },
    {
        "name": "task_update",
        "description": "Update a task's status or dependencies.",  # 更新任务状态或依赖关系
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"]
                },
                "addBlockedBy": {
                    "type": "array",
                    "items": {"type": "integer"}
                },
                "removeBlockedBy": {
                    "type": "array",
                    "items": {"type": "integer"}
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "task_list",
        "description": "List all tasks with status summary.",  # 列出所有任务及状态摘要
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "task_get",
        "description": "Get full details of a task by ID.",  # 根据 ID 获取任务完整信息
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"}
            },
            "required": ["task_id"]
        }
    },
]


# ============================================================
# Agent 主循环
# ============================================================

def agent_loop(messages: list):
    """
    Agent 的主要对话循环（包含流式输出和思考过程可视化）
    
    工作流程：
    1. 调用 Claude API 生成响应（流式 + 扩展思考）
    2. 实时显示模型的思考过程和回答内容
    3. 检查是否需要使用工具（stop_reason == "tool_use"）
    4. 执行所有工具调用
    5. 将工具结果添加到消息历史
    6. 继续循环，直到模型不再需要工具
    
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
        print(f"\n🛠️  执行工具调用:")
        
        for block in response.content:
            if block.type == "tool_use":
                # 打印工具名称和参数
                print(f"  📌 工具: {block.name}")
                print(f"  📝 参数: {str(block.input)[:200]}...")
                
                # 处理工具
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


# ============================================================
# 主程序入口
# ============================================================

if __name__ == "__main__":
    """
    交互式命令行界面（支持流式输出和思考过程可视化）
    
    用户可以输入查询，Agent 会：
    1. 实时显示模型的思考过程和回答内容
    2. 使用任务管理工具和文件操作工具来响应
    3. 持久化任务信息到磁盘（在 .tasks/ 目录）
    4. 管理任务间的依赖关系
    
    这样可以实现跨会话的任务管理和完整的思考过程可视化
    """
    history = []  # 初始化对话历史
    
    while True:
        try:
            # 显示提示符并获取用户输入
            # \033[36m 是青色，\033[0m 重置颜色
            query = input("\033[36ms07 >> \033[0m")
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

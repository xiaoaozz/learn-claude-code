#!/usr/bin/env python3
# 线束：按需加载的知识 -- 领域专业知识，在模型请求时加载。
"""
s05_skill_loading.py - 技能系统

双层技能注入机制，避免系统提示词膨胀：

    第一层（低成本）：系统提示词中的技能名称（约 100 tokens/技能）
    第二层（按需加载）：在 tool_result 中返回完整的技能内容

    skills/
      pdf/
        SKILL.md          <-- 前置元数据（名称、描述）+ 主体内容
      code-review/
        SKILL.md

    系统提示词：
    +--------------------------------------+
    | 你是一个编程代理。                    |
    | 可用技能：                           |
    |   - pdf: 处理 PDF 文件...            |  <-- 第一层：仅元数据
    |   - code-review: 代码审查...         |
    +--------------------------------------+

    当模型调用 load_skill("pdf") 时：
    +--------------------------------------+
    | tool_result:                         |
    | <skill>                              |
    |   完整的 PDF 处理指令                 |  <-- 第二层：完整内容
    |   步骤 1: ...                        |
    |   步骤 2: ...                        |
    | </skill>                             |
    +--------------------------------------+

核心理念："不要把所有内容都放在系统提示词中。按需加载。"
"""

# ============================================================
# 导入必要的库
# ============================================================
import os          # 操作系统接口
import re          # 正则表达式
import subprocess  # 子进程管理
import yaml        # YAML 解析
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
SKILLS_DIR = WORKDIR / "skills"  # 技能文件目录路径

# ============================================================
# 技能加载器类：扫描并加载 skills/<name>/SKILL.md 文件
# ============================================================
class SkillLoader:
    """
    技能加载器：负责从文件系统加载和管理技能
    
    每个技能存储在 skills/<技能名称>/SKILL.md 文件中
    SKILL.md 文件格式：
    ---
    name: skill-name
    description: skill description
    tags: optional-tags
    ---
    [技能主体内容]
    """
    
    def __init__(self, skills_dir: Path):
        """
        初始化技能加载器
        
        Args:
            skills_dir: 技能目录路径
        """
        self.skills_dir = skills_dir  # 技能目录
        self.skills = {}  # 存储所有技能的字典 {技能名: {meta, body, path}}
        self._load_all()  # 立即加载所有技能

    def _load_all(self):
        """
        扫描技能目录，加载所有 SKILL.md 文件
        
        遍历 skills_dir 下所有子目录，查找并解析 SKILL.md 文件
        """
        if not self.skills_dir.exists():
            return  # 如果目录不存在，直接返回
            
        # 递归查找所有 SKILL.md 文件，并按字母顺序排序
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()  # 读取文件内容
            meta, body = self._parse_frontmatter(text)  # 解析前置元数据和主体内容
            # 技能名称优先从元数据获取，否则使用父目录名
            name = meta.get("name", f.parent.name)
            # 存储技能信息
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str) -> tuple:
        """
        解析 YAML 前置元数据
        
        前置元数据格式：
        ---
        key1: value1
        key2: value2
        ---
        [主体内容]
        
        Args:
            text: 完整的文件内容
            
        Returns:
            (元数据字典, 主体内容) 元组
        """
        # 使用正则表达式匹配 --- 分隔符之间的内容
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text  # 如果没有前置元数据，返回空字典和原始内容
            
        try:
            # 尝试解析 YAML 元数据
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}  # 解析失败则返回空字典
            
        return meta, match.group(2).strip()  # 返回元数据和去除首尾空白的主体内容

    def get_descriptions(self) -> str:
        """
        第一层：生成技能简短描述，用于系统提示词
        
        这是"廉价"的第一层：只包含技能名称和简短描述
        不包含完整的技能内容，节省 token
        
        Returns:
            格式化的技能列表字符串
        """
        if not self.skills:
            return "(no skills available)"  # 无技能时返回提示信息
            
        lines = []
        for name, skill in self.skills.items():
            # 从元数据获取描述，默认为 "No description"
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")  # 获取可选的标签
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"  # 如果有标签，添加到行尾
            lines.append(line)
            
        return "\n".join(lines)  # 返回换行符连接的技能列表

    def get_content(self, name: str) -> str:
        """
        第二层：返回完整的技能主体内容
        
        当模型调用 load_skill 工具时，会通过此方法获取完整的技能内容
        这是"昂贵"的第二层：包含技能的完整指导内容
        
        Args:
            name: 技能名称
            
        Returns:
            包装在 <skill> 标签中的完整技能内容
        """
        skill = self.skills.get(name)
        if not skill:
            # 技能不存在时返回错误信息和可用技能列表
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        # 返回带 XML 标签包装的技能内容
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"

# ============================================================
# 初始化技能加载器和系统提示词
# ============================================================
SKILL_LOADER = SkillLoader(SKILLS_DIR)  # 创建全局技能加载器实例

# 第一层：将技能元数据注入系统提示词
# 这里只包含技能的简短描述（约 100 tokens/技能）
# 完整的技能内容会在模型调用 load_skill 时按需加载
# SYSTEM = f"""你是一个位于 {WORKDIR} 的编程代理。
# 在处理不熟悉的主题之前，请使用 load_skill 访问专业知识。
#
# 可用技能：
# {SKILL_LOADER.get_descriptions()}"""
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}"""


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
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),  # 加载技能（第二层）
}

# 工具定义列表：供 Claude API 使用的工具 schema
TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",  # 运行 shell 命令
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"}  # 命令字符串参数
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file contents.",  # 读取文件内容
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},      # 文件路径
                "limit": {"type": "integer"}     # 可选的行数限制
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
                "path": {"type": "string"},      # 文件路径
                "content": {"type": "string"}    # 要写入的内容
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
                "path": {"type": "string"},       # 文件路径
                "old_text": {"type": "string"},   # 要查找的原始文本
                "new_text": {"type": "string"}    # 替换后的新文本
            },
            "required": ["path", "old_text", "new_text"]
        }
    },
    {
        "name": "load_skill",
        "description": "Load specialized knowledge by name.",  # 按名称加载专业知识
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name to load"  # 要加载的技能名称
                }
            },
            "required": ["name"]
        }
    },
]


# ============================================================
# Agent 主循环
# ============================================================

def agent_loop(messages: list):
    """
    Agent 的主要对话循环（支持流式输出和思考过程可视化）
    
    工作流程：
    1. 调用 Claude API 生成响应（流式 + 扩展思考）
    2. 实时显示模型的思考过程和回答内容
    3. 检查是否需要使用工具（stop_reason == "tool_use"）
    4. 如果需要工具，执行所有工具调用
    5. 将工具结果添加到消息历史
    6. 继续循环，直到模型不再需要工具
    
    这是一个典型的 agentic loop 模式：
    用户消息 -> 模型响应 -> 工具使用 -> 工具结果 -> 模型响应 -> ...
    
    Args:
        messages: 对话消息历史列表
    """
    iteration = 0  # 循环迭代计数器
    
    while True:
        iteration += 1
        print(f"\n{'━'*60}")
        print(f"🎯 Agent 循环 #{iteration}")
        print(f"{'━'*60}")
        
        # 调用 Claude API（启用流式处理和扩展思考）
        with client.messages.stream(
            model=MODEL,           # 使用的模型
            system=SYSTEM,         # 系统提示词（包含技能列表）
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
                print(f"  📌 工具: {block.name}")
                print(f"  📝 参数: {str(block.input)[:200]}...")
                
                # 获取对应的工具处理器
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    # 执行工具（如果处理器存在）
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    # 捕获工具执行中的任何异常
                    output = f"Error: {e}"
                
                print(f"  ✓ 结果: {str(output)[:200]}...")
                
                # 将工具结果添加到结果列表（限制在 50000 字符以内）
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,  # 对应的工具使用 ID
                    "content": str(output)[:50000]  # 工具输出结果（截断长输出）
                })
                
        # 将所有工具结果作为用户消息添加到历史
        messages.append({"role": "user", "content": results})


# ============================================================
# 主程序入口
# ============================================================

if __name__ == "__main__":
    """
    交互式命令行界面（支持实时思考过程可视化）
    
    用户可以输入查询，Agent 会：
    1. 实时显示思考过程（如果启用了扩展思考）
    2. 实时显示回答内容
    3. 使用可用的工具（包括技能加载）来响应
    """
    history = []  # 初始化对话历史
    
    while True:
        try:
            # 显示提示符并获取用户输入
            # \033[36m 是青色，\033[0m 重置颜色
            query = input("\033[36ms05 >> \033[0m")
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
        
        # 提取并显示最后一条助手响应（如果还没显示过）
        # 注意：由于我们使用了流式输出，文本内容已经在循环中实时显示了
        # 这里保留此代码以保持与原始结构一致
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            # 如果响应是列表（包含多个 content block）
            for block in response_content:
                if hasattr(block, "text"):
                    # 只打印文本块（如果之前没有显示）
                    # 由于流式输出已经显示了，这里实际上不会重复打印
                    pass
                    
        print()  # 打印空行分隔


"""
AI Client — 统一的多 Provider AI 调用模块
==========================================
支持 Anthropic (Claude) 和 OpenAI 兼容接口 (DeepSeek 等)。
根据环境变量自动选择 Provider。

环境变量:
  AI_PROVIDER          : 强制指定 provider: "anthropic" | "deepseek" | "openai"
                         (未设置时根据可用的 API Key 自动检测)
  ANTHROPIC_API_KEY    : Anthropic API 密钥
  DEEPSEEK_API_KEY     : DeepSeek API 密钥
  DEEPSEEK_BASE_URL    : DeepSeek API 地址 (默认 https://api.deepseek.com)
  OPENAI_API_KEY       : OpenAI API 密钥
  OPENAI_BASE_URL      : 自定义 OpenAI 兼容端点

模型映射 (按任务类型自动选择):
  task="fix"      → claude-sonnet-4-6       / deepseek-chat
  task="review"   → claude-sonnet-4-6       / deepseek-chat
  task="triage"   → claude-haiku-4-5-20251001 / deepseek-chat

用法:
  from ai_client import AIClient

  client = AIClient(task="fix")
  response = client.chat(
      system="你是一个助手",
      messages=[{"role": "user", "content": "你好"}],
      max_tokens=4096,
  )
  print(response)  # 直接返回文本内容
"""

import os
import json
import sys
from typing import Optional


# ============================================================
# Provider 检测
# ============================================================

def detect_provider() -> str:
    """检测应该使用哪个 AI Provider。"""
    explicit = os.environ.get("AI_PROVIDER", "").lower()
    if explicit in ("anthropic", "deepseek", "openai"):
        return explicit

    # 自动检测：优先 Anthropic，其次 DeepSeek
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    # 都没设置，报错
    print("❌ 未设置任何 AI API Key！请设置以下环境变量之一：")
    print("   ANTHROPIC_API_KEY  - 用于 Claude")
    print("   DEEPSEEK_API_KEY   - 用于 DeepSeek")
    print("   OPENAI_API_KEY     - 用于 OpenAI 或兼容接口")
    sys.exit(1)


# ============================================================
# 模型映射
# ============================================================

MODEL_MAP = {
    "anthropic": {
        "fix": "claude-sonnet-4-6",
        "review": "claude-sonnet-4-6",
        "triage": "claude-haiku-4-5-20251001",
    },
    "deepseek": {
        "fix": "deepseek-chat",
        "review": "deepseek-chat",
        "triage": "deepseek-chat",
    },
    "openai": {
        "fix": "gpt-4o",
        "review": "gpt-4o",
        "triage": "gpt-4o-mini",
    },
}

# 允许通过环境变量覆盖模型
# AI_MODEL_FIX, AI_MODEL_REVIEW, AI_MODEL_TRIAGE


def get_model(provider: str, task: str) -> str:
    """获取指定 provider 和 task 对应的模型名称。"""
    env_override = os.environ.get(f"AI_MODEL_{task.upper()}", "")
    if env_override:
        return env_override
    return MODEL_MAP.get(provider, {}).get(task, "gpt-4o")


# ============================================================
# AIClient 类
# ============================================================

class AIClient:
    """统一的多 Provider AI 客户端。"""

    def __init__(self, task: str = "fix"):
        """
        初始化客户端。

        Args:
            task: 任务类型 "fix" | "review" | "triage"
        """
        self.provider = detect_provider()
        self.task = task
        self.model = get_model(self.provider, task)

        print(f"  🧠 Provider: {self.provider}")
        print(f"  🤖 Model: {self.model}")

    # ---- Anthropic ----

    def _call_anthropic(self, system: str, messages: list[dict], max_tokens: int) -> str:
        """通过 Anthropic SDK 调用 Claude。"""
        try:
            from anthropic import Anthropic
        except ImportError:
            print("  安装 anthropic SDK...")
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "anthropic", "-q"], check=True)
            from anthropic import Anthropic

        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    # ---- OpenAI 兼容 (DeepSeek / OpenAI) ----

    def _call_openai_compatible(self, system: str, messages: list[dict], max_tokens: int) -> str:
        """通过 OpenAI 兼容接口调用（DeepSeek 或 OpenAI）。"""
        try:
            from openai import OpenAI
        except ImportError:
            print("  安装 openai SDK...")
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "openai", "-q"], check=True)
            from openai import OpenAI

        if self.provider == "deepseek":
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            base_url = os.environ.get("OPENAI_BASE_URL", None)

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = OpenAI(**client_kwargs)

        # 构建完整的消息列表（system prompt 作为第一条消息）
        full_messages = [{"role": "system", "content": system}] + messages

        response = client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=0.3,  # 代码任务需要更确定性的输出
        )
        return response.choices[0].message.content

    # ---- 统一接口 ----

    def chat(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        """
        发送 chat 请求，返回文本响应。

        Args:
            system: 系统提示词
            messages: 消息列表 [{"role": "user", "content": "..."}]
            max_tokens: 最大输出 token 数

        Returns:
            AI 响应的文本内容
        """
        if self.provider == "anthropic":
            return self._call_anthropic(system, messages, max_tokens)
        else:
            return self._call_openai_compatible(system, messages, max_tokens)


# ============================================================
# 便捷函数（Slash Command Mode - 本地交互式使用）
# ============================================================

def quick_chat(prompt: str, task: str = "fix") -> str:
    """快速对话，无需关心 Provider 细节。"""
    client = AIClient(task=task)
    return client.chat(
        system="你是一个专业的软件工程师助手。请用中文回答。",
        messages=[{"role": "user", "content": prompt}],
    )


# ============================================================
# 自检
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("AI Client 自检")
    print("=" * 50)
    provider = detect_provider()
    print(f"  检测到 Provider: {provider}")
    for task in ["fix", "review", "triage"]:
        model = get_model(provider, task)
        print(f"  {task:10s} → {model}")
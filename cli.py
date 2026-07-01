#!/usr/bin/env python3
"""
AI Workflow CLI - 命令行入口

用于本地测试和查看 AI 工作流配置信息。
"""

import sys
import os
import argparse
import tomllib

# 将 .github/scripts 加入 Python 路径，以便导入 ai_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.github', 'scripts'))

from ai_client import AIProvider, get_ai_client


def get_version():
    """从 pyproject.toml 读取版本号，若文件不存在则返回 '0.1.0'"""
    pyproject_path = os.path.join(os.path.dirname(__file__), 'pyproject.toml')
    try:
        with open(pyproject_path, 'rb') as f:
            data = tomllib.load(f)
        return data.get('project', {}).get('version', '0.1.0')
    except (FileNotFoundError, tomllib.TOMLDecodeError, KeyError):
        return '0.1.0'


def get_project_info():
    """获取项目基本信息"""
    return {
        'version': '1.0.0',
        'repo': 'https://github.com/ctemple/test_action',
        'name': 'AI Workflow'
    }


def detect_provider():
    """自动检测当前配置的 AI Provider"""
    if os.environ.get('ANTHROPIC_API_KEY'):
        return 'Anthropic', 'claude-sonnet-4-6'
    elif os.environ.get('DEEPSEEK_API_KEY'):
        return 'DeepSeek', 'deepseek-chat'
    elif os.environ.get('OPENAI_API_KEY'):
        return 'OpenAI', 'gpt-4o'
    else:
        return None, None


def show_help():
    """显示帮助信息"""
    info = get_project_info()
    provider, model = detect_provider()

    print(f"🤖 {info['name']} CLI")
    print("=" * (len(info['name']) + 8))
    if provider:
        print(f"Provider: {provider}")
        print(f"Model   : {model}")
    else:
        print("Provider: 未配置 (请设置 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY)")
    print(f"Repo    : {info['repo']}")
    print()
    print("可用命令:")
    print(f"  python cli.py          显示此帮助")
    print(f"  python cli.py info     显示 AI Provider 详细信息")
    print(f"  python cli.py check    检查 API Key 配置是否正常")


def show_info():
    """显示 AI Provider 详细信息"""
    provider, model = detect_provider()
    info = get_project_info()

    print(f"🤖 {info['name']} - Provider 详细信息")
    print("=" * 40)
    print(f"项目版本: {info['version']}")
    print(f"仓库地址: {info['repo']}")
    print()

    if provider:
        print(f"当前 Provider: {provider}")
        print(f"当前 Model  : {model}")
        print()
        print("支持的 Provider:")
        print("  - Anthropic (ANTHROPIC_API_KEY)")
        print("  - DeepSeek  (DEEPSEEK_API_KEY)")
        print("  - OpenAI    (OPENAI_API_KEY)")
        print()
        print("可通过设置 AI_PROVIDER 环境变量强制指定 Provider")
    else:
        print("未检测到任何 API Key 配置")
        print()
        print("请设置以下环境变量之一:")
        print("  - ANTHROPIC_API_KEY")
        print("  - DEEPSEEK_API_KEY")
        print("  - OPENAI_API_KEY")


def check_api_key():
    """检查 API Key 配置是否正常"""
    provider, model = detect_provider()

    if not provider:
        print("❌ 未检测到任何 API Key 配置")
        print()
        print("请设置以下环境变量之一:")
        print("  - ANTHROPIC_API_KEY")
        print("  - DEEPSEEK_API_KEY")
        print("  - OPENAI_API_KEY")
        sys.exit(1)

    print(f"✅ 检测到 {provider} API Key")
    print(f"   默认模型: {model}")

    # 尝试创建客户端，验证配置是否有效
    try:
        client = get_ai_client()
        print("✅ AI 客户端创建成功")
    except Exception as e:
        print(f"❌ AI 客户端创建失败: {e}")
        sys.exit(1)


def main():
    """主入口"""
    if len(sys.argv) == 1:
        show_help()
    elif sys.argv[1] == 'info':
        show_info()
    elif sys.argv[1] == 'check':
        check_api_key()
    else:
        print(f"未知命令: {sys.argv[1]}")
        print()
        show_help()
        sys.exit(1)


if __name__ == '__main__':
    main()

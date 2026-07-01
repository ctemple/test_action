#!/usr/bin/env python3
"""
AI Issue Triage 脚本
--------------------
由 GitHub Actions 在新 Issue 创建时触发。调用 Claude API 分析 Issue 内容，
自动添加标签、评估优先级，并在适当时给出自动回复。

环境变量:
  ANTHROPIC_API_KEY  : Anthropic API 密钥
  GITHUB_TOKEN        : GitHub Token
  GITHUB_REPOSITORY   : 仓库名
  ISSUE_NUMBER        : Issue 编号
"""

import os
import sys
import json
import subprocess
import textwrap
import re
from pathlib import Path


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
REPO = os.environ.get("GITHUB_REPOSITORY", "")
ISSUE_NUMBER = os.environ.get("ISSUE_NUMBER", "")

# 确保可以导入同目录下的 ai_client 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_client import AIClient

CLAUDE_MODEL = os.environ.get("AI_MODEL_TRIAGE", "claude-haiku-4-5-20251001")  # 分类任务使用轻量模型


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  [RUN] {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  [ERR] {result.stderr}")
    return result


def run_json(cmd: str) -> dict:
    result = run(cmd)
    return json.loads(result.stdout.strip())


# ============================================================
# Step 1: 获取 Issue
# ============================================================

def get_issue() -> dict:
    print("\n📋 获取 Issue 信息...")
    data = run_json(
        f'gh issue view {ISSUE_NUMBER} --repo {REPO} '
        f'--json title,body,author,state,labels,createdAt'
    )
    print(f"  标题: {data['title']}")
    print(f"  作者: {data['author']['login']}")
    return data


# ============================================================
# Step 2: 获取仓库现有的 labels
# ============================================================

def get_available_labels() -> list[dict]:
    print("\n🏷️  获取仓库现有标签...")
    result = run(f"gh label list --repo {REPO} --json name,description --limit 50", check=False)
    if result.returncode == 0 and result.stdout.strip():
        labels = json.loads(result.stdout)
        print(f"  找到 {len(labels)} 个标签")
        return labels
    return []


# ============================================================
# Step 3: 调用 Claude 进行分类
# ============================================================

def call_claude_triage(issue: dict, available_labels: list[dict]) -> dict:
    print("\n🤖 调用 Claude API 进行分类...")

    label_names = [l['name'] for l in available_labels]
    label_info = '\n'.join(f'- `{l["name"]}`: {l.get("description", "")}' for l in available_labels)

    system_prompt = textwrap.dedent(f"""\
    你是一个 Issue 分类助手。分析 GitHub Issue 并给出分类建议。

    ## 可用标签
    {label_info if label_info else '(仓库暂无标签，建议创建)'}

    ## 输出格式
    请严格按照以下 JSON 格式输出:

    {{
      "category": "bug | enhancement | question | documentation | duplicate | wontfix | help-wanted",
      "priority": "P0 | P1 | P2 | P3",
      "complexity": "simple | moderate | complex",
      "suggested_labels": ["标签1", "标签2"],
      "suggested_assignee_team": "适合处理此问题的团队或角色",
      "auto_reply": "如果可以自动回复（如常见问题的标准答案），写在这里；否则写 null",
      "is_ai_fixable": true,
      "triage_note": "分类理由（1-2句话）"
    }}

    ## 分类标准
    - **bug**: 功能异常、错误行为
    - **enhancement**: 功能改进、新功能建议
    - **question**: 使用问题、咨询
    - **documentation**: 文档相关
    - **duplicate**: 疑似重复
    - **wontfix**: 建议不予处理
    - **help-wanted**: 需要社区帮助

    ## 优先级标准
    - **P0**: 关键功能完全不可用，安全漏洞
    - **P1**: 重要功能受影响，需要尽快修复
    - **P2**: 一般问题，按正常排期处理
    - **P3**: 小问题、优化建议，可延后处理

    ## is_ai_fixable 标准
    - true: 问题描述清晰，预计可以在 1-2 个文件中完成修改，不需要复杂的业务知识
    - false: 需要深入理解业务、涉及架构决策、需要跨多个服务修改
    """)

    user_message = f"""## Issue

**标题**: {issue['title']}

**内容**:
{issue.get('body', '(无内容)')}

**作者**: {issue['author']['login']}

请分类此 Issue。"""
    # 使用 AIClient（自动选择 Anthropic / DeepSeek / OpenAI）
    client = AIClient(task="triage")
    content = client.chat(
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=2048,
    )
    json_str = content
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)

    try:
        triage = json.loads(json_str)
    except json.JSONDecodeError:
        start = json_str.find('{')
        end = json_str.rfind('}')
        if start != -1 and end != -1:
            triage = json.loads(json_str[start:end + 1])
        else:
            print(f"  ❌ 无法解析: {content[:500]}")
            triage = {
                "category": "bug",
                "priority": "P2",
                "suggested_labels": [],
                "auto_reply": None,
                "is_ai_fixable": False,
                "triage_note": "自动分类失败，请手动分类"
            }

    print(f"  分类: {triage.get('category')}")
    print(f"  优先级: {triage.get('priority')}")
    print(f"  可AI修复: {triage.get('is_ai_fixable')}")
    print(f"  建议标签: {triage.get('suggested_labels')}")
    return triage


# ============================================================
# Step 4: 应用标签和回复
# ============================================================

def apply_triage(issue: dict, triage: dict, available_labels: list[dict]):
    print("\n🏷️  应用分类结果...")

    existing_labels = [l['name'] for l in issue.get('labels', [])]
    suggested = triage.get("suggested_labels", [])
    available_names = [l['name'] for l in available_labels]

    # 过滤出实际存在的标签
    labels_to_add = [l for l in suggested if l in available_names and l not in existing_labels]

    # 确保 category 标签存在
    category = triage.get("category", "")
    category_labels = ["bug", "enhancement", "question", "documentation", "help-wanted"]
    if category in category_labels and category not in existing_labels and category not in labels_to_add:
        if category in available_names:
            labels_to_add.append(category)

    # 添加优先级标签
    priority = triage.get("priority", "")
    priority_labels = ["P0", "P1", "P2", "P3"]
    if priority in priority_labels and priority not in existing_labels and priority not in labels_to_add:
        if priority in available_names:
            labels_to_add.append(priority)
        else:
            # 尝试创建优先级标签
            run(
                f'gh label create {priority} --repo {REPO} '
                f'--color "FF6B6B" --description "优先级: {priority}"',
                check=False
            )
            labels_to_add.append(priority)

    # 如果 ai_fixable，添加 ai-fix 标签
    if triage.get("is_ai_fixable") and "ai-fix" not in existing_labels:
        labels_to_add.append("ai-fix")

    if labels_to_add:
        print(f"  添加标签: {labels_to_add}")
        for label in labels_to_add:
            run(f'gh issue edit {ISSUE_NUMBER} --repo {REPO} --add-label "{label}"', check=False)
    else:
        print("  ℹ️  无需添加新标签")

    # 自动回复
    auto_reply = triage.get("auto_reply")
    if auto_reply and auto_reply != "null":
        print(f"  💬 添加自动回复...")
        reply_body = f"🤖 **AI 自动分类**\n\n{auto_reply}\n\n"
        reply_body += f"- **分类**: `{triage.get('category')}`\n"
        reply_body += f"- **优先级**: `{triage.get('priority')}`\n"
        if triage.get("is_ai_fixable"):
            reply_body += f"\n💡 此问题看起来适合 AI 自动修复。维护者可以在评论中输入 `/ai-fix` 来让 AI 自动处理。\n"
        reply_body += f"\n---\n*此分类由 AI 自动生成，如有不准确请手动调整。*"

        reply_file = "/tmp/triage_reply.md"
        Path(reply_file).write_text(reply_body, encoding="utf-8")
        run(f'gh issue comment {ISSUE_NUMBER} --repo {REPO} --body-file {reply_file}')


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("🤖 AI Issue Triage")
    print(f"   仓库: {REPO}")
    print(f"   Issue: #{ISSUE_NUMBER}")
    print("=" * 60)

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("❌ 缺少 API Key！请设置 ANTHROPIC_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY")
        sys.exit(1)

    issue = get_issue()

    # 跳过 bot
    if issue.get("author", {}).get("login", "").endswith("[bot]"):
        print("⏭️ 跳过 bot 创建的 Issue")
        sys.exit(0)

    # 跳过已有标签的 Issue（避免重复分类）
    existing = issue.get("labels", [])
    has_category = any(
        l['name'] in ['bug', 'enhancement', 'question', 'documentation']
        for l in existing
    )
    if has_category and existing:
        print("⏭️ Issue 已有分类标签，跳过自动分类")
        sys.exit(0)

    available_labels = get_available_labels()
    triage = call_claude_triage(issue, available_labels)
    apply_triage(issue, triage, available_labels)

    print("\n✅ AI Issue Triage 完成！")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
AI Code Review 脚本
-------------------
由 GitHub Actions 触发，获取 PR 的 diff 内容，调用 Claude API 进行代码审查，
并自动将审查意见作为 PR Review 提交。

触发方式:
  - PR 被创建 (pull_request: opened)
  - PR 有新提交 (pull_request: synchronize)
  - PR 评论 `/ai-review`

审查维度:
  - 🐛 Bug / 逻辑错误
  - 🔒 安全漏洞
  - ⚡ 性能问题
  - 📐 代码风格 / 最佳实践
  - 🧪 测试覆盖建议
  - 📖 文档 / 注释完整性

环境变量:
  ANTHROPIC_API_KEY  : Anthropic API 密钥
  GITHUB_TOKEN        : GitHub Token
  GITHUB_REPOSITORY   : 仓库名
  PR_NUMBER           : Pull Request 编号
"""

import os
import sys
import json
import subprocess
import textwrap
import re
from pathlib import Path
from typing import Optional


# ============================================================
# 配置
# ============================================================

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
REPO = os.environ.get("GITHUB_REPOSITORY", "")
PR_NUMBER = os.environ.get("PR_NUMBER", "")

CLAUDE_MODEL = "claude-sonnet-4-6"

# 最大 diff 大小（字节），超过此大小将进行截断
MAX_DIFF_SIZE = 50000

# 是否需要批准（true = Request Changes, false = Comment only）
REQUEST_CHANGES_ON_ISSUES = os.environ.get("REQUEST_CHANGES_ON_ISSUES", "true").lower() == "true"


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """执行 shell 命令。"""
    print(f"  [RUN] {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  [ERR] stderr: {result.stderr}")
        return result  # 不直接退出，让调用者处理
    return result


def run_json(cmd: str) -> dict:
    """执行命令并解析 JSON 输出。"""
    result = run(cmd)
    return json.loads(result.stdout.strip())


# ============================================================
# Step 1: 获取 PR 信息
# ============================================================

def get_pr_info() -> dict:
    """获取 PR 的基本信息。"""
    print("\n📋 获取 PR 信息...")
    data = run_json(
        f'gh pr view {PR_NUMBER} --repo {REPO} '
        f'--json title,body,author,state,baseRefName,headRefName,changedFiles,additions,deletions,labels'
    )
    print(f"  标题: {data['title']}")
    print(f"  作者: {data['author']['login']}")
    print(f"  分支: {data['headRefName']} → {data['baseRefName']}")
    print(f"  变更: +{data['additions']} / -{data['deletions']} ({data['changedFiles']} 个文件)")
    return data


def get_pr_diff() -> str:
    """获取 PR 的完整 diff。"""
    print("\n📊 获取 PR diff...")
    result = run(f"gh pr diff {PR_NUMBER} --repo {REPO}", check=False)
    diff = result.stdout

    if len(diff) == 0:
        print("  ⚠️ diff 为空")
        sys.exit(0)

    # 如果 diff 太大，进行智能截断
    if len(diff) > MAX_DIFF_SIZE:
        print(f"  ⚠️ diff 过大 ({len(diff)} 字节)，进行智能截断...")
        # 保留每个文件的前 200 行 diff
        files = re.split(r'(?=^diff --git)', diff, flags=re.MULTILINE)
        truncated = []
        for f_diff in files:
            lines = f_diff.split('\n')
            if len(lines) > 250:
                truncated.append('\n'.join(lines[:250]) + f"\n... (截断，原始共 {len(lines)} 行)")
            else:
                truncated.append(f_diff)
        diff = '\n'.join(truncated)
        print(f"  ✓ 截断后: {len(diff)} 字节")

    print(f"  diff 大小: {len(diff)} 字节")
    return diff


def get_pr_files() -> list[str]:
    """获取 PR 变更的文件列表。"""
    result = run(f"gh pr view {PR_NUMBER} --repo {REPO} --json files --jq '.files[].path'", check=False)
    return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]


# ============================================================
# Step 2: 调用 Claude API 进行代码审查
# ============================================================

def call_claude_to_review(pr_info: dict, diff: str, changed_files: list[str]) -> dict:
    """
    调用 Claude API 审查代码变更。
    返回结构化的审查意见。
    """
    print("\n🤖 调用 Claude API 审查代码...")

    system_prompt = textwrap.dedent("""\
    你是一个资深代码审查专家。请审查以下 Pull Request 的代码变更，
    从多个维度给出专业的审查意见。

    ## 审查维度
    1. **🐛 Bug / 逻辑错误**: 可能导致程序故障的逻辑问题
    2. **🔒 安全漏洞**: 注入攻击、敏感信息泄露、认证授权问题等
    3. **⚡ 性能问题**: N+1 查询、不必要的循环、内存泄漏、阻塞操作等
    4. **📐 代码风格**: 命名规范、代码重复、过度复杂、可读性问题
    5. **🧪 测试建议**: 缺少的测试用例、边界条件
    6. **📖 文档/注释**: 缺少必要的注释或文档

    ## 输出格式
    请严格按照以下 JSON 格式输出（不要包含 markdown 代码块标记）:

    {
      "summary": "一句话总结这次 PR 的变更内容和整体评价",
      "overall_assessment": "APPROVE | COMMENT | REQUEST_CHANGES",
      "findings": [
        {
          "severity": "CRITICAL | HIGH | MEDIUM | LOW | SUGGESTION",
          "category": "bug | security | performance | style | testing | documentation",
          "file": "相对于仓库根目录的文件路径",
          "line": 42,
          "title": "简短的问题描述",
          "description": "详细的问题解释，包括为什么这是个问题和建议的修复方案",
          "suggestion": "具体的代码修改建议（可选）"
        }
      ],
      "praise": ["值得称赞的地方", "做得好的点"]
    }

    ## 注意事项
    - 只报告真正的、有实际影响的问题，不要吹毛求疵
    - severity 为 CRITICAL 时意味着这是一个阻止合并的严重问题
    - 如果没有发现问题，findings 为空数组，overall_assessment 应为 "APPROVE"
    - 对于 SUGGESTION 级别的问题，使用建设性的语气
    - 代码风格问题要参考项目现有的风格约定
    - 如果没有足够上下文判断，标注为 COMMENT 而非 REQUEST_CHANGES
    - 不要对第三方库的代码或 lock 文件进行审查
    """)

    files_summary = '\n'.join(f'- {f}' for f in changed_files[:50])

    user_message = f"""## PR 信息

**标题**: {pr_info['title']}
**分支**: {pr_info['headRefName']} → {pr_info['baseRefName']}
**变更统计**: +{pr_info['additions']} / -{pr_info['deletions']} ({pr_info['changedFiles']} 个文件)

**描述**:
{pr_info.get('body', '(无描述)')}

## 变更文件列表

{files_summary}

## Diff

```diff
{diff}
```

请对以上代码变更进行全面的代码审查，输出 JSON 格式的审查结果。"""

    # 安装并使用 anthropic SDK
    try:
        from anthropic import Anthropic
    except ImportError:
        print("  安装 anthropic SDK...")
        run("pip install anthropic -q")

    from anthropic import Anthropic

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    content = response.content[0].text

    # 解析 JSON
    json_str = content
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)

    try:
        review = json.loads(json_str)
    except json.JSONDecodeError:
        start = json_str.find('{')
        end = json_str.rfind('}')
        if start != -1 and end != -1:
            review = json.loads(json_str[start:end + 1])
        else:
            print(f"  ❌ 无法解析响应:\n{content}")
            sys.exit(1)

    findings_count = len(review.get("findings", []))
    print(f"  ✓ 审查完成")
    print(f"  ✓ 评估: {review.get('overall_assessment', 'N/A')}")
    print(f"  ✓ 发现 {findings_count} 个问题")

    for f in review.get("findings", []):
        emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "SUGGESTION": "💡"}
        e = emoji.get(f.get("severity", ""), "⚪")
        print(f"    {e} [{f.get('severity', '?')}] {f.get('title', '?')[:80]}")

    return review


# ============================================================
# Step 3: 提交 PR Review
# ============================================================

def format_review_body(review: dict, pr_info: dict) -> str:
    """将审查意见格式化为 Markdown 评论。"""
    parts = []

    # 头部
    parts.append(f"## 🤖 AI Code Review")
    parts.append(f"")
    overall = review.get("overall_assessment", "COMMENT")
    emoji_map = {
        "APPROVE": "✅",
        "COMMENT": "💬",
        "REQUEST_CHANGES": "❌"
    }
    parts.append(f"**评估结论**: {emoji_map.get(overall, '💬')} **{overall}**")
    parts.append(f"")
    parts.append(f"> {review.get('summary', 'N/A')}")
    parts.append(f"")

    # 发现问题
    findings = review.get("findings", [])
    if findings:
        parts.append(f"### 📋 审查发现 ({len(findings)} 个问题)")
        parts.append(f"")

        severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "SUGGESTION"]
        sorted_findings = sorted(
            findings,
            key=lambda x: severity_order.index(x.get("severity", "SUGGESTION"))
            if x.get("severity") in severity_order else 99
        )

        current_severity = None
        for finding in sorted_findings:
            sev = finding.get("severity", "?")
            if sev != current_severity:
                current_severity = sev
                sev_labels = {
                    "CRITICAL": "🔴 CRITICAL — 必须修复才能合并",
                    "HIGH": "🟠 HIGH — 强烈建议修复",
                    "MEDIUM": "🟡 MEDIUM — 应该修复",
                    "LOW": "🔵 LOW — 可选修复",
                    "SUGGESTION": "💡 SUGGESTION — 优化建议"
                }
                parts.append(f"#### {sev_labels.get(sev, sev)}")
                parts.append(f"")

            file = finding.get("file", "")
            line = finding.get("line", "")
            location = f"`{file}`" if file else ""
            if line:
                location += f":L{line}"

            parts.append(f"**{finding.get('title', '?')}**")
            parts.append(f"")
            parts.append(f"📍 {location} | 🏷️ `{finding.get('category', '?')}`")
            parts.append(f"")
            parts.append(f"{finding.get('description', '')}")
            parts.append(f"")

            if finding.get("suggestion"):
                parts.append(f"**建议修改**:")
                parts.append(f"```suggestion")
                parts.append(f"{finding['suggestion']}")
                parts.append(f"```")
                parts.append(f"")

            parts.append(f"---")
            parts.append(f"")

    else:
        parts.append(f"### ✅ 未发现问题")
        parts.append(f"")
        parts.append(f"代码看起来不错！没有发现明显的问题。")
        parts.append(f"")

    # 表扬
    praise = review.get("praise", [])
    if praise:
        parts.append(f"### 👏 值得称赞")
        parts.append(f"")
        for p in praise:
            parts.append(f"- ✅ {p}")
        parts.append(f"")

    # 尾部
    parts.append(f"---")
    parts.append(f"*此审查由 AI Agent 自动生成 | PR: [#{PR_NUMBER}]({pr_info.get('url', '')}) | 模型: {CLAUDE_MODEL}*")
    parts.append(f"")
    parts.append(f"*如有疑问，请在 PR 中 @ 人类审查者进行人工复核。*")

    return "\n".join(parts)


def submit_review(review: dict, pr_info: dict):
    """提交 PR Review 到 GitHub。"""
    print(f"\n📤 提交 PR Review...")

    overall = review.get("overall_assessment", "COMMENT")

    # 映射到 GitHub Review 事件类型
    event_map = {
        "APPROVE": "APPROVE",
        "COMMENT": "COMMENT",
        "REQUEST_CHANGES": "REQUEST_CHANGES",
    }

    # 如果不开启 REQUEST_CHANGES 模式，CRITICAL 才请求修改
    event = event_map.get(overall, "COMMENT")
    if not REQUEST_CHANGES_ON_ISSUES and event == "REQUEST_CHANGES":
        event = "COMMENT"

    # 格式化审查正文
    body = format_review_body(review, pr_info)

    # 写入文件
    review_file = "/tmp/review_body.md"
    Path(review_file).write_text(body, encoding="utf-8")

    # 使用 gh pr review 提交
    cmd = (
        f'gh pr review {PR_NUMBER} --repo {REPO} '
        f'--{event.lower()} --body-file {review_file}'
    )
    result = run(cmd, check=False)

    if result.returncode == 0:
        print(f"  ✓ 审查已提交 ({event})")
    else:
        print(f"  ⚠️ gh pr review 失败，改用评论: {result.stderr}")
        # Fallback: 以普通评论方式发布
        run(
            f'gh pr comment {PR_NUMBER} --repo {REPO} --body-file {review_file}',
            check=False
        )
        print(f"  ✓ 已作为评论发布")


# ============================================================
# Step 4: 可选 - 对审查意见中的建议直接生成修复 commit
# ============================================================

def auto_fix_review_issues(review: dict, diff: str):
    """
    如果有简单的代码风格问题，可以尝试自动修复并提交。
    需要 PR 作者在评论中 @ai-autofix 来触发。
    （此功能预留，默认不启用）
    """
    pass


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("🤖 AI Code Review")
    print(f"   仓库: {REPO}")
    print(f"   PR: #{PR_NUMBER}")
    print(f"   模型: {CLAUDE_MODEL}")
    print("=" * 60)

    if not ANTHROPIC_API_KEY:
        print("❌ 缺少 ANTHROPIC_API_KEY 环境变量")
        sys.exit(1)

    # 跳过 bot 创建的 PR（避免递归审查）
    pr_info = get_pr_info()
    author = pr_info.get("author", {}).get("login", "")
    if author.endswith("[bot]") or author == "github-actions":
        print(f"⏭️ 跳过 bot 创建的 PR (作者: {author})")
        sys.exit(0)

    # 检查是否需要跳过 AI 生成的 PR（AI 审查 AI 的代码通常价值有限）
    if pr_info.get("title", "").startswith("🤖 AI:"):
        print("⏭️ 跳过 AI 自动生成的 PR（避免循环审查）")
        sys.exit(0)

    # Step 1: 获取 diff
    diff = get_pr_diff()
    changed_files = get_pr_files()
    print(f"  变更文件: {len(changed_files)} 个")

    # Step 2: 调用 Claude 审查
    review = call_claude_to_review(pr_info, diff, changed_files)

    # Step 3: 提交审查
    submit_review(review, pr_info)

    print("\n✅ AI Code Review 完成！")


if __name__ == "__main__":
    main()
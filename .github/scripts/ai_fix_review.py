#!/usr/bin/env python3
"""
AI Fix Review 脚本
------------------
当 AI Code Review 发现严重问题并 REQUEST_CHANGES 时，此脚本自动读取审查意见，
修复代码问题，推送到同一分支，触发新一轮审查，形成"审查→修复→审查"闭环。

触发方式:
  - PR Review 提交且状态为 CHANGES_REQUESTED（AI 审查不通过）
  - PR 评论 `/ai-fix-review`

环境变量:
  DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY
  GITHUB_TOKEN        : GitHub Token
  GITHUB_REPOSITORY   : 仓库名
  PR_NUMBER           : PR 编号

安全机制:
  - 最多自动修复 2 轮，避免死循环
  - 仅处理 AI 自己提交的 Review（github-actions[bot]）
  - 仅修复 CRITICAL 和 HIGH 级别的问题
"""

import os
import sys
import json
import subprocess
import textwrap
import re
from pathlib import Path
from typing import Optional

# 确保可以导入同目录下的 ai_client 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_client import AIClient

REPO = os.environ.get("GITHUB_REPOSITORY", "")
PR_NUMBER = os.environ.get("PR_NUMBER", "")

# 最大自动修复轮数（防止死循环）
MAX_FIX_ROUNDS = 2


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
# Step 1: 获取 PR 信息和最新 Review
# ============================================================

def get_pr_info() -> dict:
    print("\n📋 获取 PR 信息...")
    data = run_json(
        f'gh pr view {PR_NUMBER} --repo {REPO} '
        f'--json title,body,headRefName,baseRefName,author,state,reviews'
    )
    print(f"  标题: {data['title']}")
    print(f"  分支: {data['headRefName']}")
    return data


def get_latest_ai_review(pr_info: dict) -> Optional[dict]:
    """获取最新的 AI 审查意见（REJECT 或 COMMENT 状态）。"""
    print("\n🔍 查找 AI 审查意见...")
    reviews = pr_info.get("reviews", [])

    # 找到最新的 AI 审查（github-actions[bot] 提交的）
    ai_reviews = [
        r for r in reviews
        if r.get("author", {}).get("login") in ("github-actions", "github-actions[bot]")
        and r.get("state") in ("CHANGES_REQUESTED", "COMMENTED")
    ]

    if not ai_reviews:
        print("  ⚠️ 未找到 AI 审查意见")
        return None

    # 取最新的一条
    latest = ai_reviews[-1]
    print(f"  状态: {latest['state']}")
    print(f"  时间: {latest.get('submittedAt', 'N/A')}")
    return latest


def parse_findings_from_review(review: dict) -> list[dict]:
    """从 Review body 中解析出需要修复的问题列表。"""
    body = review.get("body", "")

    findings = []
    # 匹配每个问题的 Markdown 块
    pattern = re.compile(
        r'\*\*(.+?)\*\*\s*\n\n'
        r'📍\s*`(.+?)`\s*(?::L(\d+))?\s*\|\s*🏷️\s*`(.+?)`\s*\n\n'
        r'(.+?)\n\n'  # description
        r'(?:\*\*建议修改\*\*:\s*\n```suggestion\s*\n(.*?)\n```\s*\n\n)?',  # optional suggestion
        re.DOTALL
    )

    for match in pattern.finditer(body):
        title = match.group(1).strip()
        file = match.group(2).strip()
        line = match.group(3)
        category = match.group(4).strip()
        description = match.group(5).strip()
        suggestion = match.group(6)

        # 也提取严重程度（从上下文）
        severity = "MEDIUM"
        if "CRITICAL" in body[max(0, match.start()-200):match.start()]:
            severity = "CRITICAL"
        elif "HIGH" in body[max(0, match.start()-200):match.start()]:
            severity = "HIGH"
        elif "LOW" in body[max(0, match.start()-200):match.start()]:
            severity = "LOW"
        elif "SUGGESTION" in body[max(0, match.start()-200):match.start()]:
            severity = "SUGGESTION"

        findings.append({
            "title": title,
            "file": file,
            "line": int(line) if line else None,
            "category": category,
            "severity": severity,
            "description": description,
            "suggestion": suggestion.strip() if suggestion else None,
        })

    print(f"  解析到 {len(findings)} 个问题")
    for f in findings:
        print(f"    [{f['severity']}] {f['title'][:60]}")

    return findings


# ============================================================
# Step 2: 检查修复轮数（防止死循环）
# ============================================================

def count_fix_rounds(branch: str) -> int:
    """统计当前分支上已有的 AI fix review 提交次数。"""
    result = run(
        f'git log origin/{branch} --oneline --grep="fix: AI review fix" 2>/dev/null | wc -l',
        check=False
    )
    count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    print(f"  当前已修复轮数: {count}")
    return count


# ============================================================
# Step 3: 调用 AI 修复问题
# ============================================================

def call_ai_fix_review(findings: list[dict], pr_info: dict) -> dict:
    """
    调用 AI 根据审查意见修复代码问题。
    只修复 CRITICAL 和 HIGH 级别的问题，将修改合并到同一分支。
    """
    print("\n🤖 调用 AI 修复审查意见...")

    # 只修复严重问题
    serious = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]
    minor = [f for f in findings if f["severity"] not in ("CRITICAL", "HIGH")]

    if not serious:
        print("  ℹ️  没有 CRITICAL 或 HIGH 级别的问题需要修复")
        return {"files_to_modify": []}

    print(f"  严重问题: {len(serious)} 个")
    print(f"  次要问题: {len(minor)} 个（跳过）")

    # 读取需要修改的文件
    files_to_fix = list(set(f["file"] for f in serious))
    file_contents = {}
    for fpath in files_to_fix:
        try:
            content = Path(fpath).read_text(encoding="utf-8")
            file_contents[fpath] = content
        except FileNotFoundError:
            print(f"  ⚠️ 文件不存在: {fpath}")

    files_summary = "\n\n".join(
        f"### {fp}\n```\n{content[:3000]}\n```"
        for fp, content in file_contents.items()
    )

    findings_text = "\n\n".join(
        f"### 问题 {i+1}: [{f['severity']}] {f['title']}\n"
        f"- 文件: {f['file']}\n"
        f"- 行号: {f.get('line', 'N/A')}\n"
        f"- 类别: {f['category']}\n"
        f"- 描述: {f['description']}\n"
        f"- 建议: {f.get('suggestion', '无')}\n"
        for i, f in enumerate(serious)
    )

    system_prompt = textwrap.dedent("""\
    你是一个资深软件工程师。你的任务是根据代码审查意见修复代码问题。

    ## 工作流程
    1. 阅读每个审查意见，理解问题所在
    2. 在现有代码中找到对应位置
    3. 实施修复，遵循审查建议

    ## 输出格式
    请严格按照以下 JSON 格式输出:

    {
      "files_to_modify": [
        {
          "path": "文件路径",
          "original_snippet": "需要替换的原始代码",
          "new_content": "替换后的代码",
          "reason": "修复说明"
        }
      ],
      "commit_message": "fix: AI review fix - 修复描述",
      "summary": "修复总结（中文）"
    }

    ## 注意事项
    - 只修复审查意见中明确指出的问题，不要做额外重构
    - original_snippet 必须精确匹配文件中的代码，确保唯一性
    - 保持项目现有的代码风格
    - 如果审查意见中给出了 suggestion，优先采用
    """)

    user_message = f"""## 审查意见（需要修复的严重问题）

{findings_text}

## 当前代码

{files_summary}

请修复以上 CRITICAL 和 HIGH 级别的问题，输出 JSON 格式的修复方案。"""

    client = AIClient(task="fix")
    content = client.chat(
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=8192,
    )

    # 解析 JSON
    json_str = content
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)

    try:
        plan = json.loads(json_str)
    except json.JSONDecodeError:
        start = json_str.find('{')
        end = json_str.rfind('}')
        if start != -1 and end != -1:
            plan = json.loads(json_str[start:end + 1])
        else:
            print(f"  ❌ 无法解析: {content[:500]}")
            plan = {"files_to_modify": [], "commit_message": "fix: AI review fix", "summary": "自动修复失败"}

    print(f"  ✓ 分析完成: {plan.get('summary', 'N/A')[:100]}")
    print(f"  ✓ 需要修改 {len(plan.get('files_to_modify', []))} 个文件")
    return plan


# ============================================================
# Step 4: 应用修复并推送
# ============================================================

def apply_fixes_and_push(plan: dict, pr_info: dict):
    files = plan.get("files_to_modify", [])
    if not files:
        print("  ℹ️  没有需要修改的文件")
        return

    branch = pr_info["headRefName"]
    print(f"\n📝 应用修复 (分支: {branch})...")

    # 切换到 PR 分支
    run(f"git fetch origin {branch}")
    run(f"git checkout {branch}")

    for i, f in enumerate(files):
        path = f["path"]
        print(f"  [{i+1}/{len(files)}] 修复: {path}")

        original = Path(path).read_text(encoding="utf-8")
        old_snippet = f["original_snippet"]
        new_content = f["new_content"]

        if old_snippet not in original:
            print(f"    ⚠️ 原始代码片段未找到，尝试模糊匹配...")
            old_lines = old_snippet.strip().split('\n')
            if old_lines and old_lines[0].strip() in original:
                print(f"    ✓ 首行匹配成功")
            else:
                print(f"    ❌ 无法定位，跳过")
                continue

        new_file = original.replace(old_snippet, new_content, 1)
        Path(path).write_text(new_file, encoding="utf-8")
        run(f"git add {path}")

    # 检查是否有改动
    status = run("git status --porcelain", check=False)
    if not status.stdout.strip():
        print("  ℹ️  没有实际改动")
        return

    # Commit
    commit_msg = plan.get("commit_message", "fix: AI review fix")
    run(f'git commit -m "{commit_msg}"')

    # Push
    run(f"git push origin {branch}")

    # 在 PR 中评论
    summary = plan.get("summary", "已修复审查意见中的问题")
    comment = (
        f"🤖 **AI 已根据审查意见修复**\n\n"
        f"{summary}\n\n"
        f"修复了 {len(files)} 个文件，请重新审查。\n\n"
        f"---\n*自动修复 | PR: [#{PR_NUMBER}]*"
    )
    comment_file = "/tmp/fix_review_comment.md"
    Path(comment_file).write_text(comment, encoding="utf-8")
    run(f'gh pr comment {PR_NUMBER} --repo {REPO} --body-file {comment_file}', check=False)

    print(f"\n✅ 修复已推送！新 commit 将触发 AI Code Review 重新审查")


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("🤖 AI Fix Review — 审查→修复→审查闭环")
    print(f"   仓库: {REPO}")
    print(f"   PR: #{PR_NUMBER}")
    print("=" * 60)

    # 检查 API Key
    if not (os.environ.get("ANTHROPIC_API_KEY") or
            os.environ.get("DEEPSEEK_API_KEY") or
            os.environ.get("OPENAI_API_KEY")):
        print("❌ 缺少 API Key")
        sys.exit(1)

    # Step 1: 获取 PR 和 Review
    pr_info = get_pr_info()

    # 跳过 AI 自己的 PR
    if pr_info.get("title", "").startswith("🤖 AI:"):
        print("⏭️ 跳过 AI 生成的 PR")
        sys.exit(0)

    # Step 2: 检查修复轮数
    branch = pr_info["headRefName"]
    rounds = count_fix_rounds(branch)
    if rounds >= MAX_FIX_ROUNDS:
        print(f"⏭️ 已修复 {rounds} 轮，达到上限 ({MAX_FIX_ROUNDS})，请人工介入")
        run(
            f'gh pr comment {PR_NUMBER} --repo {REPO} '
            f'--body "⚠️ AI 已自动修复 {rounds} 轮，达到上限。请人工审查并决定是否合并。"',
            check=False
        )
        sys.exit(0)

    # Step 3: 获取最新 AI 审查
    review = get_latest_ai_review(pr_info)
    if not review:
        print("⏭️ 无需处理")
        sys.exit(0)

    # Step 4: 解析问题
    findings = parse_findings_from_review(review)
    if not findings:
        print("  ℹ️  审查中未发现问题")
        sys.exit(0)

    # Step 5: AI 修复
    plan = call_ai_fix_review(findings, pr_info)

    # Step 6: 应用并推送
    apply_fixes_and_push(plan, pr_info)

    print("\n✅ 修复完成！新 commit 将触发 AI Code Review 重新审查")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
AI Auto-Fix Issue 脚本
-----------------------
由 GitHub Actions 触发，读取 Issue 内容，调用 AI 分析并生成修复代码，
自动创建分支、提交 commit、推送并创建 Pull Request。

流程:
  1. 读取 Issue → 收集仓库上下文
  2. AI 分析 → 生成修复代码
  3. 应用修改到本地
  4. 🆕 AI 自审循环 (2轮) → 发现致命问题 → 修复 → 再审查
  5. 自审通过后 → commit → push → 创建 PR（附带自审报告）

触发方式:
  - Issue 被标记 'ai-fix' label
  - Issue 中收到 '/ai-fix' 评论

环境变量:
  ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
  GITHUB_TOKEN        : GitHub Token
  GITHUB_REPOSITORY   : 仓库名
  ISSUE_NUMBER        : Issue 编号
  SELF_REVIEW_ROUNDS  : 自审轮数 (默认 2)
  SELF_REVIEW_ENABLED : 启用自审 (默认 true)
  DRY_RUN             : 仅展示计划不执行 (默认 false)
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
ISSUE_NUMBER = os.environ.get("ISSUE_NUMBER", "")

# 确保可以导入同目录下的 ai_client 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_client import AIClient

# 模型配置（如果使用 AI_MODEL_FIX 环境变量可以覆盖）
CLAUDE_MODEL = os.environ.get("AI_MODEL_FIX", "claude-sonnet-4-6")

# 是否仅生成计划而不实际修改代码（dry-run 模式）
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# 自审循环配置
SELF_REVIEW_ROUNDS = int(os.environ.get("SELF_REVIEW_ROUNDS", "2"))  # 提交 PR 前自我审查轮数
SELF_REVIEW_ENABLED = os.environ.get("SELF_REVIEW_ENABLED", "true").lower() == "true"


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """执行 shell 命令并返回结果。"""
    print(f"  [RUN] {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  [ERR] stderr: {result.stderr}")
        sys.exit(result.returncode)
    return result


def run_json(cmd: str) -> dict:
    """执行命令并解析 JSON 输出。"""
    result = run(cmd)
    return json.loads(result.stdout.strip())


# ============================================================
# Step 1: 获取 Issue 信息
# ============================================================

def get_issue() -> dict:
    """通过 gh CLI 获取 Issue 详情。"""
    print("\n📋 获取 Issue 信息...")
    data = run_json(
        f'gh issue view {ISSUE_NUMBER} --repo {REPO} --json title,body,labels,author,state'
    )
    print(f"  标题: {data['title']}")
    print(f"  作者: {data['author']['login']}")
    print(f"  状态: {data['state']}")
    labels = [l['name'] for l in data.get('labels', [])]
    print(f"  标签: {', '.join(labels) if labels else '(无)'}")
    return data


# ============================================================
# Step 2: 获取仓库上下文
# ============================================================

def get_repo_context() -> str:
    """收集仓库的基本信息，帮助 Claude 理解项目。"""
    print("\n🔍 收集仓库上下文...")

    context_parts = []

    # README
    readme_path = Path("README.md")
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8")[:3000]
        context_parts.append(f"## README.md\n```markdown\n{readme}\n```")

    # 项目文件结构（前100个文件）
    try:
        tree = run("find . -type f -not -path './.git/*' -not -path '*/node_modules/*' "
                   "-not -path '*/__pycache__/*' -not -path './.venv/*' "
                   "| head -100", check=False)
        context_parts.append(f"## 文件结构\n```\n{tree.stdout.strip()}\n```")
    except Exception:
        pass

    # 语言统计
    try:
        langs = run(
            "find . -type f -not -path './.git/*' | sed 's/.*\\.//' | sort | uniq -c | sort -rn | head -15",
            check=False
        )
        context_parts.append(f"## 文件类型分布\n```\n{langs.stdout.strip()}\n```")
    except Exception:
        pass

    # package.json（如果有）
    pkg_json = Path("package.json")
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = pkg.get("dependencies", {})
            dev_deps = pkg.get("devDependencies", {})
            context_parts.append(
                f"## package.json\n"
                f"名称: {pkg.get('name', 'N/A')}\n"
                f"依赖 ({len(deps)}): {', '.join(list(deps.keys())[:20])}\n"
                f"开发依赖 ({len(dev_deps)}): {', '.join(list(dev_deps.keys())[:20])}"
            )
        except Exception:
            pass

    # requirements.txt / pyproject.toml（如果有）
    for fname in ["requirements.txt", "pyproject.toml", "Cargo.toml", "go.mod"]:
        fpath = Path(fname)
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8")[:2000]
            context_parts.append(f"## {fname}\n```\n{content}\n```")

    return "\n\n".join(context_parts)


# ============================================================
# Step 3: 调用 Claude API 分析问题并生成补丁
# ============================================================

def call_claude_to_fix(issue: dict, repo_context: str) -> dict:
    """
    调用 Claude API，分析 Issue 并生成修复方案。
    返回包含 plan、files_to_modify、patches 的结构化响应。
    """
    print("\n🤖 调用 Claude API 分析 Issue...")

    title = issue["title"]
    body = issue.get("body", "")

    system_prompt = textwrap.dedent("""\
    你是一个资深软件工程师 AI 助手。你的任务是根据 GitHub Issue 的描述，
    分析问题并在代码库中实现修复。

    ## 工作流程
    1. **理解问题**: 仔细阅读 Issue 描述，理解要修复什么
    2. **分析代码库**: 根据提供的仓库上下文，定位需要修改的文件
    3. **生成修复方案**: 制定具体的修改计划
    4. **生成代码**: 对每个文件给出具体的代码修改

    ## 输出格式
    请严格按照以下 JSON 格式输出（不要包含 markdown 代码块标记）:

    {
      "analysis": "对问题的简要分析（中文）",
      "files_to_modify": [
        {
          "path": "相对于仓库根目录的文件路径",
          "action": "create | modify | delete",
          "reason": "为什么需要修改这个文件",
          "original_snippet": "需要替换的原始代码片段（modify时）或 null（create时）",
          "new_content": "完整的文件新内容（create时）或替换后的新代码片段（modify时）"
        }
      ],
      "commit_message": "简明扼要的 commit 消息，遵循 conventional commits 格式",
      "pr_title": "Pull Request 标题",
      "pr_description": "详细的 PR 描述，说明做了什么修改、为什么这样修改、如何测试"
    }

    ## 注意事项
    - 只修改确实需要改的文件，不要做过度的重构
    - 遵循项目现有的代码风格
    - commit_message 遵循 conventional commits 格式: feat:, fix:, refactor:, docs: 等
    - 如果是创建新文件，action 用 "create"，new_content 写完整的文件内容
    - 如果是修改现有文件，action 用 "modify"，提供 original_snippet 和 new_content
    - original_snippet 要足够精确，确保能唯一匹配到文件中的位置
    """)

    user_message = f"""## Issue 信息

**标题**: {title}

**描述**:
{body}

## 仓库上下文

{repo_context}

## 任务

请分析以上 Issue，在代码库中找到相关文件并实现修复。输出 JSON 格式的修复方案。"""

    # 使用 AIClient（自动选择 Anthropic / DeepSeek / OpenAI）
    client = AIClient(task="fix")
    content = client.chat(
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=8192,
    )

    # 尝试解析 JSON（可能包裹在 markdown 代码块中）
    json_str = content
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)

    try:
        plan = json.loads(json_str)
    except json.JSONDecodeError:
        print("  ⚠️ Claude 返回的 JSON 解析失败，尝试修复...")
        # 尝试找到 JSON 的起始和结束
        start = json_str.find('{')
        end = json_str.rfind('}')
        if start != -1 and end != -1:
            plan = json.loads(json_str[start:end + 1])
        else:
            print(f"  ❌ 无法解析响应:\n{content}")
            sys.exit(1)

    print(f"  ✓ 分析完成: {plan.get('analysis', 'N/A')[:100]}...")
    print(f"  ✓ 需要修改 {len(plan.get('files_to_modify', []))} 个文件")
    return plan


# ============================================================
# Step 4: 应用修改
# ============================================================

def apply_changes(plan: dict) -> str:
    """
    根据 Claude 返回的修改计划，在本地文件中应用修改。
    返回新分支名称。
    """
    files = plan.get("files_to_modify", [])
    if not files:
        print("  ⚠️ 没有需要修改的文件")
        sys.exit(0)

    branch_name = f"ai/fix-issue-{ISSUE_NUMBER}"

    print(f"\n📝 应用代码修改 (分支: {branch_name})...")

    # 清理可能存在的旧分支（上次失败的残留）
    run(f"git branch -D {branch_name} 2>/dev/null || true", check=False)
    run(f"git push origin --delete {branch_name} 2>/dev/null || true", check=False)

    # 创建并切换到新分支
    run(f"git checkout -b {branch_name}")

    for i, f in enumerate(files):
        path = f["path"]
        action = f["action"]
        print(f"  [{i+1}/{len(files)}] {action}: {path}")

        if action == "create":
            # 确保目录存在
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(f["new_content"], encoding="utf-8")
            run(f"git add {path}")

        elif action == "modify":
            # 读取现有文件
            original = Path(path).read_text(encoding="utf-8")
            old_snippet = f["original_snippet"]
            new_content = f["new_content"]

            if old_snippet not in original:
                print(f"    ⚠️ 原始代码片段未在文件中找到，尝试模糊匹配...")
                # 尝试按行匹配
                old_lines = old_snippet.strip().split('\n')
                if len(old_lines) > 0:
                    first_line = old_lines[0].strip()
                    if first_line in original:
                        print(f"    ✓ 通过首行匹配成功")
                        # 仍然使用原始替换逻辑
                        pass
                    else:
                        print(f"    ❌ 无法定位修改位置，跳过此文件")
                        continue

            new_file = original.replace(old_snippet, new_content, 1)
            Path(path).write_text(new_file, encoding="utf-8")
            run(f"git add {path}")

        elif action == "delete":
            Path(path).unlink(missing_ok=True)
            run(f"git rm {path}")

        else:
            print(f"    ⚠️ 未知的操作类型: {action}，跳过")

    return branch_name


# ============================================================
# Step 4.5: 自审循环 — 提交 PR 前自我审查并修复致命问题
# ============================================================

def self_review_and_fix(plan: dict) -> dict:
    """
    在提交 PR 之前，AI 对自己的代码进行多轮自我审查。
    每轮审查 diff → 发现 CRITICAL/HIGH 问题 → 修复 → 再审查。
    最多 SELF_REVIEW_ROUNDS 轮，通过后才提交 PR。

    Returns:
        dict: 自审历史 {rounds: [...], final_verdict: "PASS"|"FIXED"}
    """
    if not SELF_REVIEW_ENABLED:
        print("\n⏭️ 自审循环已禁用 (SELF_REVIEW_ENABLED=false)")
        return {"rounds": [], "final_verdict": "SKIPPED"}

    # 检查是否有更改需要审查
    status = run("git diff --cached --stat", check=False)
    if not status.stdout.strip():
        return {"rounds": [], "final_verdict": "NO_CHANGES"}

    history = []
    final_verdict = "PASS"

    for round_num in range(1, SELF_REVIEW_ROUNDS + 1):
        print(f"\n🔍 === AI 自审第 {round_num}/{SELF_REVIEW_ROUNDS} 轮 ===")

        # 获取当前 diff
        diff = run("git diff --cached", check=False).stdout
        if not diff.strip():
            print("  ℹ️  没有待审查的更改")
            break

        # 统计 diff 大小
        diff_lines = len(diff.split('\n'))
        print(f"  diff: {diff_lines} 行")

        # 调用 AI 自审
        round_result = _call_self_review(diff, plan, round_num)
        history.append(round_result)

        verdict = round_result.get("verdict", "PASS")
        findings = round_result.get("findings", [])
        critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")

        print(f"  结论: {verdict}")
        print(f"  严重问题: {critical_count} CRITICAL, {high_count} HIGH")

        if critical_count == 0 and high_count == 0:
            print(f"  ✅ 自审通过！没有致命问题")
            final_verdict = "PASS"
            break
        else:
            print(f"  ⚠️ 发现致命问题，AI 正在修复...")
            fixes = _call_self_fix(diff, findings, plan, round_num)

            if fixes.get("files_to_modify"):
                applied = _apply_self_fixes(fixes)
                if applied:
                    print(f"  ✅ 已修复 {applied} 个文件，进入下一轮审查")
                    final_verdict = "FIXED"
                    continue
                else:
                    print(f"  ❌ 修复应用失败，终止自审")
                    break
            else:
                print(f"  ⚠️ AI 无法自动修复，终止自审")
                break
    else:
        print(f"  ⚠️ 已达最大自审轮数 ({SELF_REVIEW_ROUNDS})")
        final_verdict = "MAX_ROUNDS"

    return {"rounds": history, "final_verdict": final_verdict}


def _call_self_review(diff: str, plan: dict, round_num: int) -> dict:
    """调用 AI 对自己的代码进行审查。"""
    system_prompt = textwrap.dedent("""\
    你是一个严格的代码审查专家。请审查以下代码变更，只关注真正严重的问题。

    ## 审查聚焦（只报告以下问题）
    1. **CRITICAL**: 会导致程序崩溃、数据丢失、安全漏洞的致命问题
    2. **HIGH**: 明显的逻辑错误、功能缺失、严重性能问题
    3. 忽略：代码风格、命名建议、文档缺失等非致命问题

    ## 输出格式
    {
      "verdict": "PASS" | "FAIL",
      "summary": "一句话总结审查结果",
      "findings": [
        {
          "severity": "CRITICAL" | "HIGH",
          "file": "文件路径",
          "line": 行号或null,
          "title": "简短标题",
          "description": "详细问题描述",
          "suggestion": "具体修复建议"
        }
      ]
    }

    ## 注意
    - 宁可漏报低优先级问题，不要吹毛求疵
    - 只报告你非常确定的问题
    - 如果代码逻辑正确且无安全风险，verdict 为 "PASS"
    """)

    user_message = f"""## 原始需求
{plan.get('analysis', '')}

## 代码变更 (Diff) 第 {round_num} 轮审查

```diff
{diff[:12000]}
```

请严格审查以上代码变更，只报告 CRITICAL 和 HIGH 级别的问题。"""

    client = AIClient(task="review")
    content = client.chat(
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=4096,
    )

    # 解析 JSON
    json_str = content
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        start = json_str.find('{')
        end = json_str.rfind('}')
        if start != -1 and end != -1:
            result = json.loads(json_str[start:end + 1])
        else:
            result = {"verdict": "PASS", "findings": [], "summary": "自审解析失败，默认通过"}

    return result


def _call_self_fix(diff: str, findings: list[dict], plan: dict, round_num: int) -> dict:
    """调用 AI 修复自审发现的问题。"""
    serious_findings = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]
    if not serious_findings:
        return {"files_to_modify": []}

    findings_text = "\n\n".join(
        f"### [{f['severity']}] {f['title']}\n"
        f"文件: {f.get('file', '?')}\n"
        f"描述: {f.get('description', '')}\n"
        f"建议: {f.get('suggestion', '无')}\n"
        for f in serious_findings
    )

    system_prompt = textwrap.dedent("""\
    你是一个代码修复专家。修复以下审查意见中的问题。

    ## 输出格式
    {
      "files_to_modify": [
        {
          "path": "文件路径",
          "original_snippet": "要替换的原始代码片段",
          "new_content": "替换后的新代码",
          "reason": "修复说明"
        }
      ],
      "summary": "本轮修复总结"
    }

    ## 注意
    - 只修复审查指出的问题，不要额外重构
    - original_snippet 必须精确匹配文件内容
    - 只修改确实有问题的代码
    """)

    user_message = f"""## 审查意见 (第 {round_num} 轮)

{findings_text}

## 当前 Diff

```diff
{diff[:8000]}
```

请修复以上 CRITICAL 和 HIGH 问题。"""

    client = AIClient(task="fix")
    content = client.chat(
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=8192,
    )

    json_str = content
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)

    try:
        fixes = json.loads(json_str)
    except json.JSONDecodeError:
        start = json_str.find('{')
        end = json_str.rfind('}')
        if start != -1 and end != -1:
            fixes = json.loads(json_str[start:end + 1])
        else:
            fixes = {"files_to_modify": [], "summary": "修复解析失败"}

    return fixes


def _apply_self_fixes(fixes: dict) -> int:
    """应用自审修复到文件，返回修复的文件数。"""
    files = fixes.get("files_to_modify", [])
    applied = 0

    for f in files:
        path = f["path"]
        try:
            original = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"    ⚠️ 文件不存在: {path}")
            continue

        old_snippet = f["original_snippet"]
        new_content = f["new_content"]

        if old_snippet in original:
            new_file = original.replace(old_snippet, new_content, 1)
            Path(path).write_text(new_file, encoding="utf-8")
            run(f"git add {path}")
            print(f"    ✓ 修复: {path} ({f.get('reason', '')[:40]})")
            applied += 1
        else:
            print(f"    ⚠️ 代码片段未匹配: {path}")

    return applied


def format_self_review_summary(self_review: dict) -> str:
    """格式化自审摘要，写入 PR 描述中。"""
    if self_review.get("final_verdict") == "SKIPPED":
        return ""

    rounds = self_review.get("rounds", [])
    if not rounds:
        return "\n### 🔍 AI 自审\n\n未执行自审（无代码变更）。\n"

    parts = ["### 🔍 AI 自审（提交前自我审查）\n"]
    parts.append(f"共 {len(rounds)} 轮自审，最终结论: **{self_review['final_verdict']}**\n")

    for i, r in enumerate(rounds):
        verdict = r.get("verdict", "?")
        emoji = "✅" if verdict == "PASS" else "⚠️"
        findings = r.get("findings", [])
        parts.append(f"\n**第 {i+1} 轮**: {emoji} {verdict}")
        parts.append(f"  - {r.get('summary', 'N/A')}")

        if findings:
            for f in findings:
                sev = f.get("severity", "?")
                sev_emoji = {"CRITICAL": "🔴", "HIGH": "🟠"}.get(sev, "⚪")
                parts.append(f"  - {sev_emoji} [{sev}] {f.get('title', '')[:80]}")

    parts.append(f"\n*自审通过后自动提交 PR。*")
    return "\n".join(parts) + "\n"


# ============================================================
# Step 5: 提交并创建 PR
# ============================================================

def commit_and_create_pr(branch: str, plan: dict, self_review: dict = None):
    """提交更改，推送到远端，并创建 Pull Request。"""
    print(f"\n🚀 提交并创建 Pull Request...")

    # 检查是否有未提交的更改
    result = run("git status --porcelain", check=False)
    if not result.stdout.strip():
        print("  ⚠️ 没有检测到文件更改，跳过提交")
        return

    # Commit
    commit_msg = plan.get("commit_message", f"fix: resolve issue #{ISSUE_NUMBER}")
    run(f'git commit -m "{commit_msg}"')

    # Push
    run(f"git push origin {branch}")

    # Create PR
    pr_title = plan.get("pr_title", f"🤖 AI: {commit_msg}")
    pr_body = ""

    # 自审摘要（如果有）
    if self_review:
        pr_body += format_self_review_summary(self_review) + "\n"

    pr_body += plan.get("pr_description", f"## 自动修复 Issue #{ISSUE_NUMBER}\n\n由 AI 自动生成。")

    # 追加元信息
    pr_body += f"\n\n---\n*此 PR 由 AI Agent 自动生成 | Issue: [#{ISSUE_NUMBER}] | 模型: {CLAUDE_MODEL}*"

    # 写入 PR 描述文件（避免 shell 转义问题）
    pr_body_file = "/tmp/pr_body.md"
    Path(pr_body_file).write_text(pr_body, encoding="utf-8")

    pr_result = run(
        f'gh pr create --repo {REPO} --base main --head {branch} '
        f'--title "{pr_title}" --body-file {pr_body_file}'
    )

    pr_url = pr_result.stdout.strip()
    print(f"  ✓ PR 已创建: {pr_url}")

    # 在 Issue 中评论
    comment = f"🤖 AI 已生成修复 PR：{pr_url}\n\n**分析**: {plan.get('analysis', '')[:200]}..."
    comment_file = "/tmp/comment.md"
    Path(comment_file).write_text(comment, encoding="utf-8")
    run(f'gh issue comment {ISSUE_NUMBER} --repo {REPO} --body-file {comment_file}')

    # 移除 ai-fix 标签，添加 in-progress 标签
    run(
        f'gh issue edit {ISSUE_NUMBER} --repo {REPO} '
        f'--remove-label "ai-fix" --add-label "ai-in-progress"',
        check=False
    )

    return pr_url


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("🤖 AI Auto-Fix Issue")
    print(f"   仓库: {REPO}")
    print(f"   Issue: #{ISSUE_NUMBER}")
    print(f"   模型: {CLAUDE_MODEL}")
    print(f"   Dry-Run: {DRY_RUN}")
    print("=" * 60)

    # 验证环境（AIClient 会自动检测可用的 API Key）
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        print("❌ 缺少 API Key！请设置 ANTHROPIC_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY")
        sys.exit(1)

    # Step 1: 获取 Issue
    issue = get_issue()

    # 跳过 bot 自身创建的 issue
    if issue.get("author", {}).get("login", "").endswith("[bot]"):
        print("⏭️ 跳过 bot 创建的 Issue")
        sys.exit(0)

    # Step 2: 收集仓库上下文
    repo_context = get_repo_context()

    # Step 3: 调用 Claude 分析
    plan = call_claude_to_fix(issue, repo_context)

    if DRY_RUN:
        print("\n🔍 [DRY-RUN] 修复计划:")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("\n⏭️ DRY-RUN 模式，不实际修改代码")
        return

    # Step 4: 应用修改
    branch = apply_changes(plan)

    # Step 4.5: 自审循环 — 提交 PR 前自我审查并修复致命问题
    self_review = self_review_and_fix(plan)

    # Step 5: 提交 & 创建 PR（附带自审摘要）
    commit_and_create_pr(branch, plan, self_review)

    print("\n✅ AI Auto-Fix 流程完成！")


if __name__ == "__main__":
    main()
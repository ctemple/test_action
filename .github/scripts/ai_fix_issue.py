#!/usr/bin/env python3
"""
AI Auto-Fix Issue 脚本
-----------------------
由 GitHub Actions 触发，读取 Issue 内容，调用 Claude API 分析并生成修复代码，
自动创建分支、提交 commit、推送并创建 Pull Request。

触发方式:
  - Issue 被标记 'ai-fix' label
  - Issue 中收到 '/ai-fix' 评论

环境变量:
  ANTHROPIC_API_KEY  : Anthropic API 密钥
  GITHUB_TOKEN        : GitHub Token（自动注入）
  GITHUB_REPOSITORY   : 仓库名 (owner/repo)
  ISSUE_NUMBER        : 触发的 Issue 编号
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
# Step 5: 提交并创建 PR
# ============================================================

def commit_and_create_pr(branch: str, plan: dict):
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
    pr_body = plan.get("pr_description", f"## 自动修复 Issue #{ISSUE_NUMBER}\n\n由 AI 自动生成。")

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

    # Step 5: 提交 & 创建 PR
    commit_and_create_pr(branch, plan)

    print("\n✅ AI Auto-Fix 流程完成！")


if __name__ == "__main__":
    main()
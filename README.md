# 🤖 AI-Powered GitHub Workflows

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen)](https://github.com/ctemple/test_action)

基于 **Claude Code CLI + DeepSeek** 的 GitHub Actions 全自动 AI 工作流。Claude Code 直接读取 Issue、搜索代码、修改文件、创建 PR、审查代码——全部自主完成，无需 Python 脚本。

```
                    📝 Issue 创建
                         │
                         ▼
                    🏷️ AI Triage
                    (分类打标签)
                         │
                    ┌────┴────┐
                    ▼         ▼
               ❌ 不适合    ✅ 适合AI
               AI修复       ai-clarifying
                    │         │
                    │         ▼
                    │    💬 AI Clarify
                    │    (读Issue+代码)
                    │    (提问↔回答)
                    │         │
                    │    ┌────┴────┐
                    │    ▼         ▼
                    │  ❓不明确   ✅明确
                    │   (等待     ai-fix
                    │   回复)      │
                    │         ┌────┘
                    │         ▼
                    │    🔧 AI Auto-Fix
                    │    (写代码→自审→PR)
                    │         │
                    │         ▼
                    │    🔍 AI Code Review
                    │    (自动审查)
                    │         │
                    │    ┌────┴────┐
                    │    ▼         ▼
                    │  ✅ 通过   ❌ 不通过
                    │    │         │
                    │    │    🔧 AI Fix Review
                    │    │    (修复→推送)
                    │    │         │
                    │    └────┬────┘
                    │         │
                    └────┬────┘
                         │
                         └── ✅ Complete
```

---

## 🚀 快速开始

### 1. 配置 Secrets

仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret | 说明 | 示例值 |
|--------|------|--------|
| `ANTHROPIC_BASE_URL` | DeepSeek Anthropic 兼容端点 | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_AUTH_TOKEN` | DeepSeek API Key | `sk-xxxxxxxx` |
| `ANTHROPIC_MODEL` | 默认模型 | `deepseek-v4-pro[1m]` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | 轻量模型 | `deepseek-v4-flash` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | 强力模型 | `deepseek-v4-pro[1m]` |
| `CLAUDE_CODE_DISABLE_1M_CONTEXT` | 启用 1M 上下文 | `0` |
| `GH_PAT` | GitHub PAT | `github_pat_...` |

> **GH_PAT 权限**: `Contents: R/W` + `Pull requests: R/W` + `Issues: R/W`

### 2. 创建标签（可选）

```bash
gh label create ai-fix --color "7B68EE" --description "AI 自动修复"
gh label create P0 --color "FF0000" && gh label create P1 --color "FF6B6B"
gh label create P2 --color "FFA500" && gh label create P3 --color "4ECDC4"
```

### 3. 使用

创建一个 Issue → 打上 `ai-fix` 标签 → 等 30 秒 → PR 自动出现，AI 自动审查。

---

## 📋 五个工作流（按执行顺序）

### 1️⃣ 🏷️ AI Triage — 新 Issue → 自动分类

| 触发 | 说明 |
|------|------|
| 新 Issue 创建 | 自动运行 |

**执行流程**:
1. 读取 Issue 标题和内容
2. 分析类别（bug / enhancement / question / documentation）
3. 评估优先级（P0-P3）
4. 判断是否适合 AI 修复
5. 添加对应标签 → 适合的加 `ai-clarifying`，进入 Clarify

### 2️⃣ 💬 AI Clarify — 需求澄清，Auto-Coder 的前置关卡 🆕

| 触发 | 说明 |
|------|------|
| Issue 打 `ai-clarifying` 标签 | Triage 自动添加，进入澄清 |
| Issue 有真人回复 | 作者/Collaborator 回复后重新评估 |
| ❌ AI 自己评论 | 不触发（过滤 bot 和 `## ❓` `## ✅` 前缀） |

**执行流程**:
1. 读取完整 Issue + 所有历史评论（`gh issue view --comments`）
2. 读取项目中相关代码文件（`Read` / `Glob`）
3. 综合判断需求是否明确（做什么、在哪里、期望结果、技术可行性）
4. ❓ **不明确** → 评论 2-3 个具体问题 → 保持 `ai-clarifying` → **等待真人回复**
5. ✅ **明确** → 评论需求确认总结 → 移除 `ai-clarifying` → 添加 `ai-fix` → Auto-Coder 启动

> `/ai-fix` 指令可绕过 Clarify，直接触发 Auto-Coder（适合需求已明确的情况）

### 3️⃣ 🤖 AI Auto-Coder — Issue → 代码 → PR

| 触发 | 说明 |
|------|------|
| Issue 打 `ai-fix` 标签 | 自动（由 Clarify 确认后添加） |
| Issue 评论 `/ai-fix` | 仅协作者（直接触发，绕过 Clarify） |

Claude Code CLI 自主执行：
1. **需求检查** — 如果需求模糊，转 Clarify 澄清
2. `gh issue view` 读取 Issue
3. `Glob` / `Grep` 搜索代码库
4. `Read` 读取相关文件
5. `Edit` / `Write` 修改代码
6. `git diff` 自审变更（致命问题必须修复）
7. `git commit` + `git push` 推送
8. `gh pr create` 创建 PR
9. `gh issue comment` 回复链接

### 4️⃣ 🔍 AI Code Review — PR → 审查 → Review

| 触发 | 说明 |
|------|------|
| PR 创建/更新 | 自动 |
| PR 评论 `/ai-review` | 手动 |

审查维度：🐛 Bug · 🔒 安全 · ⚡ 性能 · 📐 风格 · 🧪 测试 · 📖 文档

### 5️⃣ 🔧 AI Fix Review — 不通过 → 修复 → 重新审查

| 触发 | 说明 |
|------|------|
| AI Review REQUEST_CHANGES | 自动 |
| PR 评论 `/ai-fix-review` | 手动 |

最多自动修复 2 轮，防止死循环。仅修复 CRITICAL 和 HIGH 级别问题。

---

## ⚙️ 工作原理

```
Claude Code CLI (DeepSeek 兼容端点)
    │
    ├── 📖 Read     读取文件内容
    ├── ✏️ Edit     精确替换代码
    ├── 📝 Write    创建新文件
    ├── 🔍 Glob     文件搜索
    ├── 🔎 Grep     内容搜索
    └── 💻 Bash     执行 git / gh 命令
```

每个 workflow 给 Claude Code 一个详细的 prompt，Claude Code 自主规划并调用上述工具完成任务。不需要预写 Python 脚本逻辑——AI 根据实际情况灵活决策。

---

## 📁 项目结构

```
.
├── .github/
│   └── workflows/
│       ├── ai-issue-triage.yml         # 1️⃣ AI Triage
│       ├── ai-clarify.yml              # 2️⃣ AI Clarify
│       ├── ai-auto-coder.yml           # 3️⃣ AI Auto-Coder
│       ├── ai-code-review.yml          # 4️⃣ AI Code Review
│       └── ai-fix-review.yml           # 5️⃣ AI Fix Review
├── README.md
└── .gitignore
```

> Python 脚本 (`ai_client.py` 等) 保留在 `scripts/` 目录供本地参考，但 workflow 已不再使用。

---

## 🔒 安全设计

| 机制 | 说明 |
|------|------|
| 🔐 Secrets 隔离 | API Key 通过 GitHub Secrets 注入，日志不可见 |
| 👥 权限控制 | 仅协作者可用 `/ai-fix` `/ai-review` |
| 🔄 递归防护 | AI 不审查 AI 自己创建的 PR |
| 🤖 Bot 防护 | 跳过 bot 创建的 Issue/PR |
| 🛑 循环上限 | Fix Review 最多 2 轮 |

---

## 📄 License

MIT
# 🤖 AI-Powered GitHub Workflows

基于 **Claude Code CLI + DeepSeek** 的 GitHub Actions 全自动 AI 工作流。Claude Code 直接读取 Issue、搜索代码、修改文件、创建 PR、审查代码——全部自主完成，无需 Python 脚本。

```
                    📝 Issue 创建
                         │
                         ▼
                    🏷️ AI Triage
                    (自动分类)
                         │
                         ▼
                    💬 AI Clarify 🆕
                    (需求不明确→提问→明确→总结)
                         │
                         ▼
                    🔧 AI Auto-Fix
                    (写代码→自审→PR)
                         │
                         ▼
                    🔍 AI Code Review
                    (自动审查)
                         │
                    ┌────┴────┐
                    ▼         ▼
                  ✅ 通过   ❌ 不通过
                    │         │
                    │         ▼
                    │    🔧 AI Fix Review
                    │    (修复→推送)
                    │         │
                    └─────────┘
                         │
                         └── 审查→修复循环 ─┘
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

## 📋 五个工作流

### 💬 AI Clarify — 需求澄清 🆕

| 触发 | 说明 |
|------|------|
| Issue 打 `ai-clarifying` 标签 | 进入澄清模式 |
| Issue 有新评论（作者回复） | AI 重新评估需求 |

**执行流程**:
1. AI 读取 Issue 和所有评论
2. 评估需求是否明确（做什么、在哪里、期望结果）
3. ❓ **不明确** → 评论 2-3 个具体问题 → 保持 `ai-clarifying` 标签
4. ✅ **明确** → 评论需求确认总结 → 移除 `ai-clarifying` → 添加 `ai-fix` → 进入 Auto-Fix

### 🤖 AI Auto-Fix — Issue → 代码 → PR

| 触发 | 说明 |
|------|------|
| Issue 打 `ai-fix` 标签 | 自动 |
| Issue 评论 `/ai-fix` | 仅协作者 |

Claude Code CLI 自主执行：
1. `gh issue view` 读取 Issue
2. `Glob` / `Grep` 搜索代码库
3. `Read` 读取相关文件
4. `Edit` / `Write` 修改代码
5. `git diff` 自审变更
6. `git commit` + `git push` 推送
7. `gh pr create` 创建 PR
8. `gh issue comment` 回复链接

### 🔍 AI Code Review — PR → 审查 → Review

| 触发 | 说明 |
|------|------|
| PR 创建/更新 | 自动 |
| PR 评论 `/ai-review` | 手动 |

审查维度：🐛 Bug · 🔒 安全 · ⚡ 性能 · 📐 风格 · 🧪 测试 · 📖 文档

### 🔧 AI Fix Review — 不通过 → 修复 → 重新审查

| 触发 | 说明 |
|------|------|
| AI Review REQUEST_CHANGES | 自动 |
| PR 评论 `/ai-fix-review` | 手动 |

最多自动修复 2 轮，防止死循环。仅修复 CRITICAL 和 HIGH 级别问题。

### 🏷️ AI Triage — 新 Issue → 自动分类

新 Issue 创建时自动运行：分析类别 → 评估优先级 → 添加标签 → 自动回复。

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
│       ├── ai-auto-fix.yml             # AI 自动修复
│       ├── ai-code-review.yml          # AI 代码审查
│       ├── ai-fix-review.yml           # AI 修复审查意见
│       └── ai-issue-triage.yml         # AI 自动分类
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
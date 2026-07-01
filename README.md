# 🤖 AI-Powered GitHub Workflows

基于 **Claude / DeepSeek / OpenAI** 的 GitHub Actions AI 自动化工作流，实现 AI 写代码、AI 审代码的全自动闭环。

[![AI Auto-Fix](https://github.com/ctemple/test_action/actions/workflows/ai-auto-fix.yml/badge.svg)](https://github.com/ctemple/test_action/actions/workflows/ai-auto-fix.yml)
[![AI Code Review](https://github.com/ctemple/test_action/actions/workflows/ai-code-review.yml/badge.svg)](https://github.com/ctemple/test_action/actions/workflows/ai-code-review.yml)
[![AI Triage](https://github.com/ctemple/test_action/actions/workflows/ai-issue-triage.yml/badge.svg)](https://github.com/ctemple/test_action/actions/workflows/ai-issue-triage.yml)

```
                    📝 Issue 创建
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       🏷️ AI Triage  🔧 AI Auto-Fix  🔍 AI Code Review
       (自动分类)    (写代码→PR)    (审查PR代码)
                         │                 │
                         ▼                 │
                   📥 Pull Request         │
                         │                 │
                         ▼                 │
                   🔍 AI Review           │
                   (自动审查)             │
                         │                 │
                    ┌────┴────┐            │
                    ▼         ▼            │
                  ✅ 通过   ❌ 不通过      │
                    │         │            │
                    │         ▼            │
                    │    🔧 AI Fix Review  │
                    │    (修复→推送)       │
                    │         │            │
                    └─────────┘            │
                         │                 │
                         └───── 循环 ──────┘
```

---

## 🔌 多 Provider 支持

| Provider | Secret | 默认模型 | 费用 |
|----------|--------|----------|------|
| **DeepSeek** ⭐ | `DEEPSEEK_API_KEY` | `deepseek-chat` | 💰 ~¥0.02/次 |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | ~$0.20/次 |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` | 中等 |

> 设置任意一个即可，脚本自动检测。推荐 DeepSeek：性价比极高，成本仅为 Claude 的 1/10。

---

## 🚀 快速开始

### 1. 配置 Secrets

在仓库 **Settings → Secrets and variables → Actions → New repository secret** 添加：

| Secret | 说明 | 必需 |
|--------|------|:---:|
| `DEEPSEEK_API_KEY` | [DeepSeek API Key](https://platform.deepseek.com/) | ⭐ 推荐 |
| `GH_PAT` | Personal Access Token（Fine-grained） | ✅ 必需 |

<details>
<summary><b>GH_PAT 权限配置（点击展开）</b></summary>

去 https://github.com/settings/tokens → **Fine-grained tokens** → 选仓库，勾选：

- ✅ `Contents: Read and write`（创建分支、提交代码）
- ✅ `Pull requests: Read and write`（创建 PR、提交 Review）
- ✅ `Issues: Read and write`（在 Issue 下回复 PR 链接）

> **为什么需要 PAT？** 默认 `GITHUB_TOKEN` 创建的 PR 需要手动审批才能跑 CI/Review workflow。用 PAT 后 PR 以你的身份创建，所有 downstream workflow 自动触发，无需人工干预。
</details>

### 2. 创建标签（可选，推荐）

```bash
gh label create P0 --color "FF0000" --description "最高优先级"
gh label create P1 --color "FF6B6B" --description "高优先级"
gh label create P2 --color "FFA500" --description "中等优先级"
gh label create P3 --color "4ECDC4" --description "低优先级"
gh label create ai-fix --color "7B68EE" --description "AI 自动修复"
gh label create ai-in-progress --color "9370DB" --description "AI 正在修复"
```

### 3. 开跑！

创建一个 Issue，打上 `ai-fix` 标签，等待 30 秒 → PR 自动出现 → AI 自动审查。

---

## 📋 四个工作流

### 🤖 AI Auto-Fix — Issue → 代码 → PR

| 触发方式 | 说明 |
|----------|------|
| Issue 打 `ai-fix` 标签 | 自动触发 |
| Issue 评论 `/ai-fix` | 仅 OWNER/MEMBER/COLLABORATOR |

**执行流程**:
1. 读取 Issue 标题和内容
2. 扫描仓库结构，收集上下文
3. AI 分析问题，定位需要修改的文件
4. 创建分支 `ai/fix-issue-{编号}`
5. 写入代码变更，提交 commit
6. Push 并创建 Pull Request
7. 在 Issue 中回复 PR 链接

### 🔍 AI Code Review — PR → 审查 → Review

| 触发方式 | 说明 |
|----------|------|
| PR 创建/更新 | 自动触发 |
| PR 评论 `/ai-review` | 手动触发 |

**审查维度**:
- 🐛 Bug / 逻辑错误
- 🔒 安全漏洞
- ⚡ 性能问题
- 📐 代码风格 / 最佳实践
- 🧪 测试覆盖建议
- 📖 文档 / 注释完整性

### 🔧 AI Fix Review — 审查不通过 → 自动修复 → 重新审查 🆕

| 触发方式 | 说明 |
|----------|------|
| AI Review 提交 CHANGES_REQUESTED | 自动触发 |
| PR 评论 `/ai-fix-review` | 手动触发 |

**执行流程**:
1. AI Code Review 发现严重问题（CRITICAL/HIGH）→ REQUEST_CHANGES
2. 此 workflow 自动触发，读取审查意见
3. AI 修复 CRITICAL 和 HIGH 级别的问题
4. 推送新 commit 到同一分支
5. PR 同步事件触发新一轮 AI Code Review
6. 循环直到通过 ✅ 或达到 2 轮上限

**安全机制**:
- 🔄 最多自动修复 2 轮，防止死循环
- 🎯 仅修复 CRITICAL 和 HIGH 级别问题
- 🤖 仅响应 AI 自己的 Review（人类审查意见不触发）

### 🏷️ AI Triage — 新 Issue → 自动分类

新 Issue 创建时自动运行：
- 分析类别（bug / enhancement / question / documentation）
- 评估优先级（P0-P3）
- 自动添加标签
- 如果适合 AI 修复，自动添加 `ai-fix` 标签

---

## 📁 项目结构

```
.
├── cli.py                              # 🖥️  CLI 入口（本地测试 AI 工作流）
├── Makefile                            # 🔧 常用命令（check / test / clean）
├── pyproject.toml                      # 📦 项目配置
├── README.md
├── .gitignore
└── .github/
    ├── workflows/
    │   ├── ai-auto-fix.yml             # AI 自动修复
    │   ├── ai-code-review.yml          # AI 代码审查
    │   ├── ai-fix-review.yml           # 🆕 AI 修复审查意见（闭环）
    │   └── ai-issue-triage.yml         # AI 自动分类
    ├── scripts/
    │   ├── ai_client.py                # 🌐 统一 AI Provider（Anthropic/DeepSeek/OpenAI）
    │   ├── ai_fix_issue.py             # AI 修复核心逻辑
    │   ├── ai_review_pr.py             # AI 审查核心逻辑
    │   ├── ai_fix_review.py            # 🆕 AI 修复审查意见核心逻辑
    │   └── ai_triage_issue.py          # AI 分类核心逻辑
    ├── ISSUE_TEMPLATE/
    │   └── ai_bug_fix.yml              # Bug 修复 Issue 模板
    └── PULL_REQUEST_TEMPLATE.md        # PR 模板
```

---

## ⚙️ 配置选项

### 修改 AI Provider / 模型

在 workflow 的 `env` 中添加：

```yaml
env:
  AI_PROVIDER: "deepseek"                # 强制指定 Provider
  AI_MODEL_FIX: "deepseek-reasoner"      # 复杂任务用推理模型
  AI_MODEL_REVIEW: "deepseek-chat"
  DEEPSEEK_BASE_URL: "https://api.deepseek.com"
```

### 可用模型

| Provider | 模型 | 适用场景 |
|----------|------|----------|
| **DeepSeek** | `deepseek-chat` | 通用代码任务，默认推荐 |
| | `deepseek-reasoner` | 推理增强，复杂 Bug |
| **Anthropic** | `claude-sonnet-4-6` | 综合性价比 |
| | `claude-opus-4-8` | 最强大，复杂架构 |
| | `claude-haiku-4-5` | 快速轻量，分类 |
| **OpenAI** | `gpt-4o` | 多模态 |
| | `gpt-4o-mini` | 快速便宜 |

### 调试模式

```yaml
env:
  DRY_RUN: "true"                        # 只输出计划，不实际改代码
  REQUEST_CHANGES_ON_ISSUES: "false"     # Review 始终以 Comment 方式
```

---

## 💰 成本估算

| 工作流 | DeepSeek (¥) | Claude ($) |
|--------|:-----------:|:----------:|
| AI Auto-Fix | ~0.02 | ~0.20 |
| AI Code Review | ~0.04 | ~0.40 |
| AI Triage | ~0.005 | ~0.03 |

> DeepSeek 成本约为 Claude 的 1/10，每月处理 100 个 Issue 约 ¥2-5。

---

## 🧪 本地测试

```bash
# CLI 工具
python cli.py                # 显示项目信息和可用命令
python cli.py info           # 显示 AI Provider 详细信息
python cli.py check          # 检查 API Key 配置

# Make 命令
make check                   # 检查 Python 环境和依赖
make test                    # 运行脚本语法检查
make clean                   # 清理缓存

# 使用 DeepSeek 测试
export DEEPSEEK_API_KEY="sk-..."
export GITHUB_TOKEN="ghp_..."
export GITHUB_REPOSITORY="owner/repo"
export ISSUE_NUMBER="1"
export DRY_RUN="true"
python .github/scripts/ai_fix_issue.py

# AI Client 自检
python .github/scripts/ai_client.py
```

---

## 🔒 安全设计

| 机制 | 说明 |
|------|------|
| 🔐 Secrets 隔离 | API Key 存储在 GitHub Secrets，日志中不可见 |
| 👥 权限控制 | `/ai-fix` 和 `/ai-review` 仅仓库协作者可用 |
| 🔄 递归防护 | AI 不审查 AI 自己创建的 PR |
| 🤖 Bot 防护 | 跳过 bot 创建的 Issue/PR |
| 👀 人工兜底 | AI 生成的代码仅供审核，建议人工复核后合并 |

---

## 📝 Roadmap

- [x] AI 自动修复 Issue → PR
- [x] AI 自动代码审查（无需审批）
- [x] AI 审查→修复→审查 闭环 🆕
- [x] AI 自动 Issue 分类
- [x] 多 Provider 支持（DeepSeek / Claude / OpenAI）
- [x] CLI 本地调试工具
- [ ] 支持图片/截图分析（多模态）
- [ ] AI Review 评分仪表盘
- [ ] CODEOWNERS 智能 @ 提醒

---

## 📄 License

MIT
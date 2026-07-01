# 🤖 AI-Powered GitHub Workflows

基于 **Claude API** 的 GitHub Actions AI 自动化工作流：Issue 自动修复、PR 代码审查、Issue 智能分类。

## 📋 工作流概览

| 工作流 | 触发方式 | 功能 |
|--------|----------|------|
| 🤖 **AI Auto-Fix** | Issue 打 `ai-fix` 标签 / 评论 `/ai-fix` | AI 分析 Issue → 修改代码 → 创建 PR |
| 🔍 **AI Code Review** | PR 创建/更新 / 评论 `/ai-review` | AI 审查 PR diff → 提交 Review |
| 🏷️ **AI Triage** | 新 Issue 创建 | AI 分析内容 → 自动打标签 |

## 🚀 快速开始

### 1. 配置 Secrets

在仓库 **Settings → Secrets and variables → Actions** 中添加：

| Secret | 说明 | 必需 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | ✅ 是 |
| `GH_PAT` | 有 `contents:write` 和 `pull-requests:write` 权限的 Personal Access Token | 推荐 |

> **为什么需要 `GH_PAT`？**  
> 默认的 `GITHUB_TOKEN` 创建的 PR 不会触发其他 workflow（如 CI 检查）。使用 PAT 创建的 PR 可以触发完整的 CI 流程。  
> 获取 PAT: [GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens](https://github.com/settings/tokens)

### 2. 创建标签（可选但推荐）

为了让 AI Triage 工作得更好，建议预创建以下标签：

```bash
gh label create P0 --color "FF0000" --description "最高优先级 - 关键问题"
gh label create P1 --color "FF6B6B" --description "高优先级"
gh label create P2 --color "FFA500" --description "中等优先级"
gh label create P3 --color "4ECDC4" --description "低优先级"
gh label create ai-fix --color "7B68EE" --description "AI 自动修复"
gh label create ai-in-progress --color "9370DB" --description "AI 正在修复中"
```

### 3. 使用

#### 🤖 AI 自动修复 Issue

**方法一：标签触发**
1. 创建一个 Issue（或使用 `Bug Report (AI Fixable)` 模板）
2. 给 Issue 添加 `ai-fix` 标签
3. AI 工作流自动启动，约 2-5 分钟后生成 PR

**方法二：评论触发**
1. 在 Issue 下评论 `/ai-fix`
2. AI 工作流启动

**结果：** AI 会：
- 分析 Issue 内容和代码库
- 创建分支 `ai/fix-issue-{编号}`
- 修改相关代码
- 提交 Commit 和创建 PR
- 在 Issue 中回复 PR 链接

#### 🔍 AI 自动代码审查

**自动触发：**
- 任何 PR 创建或新提交推送时，AI 自动审查

**手动触发：**
- 在 PR 评论中输入 `/ai-review`

**审查输出：**
- 🐛 Bug / 逻辑错误
- 🔒 安全漏洞
- ⚡ 性能问题
- 📐 代码风格 / 最佳实践
- 🧪 测试覆盖建议
- 📖 文档 / 注释完整性

#### 🏷️ AI 自动分类

新 Issue 创建时自动运行，无需手动触发。AI 会：
- 分析 Issue 类别（bug / enhancement / question...）
- 评估优先级（P0-P3）
- 添加对应标签
- 如果适合 AI 修复，自动添加 `ai-fix` 标签
- 给出自动回复建议

## 📁 文件结构

```
.github/
├── workflows/
│   ├── ai-auto-fix.yml              # AI 自动修复 workflow
│   ├── ai-code-review.yml           # AI 代码审查 workflow
│   └── ai-issue-triage.yml          # AI 自动分类 workflow
├── scripts/
│   ├── ai_fix_issue.py              # AI 修复 Issue 核心脚本
│   ├── ai_review_pr.py              # AI 审查 PR 核心脚本
│   └── ai_triage_issue.py           # AI 分类 Issue 核心脚本
├── ISSUE_TEMPLATE/
│   └── ai_bug_fix.yml               # AI 修复 Bug Issue 模板
└── PULL_REQUEST_TEMPLATE.md          # PR 模板
```

## ⚙️ 配置选项

### 修改 AI 模型

在对应的 Python 脚本中修改 `CLAUDE_MODEL` 变量：

```python
# ai_fix_issue.py / ai_review_pr.py
CLAUDE_MODEL = "claude-sonnet-4-6"     # 推荐 (性价比最佳)

# ai_triage_issue.py
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # 分类用轻量模型
```

可选模型：
- `claude-opus-4-8` — 最强大，适合复杂任务
- `claude-sonnet-4-6` — 推荐，性价比最佳
- `claude-haiku-4-5-20251001` — 快速轻量，适合分类

### 启用 DRY-RUN 模式（调试用）

在 workflow 中添加环境变量：

```yaml
env:
  DRY_RUN: "true"
```

此时 AI 会输出修复计划但不实际修改代码。

### 调整 AI Review 严格度

```yaml
env:
  REQUEST_CHANGES_ON_ISSUES: "false"  # 始终以 Comment 方式审查，不阻止合并
```

## 💰 成本估算

| 工作流 | 模型 | 单次预估 Token | 单次预估成本 |
|--------|------|---------------|-------------|
| AI Auto-Fix | Sonnet | ~5K-20K | ~$0.10-0.40 |
| AI Code Review | Sonnet | ~10K-30K | ~$0.20-0.60 |
| AI Triage | Haiku | ~2K-5K | ~$0.01-0.05 |

*实际成本取决于 Issue/PR 的复杂度和代码库大小。*

## 🔒 安全注意事项

1. **API Key 安全**: `ANTHROPIC_API_KEY` 存储在 GitHub Secrets，不会暴露
2. **代码审查**: AI 生成和修改的代码仅供参考，建议人工复核后合并
3. **权限控制**: 只有仓库协作者（OWNER/MEMBER/COLLABORATOR）可以使用 `/ai-fix` 和 `/ai-review` 指令
4. **递归防护**: AI 不会审查 AI 自己创建的 PR，避免循环
5. **Bot 防护**: 跳过 bot 创建的 Issue/PR，避免死循环

## 🧪 本地测试

```bash
# 测试 AI Fix 脚本
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."
export GITHUB_REPOSITORY="owner/repo"
export ISSUE_NUMBER="1"
export DRY_RUN="true"  # 仅查看计划，不实际修改

python .github/scripts/ai_fix_issue.py

# 测试 AI Review 脚本
export PR_NUMBER="1"
python .github/scripts/ai_review_pr.py
```

## 📝 工作计划

- [x] AI 自动修复 Issue → PR
- [x] AI 自动代码审查
- [x] AI 自动 Issue 分类
- [ ] 支持图片/截图分析（多模态）
- [ ] 支持自然语言描述需求生成代码
- [ ] AI Review 评分系统 + 仪表盘
- [ ] 支持基于 CODEOWNERS 的智能 @ 提醒

## 📄 License

MIT
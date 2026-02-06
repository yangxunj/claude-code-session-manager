[English](README.md) | **中文**

# Claude Code 会话管理器

一个用于将 Claude Code 会话作为可复用领域专家进行管理的 Skill。无需每次从零开始，已积累深度上下文的会话会被记录下来，在相关工作出现时可以随时恢复。

## 安装

```bash
npx skills add yangxunj/claude-code-session-manager
```

## 功能概述

- **路由 (Route)**：当用户提出变更请求时，自动检查是否已有会话专家负责该领域，并推荐恢复该会话
- **注册 (Register)**：让会话自我评估并注册为领域专家，支持重叠度检测
- **激活 (Activate)**：将过期会话重新带回 Claude Code 的可恢复窗口（最近约 10 个）
- **初始化 (Initialize)**：为新项目搭建会话管理体系，包含模板和工具
- **维护 (Maintain)**：通过粒度准则保持会话文档的健康状态

## 工作原理

Claude Code 仅允许恢复最近约 10 个会话，但所有聊天数据都永久存储在磁盘上。本 Skill 提供：

1. **两层文档体系** — 轻量级索引文件（标签、页面树、文件路径索引）用于快速路由，详情文件用于功能领域描述
2. **激活脚本** — Python CLI 工具，通过修改时间戳将旧会话带回可恢复窗口
3. **自注册提示词** — 会话自我评估是否应注册为专家的模板（含 >60% 重叠度检测）
4. **CLAUDE.md 集成** — 指示 AI 在处理请求前先检查会话专家的配置片段

## 文件说明

| 文件 | 用途 |
|------|------|
| `SKILL.md` | 主要 Skill 指令，包含 5 个工作流 |
| `scripts/claude-session.py` | 会话管理 CLI（列表 / 激活） |
| `references/registration-prompt.md` | 自注册提示词模板 |
| `assets/template-index.md` | 索引文件模板 |
| `assets/template-details.md` | 详情文件模板 |
| `assets/template-claude-md-snippet.md` | CLAUDE.md 集成片段 |

## 环境要求

- Python 3.6+
- Claude Code CLI
- 在 Windows 上如遇 Unicode 错误，请使用 `PYTHONUTF8=1` 前缀

## 许可证

MIT

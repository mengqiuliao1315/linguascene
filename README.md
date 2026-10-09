# LinguaScene

面向英语学习者的场景化练习平台。前端为中文界面，用户以中国学生为主。

## 在线访问

**https://forddream.icu/linguascene/**

登录即可使用。注意：**不开放自助注册**，账号由管理员统一开通。

## 功能

功能清单见 [项目功能说明.md](项目功能说明.md)——涵盖账号体系、场景对话、阅读器、单词本、游戏化、社交等模块，以及 AI 与语音能力说明。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 15.1.6（App Router）、React 19、TypeScript 5.7、Tailwind 3.4 |
| 后端 | FastAPI + SQLAlchemy、SQLite、uvicorn |
| AI 接入 | 自研 provider 抽象，支持 openai / openai_responses / anthropic / gemini |
| 语音 | 合成 edge-tts；识别支持用户自配模型与本地 faster-whisper 两条通道 |

## 目录结构

```
backend/     FastAPI 服务、AI Agent、数据库迁移（alembic）、测试
frontend/    Next.js 应用（basePath = /linguascene）
ai/prompts/  各 AI Agent 的提示词
```
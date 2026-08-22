# 资产先锋 · 不良资产尽调平台

信息聚合 + AI 尽调分析工具。平台不参与买卖、不做交易撮合，只做：**信息聚合展示** 和 **AI 尽调分析**（生成尽职调查报告）。

## 功能

- **三种输入**：粘贴文本 / 粘贴拍卖链接（淘宝司法拍卖）/ 上传 Excel 债权清单
- **AI 结构化提取**：DeepSeek 提取债权字段，完整度三级评估（🟢🟡🔴），多债务人自动拆分
- **预处理确认**：内联编辑、勾选最多 5 条、预估积分
- **尽调引擎**：工商/司法风险（免费官方源）→ 法律检索 → 抵押物估值 → 本息计算 → LLM 综合分析
- **9 版块报告**：投资决策摘要 / 重要提醒（21条规则引擎）/ 债权基本情况 / 债务人调查 / 担保人调查 / 抵押物分析 / 法律依据 / 风控评估 / 处置建议
- **PDF 报告**：正式文档风格（封面 + 目录 + 三线表），WeasyPrint 生成
- **我的任务**：任务保存、进度跟踪、报告回看

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + Vite + Ant Design 5（蓝色系） |
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 |
| 数据库 | SQLite（P0）→ PostgreSQL（P2） |
| LLM | DeepSeek API |
| PDF | WeasyPrint + Jinja2 |
| 部署 | Docker + Nginx + Certbot |

## 目录结构

```
zichanxianfeng/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── api/      # 路由（auth/claims/tasks/reports）
│   │   ├── models/   # ORM 模型（5表）
│   │   ├── schemas/  # Pydantic 模型
│   │   ├── services/ # 业务逻辑（提取/尽调/本息/规则/PDF/LLM）
│   │   ├── datasources/ # 数据源适配层（可插拔）
│   │   ├── scrapers/ # 页面抓取适配器
│   │   └── templates/   # PDF 模板
│   ├── tests/        # pytest 测试（35 用例）
│   └── alembic/      # 数据库迁移
├── frontend/         # React 前端
├── deploy/           # docker-compose / nginx / 部署脚本
└── docs/             # 设计文档
```

## 本地开发

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows（Linux: source .venv/bin/activate）
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                  # http://127.0.0.1:5173
```

详细说明见 [docs/本地运行说明.md](docs/本地运行说明.md)。

## 测试

```bash
cd backend
pytest tests/ -v
```

## 部署

见 [docs/P0开发环境准备指南.md](docs/P0开发环境准备指南.md) 和 `deploy/setup.sh`。

## 文档

- [详细设计文档](docs/资产先锋平台详细设计文档.md)（架构/数据库/API/页面/引擎/部署）
- [报告9版块JSONSchema](docs/报告9版块JSONSchema.md)
- [智能提醒规则库](docs/智能提醒规则库完整定义.md)
- [开发日志](docs/开发日志.md)

## 免责声明

本平台生成的报告基于公开信息和 AI 分析自动生成，仅供参考，不构成投资建议。估值不替代专业评估机构报告，投资决策请结合专业律师意见和实地尽调。

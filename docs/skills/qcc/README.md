# 企查查官方 SKILL 资产（归档）

> 来源：企查查官方 GitHub（duhu2000 = Qichacha/QCC 团队维护）· https://agent.qcc.com/skills
> 归档日期：2026-08-31 · 用途：尽调引擎工作流参考（存档备参）

## 内容

**7 个官方 SKILL 完整工作流**（SKILL.md：业务规则 + MCP 工具清单 + 报告输出格式）：
| 文件 | 技能 | 与我们的关联 |
|---|---|---|
| skill_kyb-verification-qcc.md | KYB 企业核验（先扫后钻/A-B-C-D评级/UBO穿透）| ⭐ 主体核验已借鉴落地（due_diligence _build_kyb_summary）|
| skill_credit-due-diligence-qcc.md | 授信尽调报告 | 尽调报告参考 |
| skill_dd-checklist-qcc.md | 尽调清单 | 报告版块清单参考 |
| skill_credit-rating-qcc.md | 信用评级 | 评级维度参考 |
| skill_equity-structure-qcc.md | 股权结构穿透 | 财产线索参考 |
| skill_executive-background-qcc.md | 高管背景核查 | 担保人/实控人尽调参考 |
| skill_history-evolution-qcc.md | 企业历史沿革 | 尽调深度参考 |

**3 个官方 Python 工具**：
| 文件 | 说明 |
|---|---|
| utils__qcc_mcp_client.py | 官方 MCP 客户端（HTTP POST + SSE + Bearer token + 重试）——我们现有 qcc.py McpClient 更完善，此件备参 |
| utils__kyb_verifier.py | KYB 核验器 |
| utils__dd_report_generator.py | 尽调报告生成器 |

## 关键工作流规范（已借鉴/可借鉴）

1. **先扫后钻**（省积分）：先 `get_company_risk_scan` 分诊 → 只对命中维度调明细工具 —— **我们已实现**
2. **主体核验**：企业名称×USCC 二要素 + 登记状态 + 法人 —— **已落地为报告"主体核验"区块**
3. **金额归一化原则**：罚没/败诉金额与营收或净资产比较，行为型红线不因规模豁免 —— 可借鉴
4. **year 留空拿全量**：诉讼类工具禁逐年循环（防 60+ 次冗余调用）—— 可借鉴

> ⚠️ **治理稳定性分析未采用**（2026-08-31 用户确认）：官方 KYB SKILL 含"治理稳定性"维度（法代/股东/注册资本/地址变更计分），但本平台尽调对象均为欠款多年、普遍治理混乱的不良债权债务人，该维度无区分度且浪费积分，已回退不实现。

## 完整 27 SKILL 清单
官方 SKILL 广场：https://agent.qcc.com/skills（银行 12 / 投资 6 / 法务 6 / 供应链 3）
SKILL.md 公开可抓（格式：https://agent.qcc.com/skill/v1/{banking|investment|legal|supplychain}/{skill-id}/SKILL.md）

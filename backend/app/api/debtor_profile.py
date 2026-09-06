# -*- coding: utf-8 -*-
"""债务人画像 API（2026-09-04 用户确认新增）

菜单名「债务人画像」，报告名「XXX企业速览」（正式命名，PDF 内不出现"债务人画像"）。
流程：登录用户输入企业全称 → 确认弹窗（前端）→ 本接口调 QCC 画像工作流（走共享工具缓存，
尽调/财产线索查过的维度零新增积分）→ 清洗为章节 → 生成 PDF 落盘 → 存 qcc_profiles →
摘要返回；历史记录可回看/下载。
自然人/非企业：名称启发式 + 企查查查无此名(name_warning)双重提示。
"""
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import get_settings
from ..database import SessionLocal
from ..models import QccProfile
from ..services.company_name_check import looks_like_abbrev, looks_like_person
from .deps import get_current_user
from ..models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["debtor-profile"])


# ---------- 数据清洗：qcc profile 结果 → 可渲染 sections ----------

def _data(res: dict) -> object:
    """biz 工具结果 data；失败/异常返回 None"""
    if not (res or {}).get("ok"):
        return None
    return res.get("data")


def _kv_of(d: dict, keys_map: dict) -> list:
    """从字典取键值对（keys_map: 企查查键 → 显示名）"""
    out = []
    for src, label in keys_map.items():
        v = (d or {}).get(src)
        if v is None or v == "":
            continue
        v = str(v).strip()
        if v:
            out.append([label, v])
    return out


def _first_list(d) -> list | None:
    """dict 里第一个 list 值（企查查常把列表放在某字段，如 股东信息）"""
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list) and v:
                return v
    return None


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:200]
    return str(v)


def _limit(text, n=400):
    t = str(text or "").strip()
    return t[:n] + ("…" if len(t) > n else "")


def _dim_note(res: dict, empty_txt: str, label: str = "") -> str | None:
    """维度空结果说明(2026-09-07 海尔年报事故修复):
    查询失败(ok=False, 如余额不足/接口异常) → 提示"未能获取", 不得误报为"企业没有";
    查询成功但无记录 → empty_txt(中性, 不武断定性, 建议以官方公示渠道核验)。"""
    if not res:
        return None
    if res.get("ok") is False:
        return f"{label}信息本次未能获取，建议稍后重试，或以官方公示渠道核验。" if label else \
            "本维度信息本次未能获取，建议稍后重试，或以官方公示渠道核验。"
    return empty_txt


def _build_sections(result: dict) -> list:
    biz = result.get("biz") or {}
    risk = result.get("risk") or {}
    renamed = result.get("renamed")
    company = result.get("search_name") or result.get("company") or ""

    sections = []

    # 一、企业基本信息
    reg = biz.get("get_company_registration_info") or {}
    reg_d = _data(reg) or {}
    kvs = _kv_of(reg_d, {
        "企业名称": "企业全称", "统一社会信用代码": "统一社会信用代码", "法定代表人": "法定代表人",
        "成立日期": "成立日期", "注册资本": "注册资本", "注册地址": "注册地址", "企业类型": "企业类型",
        "登记状态": "登记状态", "核准日期": "最近核准日期", "营业期限": "营业期限",
        "经营范围": "经营范围",
    })
    # 经营范围过长截断保留
    for kv in kvs:
        if kv[0] == "经营范围":
            kv[1] = _limit(kv[1], 500)
    sections.append({"h": "企业基本信息", "kvs": kvs,
                     "note": ("注：该企业可能已由「%s」更名为「%s」，以下数据按现名查询。"
                              % (renamed["old_name"], renamed["new_name"])) if renamed else None})

    # 二、股权结构与实际控制人（2026-09-04 按企查查真实返回结构清洗，避免 JSON 原文堆入单元格）
    sec2 = {"h": "股权结构与实际控制人", "kvs": [], "tables": []}
    act_d = _data(biz.get("get_actual_controller") or {}) or {}
    act_lst = act_d.get("实际控制人信息") if isinstance(act_d, dict) else act_d
    if isinstance(act_lst, list) and act_lst:
        it = act_lst[0]
        if isinstance(it, dict):
            sec2["kvs"].append(["实际控制人", _fmt(it.get("实际控制人名称") or it.get("名称") or it.get("姓名"))])
            for k, lab in (("直接持股比例", "直接持股比例"), ("表决权比例", "表决权比例"), ("间接持股比例", "间接持股比例")):
                if it.get(k):
                    sec2["kvs"].append([lab, _fmt(it[k])])
    elif act_d:
        sec2["kvs"].extend(_kv_of(act_d, {"实际控制人": "实际控制人", "摘要": "说明"}))

    ben_d = _data(biz.get("get_beneficial_owners") or {}) or {}
    ben_sum = ben_d.get("摘要") if isinstance(ben_d, dict) else None
    ben_lst = None
    if isinstance(ben_d, dict):
        inner = ben_d.get("受益所有人信息")
        if isinstance(inner, dict):
            ben_lst = inner.get("受益所有人")
        elif isinstance(inner, list):
            ben_lst = inner
    elif isinstance(ben_d, list):
        ben_lst = ben_d
    if isinstance(ben_lst, list) and ben_lst:
        it = ben_lst[0]
        if isinstance(it, dict):
            sec2["kvs"].append(["受益所有人", _fmt(it.get("受益所有人名称") or it.get("名称"))])
            typ = it.get("受益类型")
            if isinstance(typ, list):
                typ = "、".join(str(x) for x in typ)
            for k, lab in (("受益类型", "受益类型"), ("最终受益股份", "最终受益股份"),
                           ("表决权比例", "表决权比例"), ("任职类型", "任职类型"),
                           ("受益所有权形成日期", "受益形成日期")):
                if it.get(k):
                    sec2["kvs"].append([lab, _fmt(typ if k == "受益类型" else it[k])])
    if ben_sum and not any(kv[0] == "受益所有人" for kv in sec2["kvs"]):
        sec2["kvs"].append(["受益所有人", ben_sum])

    sh = _data(biz.get("get_shareholder_info") or {}) or {}
    sh_rows = []
    sh_lst = sh.get("股东信息") if isinstance(sh, dict) else sh
    if not isinstance(sh_lst, list):
        sh_lst = _first_list(sh) or []
    for it in sh_lst:
        if isinstance(it, dict):
            sh_rows.append([_fmt(it.get("股东名称") or it.get("名称")),
                            _fmt(it.get("持股比例")),
                            _fmt(it.get("认缴出资额")),
                            _fmt(it.get("认缴出资日期"))])
    if sh_rows:
        sec2["tables"].append({"headers": ["股东名称", "持股比例", "认缴出资额", "认缴出资日期"], "rows": sh_rows[:30]})
    if not sec2["kvs"] and not sh_rows:
        sec2["note"] = _dim_note(biz.get("get_shareholder_info"),
                                 "未检索到公示的股权结构信息（该主体股东或未公示，以工商登记为准）。", "股权结构")
    sections.append(sec2)

    # 三、主要人员
    per_res = biz.get("get_key_personnel") or {}
    per = _data(per_res)
    per_rows = []
    for it in (_first_list(per) or []):
        if isinstance(it, dict):
            per_rows.append([_fmt(it.get("姓名") or it.get("name")),
                             _fmt(it.get("职务") or it.get("职位"))])
    per_note = None
    if not per_rows:
        if per_res.get("ok") is False:
            per_note = _dim_note(per_res, "", "主要人员")
        elif per is not None:
            # 查询成功但该主体无董监高公示数据(老主体/股份制集团常见) → 中性提示, 不武断
            per_note = "未检索到该主体公示的主要人员（董监高）备案信息，建议以工商登记或官方公示渠道核验。"
    sections.append({"h": "主要人员",
                     "tables": [{"headers": ["姓名", "职务"], "rows": per_rows[:40]}] if per_rows else [],
                     "note": per_note})

    # 四、对外投资与分支机构
    sec4 = {"h": "对外投资与分支机构", "kvs": [], "tables": []}
    inv = _data(biz.get("get_external_investments") or {})
    inv_rows = []
    for it in (_first_list(inv) or []):
        if isinstance(it, dict):
            inv_rows.append([_fmt(it.get("被投资企业名称") or it.get("企业名称") or it.get("名称")),
                             _fmt(it.get("投资比例") or it.get("持股比例")),
                             _fmt(it.get("投资金额") or it.get("认缴出资额")),
                             _fmt(it.get("状态") or it.get("登记状态"))])
    if inv_rows:
        sec4["tables"].append({"headers": ["对外投资企业", "投资比例", "投资金额", "状态"], "rows": inv_rows[:40]})
    br = _data(biz.get("get_branches") or {})
    br_rows = []
    for it in (_first_list(br) or []):
        if isinstance(it, dict):
            br_rows.append([_fmt(it.get("分支机构名称") or it.get("企业名称") or it.get("名称")),
                            _fmt(it.get("负责人") or it.get("法定代表人")),
                            _fmt(it.get("登记状态") or it.get("状态"))])
    if br_rows:
        sec4["tables"].append({"headers": ["分支机构", "负责人", "状态"], "rows": br_rows[:40]})
    if not inv_rows and not br_rows:
        sec4["note"] = _dim_note(biz.get("get_external_investments"),
                                 "未检索到对外投资或分支机构记录。", "对外投资/分支")
    sections.append(sec4)

    # 五、经营与财务（年报；2026-09-06 重构：砍 get_financial_data——一般企业财务库无记录，
    # 年报财务企业普遍"选择不公示"；用 annual_reports 展示 存在性/发布日期/社保/出资/联系，
    # 财务数字有公示才填表，否则明确提示"财务未公示"）
    sec5 = {"h": "经营与财务", "kvs": [], "tables": []}
    ar = _data(biz.get("get_annual_reports") or {})
    ar_list = _first_list(ar) or []
    if ar_list:
        # 最近年报（列表第一条通常为最新；再按 年报年度 文本倒排稳妥）
        def _year_no(it: dict) -> str:
            y = str(it.get("年报年度") or it.get("年度") or "")
            m = re.search(r"(\d{4})", y)
            return m.group(1) if m else "0"

        latest = max(ar_list, key=_year_no) if ar_list else ar_list[0]
        year_label = str(latest.get("年报年度") or latest.get("年度") or "")
        pub = str(latest.get("发布日期") or "")
        basic = latest.get("企业基本信息") or {}
        asset = latest.get("企业资产状况信息") or {}
        social = latest.get("社保信息") or {}
        shares = latest.get("股东（发起人）及出资信息") or []

        # 财务数字：年报资产状况公示才填表；不公示则 kvs 明示
        def _fin(v):
            s = str(v or "").strip()
            return "" if (not s or "不公示" in s or "未公示" in s) else s

        fin_vals = {"资产总额": _fin(asset.get("资产总额")),
                    "所有者权益": _fin(asset.get("所有者权益合计")),
                    "营业总收入": _fin(asset.get("营业总收入")),
                    "净利润": _fin(asset.get("净利润")),
                    "负债总额": _fin(asset.get("负债总额"))}
        has_fin = any(fin_vals.values())
        sec5["kvs"].append(["最近年报", year_label + (f"（{pub}发布）" if pub else "")])
        # 年报总数：接口摘要优先（"该查询实体共有13条企业年报记录"，列表仅展示前3条）
        total_txt = str(ar.get("摘要") or "")
        total_no = re.search(r"(?:共|共有)\s*(\d+)\s*条", total_txt)
        sec5["kvs"].append(["年报记录", f"共 {total_no.group(1) if total_no else len(ar_list)} 条已公布年报" +
                            ("" if total_no else "（仅展示前几条）")])
        if not has_fin:
            sec5["kvs"].append(["财务数据", "企业选择不公示（一般企业年报财务多不公开，属常见情况）"])
        # 社保人数（各险种；0人=无在缴员工，空壳/停业信号）
        social_rows = []
        for k in ("城镇职工基本养老保险", "职工基本医疗保险", "失业保险", "工伤保险", "生育保险"):
            v = str(social.get(k) or "").strip()
            if v and "不公示" not in v:
                social_rows.append([k, v])
        if social_rows:
            sec5["tables"].append({"headers": ["社保险种", "参保人数"], "rows": social_rows})
        # 股东实缴出资（年报口径；股东接口已有认缴/实缴，这里仅在有值且股东节未覆盖时展示）
        share_rows = []
        for sh in shares:
            if isinstance(sh, dict):
                share_rows.append([str(sh.get("股东名称") or ""),
                                   str(sh.get("认缴出资额(万元)") or sh.get("认缴出资额") or ""),
                                   str(sh.get("实缴出资额(万元)") or sh.get("实缴出资额") or "")])
        if share_rows:
            sec5["tables"].append({"headers": ["股东", "认缴出资(万元)", "实缴出资(万元)"], "rows": share_rows})
        # 年报联系方式/主营（工商登记无电话/邮箱/主营，年报是最可靠来源）
        contact = []
        if basic.get("企业联系电话"):
            contact.append(["联系电话", str(basic["企业联系电话"])])
        if basic.get("电子邮箱"):
            contact.append(["电子邮箱", str(basic["电子邮箱"])])
        if basic.get("企业通信地址"):
            contact.append(["通信地址", str(basic["企业通信地址"])])
        if basic.get("企业主营业务活动"):
            contact.append(["主营业务", str(basic["企业主营业务活动"])[:400]])
        if contact:
            sec5["tables"].append({"headers": ["项", "内容"], "rows": contact})
        if has_fin:
            sec5["tables"].append({"headers": ["年度", "资产总额", "负债总额", "营业总收入", "净利润"],
                                   "rows": [fin_vals.get("资产总额") or "—",
                                            fin_vals.get("负债总额") or "—",
                                            fin_vals.get("营业总收入") or "—",
                                            fin_vals.get("净利润") or "—"]})
    else:
        # 2026-09-07 修复: 查询失败(如余额不足)不得误报"企业未按时报送"; 成功无记录才给中性说明
        sec5["note"] = _dim_note(biz.get("get_annual_reports"),
                                 "未检索到已公示的企业年报记录（不同查询渠道同步情况不一，"
                                 "建议以国家企业信用信息公示系统 www.gsxt.gov.cn 披露为准）。", "企业年报")
    sections.append(sec5)

    # 七、司法与合规风险（只扫不钻 2026-09-04：risk_scan 命中清单；示例仅复用缓存已有明细，零积分）
    sec7 = {"h": "司法与合规风险", "kvs": [], "tables": []}
    hits = risk.get("hits") or []
    if not hits:
        sec7["kvs"].append(["风险记录", "经全维度扫描，未发现失信/被执行/限高/终本/冻结/涉诉等记录。"])
    else:
        rows = []
        any_sample = any(h.get("sample") for h in hits)
        for h in hits:
            row = [h.get("label") or "", str(h.get("count") or 0)]
            if any_sample:
                row.append(h.get("sample") or "—")
            rows.append(row)
        headers = ["风险维度", "记录数"] + (["示例"] if any_sample else [])
        if rows:
            sec7["tables"].append({"headers": headers, "rows": rows[:40]})
    sections.append(sec7)

    # 八、历史变更（2026-09-04 用户确认重要维度；按真实返回：变更项目/变更前内容(list)/变更后内容(list)）
    chg_res = biz.get("get_change_records") or {}
    chg = _data(chg_res)
    chg_rows = []
    for it in (_first_list(chg) or []):
        if isinstance(it, dict):
            def _j(v, n=160):
                if isinstance(v, list):
                    return _limit("；".join(str(x) for x in v if x != ""), n)
                return _limit(_fmt(v), n)
            chg_rows.append([_fmt(it.get("变更日期") or it.get("变更时间") or it.get("日期")),
                             _fmt(it.get("变更项目") or it.get("变更事项") or it.get("项目")),
                             _j(it.get("变更前内容") or it.get("变更前")),
                             _j(it.get("变更后内容") or it.get("变更后"))])
    chg_note = None
    if not chg_rows:
        if chg_res.get("ok") is False:
            chg_note = _dim_note(chg_res, "", "工商变更")
        elif chg is not None:
            chg_note = "未检索到工商变更记录（该主体或长期无变更）。"
    sections.append({"h": "历史变更", "tables": [{"headers": ["变更日期", "变更事项", "变更前", "变更后"],
                                                 "rows": chg_rows[:40]}] if chg_rows else [],
                     "note": chg_note})

    return sections


# ---------- API ----------

class ProfileQueryRequest(BaseModel):
    company: str


def _summary_of(result: dict) -> dict:
    """给前端的摘要卡片：企业/法人/状态/风险概况"""
    biz = result.get("biz") or {}
    reg_d = _data(biz.get("get_company_registration_info") or {}) or {}
    risk = result.get("risk") or {}
    hits = risk.get("hits") or []
    return {
        "company": result.get("company") or "",
        "search_name": result.get("search_name") or "",
        "legal_person": reg_d.get("法定代表人") or "—",
        "status": reg_d.get("登记状态") or "—",
        "credit_code": reg_d.get("统一社会信用代码") or "—",
        "established": reg_d.get("成立日期") or "—",
        "capital": reg_d.get("注册资本") or "—",
        "risk_breakdown": [{"label": h.get("label") or "", "count": h.get("count") or 0}
                           for h in hits][:8],
        "shareholder_count": len(_first_list(_data(biz.get("get_shareholder_info") or {})) or []) or 0,
    }


@router.post("/debtor-profile/query", response_model=None)
async def profile_query(req: ProfileQueryRequest, user: User = Depends(get_current_user)):
    from .qcc import query_debtor_profile

    company = (req.company or "").strip()
    if not company:
        return {"ok": False, "error": "请输入企业名称"}
    if looks_like_person(company):
        return {"ok": False, "error": "债务人画像仅支持企业。请填写企业工商全称（如“XX有限公司/股份公司”）；"
                                      "自然人不支持画像，可用「财产线索」对个人另作处理。"}
    if looks_like_abbrev(company):
        return {"ok": False, "error": "输入的名称疑似不完整（非企业工商全称）。企业名称规范：行政区划＋字号＋行业＋组织形式"
                                      "（如：青岛市XX房地产开发有限公司）。请按工商登记全称输入后重试。"}

    # 2026-09-04：重复提交同一企业 → 提示去"我的报告"查看，不重复生成（避免重复扣积分）
    db0 = SessionLocal()
    try:
        existed = db0.query(QccProfile).filter(QccProfile.user_id == user.id,
                                               QccProfile.company == company).first()
        if existed:
            return {"ok": False, "error": "该企业的画像报告已存在，请在「我的报告」中查看（可重复下载）。"}
    finally:
        db0.close()

    try:
        result = await query_debtor_profile(company)
    except Exception as e:  # noqa: BLE001
        logger.exception("debtor profile query failed for %s", company)
        return {"ok": False, "error": f"企查查查询失败：{e}"}

    reg_ok = (result.get("biz") or {}).get("get_company_registration_info", {}).get("ok")
    if not reg_ok:
        # 查无此名 → 提示可能自然人/名称不符
        return {"ok": False,
                "error": "未在企查查查询到该名称的企业登记信息。可能原因：①名称输入不完整或非工商全称 "
                         "（曾用名/简称请先用工商全称）②该名称更像自然人。请核对后重试。"}

    sections = _build_sections(result)
    summary = _summary_of(result)
    queried_at = result.get("queried_at") or datetime.now().strftime("%Y-%m-%d")

    # 落库（先拿 id 生成编号/文件名）
    settings = get_settings()
    db = SessionLocal()
    try:
        row = QccProfile(user_id=user.id, company=company,
                         search_name=result.get("search_name") or company,
                         content=json.dumps({"sections": sections, "summary": summary,
                                             "raw": {k: v for k, v in (result.get("biz") or {}).items()},
                                             "risk": result.get("risk")},
                                            ensure_ascii=False),
                         queried_at=queried_at)
        db.add(row)
        db.commit()
        db.refresh(row)
        rid = row.id
    except Exception:
        db.rollback()
        logger.exception("debtor profile db insert failed")
        return {"ok": False, "error": "报告落库失败"}
    finally:
        db.close()

    report_no = f"QS{datetime.now().strftime('%Y%m%d')}-{rid}"
    pdf_dir = settings.pdf_dir
    pdf_path = f"{pdf_dir}/profile_{rid}.pdf"
    meta = {"queried_at": queried_at, "sources": "企查查（实时接口）", "report_no": report_no,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    try:
        from ..services.profile_pdf import generate_profile_pdf
        generate_profile_pdf(company, sections, meta, pdf_path)
    except Exception:  # noqa: BLE001
        logger.exception("profile pdf generate failed for %s", company)
        pdf_path = None  # 摘要仍可用；下载提示失败

    db = SessionLocal()
    try:
        row = db.get(QccProfile, rid)
        row.pdf_path = pdf_path
        db.commit()
    finally:
        db.close()

    return {
        "ok": True,
        "report": {
            "id": rid, "company": company,
            "search_name": result.get("search_name") or company,
            "queried_at": queried_at,
            "download_url": f"/api/debtor-profile/{rid}/download" if pdf_path else None,
        },
        "summary": summary,
        "name_warning": (f"该企业可能已由「{result['renamed']['old_name']}」更名为"
                         f"「{result['renamed']['new_name']}」，报告按现名生成。"
                         if result.get("renamed") else None),
    }


@router.get("/debtor-profile/history")
def profile_history(user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        rows = db.query(QccProfile).filter(QccProfile.user_id == user.id).order_by(QccProfile.id.desc()).limit(100).all()
        return {"ok": True, "list": [{
            "id": r.id, "company": r.company, "search_name": r.search_name,
            "queried_at": r.queried_at,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
            "download_url": f"/api/debtor-profile/{r.id}/download" if r.pdf_path else None,
        } for r in rows]}
    finally:
        db.close()


@router.get("/debtor-profile/{rid}")
def profile_detail(rid: int, user: User = Depends(get_current_user)):
    """网页版企业速览报告数据（sections/summary，供 /debtor-report/:id 渲染）"""
    db = SessionLocal()
    try:
        row = db.get(QccProfile, rid)
        if row is None or (row.user_id != user.id and user.role not in ("admin", "editor")):
            return {"ok": False, "error": "无权限或报告不存在"}
        content = json.loads(row.content or "{}")
        return {"ok": True, "report": {
            "id": row.id, "company": row.company, "search_name": row.search_name,
            "queried_at": row.queried_at or (row.created_at.strftime("%Y-%m-%d") if row.created_at else ""),
            "created_at": row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else None,
            "sections": content.get("sections") or [],
            "summary": content.get("summary") or {},
            "download_url": f"/api/debtor-profile/{row.id}/download" if row.pdf_path else None,
        }}
    finally:
        db.close()


@router.get("/debtor-profile/{rid}/download")
def profile_download(rid: int, user: User = Depends(get_current_user)):
    import os
    db = SessionLocal()
    try:
        row = db.get(QccProfile, rid)
        if row is None or (row.user_id != user.id and user.role not in ("admin", "editor")):
            return {"ok": False, "error": "无权限或报告不存在"}
        if not row.pdf_path or not os.path.exists(row.pdf_path):
            return {"ok": False, "error": "PDF 尚未生成或文件已清理"}
        company = row.company or "企业"
        fname = f"{company}企业速览.pdf"
        # no-store: 防浏览器缓存旧版 PDF(2026-09-06 与线索下载同修)
        return FileResponse(row.pdf_path, filename=fname,
                            headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                                     "Pragma": "no-cache"})
    finally:
        db.close()

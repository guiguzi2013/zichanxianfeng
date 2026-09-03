# -*- coding: utf-8 -*-
"""清理测试期写入的乱码数据（公告/反馈），重建干净演示数据"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Feedback, Notice  # noqa: E402

db = SessionLocal()
try:
    # 1. 公告：清掉乱码的，重建一条干净的
    bad = db.query(Notice).all()
    for n in bad:
        print(f"删除乱码公告 id={n.id} title={n.title!r}")
        db.delete(n)
    db.commit()

    notice = Notice(
        title="资产先锋平台正式上线",
        content="欢迎使用资产先锋智能尽调平台！平台提供债权信息聚合、系统尽调分析、九版块尽调报告等能力，助您在不良资产投资决策前快速完成风险核查。",
        is_pinned=True,
        enabled=True,
        published_at=datetime.now(),
    )
    db.add(notice)
    db.commit()
    print(f"新公告已创建 id={notice.id}")

    # 2. 反馈：修复乱码内容（若有）
    for fb in db.query(Feedback).all():
        if fb.content and "?" in fb.content and fb.content.replace("?", "").strip() == "":
            print(f"修复乱码反馈 id={fb.id}")
            fb.content = "希望增加债权对比与更多筛选维度（修复乱码）"
    db.commit()

    print("清理完成")
finally:
    db.close()

"""初始化脚本：创建管理员账号（以及可选的演示 feed 数据）

用法（在 backend 目录）：
  python scripts/init_admin.py --username admin --password 你的密码
  python scripts/init_admin.py --demo   # 同时写入演示栏目数据

需要已安装依赖并配置好数据库。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import FeedItem, User  # noqa: E402
from app.services.security import hash_password  # noqa: E402

DEMO_FEED = [
    {
        "section": "asset_revive",
        "title": "青岛青海源商贸有限公司债权招商",
        "summary": "债权本金539万元，保证人：青岛宝祥真珠宝等，抵押物：市北区广饶路三处商业网点房产687.34㎡。",
        "tags": ["539万元", "抵押+保证", "商业网点"],
        "source": "手工录入",
        "detail_json": {
            "debtor_name": "青岛青海源商贸有限公司",
            "claim_total": "539万元",
            "guaranty_type": "抵押+保证",
            "collateral_type": "商业网点",
            "contact_org": "资产先锋演示数据",
            "sections": {"债权概况": "本金539万元，利息429万元", "处置亮点": "抵押物位置优越，靠近主干道"},
        },
    },
    {
        "section": "featured",
        "title": "青岛润丰源环保科技发展有限公司债权",
        "summary": "债权本金898万元，保证人（自然人）：曹云波、薛彩云，抵押物：开发区多处住宅及商业用房。",
        "tags": ["898万元", "抵押", "住宅+商业"],
        "source": "手工录入",
    },
    {
        "section": "bargain",
        "title": "青岛众辉园林投资有限公司债权（捡漏）",
        "summary": "债权本金580万元，抵押物：市南区澳门路住宅137.49㎡（首押二封），南口路房产已拍卖成交88万。",
        "tags": ["580万元", "低折扣", "住宅"],
        "source": "手工录入",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化管理员与演示数据")
    parser.add_argument("--username", default="admin", help="管理员用户名")
    parser.add_argument("--password", default=None, help="管理员密码（不提供则随机生成）")
    parser.add_argument("--demo", action="store_true", help="同时写入演示栏目数据")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 创建管理员
        existing = db.query(User).filter(User.username == args.username).first()
        if existing:
            print(f"用户 {args.username} 已存在，跳过")
        else:
            password = args.password or "admin123456"
            user = User(
                username=args.username,
                password_hash=hash_password(password),
                nickname="管理员",
                role="admin",
            )
            db.add(user)
            db.commit()
            print(f"管理员创建成功：{args.username} / {password}")

        # 演示数据
        if args.demo:
            count = db.query(FeedItem).count()
            if count > 0:
                print("已存在栏目数据，跳过演示数据写入")
            else:
                for item in DEMO_FEED:
                    db.add(FeedItem(
                        section=item["section"],
                        title=item["title"],
                        summary=item["summary"],
                        tags=json.dumps(item.get("tags", []), ensure_ascii=False),
                        source=item.get("source", "手工录入"),
                        detail_json=json.dumps(item.get("detail_json", {}), ensure_ascii=False),
                    ))
                db.commit()
                print(f"演示数据写入完成：{len(DEMO_FEED)} 条")
    finally:
        db.close()


if __name__ == "__main__":
    main()

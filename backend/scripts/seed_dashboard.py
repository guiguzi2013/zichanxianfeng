# -*- coding: utf-8 -*-
"""M3 演示数据：写入宏观指标 / KPI / 拍卖平台 / AMC 数据（首页看板真实数据）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import AmcStat, AuctionStat, MacroKpi  # noqa: E402

db = SessionLocal()
try:
    if db.query(MacroKpi).count() == 0:
        db.add_all([
            # 宏观数据条
            MacroKpi(category="macro", label="不良贷款余额", value="3.7", unit="万亿", sort=1, source="金融监管总局"),
            MacroKpi(category="macro", label="商业银行不良率", value="1.51", unit="%", sort=2, source="金融监管总局"),
            MacroKpi(category="macro", label="持牌 AMC 数量", value="64", unit="家", sort=3, source="金融监管总局"),
            MacroKpi(category="macro", label="年处置规模", value="3.8", unit="万亿", sort=4, source="金融监管总局"),
            # KPI 卡片
            MacroKpi(category="kpi", label="在拍总数", value="12,846", unit="笔", trend="+3.2% 较上月", trend_up=1, sort=1),
            MacroKpi(category="kpi", label="今日新增", value="37", unit="笔", trend="+12 较昨日", trend_up=1, sort=2),
            MacroKpi(category="kpi", label="近一年成交额", value="4.52", unit="万亿", trend="环比 +8.6%", trend_up=1, sort=3),
            MacroKpi(category="kpi", label="平均折扣率", value="38.5", unit="%", trend="同比 -2.1%", trend_up=0, sort=4),
        ])
        db.commit()
        print("macro/kpi seeded")

    if db.query(AuctionStat).count() == 0:
        db.add_all([
            AuctionStat(platform="阿里资产", period="2026-07", on_auction=4203, sold=1258, amount=15820.5),
            AuctionStat(platform="京东拍卖", period="2026-07", on_auction=2611, sold=842, amount=9240.3),
            AuctionStat(platform="人民法院诉讼资产网", period="2026-07", on_auction=1830, sold=516, amount=6135.8),
            AuctionStat(platform="中拍平台", period="2026-07", on_auction=1255, sold=387, amount=4210.2),
            AuctionStat(platform="北交互联", period="2026-07", on_auction=860, sold=224, amount=2860.4),
        ])
        db.commit()
        print("auction seeded")

    if db.query(AmcStat).count() == 0:
        db.add_all([
            # 全国
            AmcStat(org_name="中信金融资产管理", scope="national", period="2026-07", listed_count=3196, market_share=32.71, trend="up"),
            AmcStat(org_name="信达资产管理", scope="national", period="2026-07", listed_count=2584, market_share=22.84, trend="up"),
            AmcStat(org_name="东方资产管理", scope="national", period="2026-07", listed_count=2024, market_share=17.35, trend="flat"),
            AmcStat(org_name="长城资产管理", scope="national", period="2026-07", listed_count=1488, market_share=12.60, trend="down"),
            AmcStat(org_name="银河资产管理", scope="national", period="2026-07", listed_count=113, market_share=4.10, trend="flat"),
            # 地方
            AmcStat(org_name="河南省国锦管理合伙", scope="local", period="2026-07", listed_count=980, market_share=13.04, trend="up"),
            AmcStat(org_name="天津弘发企业管理", scope="local", period="2026-07", listed_count=860, market_share=12.83, trend="up"),
            AmcStat(org_name="浙商资产管理", scope="local", period="2026-07", listed_count=640, market_share=6.20, trend="flat"),
            AmcStat(org_name="山东金融资产管理", scope="local", period="2026-07", listed_count=560, market_share=5.45, trend="down"),
            AmcStat(org_name="广东粤财资产管理", scope="local", period="2026-07", listed_count=470, market_share=4.80, trend="up"),
        ])
        db.commit()
        print("amc seeded")
    else:
        print("data exists, skip")
finally:
    db.close()

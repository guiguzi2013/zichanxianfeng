"""资产先锋 · 后端配置

所有可调参数集中在 .env / 环境变量，避免硬编码。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 安全 ---
    secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24h

    # --- LLM ---
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # 材料识别/长文本任务（多文件合并可达数万字符）需更长超时，避免 60s 掐断+重试造成"卡死"观感
    llm_timeout_seconds: int = 300
    llm_max_retries: int = 1
    # mock 模式：无 API Key 时用预设数据跑通全流程（验收/演示用），生产关闭
    # 默认 True：没有 .env 时开箱即用；配置了 DEEPSEEK_API_KEY 后可在 .env 设 LLM_MOCK=false 走真实模型
    llm_mock: bool = True

    # --- 数据库 ---
    database_url: str = "sqlite:///./data/app.db"

    # --- 存储 ---
    upload_dir: str = "./data/uploads"
    pdf_dir: str = "./data/pdf"

    # --- 数据源开关（P0 免费源）---
    gsxt_enabled: bool = True
    zxgk_enabled: bool = True
    # 爱企查（补充源，待申请 AppKey 后启用）
    aiqicha_app_key: str = ""
    aiqicha_enabled: bool = False
    # 企查查 MCP 凭证（.env 配置；空则回退代码内旧 token）
    qcc_token: str = ""

    # --- 本息计算 ---
    lpr_rate: float = 0.0345  # 无判决书时的估算利率，可更新

    # --- 业务 ---
    max_claims_per_task: int = 5  # 单次尽调最多勾选条数


@lru_cache
def get_settings() -> Settings:
    return Settings()

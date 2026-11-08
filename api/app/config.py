from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/groundproof.db"
    jwt_secret: str = "dev-only-change-me-dev-only-change-me"
    jwt_expire_minutes: int = 600
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-admin"
    demo_seed: bool = True
    storage_dir: str = "./data/storage"
    # Adapters: "mock" is the default; "real" only works with credentials.
    cutoff_adapter: str = "mock"          # mock | whisp
    imagery_mode: str = "offline"         # offline | stac
    stac_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    gee_service_account_json: str = ""
    firms_map_key: str = ""
    # Commercial tasking: off by default, budget capped, human approval required.
    iceye_enabled: bool = False
    iceye_api_key: str = ""
    tasking_monthly_budget_eur: float = 5000.0
    tasking_four_eyes: bool = True
    # Monitoring thresholds
    min_clearing_ha: float = 0.5
    ndvi_drop_threshold: float = 0.25
    sar_drop_db: float = 3.0
    # C2PA / signing
    c2pa_cert_path: str = ""
    c2pa_key_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

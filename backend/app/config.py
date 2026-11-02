from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path(".runtime")
    database_url: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    task_mode: str = "local"
    redis_url: str = "redis://127.0.0.1:6379/0"
    secret_key: str = ""
    admin_password: str = ""
    manager_password: str = ""
    session_hours: int = 8
    cookie_secure: bool = False
    allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000"
    allow_private_providers: bool = False
    request_timeout: float = 60
    @property
    def sql_url(self):
        return self.database_url or f"sqlite:///{self.data_dir.resolve() / 'knowledge.db'}"
    @property
    def origins(self):
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]

config = Config()
config.data_dir.mkdir(parents=True, exist_ok=True)

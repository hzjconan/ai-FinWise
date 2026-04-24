from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENV: str = "dev"  # dev / prod
    DATABASE_URL: str = "sqlite:///./finwise.db"
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    ADMIN_DEFAULT_USERNAME: str = "admin"
    ADMIN_DEFAULT_PASSWORD: str = "admin123"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # LLM 相关
    # mock：测试 + P1/P3 开发阶段使用；api：走 Anthropic SDK（生产或 dev+bridge）
    LLM_PROVIDER: str = "mock"
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"
    ANTHROPIC_MAX_TOKENS: int = 1024

    model_config = {"env_prefix": "FINWISE_", "env_file": ".env"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()

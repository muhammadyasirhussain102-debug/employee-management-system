from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Workforce Platform - Employee Management"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./workforce_os.db"
    SECRET_KEY: str = "change-this-secret-in-production"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
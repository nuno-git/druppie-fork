import os


class Settings:
    app_name: str = os.getenv("APP_NAME", "My App")
    database_url: str = os.getenv("DATABASE_URL", "postgresql://app:app@db:5432/app")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()

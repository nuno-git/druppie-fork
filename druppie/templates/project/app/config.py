import os


class Settings:
    app_name: str = os.getenv("APP_NAME", "My App")
    database_url: str = os.getenv("DATABASE_URL", "postgresql://app:app@db:5432/app")
    deepinfra_api_key: str = os.getenv("DEEPINFRA_API_KEY", "")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()

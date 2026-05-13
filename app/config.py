"""
config.py
---------
Loads all settings from the .env file using pydantic-settings.
Every part of the app imports from here — no scattered os.getenv() calls.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    claude_api_key: str
    claude_model: str = "claude-sonnet-4-20250514"
    app_env: str = "development"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

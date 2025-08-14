"""Configuration settings."""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.1
    
    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra fields from .env


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()

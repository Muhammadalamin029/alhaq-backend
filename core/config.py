from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "LEL Store"
    API_V1_STR: str = "/api/v1"

    # CORS
    ALLOWED_ORIGINS: list[str]

    # Database
    DATABASE_URL: str

    # JWT Authentication
    SECRET_KEY: str
    REFRESH_SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str

    # Google Sign-In
    GOOGLE_CLIENT_ID: str = ""

    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str = ""

    # Celery Configuration - Use REDIS_URL for both broker and backend
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set Celery URLs from REDIS_URL if not explicitly provided
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = self.REDIS_URL

    # Email Configuration
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    FROM_EMAIL: str = ""
    FROM_NAME: str = "LEL Store"

    # Email verification settings
    EMAIL_VERIFICATION_EXPIRE_MINUTES: int = 15
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30

    # Paystack Configuration
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    PAYSTACK_WEBHOOK_SECRET: str = ""

    # Frontend URL — used for deep links in emails (e.g. "View Order" CTA)
    # and as the base for the email logo image.
    FRONTEND_URL: str = "https://lelstore.com"

    # Security email — set to False to stop sending a "New Sign-In" email on
    # every login (useful when users authenticate frequently from mobile).
    SEND_LOGIN_EMAIL: bool = True

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    JSON_LOGS: bool = False
    LOG_TO_FILE: bool = False  # Disabled file-based logging
    LOG_TO_CONSOLE: bool = True

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()

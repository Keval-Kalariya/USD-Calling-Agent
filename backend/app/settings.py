from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_NUMBER: str = ""

    DEEPGRAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"
    GEMINI_TTS_MODEL: str = "models/gemini-3.1-flash-tts-preview"
    GEMINI_TTS_VOICE: str = "Puck"
    GEMINI_TTS_TIMEOUT: float = 10.0
    TTS_PROVIDER: str = "elevenlabs"

    INTERNAL_KEY: str = "default_internal_secret_key"
    ALLOWED_NUMBERS: str = ""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
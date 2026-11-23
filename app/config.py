from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every value can be overridden by an environment variable of the same name (upper case),
    or by a line in a `.env` file in the project root (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Aasra"
    prototype_label: str = "PROTOTYPE - all people, documents and payments are fake"
    database_url: str = "sqlite:///./lastmile.db"

    # --- live or demo
    demo_mode: bool = True          # true: one-tap demo accounts on the login page and fake claims; false: live
    sms_mode: str = "screen"        # screen: one-time codes are shown on screen (no SMS gateway yet) | gateway

    # --- login (JWT)
    secret_key: str = "change-me-before-deploying"
    access_token_minutes: int = 8 * 60
    # start.bat fresh sets a new random value, so every login from before the reset stops working and the
    # browser (and the phone app) opens on the login page instead of the last demo account
    session_epoch: str = ""
    max_failed_logins: int = 5      # then the account is locked for lockout_minutes
    lockout_minutes: int = 15
    code_minutes: int = 10          # a one-time SMS code is valid this long

    # --- AI engines (run inside this app; see app/ai_engines.py)
    ocr_mock: bool = False          # true: instant fake OCR answers from data/ocr_fixtures (for building screens)
    voice_mock: bool = False        # true: no Whisper; every recording "says" one fixed sentence
    voice_preload: bool = True      # load Whisper when the app starts (first start downloads ~500 MB)
    whisper_model: str = "small"    # base (fast, weak Urdu) | small | medium
    ocr_timeout_s: float = 60.0     # how long a request waits for the OCR engine when it is busy
    local_ocr_fallback: bool = True # OCR engine down: read CNICs with Tesseract (app/doc_check.py), if installed

    # --- files
    upload_dir: str = "uploads"     # document photos (git-ignored), for the officer

    # --- the benefit in this prototype
    benefit_name: str = "Widow support (mock programme)"
    benefit_amount: int = 25000     # PKR, paid once
    payment_settlement_days: int = 3  # what the citizen is told: the money reaches the account within N days


settings = Settings()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    model_service_url: str
    model_service_token: str = ""  # HF read token for the private Space; empty for the local copy
    model_call_timeout_seconds: float = 30
    hf_model_repo: str
    labels_path: str = "/app/config/labels.yaml"
    log_level: str = "INFO"

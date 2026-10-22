from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    hf_model_repo: str
    model_revision: str = "main"
    hf_token: str | None = None  # read token; needed because the model repo is private
    log_level: str = "INFO"

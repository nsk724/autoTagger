from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    labels_path: str = "/app/config/labels.yaml"
    log_level: str = "INFO"

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    backend_url: str = "http://backend-api:8000"
    ticket_interval_seconds: float = 15
    drift_enabled: bool = False
    drift_start_after: int = 100
    drift_ratio: float = 0.4
    drift_seed: int = 42
    data_dir: str = "/app/data"
    state_dir: str = "/state"
    log_level: str = "INFO"

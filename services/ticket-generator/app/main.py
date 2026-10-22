import time
from pathlib import Path

import httpx
import pandas as pd

from app.generator import DriftConfig, load_state, save_state, tick
from app.observability import setup_logging
from app.settings import Settings


def main() -> None:
    s = Settings()
    setup_logging(s.log_level)
    data = {
        name: pd.read_parquet(Path(s.data_dir) / f"{name}.parquet")
        for name in ("stream", "heldout")
    }
    cfg = DriftConfig(
        s.drift_enabled, s.drift_start_after, s.drift_ratio, {k: len(v) for k, v in data.items()}
    )
    state_path, heartbeat = Path(s.state_dir) / "cursor.json", Path(s.state_dir) / "heartbeat"
    state = load_state(state_path)
    # backend's own timeout to the model is 30s by default, plus Space wake-up
    with httpx.Client(base_url=s.backend_url, timeout=60) as http:
        while True:
            new = tick(state, cfg, data, http, s.drift_seed)
            if new != state:
                save_state(state_path, new)
                state = new
            heartbeat.touch()
            time.sleep(s.ticket_interval_seconds)


if __name__ == "__main__":
    main()

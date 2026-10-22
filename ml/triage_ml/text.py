import re

import numpy as np
import pandas as pd

EMB_PREFIX = "emb_"


def build_text(subject: str | None, body: str) -> str:
    subject = subject if isinstance(subject, str) else ""  # pandas gives NaN for a missing subject
    text = f"{subject.strip()}\n\n{body.strip()}".strip()
    return re.sub(r"[ \t]+", " ", text)


def feature_frame(texts, embeddings: np.ndarray) -> pd.DataFrame:
    """Classifier input: the text (for TF-IDF) plus one column per embedding dimension."""
    emb = pd.DataFrame(embeddings, columns=[f"{EMB_PREFIX}{i}" for i in range(embeddings.shape[1])])
    return pd.concat([pd.DataFrame({"text": list(texts)}), emb], axis=1)

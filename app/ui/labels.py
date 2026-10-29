"""데이터프레임 컬럼/표시용 한글 라벨."""

from __future__ import annotations

import pandas as pd

from app.config import COLUMN_LABELS_KO


def rename_columns_ko(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    mapping = {c: COLUMN_LABELS_KO[c] for c in df.columns if c in COLUMN_LABELS_KO}
    return df.rename(columns=mapping)

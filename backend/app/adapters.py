from pathlib import Path

from app.core import ApiError


SUPPORTED = {'.csv': 'read_csv_auto', '.parquet': 'read_parquet'}


def reader_for(path: Path) -> str:
    """Only fixed DuckDB readers are admitted; the uploaded name never becomes SQL."""
    try:
        return SUPPORTED[path.suffix.lower()]
    except KeyError:
        raise ApiError(415, 'unsupported_format', 'Upload a CSV or Parquet file') from None

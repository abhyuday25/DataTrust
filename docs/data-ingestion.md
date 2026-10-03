# Data ingestion

`adapters.py` is the small format boundary: extension → fixed DuckDB reader. CSV uses `read_csv_auto`; Parquet uses `read_parquet`. Add a reader only after validating its input behavior and adding an API integration test. XLSX is deferred.

The service checks extension, name, streamed size, and nonempty bytes before loading. DuckDB rejects unreadable files. The app generates UUID storage and table names, so original paths never affect SQL identifiers. A duplicate display name is rejected case insensitively. Schema discovery checks columns, then computes row count and profiles. Every column attempts null count, percentage, distinct count, min/max, and five representative non-null values from at most 10,000 rows. A column profiling error produces a warning and keeps the dataset usable.

The database table and catalog row commit together. A failed load rolls back and deletes the stored file. Catalog and uploaded files persist across restarts; operators should back up both. Phase 1 has no replacement or deletion API.

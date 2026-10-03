# Dataset versioning

Dataset IDs are random UUID4 hex strings assigned once at registration. They are safe internal identifiers and do not depend on upload names. Duplicate names are rejected, so a new file with the same display name is not a replacement in Phase 1.

Version is SHA-256 of the exact uploaded bytes. Any byte change changes the version, including row order, whitespace, or file metadata. Identical bytes give the same version even across different dataset IDs.

Schema is a list of `(column name, uppercased DuckDB type)` pairs sorted lexically, serialized as compact UTF-8 JSON, then SHA-256 hashed. Column order does not change the schema hash; a name or type change does. Content version, schema hash, and dataset ID together form the future cache identity; cache entries must also check TTL. `updated_at` is registration time and does not affect hashes.

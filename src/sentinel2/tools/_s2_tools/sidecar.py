"""Per-entry cache sidecar.

Each cached artifact ``<path>`` gets a sibling ``<path>.meta.json`` recording
size, sha256, source, and tool lineage — so N writers on N keys never contend
and a cache hit is a cheap presence + checksum check. All I/O goes through
``storage`` so the same protocol works on local disk or S3/MinIO.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from _s2_tools import storage

SIDECAR_SUFFIX = ".meta.json"


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_path(cache_type: str, relative_path: str) -> str:
    """Path of a cached artifact: ``<cache_root>/s2/<cache_type>/<rel>`` (local
    path or s3:// URI depending on the backend)."""
    return storage.join(storage.cache_root(), storage.NAMESPACE, cache_type, relative_path)


def _meta_path(abs_path: str) -> str:
    return abs_path + SIDECAR_SUFFIX


def exists(cache_type: str, relative_path: str) -> bool:
    """True when both the artifact and its sidecar are present."""
    p = cache_path(cache_type, relative_path)
    return storage.exists(p) and storage.exists(_meta_path(p))


def write(cache_type: str, relative_path: str, data: bytes, *, source: str, tool: str,
          extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write ``data`` to the cache and its sidecar. Returns the sidecar dict."""
    abs_path = cache_path(cache_type, relative_path)
    storage.write_bytes(abs_path, data)
    meta = {
        "version": 1,
        "cache_type": cache_type,
        "relative_path": relative_path,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": source,
        "tool": tool,
        "created_at": utcnow_iso(),
        "extras": extras or {},
    }
    storage.write_text(_meta_path(abs_path), json.dumps(meta, indent=2))
    return meta


def read_meta(cache_type: str, relative_path: str) -> dict[str, Any]:
    return json.loads(storage.read_text(_meta_path(cache_path(cache_type, relative_path))))


def list_entries(cache_type: str) -> list[str]:
    """Relative paths of cached artifacts of ``cache_type`` (sidecars excluded)."""
    base = storage.join(storage.cache_root(), storage.NAMESPACE, cache_type)
    return sorted(f for f in storage.list_files(base) if not f.endswith(SIDECAR_SUFFIX))

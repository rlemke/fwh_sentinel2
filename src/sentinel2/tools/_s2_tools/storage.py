"""Storage for the s2 tools — local filesystem or S3/MinIO.

One backend, selected by ``AFL_STORAGE`` (``local`` default, or ``s3``). All
file I/O in ``_s2_tools`` (the sidecar cache + the rendered map bundle) goes
through ``read_bytes`` / ``write_bytes`` / ``exists`` / ``list_files`` here, so
the same code path produces a local tree or S3 objects. On ``s3`` the cache lands
at ``s3://<bucket>/cache/s2/…`` and the map bundle at ``s3://<bucket>/output/s2/…``
(which the dashboard's /output/raw artifact server can serve).

Conforms to agent-spec/cache-layout. S3 needs ``boto3`` (``pip install -e ".[s3]"``)
and the standard ``AFL_S3_*`` env (endpoint/creds), exactly like the runtime.
"""

from __future__ import annotations

import os

NAMESPACE = "s2"
LOCAL_DEFAULT_ROOT = os.path.expanduser("~/afl_data")
S3_DEFAULT_ROOT = "s3://afl-cache"


def backend() -> str:
    return (os.environ.get("AFL_STORAGE") or "local").lower()


def is_s3(path: str) -> bool:
    return isinstance(path, str) and path.startswith("s3://")


# ── roots ────────────────────────────────────────────────────────────────────


def data_root() -> str:
    env = os.environ.get("AFL_DATA_ROOT")
    if env:
        return env
    return S3_DEFAULT_ROOT if backend() == "s3" else LOCAL_DEFAULT_ROOT


def cache_root() -> str:
    return os.environ.get("AFL_CACHE_ROOT") or join(data_root(), "cache")


def output_root() -> str:
    """Where the rendered map bundle is written.

    On ``s3`` the bundle goes to the object store so the dashboard can serve it;
    ``AFL_OUTPUT_BASE`` is honored only when it is itself an ``s3://`` URI (it is
    often a *local* scratch dir under the runtime's staging model). On ``local``
    it's ``AFL_OUTPUT_BASE`` or ``<data_root>/output``.
    """
    if backend() == "s3":
        ob = os.environ.get("AFL_S2_OUTPUT_BASE") or os.environ.get("AFL_OUTPUT_BASE")
        if ob and is_s3(ob):
            return ob
        return join(data_root(), "output")
    return os.environ.get("AFL_OUTPUT_BASE") or join(data_root(), "output")


def join(*parts: str) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if is_s3(parts[0]):
        head = parts[0].rstrip("/")
        tail = "/".join(p.strip("/") for p in parts[1:])
        return head + ("/" + tail if tail else "")
    return os.path.join(*parts)


# ── S3 client ────────────────────────────────────────────────────────────────


def _s3():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("AFL_S3_ENDPOINT") or None,
        region_name=os.environ.get("AFL_S3_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AFL_S3_ACCESS_KEY") or os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=(
            os.environ.get("AFL_S3_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        ),
    )


def _split(uri: str) -> tuple[str, str]:
    bucket, _, key = uri[len("s3://"):].partition("/")
    return bucket, key


# ── ops (local or s3, dispatched on the path) ──────────────────────────────────


def exists(path: str) -> bool:
    if is_s3(path):
        from botocore.exceptions import ClientError

        b, k = _split(path)
        try:
            _s3().head_object(Bucket=b, Key=k)
            return True
        except ClientError:
            return False
    return os.path.exists(path)


def read_bytes(path: str) -> bytes:
    if is_s3(path):
        b, k = _split(path)
        return _s3().get_object(Bucket=b, Key=k)["Body"].read()
    with open(path, "rb") as f:
        return f.read()


def write_bytes(path: str, data: bytes) -> None:
    if is_s3(path):
        b, k = _split(path)
        _s3().put_object(Bucket=b, Key=k, Body=data)
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path: str) -> str:
    return read_bytes(path).decode("utf-8")


def write_text(path: str, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def list_files(dir_path: str) -> list[str]:
    """File paths relative to ``dir_path`` (recursive). Local dir or S3 prefix."""
    if is_s3(dir_path):
        b, prefix = _split(dir_path.rstrip("/") + "/")
        out: list[str] = []
        for page in _s3().get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix):
            for obj in page.get("Contents", []):
                out.append(obj["Key"][len(prefix):])
        return out
    if not os.path.isdir(dir_path):
        return []
    out = []
    for root, _dirs, files in os.walk(dir_path):
        for fn in files:
            out.append(os.path.relpath(os.path.join(root, fn), dir_path))
    return out

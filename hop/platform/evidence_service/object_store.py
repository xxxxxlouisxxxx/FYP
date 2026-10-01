"""S3-compatible object store interface with a local filesystem implementation.

Objects are write-once: writing a different payload to an existing key fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from hop.platform.common_contracts.base import sha256_hex


class ObjectStoreError(RuntimeError):
    pass


class ObjectStore(Protocol):
    scheme: str

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> str: ...

    def get(self, uri: str) -> bytes: ...

    def exists(self, uri: str) -> bool: ...


class LocalObjectStore:
    scheme = "file"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ObjectStoreError(f"key escapes object store root: {key}")
        return path

    def _key(self, uri: str) -> str:
        prefix = "objects://"
        if not uri.startswith(prefix):
            raise ObjectStoreError(f"unsupported uri {uri}")
        return uri[len(prefix) :]

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        path = self._path(key)
        if path.exists():
            if sha256_hex(path.read_bytes()) != sha256_hex(data):
                raise ObjectStoreError(f"object {key} already exists with different content (write-once)")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return f"objects://{key}"

    def get(self, uri: str) -> bytes:
        path = self._path(self._key(uri))
        if not path.exists():
            raise ObjectStoreError(f"object not found: {uri}")
        return path.read_bytes()

    def exists(self, uri: str) -> bool:
        return self._path(self._key(uri)).exists()


class S3ObjectStore:  # pragma: no cover - requires boto3 and credentials
    """Production adapter for S3-compatible storage (MinIO, AWS S3). Enable versioning on the bucket."""

    scheme = "s3"

    def __init__(self, bucket: str, prefix: str = "hop/", endpoint_url: str | None = None) -> None:
        import boto3  # type: ignore[import-not-found]

        self.bucket = bucket
        self.prefix = prefix
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        full = self.prefix + key
        self.client.put_object(Bucket=self.bucket, Key=full, Body=data, ContentType=content_type)
        return f"s3://{self.bucket}/{full}"

    def get(self, uri: str) -> bytes:
        _, _, rest = uri.partition("s3://")
        bucket, _, key = rest.partition("/")
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def exists(self, uri: str) -> bool:
        try:
            self.get(uri)
            return True
        except Exception:
            return False

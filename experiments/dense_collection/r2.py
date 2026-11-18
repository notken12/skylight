import os
import tarfile
import time
from collections import Counter
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import boto3

type Upload = Callable[[str, Path], None]


class R2Store:
    def __init__(self, client: Any, bucket: str) -> None:
        self.client = client
        self.bucket = bucket
        self.uploaded_bytes: Counter[str] = Counter()

    @classmethod
    def from_environment(cls) -> "R2Store":
        return cls(
            boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT"]),
            os.environ["R2_BUCKET"],
        )

    def upload(self, key: str, path: Path) -> None:
        size = path.stat().st_size
        self.client.upload_file(str(path), self.bucket, key)
        stored = self.client.head_object(Bucket=self.bucket, Key=key)
        if stored["ContentLength"] != size:
            raise OSError(
                f"R2 holds {stored['ContentLength']} bytes of {key}, not {size}"
            )
        self.uploaded_bytes[key.split("/")[0]] += size

    def etag(self, key: str) -> str:
        return self.client.head_object(Bucket=self.bucket, Key=key)["ETag"]

    def download(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(path))

    def keys(self, prefix: str) -> dict[str, int]:
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        )
        return {
            stored["Key"]: stored["Size"]
            for page in pages
            for stored in page.get("Contents", [])
        }


def add_tar_member(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mtime = int(time.time())
    archive.addfile(member, BytesIO(data))


class TarShardWriter:
    def __init__(
        self, directory: Path, key_prefix: str, upload: Upload, max_bytes: int
    ) -> None:
        self.directory = directory
        self.key_prefix = key_prefix
        self.upload = upload
        self.max_bytes = max_bytes
        self.shard_index = 0
        self.archive: tarfile.TarFile | None = None

    def shard_key(self) -> str:
        return f"{self.key_prefix}/{self.shard_index:03d}.tar"

    def shard_path(self) -> Path:
        return (
            self.directory
            / f"{self.key_prefix.replace('/', '_')}_{self.shard_index:03d}.tar"
        )

    def add(self, name: str, data: bytes) -> str:
        if self.archive is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.archive = tarfile.open(  # noqa: SIM115 - stays open across add() calls
                self.shard_path(), "w", format=tarfile.PAX_FORMAT
            )
        add_tar_member(self.archive, name, data)
        key = self.shard_key()
        if self.archive.offset >= self.max_bytes:
            self.close()
        return key

    def close(self) -> None:
        if self.archive is None:
            return
        self.archive.close()
        self.archive = None
        self.upload(self.shard_key(), self.shard_path())
        self.shard_path().unlink()
        self.shard_index += 1

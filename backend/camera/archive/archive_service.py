import sqlite3
from dataclasses import dataclass
from io import BytesIO
from PIL import Image
from typing import Protocol
from datetime import datetime, timezone
from types_boto3_s3 import S3Client
from backend.sqlite_utils import inserted_id


@dataclass
class ConvertedImage:
    image_bytes: bytes
    ext: str
    content_type: str


class ImageConverter(Protocol):
    def convert_image(self, image_bytes: bytes) -> ConvertedImage:
        raise NotImplementedError()


class WebpImageConverter(ImageConverter):
    def convert_image(self, image_bytes: bytes) -> ConvertedImage:
        with Image.open(BytesIO(image_bytes)) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            output_buffer = BytesIO()
            quality = 80
            img.save(output_buffer, format="WEBP", quality=quality)
            return ConvertedImage(
                image_bytes=output_buffer.getvalue(),
                ext="webp",
                content_type="image/webp",
            )


class CameraArchiveService:
    def __init__(
        self,
        s3: S3Client,
        db_connection: sqlite3.Connection,
        bucket: str,
        image_converter: ImageConverter,
    ):
        self.s3 = s3
        self.bucket = bucket
        self.image_converter = image_converter
        self.db_connection = db_connection

    def archive_frame(self, network: str, camera_id: str, image: bytes) -> int:
        now = datetime.now(timezone.utc)
        filename = now.strftime("%Y-%m-%d-%H-%M-%S")
        converted = self.image_converter.convert_image(image)
        path = f"frames/{network}/{camera_id}/{filename}.{converted.ext}"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=path,
            Body=converted.image_bytes,
            ContentType=converted.content_type,
        )
        cursor = self.db_connection.execute(
            """
            INSERT INTO archived_frames
            (network, camera_id, created_at_utc, s3_key)
            VALUES (?, ?, ?, ?)
            """,
            (network, camera_id, now.isoformat(), path),
        )
        frame_id = inserted_id(cursor)
        return frame_id

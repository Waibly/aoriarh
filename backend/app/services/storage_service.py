import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile

from app.core.config import settings


class StorageService:
    """MinIO/S3-compatible storage service."""

    def __init__(self) -> None:
        self.bucket = settings.minio_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    async def upload_file(self, file: UploadFile, path: str) -> str:
        contents = await file.read()
        self.client.put_object(
            Bucket=self.bucket,
            Key=path,
            Body=contents,
            ContentType=file.content_type or "application/octet-stream",
        )
        return path

    def put_file_bytes(
        self, path: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=path,
            Body=data,
            ContentType=content_type,
        )
        return path

    def delete_file(self, path: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=path)

    def get_file_bytes(self, path: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=path)
        return response["Body"].read()

    def get_presigned_url(self, path: str, expires: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": path},
            ExpiresIn=expires,
        )

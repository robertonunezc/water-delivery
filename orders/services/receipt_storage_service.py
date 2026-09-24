from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.config import Config
from django.conf import settings


class ReceiptStorageError(RuntimeError):
    """Raised when receipt PDF storage cannot complete."""


@dataclass(frozen=True)
class ReceiptStorageConfig:
    endpoint_url: str
    bucket_name: str
    access_key_id: str
    secret_access_key: str
    region: str
    object_prefix: str
    signed_url_expires_seconds: int


class CloudflareR2ReceiptStorage:
    def __init__(self, config: ReceiptStorageConfig) -> None:
        self.config = config
        self.client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
            config=Config(signature_version="s3v4"),
        )

    @classmethod
    def from_settings(cls) -> CloudflareR2ReceiptStorage:
        config = ReceiptStorageConfig(
            endpoint_url=settings.RECEIPT_R2_ENDPOINT_URL,
            bucket_name=settings.RECEIPT_R2_BUCKET_NAME,
            access_key_id=settings.RECEIPT_R2_ACCESS_KEY_ID,
            secret_access_key=settings.RECEIPT_R2_SECRET_ACCESS_KEY,
            region=settings.RECEIPT_R2_REGION,
            object_prefix=settings.RECEIPT_R2_OBJECT_PREFIX.strip("/"),
            signed_url_expires_seconds=settings.RECEIPT_R2_SIGNED_URL_EXPIRES_SECONDS,
        )
        missing = [
            label
            for label, value in (
                ("RECEIPT_R2_ENDPOINT_URL", config.endpoint_url),
                ("RECEIPT_R2_BUCKET_NAME", config.bucket_name),
                ("RECEIPT_R2_ACCESS_KEY_ID", config.access_key_id),
                ("RECEIPT_R2_SECRET_ACCESS_KEY", config.secret_access_key),
            )
            if not value
        ]
        if missing:
            raise ReceiptStorageError(
                f"Cloudflare R2 receipt storage is not configured: {', '.join(missing)}"
            )
        return cls(config)

    def upload_pdf(
        self,
        order_id: int,
        pdf_bytes: bytes,
        *,
        tenant_id: int | None = None,
        client_id: int | None = None,
    ) -> str:
        key = self._object_key(
            tenant_id=tenant_id,
            client_id=client_id,
            order_id=order_id,
        )
        self.client.put_object(
            Bucket=self.config.bucket_name,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        return key

    def download_pdf(self, pdf_url: str) -> bytes:
        response = self.client.get_object(
            Bucket=self.config.bucket_name,
            Key=pdf_url,
        )
        return response["Body"].read()

    def generate_signed_url(self, pdf_url: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.config.bucket_name, "Key": pdf_url},
            ExpiresIn=self.config.signed_url_expires_seconds,
        )

    def _object_key(
        self,
        tenant_id: int | None,
        client_id: int | None,
        order_id: int,
    ) -> str:
        if tenant_id is not None and client_id is not None:
            return (
                f"{self.config.object_prefix}/tenants/{tenant_id}"
                f"/clients/{client_id}/orders/{order_id}/receipt.pdf"
            )
        return f"{self.config.object_prefix}/orders/{order_id}/receipt.pdf"


def get_receipt_storage() -> CloudflareR2ReceiptStorage:
    return CloudflareR2ReceiptStorage.from_settings()

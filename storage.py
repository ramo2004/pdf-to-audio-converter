# storage.py

from google.cloud import storage
import os
from datetime import timedelta

BUCKET = os.getenv("BUCKET_NAME", "my-text-to-audio-bucket")

client = storage.Client()

def download_blob(remote_path: str, local_path: str) -> str:
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(remote_path)
    blob.download_to_filename(local_path)
    return local_path

def upload_blob(local_path: str, remote_path: str) -> str:
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(remote_path)
    blob.upload_from_filename(local_path)
    return f"gs://{BUCKET}/{remote_path}"

def presigned_url(remote_path: str, expires_seconds: int = 86400) -> str:
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(remote_path)
    return blob.generate_signed_url(
        expiration=timedelta(seconds=expires_seconds),
        version="v4"
    )


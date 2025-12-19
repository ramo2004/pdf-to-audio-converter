import os
import datetime
from typing import Optional

from google.cloud import storage
import google.auth
from google.auth import impersonated_credentials


# ---- Configuration ----
# IMPORTANT: set these in Cloud Run via env vars.
BUCKET_NAME = os.getenv("BUCKET_NAME", "").strip()

# This MUST be a real service account email in Cloud Run (NOT "default").
# Example:
# text2audio-sa@text-to-audio-460215.iam.gserviceaccount.com
SIGNER_SA_EMAIL = os.getenv("SIGNER_SA_EMAIL", "").strip()

# Cloud Run sets K_SERVICE; we can use it to detect runtime.
IS_CLOUD_RUN = bool(os.getenv("K_SERVICE"))


print("[storage] Initializing GCS client...")
client = storage.Client()
print("[storage] GCS client initialized.")
print(f"[storage] IS_CLOUD_RUN={IS_CLOUD_RUN}")
print(f"[storage] BUCKET_NAME={'(set)' if BUCKET_NAME else '(missing)'}")
print(f"[storage] SIGNER_SA_EMAIL={SIGNER_SA_EMAIL or '(missing)'}")


def _require_bucket():
    if not BUCKET_NAME:
        raise ValueError(
            "BUCKET_NAME env var is not set. "
            "Set BUCKET_NAME=my-text-to-audio-bucket on Cloud Run."
        )


def _signing_credentials_if_available():
    """
    Returns credentials capable of signing URLs via IAM Credentials API
    (impersonated creds), or None if not configured.
    """
    if not SIGNER_SA_EMAIL:
        return None

    source_creds, _ = google.auth.default()

    # This uses IAM Credentials API under the hood.
    # Requires:
    # - iamcredentials.googleapis.com enabled
    # - roles/iam.serviceAccountTokenCreator on SIGNER_SA_EMAIL for the calling identity
    return impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=SIGNER_SA_EMAIL,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )


def download_blob(blob_name: str, destination_file_name: str) -> None:
    """
    Downloads a blob from the configured GCS bucket.
    :param blob_name: The GCS object name (e.g., 'users/user_id/input/document.pdf').
    :param destination_file_name: The local path to save the downloaded file.
    """
    _require_bucket()

    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)

    # Ensure parent directory exists for the destination file
    parent = os.path.dirname(destination_file_name)
    if parent:
        os.makedirs(parent, exist_ok=True)

    blob.download_to_filename(destination_file_name)
    print(f"[storage] Downloaded gs://{BUCKET_NAME}/{blob_name} -> {destination_file_name}")


def upload_blob(source_file_name: str, blob_name: str) -> None:
    """
    Uploads a file to the configured GCS bucket.
    :param source_file_name: The local path of the file to upload.
    :param blob_name: The GCS object name (e.g., 'users/user_id/output/audio.mp3').
    """
    _require_bucket()

    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(source_file_name)
    print(f"[storage] Uploaded {source_file_name} -> gs://{BUCKET_NAME}/{blob_name}")


def delete_blob(blob_name: str) -> None:
    """
    Deletes the blob at gs://<BUCKET_NAME>/<blob_name>.
    :param blob_name: The GCS object name to delete.
    """
    _require_bucket()

    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.delete()
    print(f"[storage] Deleted gs://{BUCKET_NAME}/{blob_name}")


def presigned_url(
    blob_name: str,
    expiration_seconds: int = 3600,
    method: str = "GET",
    content_type: Optional[str] = None,
) -> str:
    """
    Generates a v4 signed URL for downloading or uploading a blob.

    Cloud Run:
      Uses IAM Credentials API signing (impersonated creds). Requires SIGNER_SA_EMAIL.
    Local:
      If SIGNER_SA_EMAIL is set, uses IAM signing too.
      Otherwise, uses default credentials signing (works only if you have a SA key file).

    :param blob_name: GCS object name
    :param expiration_seconds: URL expiration in seconds
    :param method: 'GET' or 'PUT'
    :param content_type: optional content-type to bind into the signature (recommended for PUT)
    """
    _require_bucket()

    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)

    print(
        f"[storage] Generating signed URL: method={method}, exp={expiration_seconds}s, "
        f"blob=gs://{BUCKET_NAME}/{blob_name}, content_type={content_type}"
    )

    creds = _signing_credentials_if_available()

    # In Cloud Run we REQUIRE IAM signing to avoid the token-only signing issue.
    if IS_CLOUD_RUN and creds is None:
        raise ValueError(
            "SIGNER_SA_EMAIL is required on Cloud Run to generate signed URLs. "
            "Set SIGNER_SA_EMAIL=text2audio-sa@text-to-audio-460215.iam.gserviceaccount.com"
        )

    kwargs = dict(
        version="v4",
        expiration=datetime.timedelta(seconds=expiration_seconds),
        method=method,
    )

    # Only include content_type if provided (especially important for PUT)
    if content_type:
        kwargs["content_type"] = content_type

    # If creds is provided, generate_signed_url will use IAM Credentials signing.
    if creds is not None:
        signed_url = blob.generate_signed_url(credentials=creds, **kwargs)
    else:
        # Local fallback: requires a service account key file as ADC to sign.
        signed_url = blob.generate_signed_url(**kwargs)

    print("[storage] Signed URL generated successfully.")
    return signed_url

import os
import uuid
import subprocess
import google.auth
import re
import time
import json
import base64
import hmac
import hashlib
# Removed argparse as it's not used for FastAPI app execution
# from argparse import ArgumentParser # No longer needed

from fastapi import FastAPI, HTTPException, Query, Request # Import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse # Still imported, but not used for final MP3 output
from pydantic import BaseModel
from typing import Optional # Import Optional

# Assuming these are in your project directory
from extracter import extract_pdf_text, extract_epub_text, ocr_pdf
from filter import parse_ocr_data, cluster_body_sizes, filter_body_words
from tts import long_synthesize_to_wav
from storage import download_blob, upload_blob, presigned_url, delete_blob, get_blob_size # Ensure delete_blob is imported
from quota import check_and_update_quota, get_quota_status

# --- Configuration (read from environment variables) ---
# IMPORTANT: For local testing, ensure these are set in your shell or via the -e flag in docker run.
# For Cloud Run, these will be set as service environment variables.
BUCKET_NAME = os.getenv("BUCKET_NAME", "my-text-to-audio-bucket") # Replace with your actual GCS bucket name or ensure env var is always set
VOICE = os.getenv("VOICE_NAME", "en-US-Wavenet-F")
LANG_CODE = os.getenv("LANG_CODE", "en-US") # Derived from voice, but explicitly set for clarity
API_KEY = os.getenv("API_KEY")

# Resolve GCP project ID from env or ADC, so Cloud Run and local dev both work without manual env setup.
GOOGLE_CLOUD_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
if not GOOGLE_CLOUD_PROJECT_ID:
    try:
        _, GOOGLE_CLOUD_PROJECT_ID = google.auth.default()
        print(f"Resolved project ID from ADC: {GOOGLE_CLOUD_PROJECT_ID}")
    except Exception:
        GOOGLE_CLOUD_PROJECT_ID = None
        print("WARNING: Could not resolve project ID from ADC; Text-to-Speech will fail without it.")

# Hard file size limit (same as frontend guard). Prevents oversized uploads via direct signed URL use.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Temporary directory inside the Docker container.
# This is where all intermediate files (downloaded input, WAV, MP3) will be stored
# before being streamed or deleted.
TMP_DIR = "/tmp/audio_processing"

# Ensure the temporary directory exists when the app starts.
# This runs once when the module is loaded.
os.makedirs(TMP_DIR, exist_ok=True)
print(f"Temporary directory '{TMP_DIR}' ensured to exist.")

# Initialize the FastAPI application
app = FastAPI()

# --- CORS Middleware ---
# This must be placed before any routes are defined.
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3003",  # Allow your Next.js frontend, currently running on 3003
    "https://pdftoaudioconverter.netlify.app",
    # You can add other origins here, e.g., your deployed frontend URL
    # "https://your-frontend-domain.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)


# --- Pydantic Models for Request Bodies ---

class UploadUrlRequest(BaseModel):
    """
    Request body for getting a signed URL for file upload.
    """
    user_id: str
    file_name: str # The original name of the file to be uploaded (e.g., "my_document.pdf")
    content_type: Optional[str] = None

class ProcessRequest(BaseModel):
    """
    Request body for processing a document.
    remote_path here refers to the full GCS path to the input file,
    which the frontend obtained from the /upload_url endpoint.
    """
    user_id: str
    remote_path: str # e.g., "users/your-uuid/input/my_doc.pdf"
    voice_name: str | None = None # Optional voice name from the frontend
    process_token: Optional[str] = None


PROCESS_TOKEN_TTL_SECONDS = 15 * 60


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _sign_process_token(payload: dict) -> str:
    if not API_KEY:
        raise ValueError("API key not configured.")
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    signature = hmac.new(API_KEY.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify_process_token(token: str, user_id: str, remote_path: str) -> bool:
    if not API_KEY:
        return False
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return False
    expected_sig = hmac.new(
        API_KEY.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return False
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return False
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return False
    return payload.get("user_id") == user_id and payload.get("remote_path") == remote_path


def _require_api_key(request: Request) -> None:
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured.")
    provided = request.headers.get("x-api-key")
    if not provided or provided != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized.")


def _authorize_process(request: Request, payload: ProcessRequest) -> None:
    if API_KEY:
        provided = request.headers.get("x-api-key")
        if provided and provided == API_KEY:
            return
    if payload.process_token and _verify_process_token(
        payload.process_token, payload.user_id, payload.remote_path
    ):
        return
    raise HTTPException(status_code=401, detail="Unauthorized.")


def _validate_user_id(user_id: str) -> None:
    if not user_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id.")


def _validate_file_name(file_name: str) -> None:
    if not file_name or len(file_name) > 200:
        raise HTTPException(status_code=400, detail="Invalid file_name.")
    if os.path.basename(file_name) != file_name:
        raise HTTPException(status_code=400, detail="Invalid file_name.")
    if ".." in file_name or "/" in file_name or "\\" in file_name:
        raise HTTPException(status_code=400, detail="Invalid file_name.")
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in {".pdf", ".epub"}:
        raise HTTPException(status_code=400, detail="Unsupported file type.")


def _validate_remote_path(user_id: str, remote_path: str) -> None:
    if not remote_path:
        raise HTTPException(status_code=400, detail="Invalid remote_path.")
    if ".." in remote_path or "\\" in remote_path:
        raise HTTPException(status_code=400, detail="Invalid remote_path.")
    prefix = f"users/{user_id}/input/"
    if not remote_path.startswith(prefix):
        raise HTTPException(status_code=400, detail="Invalid remote_path.")
    file_name = os.path.basename(remote_path)
    _validate_file_name(file_name)


def _validate_file_id(file_id: str) -> None:
    if not file_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", file_id):
        raise HTTPException(status_code=400, detail="Invalid file_id.")


# --- New Endpoint: Get Signed URL for Upload ---
@app.post("/upload_url")
async def get_upload_signed_url(request: Request, upload_request: Optional[UploadUrlRequest] = None): # Use Request and Optional Pydantic model
    """
    Generates a presigned URL for the frontend to upload a file directly to GCS.
    The file will be placed in the user's input folder:
    gs://{bucket}/users/{user_id}/input/{file_name}
    """
    if request.method == "OPTIONS":
        # For OPTIONS requests, just return a 200 OK. CORS middleware should handle headers.
        return {"message": "OK"}

    if not upload_request:
        raise HTTPException(status_code=400, detail="Request body is missing for POST method.")

    _require_api_key(request)
    print(f"Received request for /upload_url. User ID: {upload_request.user_id}, File Name: {upload_request.file_name}")
    _validate_user_id(upload_request.user_id)
    _validate_file_name(upload_request.file_name)
    user_id = upload_request.user_id
    file_name = upload_request.file_name
    # Use provided content_type (if any) so the browser's PUT matches the signature.
    # Fallback keeps uploads working for callers that don't pass it.
    content_type_for_signed_url = upload_request.content_type or "application/octet-stream"

    # Construct the full GCS path where the file will be uploaded
    # This ensures user isolation and places it in the 'input' folder
    gcs_blob_name = f"users/{user_id}/input/{file_name}"
    print(f"Constructed GCS blob name: {gcs_blob_name}")

    try:
        print(f"Attempting to generate signed URL for {gcs_blob_name}...")
        # Generate a signed URL for a PUT operation (upload)
        # Expiration set to 1 hour (3600 seconds)
        signed_url = presigned_url(
            gcs_blob_name,
            expiration_seconds=3600,
            method="PUT",
            content_type=content_type_for_signed_url,
        )
        print(f"Successfully generated signed URL for {gcs_blob_name}.")
        process_token = _sign_process_token(
            {
                "user_id": user_id,
                "remote_path": gcs_blob_name,
                "exp": int(time.time()) + PROCESS_TOKEN_TTL_SECONDS,
            }
        )
        return {
            "signed_url": signed_url,
            "gcs_path": gcs_blob_name,
            "process_token": process_token,
        }
    except Exception as e:
        print(f"Error generating signed URL for {gcs_blob_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not generate upload URL: {e}")


# --- Main Endpoint: Process Document ---
@app.post("/process")
async def process_document_endpoint(request: Request, payload: ProcessRequest): # Renamed to avoid conflict with old process_file
    """
    Processes a PDF/EPUB, converts it to MP3, uploads to GCS, and returns a signed URL.
    Input and temporary files are immediately deleted from GCS and local storage.
    """
    _authorize_process(request, payload)
    _validate_user_id(payload.user_id)
    _validate_remote_path(payload.user_id, payload.remote_path)
    user_id = payload.user_id
    # remote_path is now the full GCS path provided by the frontend after /upload_url
    full_gcs_input_path = payload.remote_path # e.g., "users/your-uuid/input/my_doc.pdf"
    voice_name = payload.voice_name or VOICE # Use voice from request or fallback to default

    # Extract language code from voice name (e.g., "en-US-Wavenet-F" -> "en-US")
    # This ensures the language code matches the selected voice
    if voice_name and "-" in voice_name:
        lang_code = "-".join(voice_name.split("-")[:2])  # Get "en-US", "en-GB", "en-AU", etc.
    else:
        lang_code = LANG_CODE  # Fallback to default

    # Extract filename for local storage (e.g., "my_doc.pdf")
    local_in_filename = os.path.basename(full_gcs_input_path)
    local_in = os.path.join(TMP_DIR, local_in_filename)

    # Generate a unique ID for this specific conversion job instance
    job_id = uuid.uuid4().hex

    # Define paths for temporary files within the container's /tmp
    # Using job_id in names to prevent conflicts if multiple processes run
    local_wav_path = os.path.join(TMP_DIR, f"synthesized-{job_id}.wav")
    local_mp3_path = os.path.join(TMP_DIR, f"final-{job_id}.mp3")

    # List of local files that need to be cleaned up.
    # We add them here and remove from list as they are deleted to ensure robustness.
    files_to_cleanup_locally = [local_in, local_wav_path, local_mp3_path]

    # Define the GCS path for the final MP3 output
    # This will be in the user's specific output folder
    output_mp3_gcs_name = f"final-{job_id}.mp3" # Unique name for the output MP3
    gcs_output_mp3_path = f"users/{user_id}/output/{output_mp3_gcs_name}"


    try:
        # Guardrail: enforce max file size before processing
        blob_size = get_blob_size(full_gcs_input_path)
        if blob_size > MAX_UPLOAD_BYTES:
            try:
                delete_blob(full_gcs_input_path)
            except Exception as e:
                print(f"Warning: Failed to delete oversized file {full_gcs_input_path} from GCS: {e}")
            raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.")

        # 1) Download input PDF/EPUB from GCS
        print(f"Downloading input file from GCS: {full_gcs_input_path} to {local_in}")
        download_blob(full_gcs_input_path, local_in)

        # --- IMMEDIATE DELETION STEP 1: Delete the original input PDF/EPUB from GCS ---
        try:
            print(f"Deleting original input file from GCS: {full_gcs_input_path}")
            delete_blob(full_gcs_input_path)
        except Exception as e:
            print(f"Warning: Failed to delete original input file {full_gcs_input_path} from GCS: {e}")
        # --- END DELETION STEP 1 ---

        # 2) Extract raw text (OCR fallback for scanned PDFs)
        ext = os.path.splitext(local_in)[1].lower()
        raw_text = ""
        if ext == ".epub":
            print(f"Extracting text from EPUB: {local_in}")
            raw_text = extract_epub_text(local_in)
        elif ext == ".pdf":
            print(f"Extracting text from PDF: {local_in}")
            raw_text = extract_pdf_text(local_in)
            if not raw_text.strip():
                print(f"No text extracted, attempting OCR for {local_in}")
                # Assuming ocr_pdf takes local file path. If it needs GCS path, adjust here.
                ocr_data = ocr_pdf(local_in)
                words, sizes = parse_ocr_data(ocr_data)
                breaks = cluster_body_sizes(sizes)
                raw_text = " ".join(filter_body_words(list(zip(words, sizes)), breaks))
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported extension: {ext}")

        # Clean up local input file immediately after extraction
        if os.path.exists(local_in):
            os.remove(local_in)
            print(f"Deleted local input file: {local_in}")
            # Mark as cleaned up so finally block doesn't try again
            if local_in in files_to_cleanup_locally: files_to_cleanup_locally.remove(local_in)

        # Check text length - Conservative limit to stay within free tier
        max_chars_per_doc = 100000  # 100k characters per document (~65 pages)
        daily_limit = 50000  # 50k characters per day (~30 pages)
        monthly_limit = 1000000  # 1M characters per month (Google free tier)

        text_length = len(raw_text)

        if text_length > max_chars_per_doc:
            print(f"Document too long: {text_length} chars (max {max_chars_per_doc})")
            raise HTTPException(
                status_code=413,
                detail=f"Document is too long ({text_length:,} characters). Maximum is {max_chars_per_doc:,} characters (~65 pages). Try a shorter document."
            )

        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract any text from this document. The file may be empty, corrupted, or image-only.")

        # Check quota before processing
        allowed, quota_msg, remaining_daily, remaining_monthly = check_and_update_quota(text_length)
        print(f"Quota check: {quota_msg}")

        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=quota_msg
            )

        # 3) Synthesize Long-Audio to WAV in GCS
        # The TTS API often writes directly to GCS.
        gcs_wav_name = f"synthesized-{job_id}.wav"
        # The WAV is stored in a user-specific temporary folder in GCS
        gcs_wav_path = f"users/{user_id}/tmp/{gcs_wav_name}"

        print(f"Synthesizing audio to GCS: gs://{BUCKET_NAME}/{gcs_wav_path}")
        print(f"Text length: {len(raw_text):,} characters, Voice: {voice_name}, Language: {lang_code}")

        try:
            long_synthesize_to_wav(
                raw_text=raw_text,
                gcs_output_wav=f"gs://{BUCKET_NAME}/{gcs_wav_path}",
                voice_name=voice_name,
                language_code=lang_code,  # Use the extracted language code instead of hardcoded LANG_CODE
                project_id=GOOGLE_CLOUD_PROJECT_ID # Pass the project ID
            )
        except Exception as tts_error:
            print(f"TTS API error: {tts_error}")
            error_msg = str(tts_error)
            if "QUOTA_EXCEEDED" in error_msg or "quota" in error_msg.lower():
                raise HTTPException(
                    status_code=429,
                    detail="Daily quota exceeded. Please try again tomorrow."
                )
            elif "PERMISSION_DENIED" in error_msg or "permission" in error_msg.lower():
                raise HTTPException(
                    status_code=403,
                    detail="Audio generation permission denied. Please contact support."
                )
            elif "INTERNAL" in error_msg and "TTS_BACKEND" in error_msg:
                raise HTTPException(
                    status_code=500,
                    detail="Audio generation service temporarily unavailable. This usually happens with very large documents. Try a shorter document or try again later."
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to generate audio. Please try a shorter document or contact support."
                )

        # 4) Download WAV locally
        print(f"Downloading WAV from GCS: {gcs_wav_path} to {local_wav_path}")
        # Note: download_blob expects just the blob name, not the full GCS path (gs://bucket/...)
        # So, it should be gcs_wav_path (which is 'users/{user_id}/tmp/{wav_name}')
        download_blob(gcs_wav_path, local_wav_path)

        # --- IMMEDIATE DELETION STEP 2: Delete the temporary WAV file from GCS ---
        try:
            print(f"Deleting temporary WAV file from GCS: {gcs_wav_path}")
            delete_blob(gcs_wav_path)
        except Exception as e:
            print(f"Warning: Failed to delete temporary WAV file {gcs_wav_path} from GCS: {e}")
        # --- END DELETION STEP 2 ---

        # 5) Transcode WAV to MP3 via ffmpeg
        print(f"Transcoding WAV to MP3: {local_wav_path} to {local_mp3_path}")
        subprocess.run([
            "ffmpeg", "-y", "-i", local_wav_path,
            "-codec:a", "libmp3lame", "-b:a", "192k",
            local_mp3_path
        ], check=True)

        # Clean up local WAV file immediately after transcoding
        if os.path.exists(local_wav_path):
            os.remove(local_wav_path)
            print(f"Deleted local WAV file: {local_wav_path}")
            # Mark as cleaned up
            if local_wav_path in files_to_cleanup_locally: files_to_cleanup_locally.remove(local_wav_path)

        # --- Re-enabled: Upload MP3 to GCS ---
        print(f"Uploading final MP3 to GCS: {gcs_output_mp3_path}")
        upload_blob(local_mp3_path, gcs_output_mp3_path)

        # Clean up local MP3 file after upload
        if os.path.exists(local_mp3_path):
            os.remove(local_mp3_path)
            print(f"Deleted local MP3 file: {local_mp3_path}")
            # Mark as cleaned up
            if local_mp3_path in files_to_cleanup_locally: files_to_cleanup_locally.remove(local_mp3_path)

        # Return presigned URL for the final MP3
        print(f"Generating signed URL for MP3: {gcs_output_mp3_path}")
        # Use 'GET' method for download URL
        signed_url = presigned_url(gcs_output_mp3_path, expiration_seconds=3600, method='GET') # 1 hour expiration for download

        return {"audio_url": signed_url}

    except HTTPException as http_exc:
        print(f"HTTP Exception caught: {http_exc.detail}. Initiating local file cleanup.")
        raise http_exc # Re-raise the HTTPException after cleanup
    except Exception as e:
        print(f"An unexpected error occurred: {e}. Initiating local file cleanup.")
        error_msg = str(e)

        # Make common errors user-friendly
        if "jenks_breaks" in error_msg or "nb_class" in error_msg or "Number of class" in error_msg:
            raise HTTPException(
                status_code=400,
                detail="Could not extract readable text from this PDF. This may be an image-only or scanned document with text in an unsupported language. Try a different document with selectable text."
            )
        elif "ebooklib" in error_msg or "EPUB" in error_msg:
            raise HTTPException(
                status_code=500,
                detail="Error reading EPUB file. The file may be corrupted or in an unsupported format."
            )
        elif "Permission denied" in error_msg or "403" in error_msg:
            raise HTTPException(
                status_code=403,
                detail="Permission denied. Please contact support."
            )
        elif "OCR" in error_msg or "vision" in error_msg:
            raise HTTPException(
                status_code=500,
                detail="OCR (text recognition) failed. The document may contain unsupported text or be too complex to process."
            )
        else:
            # Generic error for unexpected issues - include first part of error for debugging
            detail_msg = f"Could not process this document. It may contain unsupported content or formatting."
            if error_msg:
                # Include sanitized error hint
                error_hint = error_msg[:100].replace('\n', ' ')
                detail_msg += f" (Error: {error_hint})"
            raise HTTPException(status_code=500, detail=detail_msg)
    finally:
        # Final cleanup for any local files that might still exist (e.g., if an error occurred before removal)
        for f in files_to_cleanup_locally:
            if os.path.exists(f):
                os.remove(f)
                print(f"Cleaned up lingering local file in finally block: {f}")


# --- Quota Status Endpoint ---
@app.get("/quota")
async def get_quota():
    """
    Get current quota usage status.
    Returns daily and monthly character usage and limits.
    """
    try:
        status = get_quota_status()
        return {
            "daily": {
                "used": status["daily"]["used"],
                "limit": status["daily"]["limit"],
                "remaining": status["daily"]["remaining"],
                "percentage": round((status["daily"]["used"] / status["daily"]["limit"]) * 100, 1)
            },
            "monthly": {
                "used": status["monthly"]["used"],
                "limit": status["monthly"]["limit"],
                "remaining": status["monthly"]["remaining"],
                "percentage": round((status["monthly"]["used"] / status["monthly"]["limit"]) * 100, 1)
            },
            "limits": {
                "per_document": 100000,
                "daily": 50000,
                "monthly": 1000000
            }
        }
    except Exception as e:
        print(f"Error getting quota status: {e}")
        return {
            "error": "Could not retrieve quota status",
            "limits": {
                "per_document": 100000,
                "daily": 50000,
                "monthly": 1000000
            }
        }


# --- Updated /cleanup endpoint to use user_id ---
@app.delete("/cleanup")
async def cleanup_endpoint(
    request: Request,
    user_id: str, # Now requires user_id
    file_id: str = Query(..., description="Base filename (without extension) for the user's files to delete")
):
    """
    Delete the WAV and MP3 blobs for the given file_id for a specific user.
    This is useful for manually cleaning up user's output files if needed.
    """
    _require_api_key(request)
    _validate_user_id(user_id)
    _validate_file_id(file_id)
    # Construct user-specific paths for deletion
    tmp_wav_path    = f"users/{user_id}/tmp/{file_id}.wav"
    output_mp3_path = f"users/{user_id}/output/{file_id}.mp3"

    errors = []
    for blob_path in (tmp_wav_path, output_mp3_path):
        try:
            delete_blob(blob_path)
            print(f"Cleaned up GCS blob: {blob_path}")
        except Exception as e:
            errors.append(f"{blob_path}: {e}")
    if errors:
        # Raise HTTPException only if there are actual errors during deletion
        raise HTTPException(status_code=500, detail={"errors": errors})
    return {"status": "deleted", "user_id": user_id, "file_id": file_id}


# --- Removed old __main__ block for script execution ---
# This application is now designed to be run by Uvicorn.
# The port can be configured via the 'PORT' environment variable.
# Example: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
# The argparse block is no longer relevant for the FastAPI application.

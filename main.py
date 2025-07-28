#!/usr/bin/env python3
import os
import uuid
import subprocess
import argparse
from extracter import extract_pdf_text, extract_epub_text, ocr_pdf
from filter import parse_ocr_data, cluster_body_sizes, filter_body_words
from tts import long_synthesize_to_wav
from storage import download_blob, upload_blob, presigned_url

BUCKET      = os.getenv("BUCKET_NAME", "my-text-to-audio-bucket")
VOICE       = os.getenv("VOICE_NAME", "en-US-Wavenet-F")
LANG_CODE  = "-".join(VOICE.split("-")[:2])
TMP_DIR     = "/tmp"

def process_file(remote_path: str) -> str:
    # 1) fetch input PDF/EPUB
    local_in = os.path.join(TMP_DIR, os.path.basename(remote_path))
    download_blob(remote_path, local_in)

    # 2) extract raw text
    ext = os.path.splitext(local_in)[1].lower()
    if ext == ".epub":
        raw = extract_epub_text(local_in)
    elif ext == ".pdf":
        raw = extract_pdf_text(local_in)
        if not raw.strip():
            ocr_data = ocr_pdf(f"gs://{BUCKET}/{remote_path}")
            words, sizes = parse_ocr_data(ocr_data)
            breaks = cluster_body_sizes(sizes)
            raw = " ".join(filter_body_words(list(zip(words, sizes)), breaks))
    else:
        raise ValueError(f"Unsupported extension: {ext}")

    # 3) Long‑Audio to WAV in GCS
    base_name  = os.path.splitext(os.path.basename(local_in))[0]
    unique_id  = uuid.uuid4()
    wav_name   = f"{base_name}-{unique_id}.wav"
    gcs_wav    = f"gs://{BUCKET}/tmp/{wav_name}"
    long_synthesize_to_wav(
        raw_text=raw,
        gcs_output_wav=gcs_wav,
        voice_name=VOICE,
        language_code=LANG_CODE
    )

    # 4) Download WAV locally
    local_wav  = os.path.join(TMP_DIR, wav_name)
    download_blob(f"tmp/{wav_name}", local_wav)

    # 5) Transcode WAV → MP3 via ffmpeg
    mp3_name   = f"{base_name}-{unique_id}.mp3"
    local_mp3  = os.path.join(TMP_DIR, mp3_name)
    subprocess.run([
        "ffmpeg", "-y", "-i", local_wav,
        "-codec:a", "libmp3lame", "-b:a", "192k",
        local_mp3
    ], check=True)

    # 6) Upload MP3 & return signed URL
    remote_mp3 = f"output/{mp3_name}"
    upload_blob(local_mp3, remote_mp3)
    return presigned_url(remote_mp3)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True,
                   help="GCS key under BUCKET, e.g. input/book.pdf")
    args = p.parse_args()

    print(process_file(args.input))

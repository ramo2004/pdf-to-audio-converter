# PDF/EPUB to Audio Converter

This is a full-stack app that converts PDF/EPUB documents into MP3 audio using Google Cloud services.

## Summary

- **Backend**: FastAPI service that generates signed upload URLs, processes documents, and returns signed download URLs.
- **Frontend**: Next.js app that uploads files directly to GCS via signed URL, triggers processing, and plays/downloads MP3 output.
- **Storage/TTS**: Google Cloud Storage + Google Cloud Text-to-Speech Long Audio.

## Backend (Python/FastAPI)

**Core endpoints (all require `X-API-Key`):**
- `POST /upload_url`: Generates a signed URL for direct upload to GCS.
- `POST /process`: Downloads the uploaded file, extracts text (OCR fallback for scanned PDFs), synthesizes WAV via TTS, converts to MP3 with ffmpeg, uploads MP3 to GCS, returns a signed download URL.
- `DELETE /cleanup`: Deletes temporary WAV and output MP3 for a given user and file ID.

**Files:**
- `main.py`: API server and processing pipeline.
- `extracter.py`: PDF/EPUB extraction and OCR.
- `filter.py`: OCR post-processing (filters body text using Jenks breaks).
- `tts.py`: Long-audio synthesis to WAV in GCS.
- `storage.py`: GCS operations and signed URL generation.

## Frontend (Next.js/React)

**Main UI**
- `text-to-audio-frontend/src/app/page.tsx`
- Lets users select a PDF/EPUB, choose a voice, uploads to GCS via signed URL, triggers processing, then plays/downloads MP3.
- User IDs are generated per request (random UUID), so they are not hardcoded.

**Proxy routes (server-side)**
- `text-to-audio-frontend/src/app/api/upload_url/route.ts`
- `text-to-audio-frontend/src/app/api/process/route.ts`
- These forward requests to the backend and include `X-API-Key`.

## Data Flow

User uploads file → GCS (signed URL)  
↓  
Backend downloads → Extracts text → TTS to WAV (in GCS)  
↓  
Download WAV → ffmpeg → MP3 → Upload to GCS  
↓  
Signed URL returned to user

## Deploy: Backend (Cloud Run)

### One-time env vars

```bash
gcloud run services update pdf2audio-service \
  --region us-central1 \
  --set-env-vars BUCKET_NAME=my-text-to-audio-bucket,SIGNER_SA_EMAIL=text2audio-sa@text-to-audio-460215.iam.gserviceaccount.com,API_KEY=YOUR_SECRET_HERE
```

Replace `YOUR_SECRET_HERE` with a long random string.

### Deploy

```bash
gcloud run deploy pdf2audio-service \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --service-account text2audio-sa@text-to-audio-460215.iam.gserviceaccount.com
```

### Health check

```bash
curl -s https://pdf2audio-service-542560471542.us-central1.run.app/openapi.json | head
```

### Quick test (requires API key)

```bash
curl -s -X POST "https://pdf2audio-service-542560471542.us-central1.run.app/upload_url" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_SECRET_HERE" \
  -d '{"user_id":"omar","file_name":"test.pdf"}'
```

Expected: JSON containing `signed_url` and `gcs_path`.

## Run Frontend Locally

Create `text-to-audio-frontend/.env.local`:

```bash
BACKEND_URL="https://pdf2audio-service-542560471542.us-central1.run.app"
API_KEY="YOUR_SECRET_HERE"
```

Then run:

```bash
cd text-to-audio-frontend
npm install
npm run dev
```

Open: http://localhost:3000

## Deploy: Frontend (Netlify)

1) Connect GitHub repo in Netlify.
2) Build settings:
   - Base directory: `text-to-audio-frontend`
   - Build command: `npm run build`
   - Publish directory: leave blank (Next.js plugin handles it)
3) Set Netlify env vars:
   - `BACKEND_URL` = `https://pdf2audio-service-542560471542.us-central1.run.app`
   - `API_KEY` = `YOUR_SECRET_HERE`
4) After deploy, confirm site URL is:
   - `https://pdftoaudioconverter.netlify.app`

## GCS CORS

Update your bucket CORS to include Netlify:

```bash
cat > cors.json <<'EOF'
[
  {
    "origin": ["http://localhost:3000", "https://pdftoaudioconverter.netlify.app"],
    "method": ["GET", "PUT", "HEAD", "OPTIONS"],
    "responseHeader": ["Content-Type", "x-goog-resumable"],
    "maxAgeSeconds": 3600
  }
]
EOF

gcloud storage buckets update gs://my-text-to-audio-bucket --cors-file=cors.json
```


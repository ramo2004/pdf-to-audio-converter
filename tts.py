import os
import google.auth
from google.cloud import texttospeech_v1 as tts_v1

client = tts_v1.TextToSpeechLongAudioSynthesizeClient()

def long_synthesize_to_wav(
    raw_text: str,
    gcs_output_wav: str,
    voice_name: str = "en-US-Wavenet-F",
    language_code: str = "en-US",
    project_id: str = None # project_id is now expected to be passed in
) -> None:
    # If project_id is not provided, it will still try to get it from the environment,
    # but main.py is now responsible for passing it.
    if not project_id:
        # Fallback for direct calls or if main.py doesn't provide it (less ideal)
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
        if not project_id:
            try:
                _, project_id = google.auth.default()
            except Exception:
                project_id = None
        if not project_id:
            raise ValueError("Google Cloud Project ID not provided and not found in environment variables or ADC.")

    parent = f"projects/{project_id}/locations/us-central1"

    request = tts_v1.SynthesizeLongAudioRequest(
        parent=parent,
        input=tts_v1.SynthesisInput(text=raw_text),
        voice=tts_v1.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        ),
        audio_config=tts_v1.AudioConfig(
            audio_encoding=tts_v1.AudioEncoding.LINEAR16
        ),
        output_gcs_uri=gcs_output_wav,
    )

    op = client.synthesize_long_audio(request=request)
    op.result(timeout=300)

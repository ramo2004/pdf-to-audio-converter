"use client";

import { useState, useMemo } from "react";
import styles from "./page.module.css";

// A list of some available Google Cloud TTS voices
const voices = [
  { name: "en-US-Wavenet-F", label: "US Female" },
  { name: "en-US-Wavenet-A", label: "US Male" },
  { name: "en-GB-Wavenet-F", label: "UK Female" },
  { name: "en-GB-Wavenet-A", label: "UK Male" },
  { name: "en-AU-Wavenet-F", label: "AU Female" },
  { name: "en-AU-Wavenet-A", label: "AU Male" },
];

export default function Home() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedVoice, setSelectedVoice] = useState<string>(voices[0].name);
  const [status, setStatus] = useState<
    "idle" | "uploading" | "processing" | "success" | "error"
  >("idle");
  const [progress, setProgress] = useState<number>(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stepMessage, setStepMessage] = useState<string>("");

  const MAX_MB = 20;

  const generateUserId = () => {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
    return `u_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files[0]) {
      setSelectedFile(event.target.files[0]);
      setStatus("idle");
      setError(null);
      setAudioUrl(null);
      setProgress(0);
    }
  };

  // Helper to make POST requests with better error handling
  const getStringProp = (value: unknown, key: string): string | undefined => {
    if (!value || typeof value !== "object") {
      return undefined;
    }
    const record = value as Record<string, unknown>;
    const prop = record[key];
    return typeof prop === "string" ? prop : undefined;
  };

  const getErrorDetail = (value: unknown): string | undefined => {
    if (!value || typeof value !== "object") {
      return undefined;
    }
    const record = value as Record<string, unknown>;
    const detail = record.detail;
    if (typeof detail === "string") {
      return detail;
    }
    const error = record.error;
    return typeof error === "string" ? error : undefined;
  };

  const getErrorMessage = (err: unknown): string =>
    err instanceof Error ? err.message : "An unknown error occurred.";

  const postJson = async (url: string, body: object): Promise<unknown> => {
    console.log(`[Frontend] POST ${url}`, body);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const text = await res.text();
    console.log(`[Frontend] Response ${res.status}:`, text);

    let json: unknown = null;
    try {
      json = JSON.parse(text);
    } catch {
      // Not JSON
    }

    if (!res.ok) {
      const errorMsg = getErrorDetail(json) || text || `HTTP ${res.status}`;
      throw new Error(errorMsg);
    }

    return json ?? text;
  };

  const uploadFileWithProgress = (url: string, file: File) => {
    return new Promise<Response>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", url);
      xhr.setRequestHeader("Content-Type", file.type || "application/pdf");

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = (event.loaded / event.total) * 100;
          setProgress(percent);
          setStepMessage(`Uploading... ${percent.toFixed(0)}%`);
        }
      };

      xhr.onload = () => {
        resolve(new Response(xhr.responseText, { status: xhr.status }));
      };

      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.onabort = () => reject(new Error("Upload aborted"));

      xhr.send(file);
    });
  };

  const handleUploadAndProcess = async () => {
    if (!selectedFile) {
      setError("Please select a file first.");
      setStatus("error");
      return;
    }

    if (selectedFile.size > MAX_MB * 1024 * 1024) {
      setError(`File too large. Max ${MAX_MB}MB.`);
      setStatus("error");
      return;
    }

    setStatus("uploading");
    setError(null);
    setAudioUrl(null);
    setProgress(0);
    setStepMessage("Requesting upload URL...");

    try {
      const requestUserId = generateUserId();
      // 1. Get a signed URL for upload (via local proxy)
      console.log("[Frontend] Step 1: Getting signed upload URL...");
      const uploadUrlData = await postJson("/api/upload_url", {
        user_id: requestUserId,
        file_name: selectedFile.name,
        content_type: selectedFile.type || "application/octet-stream",
      });

      const signedUrl = getStringProp(uploadUrlData, "signed_url");
      const gcsPath = getStringProp(uploadUrlData, "gcs_path");
      if (!signedUrl || !gcsPath) {
        throw new Error("No signed_url returned from backend");
      }
      console.log("[Frontend] Got signed URL, gcs_path:", gcsPath);
      setStepMessage("Uploading file...");

      // 2. Upload the file directly to GCS using the signed URL
      console.log("[Frontend] Step 2: Uploading file to GCS...");
      const uploadResponse = await uploadFileWithProgress(signedUrl, selectedFile);

      if (!uploadResponse.ok) {
        const errorText = await uploadResponse.text();
        throw new Error(
          `GCS upload failed (${uploadResponse.status}): ${errorText}`
        );
      }
      console.log("[Frontend] File uploaded to GCS successfully");
      setProgress(100);
      setStepMessage("Upload complete");

      // 3. Trigger backend processing (via local proxy)
      setStatus("processing");
      setProgress(0);
      setStepMessage("Processing document (this may take a minute)...");
      console.log("[Frontend] Step 3: Processing document...");

      const processData = await postJson("/api/process", {
        user_id: requestUserId,
        remote_path: gcsPath,
        voice_name: selectedVoice,
      });

      const audioUrl = getStringProp(processData, "audio_url");
      if (!audioUrl) {
        throw new Error("No audio_url returned from backend");
      }

      console.log("[Frontend] Processing complete, audio URL received");
      setAudioUrl(audioUrl);
      setStatus("success");
      setStepMessage("Done! Your audio is ready.");
    } catch (err: unknown) {
      console.error("[Frontend] Error:", err);
      setError(getErrorMessage(err));
      setStatus("error");
      setStepMessage("");
    }
  };

  const buttonText = useMemo(() => {
    switch (status) {
      case "uploading":
        return `Uploading... ${progress.toFixed(0)}%`;
      case "processing":
        return "Processing...";
      case "success":
        return "Done!";
      default:
        return "Convert to Audio";
    }
  }, [status, progress]);

  return (
    <main className={styles.shell}>
      <div className={styles.container}>
        <header className={styles.header}>
          <div className={styles.badge}>Text to Audio</div>
          <h1 className={styles.title}>
            Convert documents to audio narration
          </h1>
          <p className={styles.subtitle}>
            Upload a PDF or EPUB file, select a voice, and download your audio file in seconds.
          </p>
          <p className={styles.statLine}>
            MP3 format • 6 voices • PDF and EPUB support
          </p>
        </header>

        <div className={styles.form}>

          {/* File Upload Section */}
          <div className={styles.formGroup}>
            <label htmlFor="file-upload" className={styles.label}>
              File
            </label>
            <div className={styles.fileInput}>
              <input
                id="file-upload"
                type="file"
                accept=".pdf,.epub"
                onChange={handleFileChange}
              />
              <div className={styles.fileInputInner}>
                <div className={styles.fileIcon}>📄</div>
                <div>
                  <p className={styles.filePrimary}>
                    {selectedFile
                      ? selectedFile.name
                      : "Choose file (PDF or EPUB)"}
                  </p>
                  <p className={styles.fileSecondary}>PDF or EPUB, max 20MB</p>
                </div>
              </div>
            </div>
          </div>

          {/* Voice Selection */}
          <div className={styles.formGroup}>
            <label htmlFor="voice-select" className={styles.label}>
              Voice
            </label>
            <div className={styles.voiceGrid}>
              {voices.map((voice) => (
                <button
                  key={voice.name}
                  type="button"
                  className={`${styles.voiceCard} ${
                    selectedVoice === voice.name ? styles.voiceCardActive : ""
                  }`}
                  onClick={() => setSelectedVoice(voice.name)}
                >
                  <span className={styles.voiceName}>{voice.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Progress Bar */}
          {(status === "uploading" || status === "processing") && (
            <>
              <div className={styles.progressBar}>
                {status === "uploading" ? (
                  <div
                    className={styles.progress}
                    style={{ width: `${progress}%` }}
                  ></div>
                ) : (
                  <div
                    className={`${styles.progress} ${styles.progressIndeterminate}`}
                  ></div>
                )}
              </div>
              {stepMessage && <p className={styles.statusText}>{stepMessage}</p>}
            </>
          )}

          {/* Action Button */}
          <button
            onClick={handleUploadAndProcess}
            disabled={
              !selectedFile || status === "uploading" || status === "processing"
            }
            className={styles.button}
          >
            {buttonText}
          </button>

          {/* Error Message */}
          {status === "error" && error && (
            <p className={styles.error}>Error: {error}</p>
          )}

          {/* Audio Player */}
          {status === "success" && audioUrl && (
            <div className={styles.audioPlayer}>
              <div className={styles.audioHeader}>
                <h3>Audio file</h3>
                <span className={styles.badgeSoft}>MP3</span>
              </div>
              <audio controls src={audioUrl} className={styles.audioControl}>
                Your browser does not support the audio element.
              </audio>
              <a
                className={styles.downloadLink}
                href={audioUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Download MP3
              </a>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

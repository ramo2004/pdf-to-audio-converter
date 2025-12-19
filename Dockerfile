# syntax=docker/dockerfile:1
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies:
# - build-essential: Required for compiling Python packages with C extensions (like jenkspy).
# - ffmpeg: Essential for audio processing (e.g., converting, merging audio files).
# We combine update and install in one RUN command to optimize Docker layers and ensure fresh package lists.
# We also clean up the apt cache immediately to keep the image size small.
RUN apt-get update && \
    apt-get install -y build-essential ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first to leverage Docker's layer caching.
# If only application code changes, this layer remains cached.
COPY requirements.txt .

# Install Python dependencies from requirements.txt.
# --no-cache-dir prevents pip from storing downloaded packages, reducing image size.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container.
# This should be after installing dependencies to optimize caching.
COPY . .

# Expose the port on which the FastAPI application will listen.
# Cloud Run typically expects services to listen on the port specified by the PORT environment variable,
# which defaults to 8080.
EXPOSE 8080

# Command to run your FastAPI application using Uvicorn.
# "main:app" assumes your FastAPI application object is named 'app'
# and is defined in a file named 'main.py' at the root of your WORKDIR.
# Adjust "main:app" if your application file or object name differs (e.g., "app:app" if it's app.py).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

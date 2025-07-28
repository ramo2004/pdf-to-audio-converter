# app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from main import process_file  # assume your function lives here

class ProcessRequest(BaseModel):
    remote_path: str  # e.g. "input/document.pdf"

app = FastAPI()

@app.post("/process")
async def process(req: ProcessRequest):
    try:
        output_url = process_file(req.remote_path)
        return {"audio_url": output_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

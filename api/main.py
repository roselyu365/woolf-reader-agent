"""
main.py
FastAPI application entry point.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).parent))  # api/ directory for router imports

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from notes_router import router as notes_router
from mobile_router import router as mobile_router
from reader_router import router as reader_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up embeddings on startup
    from kb_client import get_embedding_function
    get_embedding_function()
    yield


app = FastAPI(title="Woolf Reader Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(notes_router)
app.include_router(mobile_router)
app.include_router(reader_router)


@app.get("/health")
def health():
    return {"status": "ok", "agent": "woolf-reader"}

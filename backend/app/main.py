from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import auth, categorize, export, forecast, transactions, voice
from .services import categorizer, speech


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Load the BERT model, Qdrant client, and Whisper model once, at process
    # startup, instead of on the first request -- see the plan's Scalability
    # section.
    categorizer.warm_up()
    speech.warm_up()
    yield


app = FastAPI(title="YAFA AI-Powered Expense Tracker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(voice.router)
app.include_router(categorize.router)
app.include_router(forecast.router)
app.include_router(export.router)


@app.get("/health")
def health():
    return {"status": "ok"}

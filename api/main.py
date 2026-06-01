from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import forecast, trends, evidence, devpanel

app = FastAPI(title="Predictive Threat Engine API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(forecast.router, prefix="/api")
app.include_router(trends.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(devpanel.router, prefix="/api")

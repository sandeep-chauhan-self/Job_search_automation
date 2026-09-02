from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.dashboard.routes import router
import os

app = FastAPI(title="Job Search Automation Dashboard")

# Ensure static directory exists
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

# API routes
app.include_router(router, prefix="/api")

# Serve frontend static files
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Root -> serve index.html
@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "index.html not found"}

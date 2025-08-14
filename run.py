"""Run script for the new clean implementation."""

import uvicorn
from src.api.main import app
from src.config.settings import get_settings

if __name__ == "__main__":
    settings = get_settings()
    
    print("🚀 Starting Natural Language Filter Agent (Clean Implementation)")
    print(f"📍 Running on http://{settings.api_host}:{settings.api_port}")
    print("🔧 Ready to process filter requests!")
    
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        reload=False
    )

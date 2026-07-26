import json
import os
from aiohttp import web
from logger import logger
from utils import load_config

async def handle_index(request):
    """Serves the frontend panel.html"""
    try:
        with open("panel.html", "r", encoding="utf-8") as f:
            content = f.read()
        return web.Response(text=content, content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="panel.html not found", status=404)

async def handle_get_config(request):
    """Returns the current config.json"""
    try:
        config = load_config()
        # Hide the token for security reasons before sending to frontend
        config["token"] = "HIDDEN" 
        return web.json_response(config)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_post_config(request):
    """Updates the config.json"""
    try:
        new_data = await request.json()
        current_config = load_config()
        
        # We must preserve the actual token if it was HIDDEN
        if "token" in new_data and new_data["token"] == "HIDDEN":
            new_data["token"] = current_config["token"]
            
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=4)
            
        logger.info("Configuration updated via Web Panel")
        return web.json_response({"status": "success"})
    except Exception as e:
        logger.error(f"Failed to update config via Web Panel: {e}")
        return web.json_response({"error": str(e)}, status=400)

async def start_web_server():
    """Initializes and runs the aiohttp web server"""
    app = web.Application()
    app.add_routes([
        web.get('/', handle_index),
        web.get('/api/config', handle_get_config),
        web.post('/api/config', handle_post_config)
    ])
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    
    logger.info("Starting Web Panel on http://0.0.0.0:8080")
    await site.start()

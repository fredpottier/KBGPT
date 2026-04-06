"""Permet de lancer le cockpit avec: python -m cockpit"""
from cockpit.main import app
import uvicorn
from cockpit.config import COCKPIT_HOST, COCKPIT_PORT

uvicorn.run(app, host=COCKPIT_HOST, port=COCKPIT_PORT, log_level="info")

"""
OSMOSIS Cockpit — Point d'entrée FastAPI.

Service indépendant de supervision opérationnelle.
- GET  /cockpit/state   → snapshot JSON complet
- WS   /cockpit/ws      → push incrémental via WebSocket
- GET  /cockpit          → UI statique (HTML/SVG/CSS/JS)

Usage:
    python -m cockpit.main
    # ou
    uvicorn cockpit.main:app --host 0.0.0.0 --port 9090
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cockpit.config import COCKPIT_HOST, COCKPIT_PORT, STATIC_DIR, COLLECT_INTERVAL
from cockpit.engine.aggregator import Aggregator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("cockpit")

# ── Singleton ─────────────────────────────────────────────────────────
aggregator = Aggregator()

# ── WebSocket clients ─────────────────────────────────────────────────
ws_clients: set[WebSocket] = set()


async def broadcast_state(state):
    """Envoie l'état à tous les clients WebSocket connectés."""
    if not ws_clients:
        return
    payload = state.to_json()
    disconnected = set()
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)
    ws_clients -= disconnected


# ── Lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Démarre la boucle de collecte au startup."""
    task = asyncio.create_task(aggregator.run_loop(callback=broadcast_state))
    logger.info(
        f"[COCKPIT] Started on http://{COCKPIT_HOST}:{COCKPIT_PORT} "
        f"(collect every {COLLECT_INTERVAL}s)"
    )
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="OSMOSIS Cockpit",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/cockpit/state")
async def get_state():
    """Retourne le snapshot complet de l'état du cockpit."""
    state = aggregator.state
    return JSONResponse(content=json.loads(state.to_json()))


@app.websocket("/cockpit/ws")
async def cockpit_ws(websocket: WebSocket):
    """WebSocket pour push temps réel du cockpit state."""
    await websocket.accept()
    ws_clients.add(websocket)
    logger.info(f"[COCKPIT:WS] Client connected ({len(ws_clients)} total)")

    try:
        # Envoyer immédiatement l'état courant
        await websocket.send_text(aggregator.state.to_json())

        # Écouter les messages du client (ex: reset_llm_session)
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "reset_llm_session":
                    aggregator.reset_llm_session()
                    logger.info("[COCKPIT:WS] LLM session reset by client")
                    state = await aggregator.collect_once()
                    await websocket.send_text(state.to_json())

                elif msg_type == "set_balance":
                    provider = msg.get("provider", "")
                    value = msg.get("value", 0)
                    if provider and isinstance(value, (int, float)):
                        aggregator.llm_collector.save_manual_balance(provider, float(value))
                        logger.info(f"[COCKPIT:WS] Balance set: {provider}=${value}")
                        state = await aggregator.collect_once()
                        await websocket.send_text(state.to_json())

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(websocket)
        logger.info(f"[COCKPIT:WS] Client disconnected ({len(ws_clients)} total)")


# ── Static files & UI ─────────────────────────────────────────────────

@app.get("/cockpit")
async def cockpit_ui():
    """Sert la page cockpit."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        content={"error": "UI not built yet — use /cockpit/state or /cockpit/ws"},
        status_code=404,
    )


# Mount static files (CSS, JS, SVG)
if STATIC_DIR.exists():
    app.mount("/cockpit/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Entrypoint ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "cockpit.main:app",
        host=COCKPIT_HOST,
        port=COCKPIT_PORT,
        reload=False,
        log_level="info",
    )

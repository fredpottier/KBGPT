"""
Regulatory Domain Pack — Sidecar NER Server.

GLiNER zero-shot NER + gazetteer force-include + canonical alias resolution.
Same architecture as enterprise_sap sidecar.

Endpoints:
    GET  /health  → {status, models, version, entity_types}
    POST /extract → {entities, existing_matches, claims_processed, time_ms}
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("regulatory-pack")

app = FastAPI(title="OSMOSIS Regulatory Domain Pack", version="1.0.0")

# ── Configuration ─────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "context_defaults.json"
MODEL_NAME = os.getenv("NER_MODEL", "urchade/gliner_medium-v2.1")

# Loaded at startup
_config: Dict[str, Any] = {}
_gazetteer: Set[str] = set()
_gazetteer_lower: Dict[str, str] = {}
_aliases: Dict[str, str] = {}
_stoplist: Set[str] = set()
_acronyms: Dict[str, str] = {}
_model = None


# ── Schemas ───────────────────────────────────────────────────────────────────

class ClaimInput(BaseModel):
    claim_id: str
    text: str

class ExtractRequest(BaseModel):
    claims: List[ClaimInput]
    existing_norms: List[str] = []

class EntityOutput(BaseModel):
    name: str
    ner_label: str
    claim_ids: List[str]
    source: str = "gliner"

class ExistingMatch(BaseModel):
    entity_id: str
    name: str
    claim_ids: List[str]

class ExtractResponse(BaseModel):
    entities: List[EntityOutput]
    existing_matches: List[ExistingMatch]
    claims_processed: int
    time_ms: int


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global _config, _gazetteer, _gazetteer_lower, _aliases, _stoplist, _acronyms, _model

    # Load config
    if CONFIG_PATH.exists():
        _config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        logger.info(f"Config loaded: {len(_config)} keys")

    # Gazetteer
    gaz = _config.get("product_gazetteer", [])
    _gazetteer = set(gaz)
    _gazetteer_lower = {g.lower(): g for g in gaz}
    logger.info(f"Gazetteer: {len(_gazetteer)} regulations")

    # Aliases
    _aliases = {k.lower(): v for k, v in _config.get("canonical_aliases", {}).items()}
    logger.info(f"Aliases: {len(_aliases)} mappings")

    # Stoplist
    _stoplist = set(s.lower() for s in _config.get("entity_stoplist", []))

    # Acronyms
    _acronyms = _config.get("common_acronyms", {})

    # Load GLiNER model
    try:
        from gliner import GLiNER
        logger.info(f"Loading GLiNER model: {MODEL_NAME}...")
        _model = GLiNER.from_pretrained(MODEL_NAME)
        logger.info("GLiNER model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load GLiNER: {e}")
        _model = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok" if _model else "degraded",
        "models": [MODEL_NAME] if _model else [],
        "version": "1.0.0",
        "entity_types": ["REGULATION", "LEGAL_STANDARD", "REGULATORY_BODY",
                         "COMPLIANCE_FRAMEWORK", "LEGAL_INSTRUMENT", "JURISDICTION"],
        "gazetteer_size": len(_gazetteer),
        "aliases_size": len(_aliases),
    }


@app.post("/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest):
    start = time.time()

    existing_lower = {n.lower(): n for n in request.existing_norms}
    entities_map: Dict[str, EntityOutput] = {}  # normalized_name → EntityOutput
    existing_matches: Dict[str, ExistingMatch] = {}

    NER_LABELS = [
        "regulation", "law", "legal standard", "regulatory body",
        "compliance framework", "legal instrument", "data protection regulation",
        "AI regulation", "privacy law", "international agreement",
    ]

    for claim in request.claims:
        detected: List[tuple] = []

        # 1. GLiNER NER (if model loaded)
        if _model:
            try:
                results = _model.predict_entities(claim.text, NER_LABELS, threshold=0.4)
                for r in results:
                    name = r["text"].strip()
                    label = r["label"].upper().replace(" ", "_")
                    if len(name) >= 3 and name.lower() not in _stoplist:
                        detected.append((name, label))
            except Exception:
                pass

        # 2. Gazetteer force-include (substring match)
        text_lower = claim.text.lower()
        for gaz_lower, gaz_canonical in _gazetteer_lower.items():
            if gaz_lower in text_lower and len(gaz_lower) > 5:
                detected.append((gaz_canonical, "REGULATION"))

        # 3. Acronym expansion
        for acronym, expansion in _acronyms.items():
            if acronym in claim.text and len(acronym) >= 3:
                # Check if expansion is in gazetteer
                if expansion.lower() in _gazetteer_lower:
                    detected.append((_gazetteer_lower[expansion.lower()], "REGULATION"))

        # Process detected entities
        for name, label in detected:
            # Apply canonical aliases
            normalized = _aliases.get(name.lower(), name)
            # Check gazetteer for canonical form
            if normalized.lower() in _gazetteer_lower:
                normalized = _gazetteer_lower[normalized.lower()]

            norm_lower = normalized.lower()

            # Check if existing entity
            if norm_lower in existing_lower:
                key = norm_lower
                if key not in existing_matches:
                    existing_matches[key] = ExistingMatch(
                        entity_id=existing_lower[norm_lower],
                        name=existing_lower[norm_lower],
                        claim_ids=[],
                    )
                if claim.claim_id not in existing_matches[key].claim_ids:
                    existing_matches[key].claim_ids.append(claim.claim_id)
            else:
                # New entity
                if norm_lower not in entities_map:
                    entities_map[norm_lower] = EntityOutput(
                        name=normalized, ner_label=label, claim_ids=[], source="gliner+gazetteer",
                    )
                if claim.claim_id not in entities_map[norm_lower].claim_ids:
                    entities_map[norm_lower].claim_ids.append(claim.claim_id)

    elapsed_ms = int((time.time() - start) * 1000)

    return ExtractResponse(
        entities=list(entities_map.values()),
        existing_matches=list(existing_matches.values()),
        claims_processed=len(request.claims),
        time_ms=elapsed_ms,
    )

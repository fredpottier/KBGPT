"""
Aerospace Compliance Domain Pack — Sidecar NER Server.

GLiNER zero-shot NER + gazetteer force-include + canonical alias resolution.
Same architecture as regulatory and enterprise_sap sidecars.

Entity types covered:
- REGULATION (Regulation 2021/821, 428/2009, delegated regulations)
- CERTIFICATION_STANDARD (CS-25, FAR Part 25)
- AMENDMENT (Amendment 22-28, Delegated Regulation 2024/2547, etc.)
- ARTICLE_REFERENCE (CS 25.561, Article 4(2), etc.)
- AIRCRAFT_COMPONENT (seat, fuel tank, landing gear, etc.)
- DUAL_USE_ITEM (cyber-surveillance items, ECCN categories)
- REGULATORY_BODY (EASA, FAA, ICAO, European Commission)
- EXPORT_CONTROL_REGIME (Wassenaar, MTCR, NSG, Australia Group)
- JURISDICTION (EU, US, third country)
- INTERNATIONAL_AGREEMENT (CWC, BWC, UN Resolution 1540)

Endpoints:
    GET  /health  -> {status, models, version, entity_types}
    POST /extract -> {entities, existing_matches, claims_processed, time_ms}
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
logger = logging.getLogger("aerospace-compliance-pack")

app = FastAPI(title="OSMOSIS Aerospace Compliance Domain Pack", version="1.0.0")

# -- Configuration ------------------------------------------------------------

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


# -- Schemas ------------------------------------------------------------------

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


# -- Startup ------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    global _config, _gazetteer, _gazetteer_lower, _aliases, _stoplist, _acronyms, _model

    if CONFIG_PATH.exists():
        _config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        logger.info(f"Config loaded: {len(_config)} keys")

    gaz = _config.get("product_gazetteer", [])
    _gazetteer = set(gaz)
    _gazetteer_lower = {g.lower(): g for g in gaz}
    logger.info(f"Gazetteer: {len(_gazetteer)} entries")

    _aliases = {k.lower(): v for k, v in _config.get("canonical_aliases", {}).items()}
    logger.info(f"Aliases: {len(_aliases)} mappings")

    _stoplist = set(s.lower() for s in _config.get("entity_stoplist", []))
    _acronyms = _config.get("common_acronyms", {})

    try:
        from gliner import GLiNER
        logger.info(f"Loading GLiNER model: {MODEL_NAME}...")
        _model = GLiNER.from_pretrained(MODEL_NAME)
        logger.info("GLiNER model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load GLiNER: {e}")
        _model = None


# -- Endpoints ----------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok" if _model else "degraded",
        "models": [MODEL_NAME] if _model else [],
        "version": "1.0.0",
        "entity_types": [
            "REGULATION", "CERTIFICATION_STANDARD", "AMENDMENT",
            "ARTICLE_REFERENCE", "AIRCRAFT_COMPONENT", "DUAL_USE_ITEM",
            "REGULATORY_BODY", "EXPORT_CONTROL_REGIME", "JURISDICTION",
            "INTERNATIONAL_AGREEMENT",
        ],
        "gazetteer_size": len(_gazetteer),
        "aliases_size": len(_aliases),
    }


@app.post("/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest):
    start = time.time()

    existing_lower = {n.lower(): n for n in request.existing_norms}
    entities_map: Dict[str, EntityOutput] = {}
    existing_matches: Dict[str, ExistingMatch] = {}

    NER_LABELS = [
        "regulation", "certification specification", "amendment",
        "regulatory body", "international agreement", "aviation authority",
        "export control regime", "dual-use item", "aircraft component",
        "law", "treaty", "delegated regulation",
    ]

    for claim in request.claims:
        detected: List[tuple] = []

        # 1. GLiNER NER
        if _model:
            try:
                results = _model.predict_entities(claim.text, NER_LABELS, threshold=0.4)
                for r in results:
                    name = r["text"].strip()
                    label = r["label"].upper().replace(" ", "_").replace("-", "_")
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
                if expansion.lower() in _gazetteer_lower:
                    detected.append((_gazetteer_lower[expansion.lower()], "REGULATION"))

        # Process detected entities
        for name, label in detected:
            normalized = _aliases.get(name.lower(), name)
            if normalized.lower() in _gazetteer_lower:
                normalized = _gazetteer_lower[normalized.lower()]

            norm_lower = normalized.lower()

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
                if norm_lower not in entities_map:
                    entities_map[norm_lower] = EntityOutput(
                        name=normalized, ner_label=label, claim_ids=[],
                        source="gliner+gazetteer",
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

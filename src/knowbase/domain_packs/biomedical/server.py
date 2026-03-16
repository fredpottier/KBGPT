"""
Serveur NER sidecar pour le Domain Pack Biomedical.

API minimale :
  GET  /health   → status des modèles
  POST /extract  → NER sur une liste de claims

Modèles chargés :
  - en_ner_bc5cdr_md      → CHEMICAL, DISEASE
  - en_ner_bionlp13cg_md  → GENE_OR_GENE_PRODUCT, ORGANISM, CANCER, CELL, etc.
"""

import logging
import time
from typing import Dict, List

import spacy
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("biomedical-pack")

app = FastAPI(title="OSMOSE Pack: Biomedical NER", version="2.0.0")

# ============================================================================
# Chargement des modèles au démarrage
# ============================================================================

MODELS = {}

logger.info("Loading en_ner_bc5cdr_md (Chemical/Disease)...")
start = time.time()
MODELS["bc5cdr"] = spacy.load("en_ner_bc5cdr_md")
logger.info(f"  bc5cdr loaded in {time.time() - start:.1f}s")

logger.info("Loading en_ner_bionlp13cg_md (Gene/Organism/Cell)...")
start = time.time()
MODELS["bionlp13cg"] = spacy.load("en_ner_bionlp13cg_md")
logger.info(f"  bionlp13cg loaded in {time.time() - start:.1f}s")

# Labels supportés par modèle
MODEL_LABELS = {
    "bc5cdr": {"CHEMICAL", "DISEASE"},
    "bionlp13cg": {
        "GENE_OR_GENE_PRODUCT",
        "ORGANISM",
        "CANCER",
        "CELL",
        "SIMPLE_CHEMICAL",
        "TISSUE",
        "ORGAN",
    },
}

# Labels combinés
ALL_LABELS = set()
for labels in MODEL_LABELS.values():
    ALL_LABELS |= labels


# ============================================================================
# Schemas
# ============================================================================


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
    is_existing: bool = False


class ExtractResponse(BaseModel):
    entities: List[EntityOutput]
    existing_matches: List[EntityOutput]
    claims_processed: int
    time_ms: int


class HealthResponse(BaseModel):
    status: str
    models: List[str]
    version: str
    entity_types: List[str]


# ============================================================================
# Endpoints
# ============================================================================


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        models=list(MODELS.keys()),
        version="2.0.0",
        entity_types=sorted(ALL_LABELS),
    )


@app.post("/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest):
    start = time.time()

    existing_norms = set(request.existing_norms)

    # Index : normalized_name → EntityOutput (nouvelles entités)
    new_entities: Dict[str, EntityOutput] = {}
    # Index : normalized_name → EntityOutput (matchs sur entités existantes)
    existing_matches: Dict[str, EntityOutput] = {}

    texts = [c.text for c in request.claims]
    claim_ids = [c.claim_id for c in request.claims]

    # Passer chaque modèle sur les claims
    for model_name, nlp in MODELS.items():
        supported = MODEL_LABELS[model_name]

        for doc, claim_id in zip(nlp.pipe(texts, batch_size=64), claim_ids):
            for ent in doc.ents:
                if ent.label_ not in supported:
                    continue

                name = ent.text.strip()
                if len(name) < 3:
                    continue

                # Filtrer les entités trop génériques
                if name.lower() in _STOPWORDS:
                    continue

                norm = name.lower().strip()

                if norm in existing_norms:
                    # Match sur entité existante → créer ABOUT link
                    if norm in existing_matches:
                        if claim_id not in existing_matches[norm].claim_ids:
                            existing_matches[norm].claim_ids.append(claim_id)
                    else:
                        existing_matches[norm] = EntityOutput(
                            name=name,
                            ner_label=ent.label_,
                            claim_ids=[claim_id],
                            is_existing=True,
                        )
                else:
                    # Nouvelle entité
                    if norm in new_entities:
                        if claim_id not in new_entities[norm].claim_ids:
                            new_entities[norm].claim_ids.append(claim_id)
                    else:
                        new_entities[norm] = EntityOutput(
                            name=name,
                            ner_label=ent.label_,
                            claim_ids=[claim_id],
                            is_existing=False,
                        )

    elapsed_ms = int((time.time() - start) * 1000)

    logger.info(
        f"Extracted {len(new_entities)} new + {len(existing_matches)} existing "
        f"from {len(request.claims)} claims in {elapsed_ms}ms "
        f"({len(MODELS)} models)"
    )

    return ExtractResponse(
        entities=list(new_entities.values()),
        existing_matches=list(existing_matches.values()),
        claims_processed=len(request.claims),
        time_ms=elapsed_ms,
    )


# Termes trop génériques à ignorer (communs dans le texte scientifique)
_STOPWORDS = {
    "cell", "cells", "protein", "proteins", "gene", "genes",
    "treatment", "therapy", "study", "studies", "patient", "patients",
    "group", "groups", "effect", "effects", "result", "results",
    "method", "model", "system", "sample", "samples", "level", "levels",
    "factor", "factors", "response", "type", "activity", "analysis",
    "data", "control", "rate", "risk", "time", "dose", "test",
    "agent", "role", "mechanism", "process", "function", "expression",
    "tissue", "organ", "body", "blood", "water", "acid",
    "mouse", "mice", "rat", "rats", "human", "humans",
    "disease", "infection", "cancer", "tumor",
}

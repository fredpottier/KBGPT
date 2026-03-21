"""
Serveur NER sidecar pour le Domain Pack SAP Enterprise.

API minimale :
  GET  /health   → status du modele GLiNER
  POST /extract  → NER zero-shot sur une liste de claims

Modele : urchade/gliner_medium-v2.1 (209MB, zero-shot, CPU-friendly)
Strategie : GLiNER zero-shot + gazetteer produits SAP (force-include)
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Set

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sap-enterprise-pack")

app = FastAPI(title="OSMOSE Pack: SAP Enterprise NER", version="1.0.0")

# ============================================================================
# Chargement du modele GLiNER au demarrage
# ============================================================================

logger.info("Loading GLiNER model (urchade/gliner_medium-v2.1)...")
start = time.time()

from gliner import GLiNER  # noqa: E402

MODEL = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
logger.info(f"  GLiNER loaded in {time.time() - start:.1f}s")

# Labels zero-shot en langage naturel (GLiNER raisonne sur les descriptions)
SAP_LABELS = [
    "SAP software product",
    "SAP functional module or component",
    "SAP cloud service or SaaS offering",
    "SAP technical platform or infrastructure",
    "technology standard or protocol",
    "SAP certification or exam",
]

# Mapping labels naturels → codes types
LABEL_TO_TYPE: Dict[str, str] = {
    "SAP software product": "SAP_PRODUCT",
    "SAP functional module or component": "SAP_MODULE",
    "SAP cloud service or SaaS offering": "SAP_SERVICE",
    "SAP technical platform or infrastructure": "SAP_PLATFORM",
    "technology standard or protocol": "TECHNOLOGY_STANDARD",
    "SAP certification or exam": "CERTIFICATION",
}

ALL_TYPES = sorted(set(LABEL_TO_TYPE.values()))

# Seuil de confiance GLiNER
GLINER_THRESHOLD = 0.45

# ============================================================================
# Chargement du gazetteer et de la stoplist depuis context_defaults.json
# ============================================================================

_defaults_path = Path(__file__).parent / "context_defaults.json"
_defaults: dict = {}
if _defaults_path.exists():
    _defaults = json.loads(_defaults_path.read_text(encoding="utf-8"))
    logger.info(f"  context_defaults.json loaded ({len(_defaults)} keys)")

# Gazetteer : set de noms de produits SAP (lowercase) pour force-include
GAZETTEER_SET: Set[str] = {
    term.lower() for term in _defaults.get("product_gazetteer", [])
}
logger.info(f"  Gazetteer: {len(GAZETTEER_SET)} SAP products")

# Stoplist : termes trop generiques
_STOPWORDS: Set[str] = {
    term.lower() for term in _defaults.get("entity_stoplist", [])
}
logger.info(f"  Stoplist: {len(_STOPWORDS)} terms")

# Canonical aliases : alias (lowercase) → nom canonique
# Permet de resoudre "RISE" → "SAP S/4HANA Cloud Private Edition" des l'extraction
CANONICAL_ALIASES: Dict[str, str] = {
    alias.lower(): canonical
    for alias, canonical in _defaults.get("canonical_aliases", {}).items()
}
logger.info(f"  Canonical aliases: {len(CANONICAL_ALIASES)} mappings")

# Ajouter les aliases au gazetteer pour le force-include
GAZETTEER_SET.update(CANONICAL_ALIASES.keys())


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
        models=["gliner_medium-v2.1"],
        version="1.0.0",
        entity_types=ALL_TYPES,
    )


@app.post("/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest):
    start_time = time.time()

    existing_norms = set(request.existing_norms)

    new_entities: Dict[str, EntityOutput] = {}
    existing_matches: Dict[str, EntityOutput] = {}

    texts = [c.text for c in request.claims]
    claim_ids = [c.claim_id for c in request.claims]

    # GLiNER batch predict
    try:
        all_predictions = MODEL.batch_predict_entities(
            texts, SAP_LABELS, threshold=GLINER_THRESHOLD
        )
    except Exception as e:
        logger.error(f"GLiNER batch_predict failed: {e}")
        all_predictions = [[] for _ in texts]

    for idx, (predictions, claim_id, text) in enumerate(
        zip(all_predictions, claim_ids, texts)
    ):
        text_lower = text.lower()
        seen_spans: Set[str] = set()

        # 1. Entites detectees par GLiNER
        for pred in predictions:
            name = pred["text"].strip()
            if len(name) < 3:
                continue
            if name.lower() in _STOPWORDS:
                continue

            label = LABEL_TO_TYPE.get(pred["label"], "SAP_PRODUCT")
            norm = name.lower().strip()
            seen_spans.add(norm)

            _add_entity(
                norm, name, label, claim_id,
                existing_norms, new_entities, existing_matches,
            )

        # 2. Gazetteer force-include : produits SAP non detectes par GLiNER
        #    Match mot entier uniquement (pas de substring "ase" dans "based")
        import re as _re
        for product in GAZETTEER_SET:
            if product not in seen_spans and len(product) >= 3:
                # Pour les termes courts (<= 4 chars), exiger un match mot entier strict
                # Pour les termes plus longs, un match mot entier suffit
                pattern = r'\b' + _re.escape(product) + r'\b'
                match = _re.search(pattern, text_lower)
                if match:
                    start_pos = match.start()
                    original_name = text[start_pos:start_pos + len(product)]

                    _add_entity(
                        product, original_name, "SAP_PRODUCT", claim_id,
                        existing_norms, new_entities, existing_matches,
                    )

    elapsed_ms = int((time.time() - start_time) * 1000)

    logger.info(
        f"Extracted {len(new_entities)} new + {len(existing_matches)} existing "
        f"from {len(request.claims)} claims in {elapsed_ms}ms "
        f"(GLiNER + gazetteer)"
    )

    return ExtractResponse(
        entities=list(new_entities.values()),
        existing_matches=list(existing_matches.values()),
        claims_processed=len(request.claims),
        time_ms=elapsed_ms,
    )


def _add_entity(
    norm: str,
    name: str,
    label: str,
    claim_id: str,
    existing_norms: set,
    new_entities: dict,
    existing_matches: dict,
) -> None:
    """Ajoute une entite dans le bon index (new ou existing).

    Resout les aliases canoniques : "RISE" → "SAP S/4HANA Cloud Private Edition"
    pour eviter de creer des entites dupliquees.
    """
    # Resoudre l'alias vers le nom canonique si disponible
    canonical = CANONICAL_ALIASES.get(norm)
    if canonical:
        name = canonical
        norm = canonical.lower()
    if norm in existing_norms:
        if norm in existing_matches:
            if claim_id not in existing_matches[norm].claim_ids:
                existing_matches[norm].claim_ids.append(claim_id)
        else:
            existing_matches[norm] = EntityOutput(
                name=name,
                ner_label=label,
                claim_ids=[claim_id],
                is_existing=True,
            )
    else:
        if norm in new_entities:
            if claim_id not in new_entities[norm].claim_ids:
                new_entities[norm].claim_ids.append(claim_id)
        else:
            new_entities[norm] = EntityOutput(
                name=name,
                ner_label=label,
                claim_ids=[claim_id],
                is_existing=False,
            )

import re
from typing import List, Dict, Tuple
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

# Ontologie des claims : clé = nom canonique, valeur = dict des variantes, unité et seuil de tolérance
CLAIM_ONTOLOGY = {
    "sap.rise.sla_availability": {
        "keywords": ["availability", "SLA", "uptime", "service availability"],
        "unit": "%",
        "tolerance": 0.1,  # seuil de tolérance en valeur absolue
    },
    "sap.rise.rto_minutes": {
        "keywords": ["RTO", "recovery time objective"],
        "unit": "minutes",
        "tolerance": 5,
    },
    "sap.rise.rpo_minutes": {
        "keywords": ["RPO", "recovery point objective"],
        "unit": "minutes",
        "tolerance": 5,
    },
    # Tu peux enrichir dynamiquement ce dictionnaire
}


def extract_claims_from_chunk(meta: Dict) -> List[Dict]:
    """
    Extrait les claims de type métrique à partir des metadata d’un chunk.
    """
    claims = []
    metrics = meta.get("metrics", [])
    if not isinstance(metrics, list):
        return []

    for m in metrics:
        name = m.get("name", "").strip().lower()
        value = m.get("value")
        unit = m.get("unit", "").strip().lower()

        if name and value is not None:
            canonical = find_canonical_claim_name(name, unit)
            if canonical:
                try:
                    numeric_value = float(str(value).replace(",", "."))
                    claims.append(
                        {
                            "canonical_name": canonical,
                            "value": numeric_value,
                            "unit": unit,
                        }
                    )
                except ValueError:
                    continue
    return claims


def find_canonical_claim_name(name: str, unit: str) -> str:
    """
    Essaie de retrouver le nom canonique d’un claim selon l’ontologie définie.
    """
    name = name.lower()
    unit = unit.lower()
    for canonical, data in CLAIM_ONTOLOGY.items():
        if unit != data.get("unit", unit):
            continue
        for kw in data.get("keywords", []):
            if re.search(rf"\b{re.escape(kw.lower())}\b", name):
                return canonical
    return ""


def check_claim_conflicts(
    qdrant: QdrantClient, collection: str, claim: Dict
) -> Tuple[str, List[str]]:
    """
    Recherche si un claim similaire existe déjà dans la base.
    Si oui, compare sa valeur pour détecter un conflit.
    Retourne un tuple (tag, conflicting_ids)
    """
    canonical_name = claim["canonical_name"]
    value = claim["value"]

    # Recherche tous les chunks avec le même claim_tag = "Valid" et contenant le nom canonique
    filter_ = Filter(
        must=[
            FieldCondition(key="claim_tag", match=MatchValue(value="Valid")),
            FieldCondition(
                key="chunk_meta.metrics.name", match=MatchValue(value=canonical_name)
            ),
        ]
    )

    try:
        results = qdrant.scroll(
            collection_name=collection,
            scroll_filter=filter_,
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        return "Valid", []

    tolerance = CLAIM_ONTOLOGY.get(canonical_name, {}).get("tolerance", 0)
    conflicts = []

    for point in results[0]:  # results = (List[PointStruct], next_page)
        payload = point.payload or {}
        metrics = payload.get("chunk_meta", {}).get("metrics", [])
        for m in metrics:
            mname = m.get("name", "").lower()
            mval = m.get("value")
            munit = m.get("unit", "").lower()

            if find_canonical_claim_name(mname, munit) != canonical_name:
                continue
            try:
                existing_value = float(str(mval).replace(",", "."))
            except ValueError:
                continue

            diff = abs(existing_value - value)
            if diff > tolerance:
                conflicts.append(point.id)
                break

    if conflicts:
        return "Pending", conflicts
    else:
        return "Valid", []

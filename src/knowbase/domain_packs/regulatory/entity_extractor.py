"""Regulatory Entity Extractor — HTTP client to sidecar container."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from knowbase.domain_packs.base import DomainEntityExtractor

logger = logging.getLogger(__name__)


class RegulatoryEntityExtractor(DomainEntityExtractor):
    """Extracts regulatory entities via sidecar container (GLiNER zero-shot NER)."""

    def __init__(self):
        self._base_url: Optional[str] = None
        self._available: Optional[bool] = None

    def load_model(self) -> None:
        """Verify sidecar container is reachable."""
        try:
            from knowbase.domain_packs.pack_manager import get_pack_manager
            manager = get_pack_manager()
            self._base_url = manager.get_container_url("regulatory")

            import httpx
            resp = httpx.get(f"{self._base_url}/health", timeout=10.0)
            if resp.status_code == 200:
                self._available = True
                logger.info(f"[PACK:regulatory] Sidecar OK at {self._base_url}")
            else:
                self._available = False
                logger.warning(f"[PACK:regulatory] Sidecar unhealthy: {resp.status_code}")
        except Exception as e:
            self._available = False
            logger.warning(f"[PACK:regulatory] Sidecar unavailable: {e}")

    @property
    def entity_type_mapping(self) -> Dict[str, Any]:
        from knowbase.claimfirst.models.entity import EntityType
        return {
            "REGULATION": EntityType.CONCEPT,
            "LEGAL_STANDARD": EntityType.CONCEPT,
            "REGULATORY_BODY": EntityType.CONCEPT,
            "COMPLIANCE_FRAMEWORK": EntityType.CONCEPT,
            "LEGAL_INSTRUMENT": EntityType.CONCEPT,
            "JURISDICTION": EntityType.CONCEPT,
        }

    def extract(
        self,
        claims: List[Any],
        existing_entities: List[Any],
        domain_context: Any,
    ) -> Tuple[List[Any], Dict[str, List[str]]]:
        """Extract regulatory entities from claims via sidecar."""
        if not self._available:
            self.load_model()
        if not self._available or not self._base_url:
            return [], {}

        try:
            import httpx

            payload = {
                "claims": [
                    {"claim_id": c.claim_id, "text": c.text}
                    for c in claims[:200]  # batch limit
                ],
                "existing_norms": [
                    e.canonical_name for e in existing_entities
                    if hasattr(e, "canonical_name") and e.canonical_name
                ],
            }

            resp = httpx.post(
                f"{self._base_url}/extract",
                json=payload,
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()

            from knowbase.claimfirst.models.entity import Entity, EntityType

            new_entities = []
            candidate_map: Dict[str, List[str]] = {}

            for ent_data in data.get("entities", []):
                entity = Entity(
                    name=ent_data["name"],
                    entity_type=EntityType.CONCEPT,
                    source="domain_pack_regulatory",
                )
                new_entities.append(entity)
                for cid in ent_data.get("claim_ids", []):
                    candidate_map.setdefault(cid, []).append(entity.entity_id)

            # Existing matches
            for match in data.get("existing_matches", []):
                for cid in match.get("claim_ids", []):
                    candidate_map.setdefault(cid, []).append(match["entity_id"])

            logger.info(
                f"[PACK:regulatory] Extracted {len(new_entities)} new entities, "
                f"{len(data.get('existing_matches', []))} existing matches"
            )
            return new_entities, candidate_map

        except Exception as e:
            logger.warning(f"[PACK:regulatory] Extraction failed: {e}")
            return [], {}

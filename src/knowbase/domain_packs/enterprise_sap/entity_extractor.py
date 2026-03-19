# src/knowbase/domain_packs/enterprise_sap/entity_extractor.py
"""
SapEntityExtractor — Client HTTP vers le container sidecar GLiNER.

Appelle le container osmose-pack-enterprise_sap via HTTP POST /extract.
Retourne les nouvelles entites ET les matchs vers entites existantes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
import json as json_module

from knowbase.domain_packs.base import DomainEntityExtractor

logger = logging.getLogger(__name__)


class SapEntityExtractor(DomainEntityExtractor):
    """
    Client HTTP vers le sidecar NER SAP (GLiNER zero-shot).

    Le sidecar retourne deux listes :
    - entities : nouvelles entites non presentes dans le KG
    - existing_matches : entites deja dans le KG detectees dans les claims
    """

    def __init__(self):
        self._base_url: Optional[str] = None
        self._available: Optional[bool] = None

    def load_model(self) -> None:
        """Verifie que le container sidecar est accessible."""
        if self._available is False:
            return

        from knowbase.domain_packs.pack_manager import get_pack_manager
        manager = get_pack_manager()
        url = manager.get_container_url("enterprise_sap")

        if not url:
            self._available = False
            logger.warning("[SapNER] Pack not installed, no container URL")
            return

        try:
            req = urlopen(f"{url}/health", timeout=5)
            if req.status == 200:
                self._base_url = url
                self._available = True
                logger.info(f"[SapNER] Container accessible at {url}")
                return
        except Exception as e:
            logger.warning(f"[SapNER] Container not reachable at {url}: {e}")

        self._available = False

    @property
    def entity_type_mapping(self) -> Dict[str, "EntityType"]:
        from knowbase.claimfirst.models.entity import EntityType
        return {
            "SAP_PRODUCT": EntityType.CONCEPT,
            "SAP_MODULE": EntityType.CONCEPT,
            "SAP_SERVICE": EntityType.CONCEPT,
            "SAP_PLATFORM": EntityType.CONCEPT,
            "TECHNOLOGY_STANDARD": EntityType.CONCEPT,
            "CERTIFICATION": EntityType.CONCEPT,
        }

    def extract(
        self,
        claims: "List",
        existing_entities: "List",
        domain_context: "Optional[object]",
    ) -> "Tuple[List, Dict[str, List[str]]]":
        """
        Extrait entites SAP via appel HTTP au sidecar GLiNER.

        Returns:
            (new_entities, {claim_id: [entity_ids]})
        """
        from knowbase.claimfirst.models.entity import Entity, EntityType

        if self._base_url is None and self._available is not False:
            self.load_model()

        if not self._base_url:
            return [], {}

        existing_norm_to_id = {
            e.normalized_name: e.entity_id for e in existing_entities
        }
        existing_norms = list(existing_norm_to_id.keys())

        payload = {
            "claims": [
                {"claim_id": c.claim_id, "text": c.text}
                for c in claims
            ],
            "existing_norms": existing_norms,
        }

        try:
            req = Request(
                f"{self._base_url}/extract",
                data=json_module.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req, timeout=300)
            result = json_module.loads(resp.read())
        except Exception as e:
            logger.error(f"[SapNER] HTTP call failed: {e}")
            self._available = False
            return [], {}

        tenant_id = claims[0].tenant_id if claims else "default"
        new_entities: List[Entity] = []
        candidate_map: Dict[str, List[str]] = {}

        for ent_data in result.get("entities", []):
            ner_label = ent_data["ner_label"]
            entity_type = self.entity_type_mapping.get(ner_label, EntityType.CONCEPT)

            eid = f"ent_{uuid.uuid4().hex[:12]}"
            entity = Entity(
                entity_id=eid,
                tenant_id=tenant_id,
                name=ent_data["name"],
                entity_type=entity_type,
                source_pack="enterprise_sap",
            )
            new_entities.append(entity)

            for claim_id in ent_data.get("claim_ids", []):
                candidate_map.setdefault(claim_id, []).append(eid)

        existing_links = 0
        for match_data in result.get("existing_matches", []):
            norm = match_data["name"].lower().strip()
            existing_eid = existing_norm_to_id.get(norm)
            if not existing_eid:
                continue

            for claim_id in match_data.get("claim_ids", []):
                candidate_map.setdefault(claim_id, []).append(existing_eid)
                existing_links += 1

        logger.info(
            f"[SapNER] Received {len(new_entities)} new entities + "
            f"{existing_links} existing links from sidecar "
            f"({result.get('time_ms', '?')}ms)"
        )

        return new_entities, candidate_map


__all__ = ["SapEntityExtractor"]

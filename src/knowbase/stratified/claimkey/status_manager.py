# src/knowbase/stratified/claimkey/status_manager.py
"""
Gestionnaire de statuts ClaimKey pour MVP V1.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
import logging
from typing import Optional

from ..models.claimkey import ClaimKey, ClaimKeyStatus

logger = logging.getLogger(__name__)


class ClaimKeyStatusManager:
    """
    Gestionnaire de statuts ClaimKey.

    Responsabilités:
    - Créer/récupérer des ClaimKeys
    - Mettre à jour les métriques
    - Recalculer les statuts
    """

    def __init__(self, neo4j_driver, tenant_id: str):
        self.neo4j_driver = neo4j_driver
        self.tenant_id = tenant_id

    def get_or_create(
        self,
        claimkey_id: str,
        key: str,
        domain: str,
        canonical_question: str,
        inference_method: str = "pattern_level_a"
    ) -> ClaimKey:
        """
        Récupère ou crée un ClaimKey.

        Args:
            claimkey_id: ID unique du ClaimKey
            key: Clé machine
            domain: Domaine
            canonical_question: Question canonique
            inference_method: Méthode d'inférence

        Returns:
            ClaimKey existant ou nouvellement créé
        """
        with self.neo4j_driver.session() as session:
            # Tenter de récupérer
            result = session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                RETURN ck
            """, ck_id=claimkey_id, tenant_id=self.tenant_id).single()

            if result:
                return ClaimKey.from_neo4j_record(dict(result["ck"]))

            # Créer
            claimkey = ClaimKey(
                claimkey_id=claimkey_id,
                tenant_id=self.tenant_id,
                key=key,
                canonical_question=canonical_question,
                domain=domain,
                inference_method=inference_method
            )

            session.run("""
                CREATE (ck:ClaimKey $props)
            """, props=claimkey.to_neo4j_properties())

            logger.info(f"[CLAIMKEY] Created: {claimkey_id} ({domain})")
            return claimkey

    def update_metrics(self, claimkey_id: str) -> ClaimKeyStatus:
        """
        Met à jour les métriques d'un ClaimKey et recalcule son statut.

        Returns:
            Nouveau statut
        """
        with self.neo4j_driver.session() as session:
            result = session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                OPTIONAL MATCH (i:InformationMVP)-[:ANSWERS]->(ck)
                WHERE i.promotion_status = 'PROMOTED_LINKED'
                OPTIONAL MATCH (i)-[:EXTRACTED_FROM]->(d:Document)
                WITH ck, count(DISTINCT i) as info_count, count(DISTINCT d) as doc_count
                RETURN info_count, doc_count
            """, ck_id=claimkey_id, tenant_id=self.tenant_id).single()

            if not result:
                return ClaimKeyStatus.ORPHAN

            info_count = result["info_count"]
            doc_count = result["doc_count"]

            # Déterminer le statut
            if info_count == 0:
                new_status = ClaimKeyStatus.ORPHAN
            elif doc_count < 2:
                new_status = ClaimKeyStatus.EMERGENT
            else:
                new_status = ClaimKeyStatus.COMPARABLE

            # Mettre à jour
            session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                SET ck.status = $status,
                    ck.info_count = $info_count,
                    ck.doc_count = $doc_count,
                    ck.updated_at = datetime()
            """, ck_id=claimkey_id, tenant_id=self.tenant_id,
                status=new_status.value, info_count=info_count, doc_count=doc_count)

            logger.info(
                f"[CLAIMKEY] Updated {claimkey_id}: "
                f"status={new_status.value}, infos={info_count}, docs={doc_count}"
            )
            return new_status

    def link_information(
        self,
        information_id: str,
        claimkey_id: str
    ) -> bool:
        """
        Lie une Information à un ClaimKey.

        Returns:
            True si lien créé
        """
        with self.neo4j_driver.session() as session:
            result = session.run("""
                MATCH (i:InformationMVP {information_id: $info_id, tenant_id: $tenant_id})
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                MERGE (i)-[r:ANSWERS]->(ck)
                SET i.claimkey_id = $ck_id,
                    i.promotion_status = 'PROMOTED_LINKED'
                RETURN r
            """, info_id=information_id, ck_id=claimkey_id, tenant_id=self.tenant_id)

            return result.single() is not None

    def get_claimkey(self, claimkey_id: str) -> Optional[ClaimKey]:
        """
        Récupère un ClaimKey par ID.

        Returns:
            ClaimKey ou None si non trouvé
        """
        with self.neo4j_driver.session() as session:
            result = session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                RETURN ck
            """, ck_id=claimkey_id, tenant_id=self.tenant_id).single()

            if result:
                return ClaimKey.from_neo4j_record(dict(result["ck"]))
            return None

    def find_by_key(self, key: str) -> Optional[ClaimKey]:
        """
        Recherche un ClaimKey par sa clé machine.

        Returns:
            ClaimKey ou None si non trouvé
        """
        with self.neo4j_driver.session() as session:
            result = session.run("""
                MATCH (ck:ClaimKey {key: $key, tenant_id: $tenant_id})
                RETURN ck
            """, key=key, tenant_id=self.tenant_id).single()

            if result:
                return ClaimKey.from_neo4j_record(dict(result["ck"]))
            return None

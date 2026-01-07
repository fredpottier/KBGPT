"""
OSMOSE Graph Governance - Conflict Layer

ADR_GRAPH_GOVERNANCE_LAYERS - Phase C

Ce service implémente la couche Conflict/Contradiction Exposure du framework.
Il détecte, expose et permet l'annotation des tensions dans le graphe
SANS jamais les résoudre automatiquement.

IMPORTANT (garde-fous ADR):
- OSMOSE ne tranche JAMAIS les contradictions
- Il les expose à l'utilisateur avec contexte pour décision humaine
- Le statut EXPLAINED signifie qu'un humain a fourni une explication,
  PAS que la tension est "résolue" globalement
- Les deux assertions sources restent TOUJOURS intactes dans le graphe

Types de tensions:
- TEMPORAL: Informations de dates différentes
- SEMANTIC: Assertions contradictoires (REPLACES vs COMPLEMENTS)
- SCOPE: Contextes d'application différents
- SOURCE: Sources de fiabilité différente

Date: 2026-01-07
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from datetime import datetime

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


class TensionType(str, Enum):
    """Type de tension détectée."""
    # Contradictions impossibles (bloquantes)
    HARD = "HARD"               # Prédicats mutuellement exclusifs (ENABLES vs PREVENTS)

    # Combinaisons suspectes (à revoir)
    SUSPECT = "SUSPECT"         # Combinaisons inhabituelles, probables erreurs LLM

    # Conflits bidirectionnels (erreurs structurelles)
    BIDIRECTIONAL = "BIDIRECTIONAL"  # Même relation dans les deux sens (A→B et B→A)

    # Types historiques (gardés pour compatibilité)
    TEMPORAL = "TEMPORAL"       # Dates/versions contradictoires
    SEMANTIC = "SEMANTIC"       # Prédicats contradictoires (legacy, remplacé par HARD)
    SCOPE = "SCOPE"             # Contextes d'application différents
    SOURCE = "SOURCE"           # Sources de fiabilité différente


class TensionStatus(str, Enum):
    """Statut d'une tension."""
    UNRESOLVED = "UNRESOLVED"   # Détectée, non traitée
    ACKNOWLEDGED = "ACKNOWLEDGED"  # Vue par un humain
    EXPLAINED = "EXPLAINED"     # Explication fournie (pas résolution!)


# ===========================================================================
# ADR: Agnostic Relation Semantics for Evidence-First Knowledge Graph
#
# Trois niveaux de détection de conflits, du plus grave au plus léger :
# 1. HARD_CONTRADICTIONS - Impossibles logiquement (bloquantes)
# 2. SUSPECT_COMBINATIONS - Inhabituelles, probables erreurs LLM (à revoir)
# 3. BIDIRECTIONAL_PREDICATES - Relations asymétriques (A→B et B→A impossible)
#
# Voir semantic_consolidation_pass3.py pour VALID_PREDICATES (15 prédicats).
# ===========================================================================

# 1. CONTRADICTIONS IMPOSSIBLES (HARD)
# Si A a ces deux relations vers B simultanément, c'est une erreur certaine
HARD_CONTRADICTIONS = [
    ("ENABLES", "PREVENTS"),   # A rend possible B vs A empêche B
    ("CAUSES", "PREVENTS"),    # A provoque B vs A empêche B
]

# 2. COMBINAISONS SUSPECTES (SUSPECT)
# Pas impossibles, mais très souvent des erreurs LLM ou inversions sujet/objet
# → Log/warning, demande de re-validation, "needs review"
SUSPECT_COMBINATIONS = [
    # Cycle de vie - confusion fréquente
    ("REPLACES", "VERSION_OF"),   # Remplacer vs être une version - souvent inversé
    ("REPLACES", "EXTENDS"),      # Remplacer vs étendre - incompatible conceptuellement

    # Hiérarchie - confusion is-a vs has-a
    ("SUBTYPE_OF", "PART_OF"),    # Taxonomie vs composition - erreur classique
    ("SUBTYPE_OF", "IMPLEMENTS"), # Taxonomie vs réalisation - confusion fréquente

    # Dépendance - inversion de direction
    ("REQUIRES", "SUPPORTS"),     # Souvent inversion plateforme/feature
]

# 3. PRÉDICATS ASYMÉTRIQUES (BIDIRECTIONAL)
# Relations qui ne peuvent PAS exister dans les deux sens simultanément
# Si A→B ET B→A existent pour ces prédicats, c'est une erreur structurelle
BIDIRECTIONAL_PREDICATES = [
    "PART_OF",      # A partie de B ET B partie de A = impossible
    "SUBTYPE_OF",   # A sous-type de B ET B sous-type de A = impossible
    "VERSION_OF",   # A version de B ET B version de A = impossible (cycle)
    "REPLACES",     # A remplace B ET B remplace A = impossible (cycle)
    "EXTENDS",      # A étend B ET B étend A = impossible (cycle)
    "IMPLEMENTS",   # A implémente B ET B implémente A = rare/suspect
    "REQUIRES",     # A requiert B ET B requiert A = dépendance circulaire
]

# Legacy - pour compatibilité avec code existant
CONTRADICTORY_PREDICATES = HARD_CONTRADICTIONS


@dataclass
class TensionEvidence:
    """Preuve d'une tension."""
    doc_id: str
    doc_title: Optional[str]
    assertion: str
    predicate: str
    date: Optional[str] = None


@dataclass
class Tension:
    """
    Représente une tension détectée dans le graphe.

    Une tension est créée quand deux assertions semblent contradictoires.
    Elle n'implique PAS que l'une ou l'autre est fausse - juste qu'il y a
    une incohérence apparente à exposer à l'utilisateur.
    """
    tension_id: str
    tension_type: TensionType
    status: TensionStatus

    # Concepts concernés
    concept1_id: str
    concept1_name: str
    concept2_id: str
    concept2_name: str

    # Description
    description: str

    # Preuves des deux côtés
    evidence: List[TensionEvidence] = field(default_factory=list)

    # Annotation humaine
    resolution_note: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None

    # Métadonnées
    detected_at: datetime = field(default_factory=datetime.now)
    tenant_id: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tension_id": self.tension_id,
            "tension_type": self.tension_type.value,
            "status": self.status.value,
            "concept1": {"id": self.concept1_id, "name": self.concept1_name},
            "concept2": {"id": self.concept2_id, "name": self.concept2_name},
            "description": self.description,
            "evidence": [
                {
                    "doc_id": e.doc_id,
                    "doc_title": e.doc_title,
                    "assertion": e.assertion,
                    "predicate": e.predicate,
                    "date": e.date,
                }
                for e in self.evidence
            ],
            "resolution_note": self.resolution_note,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass
class ConflictDetectionStats:
    """Statistiques de détection des conflits."""
    pairs_analyzed: int = 0
    tensions_detected: int = 0

    # Par niveau de sévérité
    hard_contradictions: int = 0      # Impossibles logiquement
    suspect_combinations: int = 0      # À revoir
    bidirectional_conflicts: int = 0   # Erreurs structurelles

    # Legacy
    semantic_tensions: int = 0
    temporal_tensions: int = 0

    new_tensions: int = 0
    existing_tensions: int = 0
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pairs_analyzed": self.pairs_analyzed,
            "tensions_detected": self.tensions_detected,
            "by_severity": {
                "HARD": self.hard_contradictions,
                "SUSPECT": self.suspect_combinations,
                "BIDIRECTIONAL": self.bidirectional_conflicts,
            },
            "by_type": {
                "SEMANTIC": self.semantic_tensions,
                "TEMPORAL": self.temporal_tensions,
            },
            "new_tensions": self.new_tensions,
            "existing_tensions": self.existing_tensions,
            "processing_time_ms": round(self.processing_time_ms, 1),
        }


class GovernanceConflictService:
    """
    Service de détection et gestion des tensions dans le KG.

    IMPORTANT: Ce service ne "résout" jamais les tensions automatiquement.
    Il les détecte, les expose, et permet leur annotation par des humains.
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id

    def _execute_query(
        self,
        query: str,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Execute une requête Cypher."""
        if not self.neo4j.driver:
            return []

        database = getattr(self.neo4j, 'database', 'neo4j')
        with self.neo4j.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    async def detect_all_conflicts(self) -> ConflictDetectionStats:
        """
        Détecte tous les conflits dans le Knowledge Graph.

        Exécute la détection des trois types de conflits :
        1. HARD - Contradictions impossibles (ENABLES vs PREVENTS)
        2. SUSPECT - Combinaisons inhabituelles (erreurs LLM probables)
        3. BIDIRECTIONAL - Relations asymétriques dans les deux sens

        Returns:
            ConflictDetectionStats avec les résultats consolidés
        """
        start_time = datetime.now()
        stats = ConflictDetectionStats()

        logger.info(f"[Governance:Conflict] Starting full conflict detection for tenant={self.tenant_id}")

        # 1. Détecter HARD contradictions (bloquantes)
        hard_stats = await self._detect_hard_contradictions()
        stats.hard_contradictions = hard_stats["count"]
        stats.pairs_analyzed += hard_stats["pairs"]
        stats.new_tensions += hard_stats["count"]

        # 2. Détecter SUSPECT combinations (à revoir)
        suspect_stats = await self._detect_suspect_combinations()
        stats.suspect_combinations = suspect_stats["count"]
        stats.pairs_analyzed += suspect_stats["pairs"]
        stats.new_tensions += suspect_stats["count"]

        # 3. Détecter BIDIRECTIONAL conflicts (erreurs structurelles)
        bidirectional_stats = await self._detect_bidirectional_conflicts()
        stats.bidirectional_conflicts = bidirectional_stats["count"]
        stats.pairs_analyzed += bidirectional_stats["pairs"]
        stats.new_tensions += bidirectional_stats["count"]

        stats.tensions_detected = stats.new_tensions
        stats.processing_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        logger.info(
            f"[Governance:Conflict] Detection complete: "
            f"HARD={stats.hard_contradictions}, SUSPECT={stats.suspect_combinations}, "
            f"BIDIRECTIONAL={stats.bidirectional_conflicts} "
            f"(total: {stats.tensions_detected} tensions)"
        )

        return stats

    async def _detect_hard_contradictions(self) -> Dict[str, int]:
        """
        Détecte les contradictions impossibles (HARD).

        Ex: A ENABLES B et A PREVENTS B simultanément → impossible logiquement.

        Returns:
            Dict avec pairs et count
        """
        result = {"pairs": 0, "count": 0}

        logger.info("[Governance:Conflict] Detecting HARD contradictions...")

        for pred1, pred2 in HARD_CONTRADICTIONS:
            query = f"""
            // Détecter paires avec relations contradictoires impossibles
            MATCH (c1:CanonicalConcept {{tenant_id: $tenant_id}})
                  -[r1:{pred1}]->(c2:CanonicalConcept {{tenant_id: $tenant_id}})
            MATCH (c1)-[r2:{pred2}]->(c2)

            // Vérifier qu'une tension n'existe pas déjà
            WHERE NOT EXISTS {{
                MATCH (t:Tension {{tenant_id: $tenant_id}})
                WHERE t.concept1_id = c1.canonical_id
                  AND t.concept2_id = c2.canonical_id
                  AND t.tension_type = 'HARD'
            }}

            RETURN
                c1.canonical_id AS c1_id,
                c1.canonical_name AS c1_name,
                c2.canonical_id AS c2_id,
                c2.canonical_name AS c2_name,
                '{pred1}' AS pred1,
                '{pred2}' AS pred2,
                r1.document_id AS doc1,
                r2.document_id AS doc2
            LIMIT 50
            """

            results = self._execute_query(query, {"tenant_id": self.tenant_id})
            result["pairs"] += len(results)

            for r in results:
                if self._create_tension(
                    r, pred1, pred2,
                    tension_type=TensionType.HARD,
                    description_template=(
                        f"⛔ CONTRADICTION IMPOSSIBLE: {{c1}} a simultanément "
                        f"{pred1} et {pred2} vers {{c2}} - logiquement exclusif"
                    )
                ):
                    result["count"] += 1

        logger.info(f"[Governance:Conflict] HARD: {result['count']} contradictions found")
        return result

    async def _detect_suspect_combinations(self) -> Dict[str, int]:
        """
        Détecte les combinaisons suspectes (SUSPECT).

        Pas impossibles logiquement, mais très inhabituelles et souvent
        le résultat d'erreurs LLM ou d'inversions sujet/objet.

        Returns:
            Dict avec pairs et count
        """
        result = {"pairs": 0, "count": 0}

        logger.info("[Governance:Conflict] Detecting SUSPECT combinations...")

        for pred1, pred2 in SUSPECT_COMBINATIONS:
            query = f"""
            // Détecter combinaisons suspectes (probables erreurs)
            MATCH (c1:CanonicalConcept {{tenant_id: $tenant_id}})
                  -[r1:{pred1}]->(c2:CanonicalConcept {{tenant_id: $tenant_id}})
            MATCH (c1)-[r2:{pred2}]->(c2)

            // Vérifier qu'une tension n'existe pas déjà
            WHERE NOT EXISTS {{
                MATCH (t:Tension {{tenant_id: $tenant_id}})
                WHERE t.concept1_id = c1.canonical_id
                  AND t.concept2_id = c2.canonical_id
                  AND t.tension_type = 'SUSPECT'
            }}

            RETURN
                c1.canonical_id AS c1_id,
                c1.canonical_name AS c1_name,
                c2.canonical_id AS c2_id,
                c2.canonical_name AS c2_name,
                '{pred1}' AS pred1,
                '{pred2}' AS pred2,
                r1.document_id AS doc1,
                r2.document_id AS doc2
            LIMIT 100
            """

            results = self._execute_query(query, {"tenant_id": self.tenant_id})
            result["pairs"] += len(results)

            for r in results:
                if self._create_tension(
                    r, pred1, pred2,
                    tension_type=TensionType.SUSPECT,
                    description_template=(
                        f"⚠️ COMBINAISON SUSPECTE: {{c1}} a {pred1} et {pred2} "
                        f"vers {{c2}} - à vérifier (probable erreur LLM)"
                    )
                ):
                    result["count"] += 1

        logger.info(f"[Governance:Conflict] SUSPECT: {result['count']} combinations found")
        return result

    async def _detect_bidirectional_conflicts(self) -> Dict[str, int]:
        """
        Détecte les conflits bidirectionnels (BIDIRECTIONAL).

        Pour les relations asymétriques, si A→B et B→A existent toutes deux,
        c'est une erreur structurelle (ex: A PART_OF B et B PART_OF A).

        Returns:
            Dict avec pairs et count
        """
        result = {"pairs": 0, "count": 0}

        logger.info("[Governance:Conflict] Detecting BIDIRECTIONAL conflicts...")

        for predicate in BIDIRECTIONAL_PREDICATES:
            query = f"""
            // Détecter relations asymétriques dans les deux sens
            MATCH (c1:CanonicalConcept {{tenant_id: $tenant_id}})
                  -[r1:{predicate}]->(c2:CanonicalConcept {{tenant_id: $tenant_id}})
            MATCH (c2)-[r2:{predicate}]->(c1)

            // Éviter les doublons (c1 < c2 par ID)
            WHERE c1.canonical_id < c2.canonical_id

            // Vérifier qu'une tension n'existe pas déjà
            AND NOT EXISTS {{
                MATCH (t:Tension {{tenant_id: $tenant_id}})
                WHERE ((t.concept1_id = c1.canonical_id AND t.concept2_id = c2.canonical_id)
                    OR (t.concept1_id = c2.canonical_id AND t.concept2_id = c1.canonical_id))
                  AND t.tension_type = 'BIDIRECTIONAL'
            }}

            RETURN
                c1.canonical_id AS c1_id,
                c1.canonical_name AS c1_name,
                c2.canonical_id AS c2_id,
                c2.canonical_name AS c2_name,
                '{predicate}' AS predicate,
                r1.document_id AS doc1,
                r2.document_id AS doc2
            LIMIT 100
            """

            results = self._execute_query(query, {"tenant_id": self.tenant_id})
            result["pairs"] += len(results)

            for r in results:
                tension_id = str(uuid.uuid4())
                description = (
                    f"🔄 CONFLIT BIDIRECTIONNEL: {r['c1_name']} {predicate} {r['c2_name']} "
                    f"ET {r['c2_name']} {predicate} {r['c1_name']} - "
                    f"relation asymétrique dans les deux sens (impossible)"
                )

                create_query = """
                CREATE (t:Tension {
                    tension_id: $tension_id,
                    tenant_id: $tenant_id,
                    tension_type: 'BIDIRECTIONAL',
                    status: 'UNRESOLVED',
                    concept1_id: $c1_id,
                    concept1_name: $c1_name,
                    concept2_id: $c2_id,
                    concept2_name: $c2_name,
                    description: $description,
                    predicate1: $predicate,
                    predicate2: $predicate,
                    doc_id_1: $doc1,
                    doc_id_2: $doc2,
                    detected_at: datetime()
                })

                WITH t
                MATCH (c1:CanonicalConcept {canonical_id: $c1_id, tenant_id: $tenant_id})
                MATCH (c2:CanonicalConcept {canonical_id: $c2_id, tenant_id: $tenant_id})
                CREATE (t)-[:CONCERNS]->(c1)
                CREATE (t)-[:CONCERNS]->(c2)
                RETURN t.tension_id AS created_id
                """

                try:
                    self._execute_query(create_query, {
                        "tension_id": tension_id,
                        "tenant_id": self.tenant_id,
                        "c1_id": r["c1_id"],
                        "c1_name": r["c1_name"],
                        "c2_id": r["c2_id"],
                        "c2_name": r["c2_name"],
                        "description": description,
                        "predicate": r["predicate"],
                        "doc1": r.get("doc1"),
                        "doc2": r.get("doc2"),
                    })
                    result["count"] += 1
                except Exception as e:
                    logger.warning(f"[Governance:Conflict] Failed to create BIDIRECTIONAL tension: {e}")

        logger.info(f"[Governance:Conflict] BIDIRECTIONAL: {result['count']} conflicts found")
        return result

    def _create_tension(
        self,
        record: Dict[str, Any],
        pred1: str,
        pred2: str,
        tension_type: TensionType,
        description_template: str
    ) -> bool:
        """
        Crée une tension dans le graphe.

        Args:
            record: Données du match Neo4j
            pred1, pred2: Les deux prédicats concernés
            tension_type: Type de tension (HARD, SUSPECT, etc.)
            description_template: Template de description avec {c1} et {c2}

        Returns:
            True si création réussie
        """
        tension_id = str(uuid.uuid4())
        description = description_template.format(
            c1=record['c1_name'],
            c2=record['c2_name']
        )

        create_query = """
        CREATE (t:Tension {
            tension_id: $tension_id,
            tenant_id: $tenant_id,
            tension_type: $tension_type,
            status: 'UNRESOLVED',
            concept1_id: $c1_id,
            concept1_name: $c1_name,
            concept2_id: $c2_id,
            concept2_name: $c2_name,
            description: $description,
            predicate1: $pred1,
            predicate2: $pred2,
            doc_id_1: $doc1,
            doc_id_2: $doc2,
            detected_at: datetime()
        })

        WITH t
        MATCH (c1:CanonicalConcept {canonical_id: $c1_id, tenant_id: $tenant_id})
        MATCH (c2:CanonicalConcept {canonical_id: $c2_id, tenant_id: $tenant_id})
        CREATE (t)-[:CONCERNS]->(c1)
        CREATE (t)-[:CONCERNS]->(c2)
        RETURN t.tension_id AS created_id
        """

        try:
            self._execute_query(create_query, {
                "tension_id": tension_id,
                "tenant_id": self.tenant_id,
                "tension_type": tension_type.value,
                "c1_id": record["c1_id"],
                "c1_name": record["c1_name"],
                "c2_id": record["c2_id"],
                "c2_name": record["c2_name"],
                "description": description,
                "pred1": pred1,
                "pred2": pred2,
                "doc1": record.get("doc1"),
                "doc2": record.get("doc2"),
            })
            return True
        except Exception as e:
            logger.warning(f"[Governance:Conflict] Failed to create {tension_type.value} tension: {e}")
            return False

    async def detect_semantic_tensions(self) -> ConflictDetectionStats:
        """
        Alias pour compatibilité - appelle detect_all_conflicts().

        DEPRECATED: Utiliser detect_all_conflicts() directement.
        """
        return await self.detect_all_conflicts()

    async def get_tensions(
        self,
        status: Optional[TensionStatus] = None,
        tension_type: Optional[TensionType] = None,
        limit: int = 50
    ) -> List[Tension]:
        """
        Récupère les tensions avec filtres optionnels.

        Args:
            status: Filtrer par statut (UNRESOLVED, ACKNOWLEDGED, EXPLAINED)
            tension_type: Filtrer par type (SEMANTIC, TEMPORAL, etc.)
            limit: Nombre max de résultats

        Returns:
            Liste de Tension
        """
        where_clauses = ["t.tenant_id = $tenant_id"]
        params = {"tenant_id": self.tenant_id, "limit": limit}

        if status:
            where_clauses.append("t.status = $status")
            params["status"] = status.value

        if tension_type:
            where_clauses.append("t.tension_type = $tension_type")
            params["tension_type"] = tension_type.value

        where_clause = " AND ".join(where_clauses)

        query = f"""
        MATCH (t:Tension)
        WHERE {where_clause}
        RETURN
            t.tension_id AS tension_id,
            t.tension_type AS tension_type,
            t.status AS status,
            t.concept1_id AS c1_id,
            t.concept1_name AS c1_name,
            t.concept2_id AS c2_id,
            t.concept2_name AS c2_name,
            t.description AS description,
            t.predicate1 AS pred1,
            t.predicate2 AS pred2,
            t.doc_id_1 AS doc1,
            t.doc_id_2 AS doc2,
            t.resolution_note AS resolution_note,
            t.resolved_by AS resolved_by,
            t.resolved_at AS resolved_at,
            t.detected_at AS detected_at
        ORDER BY t.detected_at DESC
        LIMIT $limit
        """

        results = self._execute_query(query, params)

        tensions = []
        for r in results:
            evidence = []
            if r.get("doc1"):
                evidence.append(TensionEvidence(
                    doc_id=r["doc1"],
                    doc_title=None,
                    assertion=f"{r['c1_name']} {r.get('pred1', '?')} {r['c2_name']}",
                    predicate=r.get("pred1", ""),
                ))
            if r.get("doc2"):
                evidence.append(TensionEvidence(
                    doc_id=r["doc2"],
                    doc_title=None,
                    assertion=f"{r['c1_name']} {r.get('pred2', '?')} {r['c2_name']}",
                    predicate=r.get("pred2", ""),
                ))

            tensions.append(Tension(
                tension_id=r["tension_id"],
                tension_type=TensionType(r["tension_type"]),
                status=TensionStatus(r["status"]),
                concept1_id=r["c1_id"],
                concept1_name=r["c1_name"],
                concept2_id=r["c2_id"],
                concept2_name=r["c2_name"],
                description=r["description"],
                evidence=evidence,
                resolution_note=r.get("resolution_note"),
                resolved_by=r.get("resolved_by"),
                resolved_at=r.get("resolved_at"),
                detected_at=r.get("detected_at") or datetime.now(),
                tenant_id=self.tenant_id,
            ))

        return tensions

    async def get_tension_counts(self) -> Dict[str, int]:
        """
        Récupère les comptages de tensions par statut.

        Returns:
            Dict avec comptages par statut
        """
        query = """
        MATCH (t:Tension {tenant_id: $tenant_id})
        RETURN
            t.status AS status,
            count(t) AS count
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        counts = {
            "total": 0,
            "UNRESOLVED": 0,
            "ACKNOWLEDGED": 0,
            "EXPLAINED": 0,
        }

        for r in results:
            status = r["status"]
            count = r["count"]
            counts[status] = count
            counts["total"] += count

        return counts

    async def update_tension_status(
        self,
        tension_id: str,
        new_status: TensionStatus,
        resolution_note: Optional[str] = None,
        resolved_by: Optional[str] = None
    ) -> bool:
        """
        Met à jour le statut d'une tension.

        IMPORTANT: EXPLAINED n'implique pas que la tension est "résolue" globalement.
        Cela signifie qu'un humain a fourni une explication contextuelle,
        mais les deux assertions sources restent intactes.

        Args:
            tension_id: ID de la tension
            new_status: Nouveau statut
            resolution_note: Note explicative (pour EXPLAINED)
            resolved_by: Email de l'utilisateur

        Returns:
            True si mise à jour réussie
        """
        query = """
        MATCH (t:Tension {tension_id: $tension_id, tenant_id: $tenant_id})
        SET t.status = $status,
            t.resolution_note = $note,
            t.resolved_by = $resolved_by,
            t.resolved_at = CASE WHEN $status IN ['ACKNOWLEDGED', 'EXPLAINED']
                                 THEN datetime()
                                 ELSE t.resolved_at END
        RETURN t.tension_id AS updated_id
        """

        results = self._execute_query(query, {
            "tension_id": tension_id,
            "tenant_id": self.tenant_id,
            "status": new_status.value,
            "note": resolution_note,
            "resolved_by": resolved_by,
        })

        if results:
            logger.info(
                f"[Governance:Conflict] Tension {tension_id} updated to {new_status.value}"
            )
            return True

        return False

    async def delete_tension(self, tension_id: str) -> bool:
        """
        Supprime une tension (si détection erronée).

        Args:
            tension_id: ID de la tension à supprimer

        Returns:
            True si suppression réussie
        """
        query = """
        MATCH (t:Tension {tension_id: $tension_id, tenant_id: $tenant_id})
        DETACH DELETE t
        RETURN count(t) AS deleted
        """

        results = self._execute_query(query, {
            "tension_id": tension_id,
            "tenant_id": self.tenant_id,
        })

        if results and results[0].get("deleted", 0) > 0:
            logger.info(f"[Governance:Conflict] Tension {tension_id} deleted")
            return True

        return False


# Singleton
_conflict_service: Optional[GovernanceConflictService] = None


def get_governance_conflict_service(tenant_id: str = "default") -> GovernanceConflictService:
    """Récupère le service de gouvernance conflits."""
    global _conflict_service
    if _conflict_service is None or _conflict_service.tenant_id != tenant_id:
        _conflict_service = GovernanceConflictService(tenant_id=tenant_id)
    return _conflict_service


__all__ = [
    "TensionType",
    "TensionStatus",
    "Tension",
    "TensionEvidence",
    "ConflictDetectionStats",
    "GovernanceConflictService",
    "get_governance_conflict_service",
    # Constantes de détection de conflits
    "HARD_CONTRADICTIONS",
    "SUSPECT_COMBINATIONS",
    "BIDIRECTIONAL_PREDICATES",
    "CONTRADICTORY_PREDICATES",  # Legacy alias
]

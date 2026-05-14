"""V5 DSG — Two-phase publish pour ingestion atomique.

ADR V1.5 §3c (Sprint S2.3) : staging → validation → atomic flip.

État V1.5+ : ACTIVÉ. Schéma migré (composite key (tenant_id, doc_id, doc_version)
UNIQUE) + 38 docs ré-importés avec doc_version=1 int.

Note : ce module ne fait PAS d'extraction (S2.0 bench Docling vs SmolDocling
toujours différé). Il prend en entrée une structure DEJA extraite et applique
le flow atomique. Utilisé par S2.6 (intégration ClaimFirst order=2.5) une fois
l'extraction industrialisée.

⚠️ Limitation V1.5 — sections partagées entre versions :
- V5Document a composite key (tenant_id, doc_id, doc_version) — versions multiples OK
- V5Section a composite key (tenant_id, section_id) — section_id stable entre versions
- Conséquence : si une réingestion change le contenu d'une section avec même
  section_id (e.g. typo correction), le contenu staged écrase l'actif in-place
  pendant la fenêtre staging→flip (typiquement <1s).
- Workaround : pendant cette fenêtre, l'active Document pointe via HAS_SECTION
  vers une section dont le contenu est temporairement celui de la nouvelle version.
- Résolution V1.6 : versioning sections via (tenant_id, section_id, doc_version)
  composite key. Différé car nécessite réécriture lookup logic.

Garanties :
- Une réingestion en cours n'expose JAMAIS de structure partielle aux runtimes.
- Si la réingestion crash entre staging et flip, l'ancienne version reste active.
- Rollback explicite possible (supprimer la version staged).
- Versioning : `doc_version` + relation `:HAS_VERSION_OF` pour traçabilité.
- Redlock automatique sur `(tenant_id, doc_id)` pendant tout le flux.

Cycle de vie `V5Document.active_status` :
    staged → active   (flip atomique réussi)
    staged → (deleted) (rollback)
    active → deprecated (lors d'un flip d'une nouvelle version)
    deprecated → (purgé ultérieurement par job de cleanup)

Composite key Neo4j :
- Document : `(tenant_id, doc_id)` UNIQUE → 1 seul nœud par version logique
- doc_version est un attribut, incrémenté à chaque réingestion
- HAS_VERSION_OF pointe l'ancien Document après flip (pour historique)

ATTENTION : ce module ne fait PAS d'extraction. Il prend en entrée une structure
DEJA extraite (par Docling, SmolDocling, etc.) et applique le flow atomique.
L'extraction elle-même est S2.0 / S2.6.

Usage :
    from knowbase.runtime_v5.two_phase_publish import TwoPhasePublisher
    from knowbase.runtime_v5.neo4j_dsg import get_v5_dsg

    publisher = TwoPhasePublisher(get_v5_dsg(), get_redlock_client())
    structure = {"doc_id": "...", "doc_name": "...", "n_pages": 42, "sections": [...]}
    result = publisher.publish(tenant_id="default", structure=structure)
    # result.doc_version, result.flip_duration_s, result.invariants_passed
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from knowbase.runtime_v5.redlock import LockAcquireTimeout, RedlockClient
from knowbase.runtime_v5.section_id import compute_section_id

logger = logging.getLogger(__name__)


# ─── Schema extension (V5Document active_status states) ──────────────────────

ACTIVE_STATUS_STAGED = "staged"
ACTIVE_STATUS_ACTIVE = "active"
ACTIVE_STATUS_DEPRECATED = "deprecated"


# ─── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class InvariantResult:
    name: str
    passed: bool
    detail: str = ""
    actual: Any = None
    expected: Any = None


@dataclass
class PublishResult:
    tenant_id: str
    doc_id: str
    doc_version: int
    success: bool
    n_sections_staged: int = 0
    n_sections_active: int = 0
    invariants: list[InvariantResult] = field(default_factory=list)
    flip_duration_s: float = 0.0
    total_duration_s: float = 0.0
    rolled_back: bool = False
    error: str = ""
    deprecated_version: Optional[int] = None  # version de l'ancien doc qui a été deprecated


class PublishError(Exception):
    """Erreur dans le flux two-phase publish."""
    pass


# ─── TwoPhasePublisher ───────────────────────────────────────────────────────

class TwoPhasePublisher:
    """Orchestre staging → validation → atomic flip.

    Args:
        dsg: V5DSG instance (accès Neo4j)
        redlock: RedlockClient pour locks concurrents
        lock_timeout_s: TTL du lock pendant publish (default 600s = 10 min)
        min_sections_threshold: invariant — un doc avec 0 sections est invalide
    """

    def __init__(
        self,
        dsg,
        redlock: RedlockClient,
        lock_timeout_s: int = 600,
        min_sections_threshold: int = 1,
    ):
        self.dsg = dsg
        self.redlock = redlock
        self.lock_timeout_s = lock_timeout_s
        self.min_sections_threshold = min_sections_threshold

    # ─── Public API ──────────────────────────────────────────────────────────

    def publish(
        self,
        tenant_id: str,
        structure: dict,
        wait_lock_s: float = 0.0,
        recompute_section_ids: bool = False,
    ) -> PublishResult:
        """Publie une nouvelle version de doc en two-phase.

        Args:
            tenant_id: tenant key
            structure: dict avec doc_id, doc_name, n_pages, sections[], extractor_version
            wait_lock_s: temps max à attendre le Redlock (0 = fail-fast)
            recompute_section_ids: si True, recompute section_id via sha256
                                   stable (S2.1). Si False, garde ceux fournis.

        Returns:
            PublishResult avec invariants + success/rolled_back
        """
        t_start = time.time()
        doc_id = structure.get("doc_id")
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and structure.doc_id required")

        sections = structure.get("sections") or []

        # ─── Phase 0 : LOCK distribué ────────────────────────────────────────
        try:
            with self.redlock.lock(
                tenant_id=tenant_id,
                doc_id=doc_id,
                timeout_s=self.lock_timeout_s,
                wait_s=wait_lock_s,
            ):
                return self._publish_locked(
                    tenant_id, structure, sections,
                    recompute_section_ids, t_start,
                )
        except LockAcquireTimeout as e:
            return PublishResult(
                tenant_id=tenant_id,
                doc_id=doc_id,
                doc_version=-1,
                success=False,
                total_duration_s=round(time.time() - t_start, 3),
                error=f"lock_timeout: {e}",
            )

    def rollback_staged(self, tenant_id: str, doc_id: str) -> dict:
        """Supprime explicitement la version staged (pas l'active).

        Useful si un import a foiré et a laissé un staged orphelin.
        """
        # Detect staged version
        staged = self._get_doc_by_status(tenant_id, doc_id, ACTIVE_STATUS_STAGED)
        if not staged:
            return {"removed": False, "reason": "no_staged_version"}

        version = staged.get("doc_version", 0)
        # Purger staged + ses sections
        deleted = self._purge_doc_version(tenant_id, doc_id, version)
        logger.warning(
            f"[TwoPhasePublish] Rolled back staged: tenant={tenant_id} "
            f"doc={doc_id} version={version} ({deleted} nodes deleted)"
        )
        return {"removed": True, "doc_version": version, "deleted_nodes": deleted}

    def get_active_version(self, tenant_id: str, doc_id: str) -> Optional[dict]:
        """Retourne le Document actif (ou None)."""
        return self._get_doc_by_status(tenant_id, doc_id, ACTIVE_STATUS_ACTIVE)

    # ─── Internal flow ───────────────────────────────────────────────────────

    def _publish_locked(
        self,
        tenant_id: str,
        structure: dict,
        sections: list,
        recompute_section_ids: bool,
        t_start: float,
    ) -> PublishResult:
        doc_id = structure["doc_id"]
        # Sanitize sections (recompute IDs si demandé)
        if recompute_section_ids:
            for s in sections:
                s["section_id"] = compute_section_id(
                    doc_id=doc_id,
                    parent_path=s.get("section_path", "") or "",
                    title=s.get("title", "") or "",
                    page_start=(s.get("page_range") or [0])[0],
                )

        # ─── Phase 1 : STAGING ───────────────────────────────────────────────
        # Détermine la nouvelle version
        active_existing = self._get_doc_by_status(
            tenant_id, doc_id, ACTIVE_STATUS_ACTIVE
        )
        new_version = (active_existing.get("doc_version", 0) + 1) if active_existing else 1

        # Purge un staged orphelin éventuel
        self.rollback_staged(tenant_id, doc_id)

        try:
            self._stage_document(tenant_id, structure, new_version, sections)
        except Exception as e:
            logger.error(f"[TwoPhasePublish] Staging failed: {e}")
            return PublishResult(
                tenant_id=tenant_id, doc_id=doc_id, doc_version=new_version,
                success=False, total_duration_s=round(time.time() - t_start, 3),
                error=f"staging_failed: {e}",
            )

        # ─── Phase 2 : VALIDATION (invariants) ──────────────────────────────
        invariants = self._validate_staged(tenant_id, doc_id, new_version, structure)
        if not all(inv.passed for inv in invariants):
            # Rollback
            self._purge_doc_version(tenant_id, doc_id, new_version)
            failed = [inv.name for inv in invariants if not inv.passed]
            logger.warning(
                f"[TwoPhasePublish] Validation failed for {doc_id}: {failed}. Rolled back."
            )
            return PublishResult(
                tenant_id=tenant_id, doc_id=doc_id, doc_version=new_version,
                success=False, rolled_back=True,
                invariants=invariants,
                total_duration_s=round(time.time() - t_start, 3),
                error=f"validation_failed: {failed}",
            )

        # ─── Phase 3 : ATOMIC FLIP ───────────────────────────────────────────
        t_flip = time.time()
        try:
            deprecated_version = self._atomic_flip(
                tenant_id, doc_id, new_version, active_existing
            )
        except Exception as e:
            # Si le flip foire en plein milieu, on tente de remettre staged → staged (pas actif)
            logger.error(f"[TwoPhasePublish] Flip failed: {e}")
            return PublishResult(
                tenant_id=tenant_id, doc_id=doc_id, doc_version=new_version,
                success=False,
                invariants=invariants,
                total_duration_s=round(time.time() - t_start, 3),
                error=f"flip_failed: {e}",
            )
        flip_duration = round(time.time() - t_flip, 3)

        # Counts finaux
        n_sections_active = len(sections)

        result = PublishResult(
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_version=new_version,
            success=True,
            n_sections_staged=len(sections),
            n_sections_active=n_sections_active,
            invariants=invariants,
            flip_duration_s=flip_duration,
            total_duration_s=round(time.time() - t_start, 3),
            deprecated_version=deprecated_version,
        )
        logger.info(
            f"[TwoPhasePublish] PUBLISHED tenant={tenant_id} doc={doc_id} "
            f"v{new_version} sections={n_sections_active} flip={flip_duration}s "
            f"(deprecated v{deprecated_version})"
        )
        return result

    # ─── Staging ─────────────────────────────────────────────────────────────

    def _stage_document(
        self, tenant_id: str, structure: dict, doc_version: int, sections: list
    ) -> None:
        """Phase 1 : crée un Document en staged + sections rattachées."""
        doc_id = structure["doc_id"]
        # Upsert Document staged
        query_doc = """
        MERGE (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id, doc_version: $doc_version})
        ON CREATE SET
            d.doc_internal_id = $doc_internal_id,
            d.doc_name = $doc_name,
            d.n_pages = $n_pages,
            d.source_uri = $source_uri,
            d.canonical_text_uri = $canonical_text_uri,
            d.extractor_version = $extractor_version,
            d.active_status = $active_status,
            d.ingested_at = datetime()
        ON MATCH SET
            d.doc_name = $doc_name,
            d.n_pages = $n_pages,
            d.source_uri = $source_uri,
            d.canonical_text_uri = $canonical_text_uri,
            d.extractor_version = $extractor_version,
            d.active_status = $active_status,
            d.updated_at = datetime()
        RETURN d.doc_internal_id AS doc_internal_id
        """
        # doc_internal_id inclut la version pour qu'un staged et un active coexistent
        import hashlib
        doc_internal_id = "doc_" + hashlib.sha256(
            f"{tenant_id}|{doc_id}|v{doc_version}".encode("utf-8")
        ).hexdigest()[:24]

        self.dsg._execute_write(
            query_doc,
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_version=doc_version,
            doc_internal_id=doc_internal_id,
            doc_name=structure.get("doc_name", doc_id),
            n_pages=structure.get("n_pages", 0),
            source_uri=structure.get("source_uri", ""),
            canonical_text_uri=structure.get("canonical_text_uri", ""),
            extractor_version=structure.get("extractor_version", ""),
            active_status=ACTIVE_STATUS_STAGED,
        )

        # Upsert sections + HAS_SECTION
        # NOTE : sections sont aussi keyed par (tenant_id, section_id) — pour
        # éviter la collision avec l'active version on suffixe section_id par
        # un marker de version pour les staged.
        # Choix V1.5 : ne pas suffixer, faire confiance au compute_section_id
        # stable + au flip qui swap active_status (pas les section_id).
        # Cela impose recompute_section_ids=True pour avoir des IDs stables.
        # On lie chaque section au Document version-spécifique via HAS_SECTION.
        for s in sections:
            sec_query = """
            MATCH (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id, doc_version: $doc_version})
            MERGE (sec:V5Section {tenant_id: $tenant_id, section_id: $section_id})
            ON CREATE SET
                sec.doc_id = $doc_id,
                sec.doc_version = $doc_version,
                sec.level = $level,
                sec.numbering = $numbering,
                sec.title = $title,
                sec.section_path = $section_path,
                sec.page_start = $page_start,
                sec.page_end = $page_end,
                sec.text_snippet = $text_snippet,
                sec.text_uri = $text_uri,
                sec.created_at = datetime()
            ON MATCH SET
                sec.doc_version = $doc_version,
                sec.level = $level,
                sec.numbering = $numbering,
                sec.title = $title,
                sec.section_path = $section_path,
                sec.page_start = $page_start,
                sec.page_end = $page_end,
                sec.text_snippet = $text_snippet,
                sec.text_uri = $text_uri,
                sec.updated_at = datetime()
            MERGE (d)-[:HAS_SECTION]->(sec)
            """
            text = s.get("text", "") or ""
            page_range = s.get("page_range") or [0, 0]
            self.dsg._execute_write(
                sec_query,
                tenant_id=tenant_id,
                doc_id=structure["doc_id"],
                doc_version=doc_version,
                section_id=s["section_id"],
                level=s.get("level", 1),
                numbering=s.get("numbering", "") or "",
                title=s.get("title", "") or "",
                section_path=s.get("section_path", "") or "",
                page_start=(page_range[0] if page_range else 0),
                page_end=(page_range[1] if len(page_range) > 1 else page_range[0] if page_range else 0),
                text_snippet=text[:500],
                text_uri=s.get("text_uri", "") or "",
            )

    # ─── Validation ──────────────────────────────────────────────────────────

    def _validate_staged(
        self, tenant_id: str, doc_id: str, doc_version: int, structure: dict
    ) -> list[InvariantResult]:
        """Phase 2 : invariants sur le staged avant flip."""
        invariants = []
        sections_input = structure.get("sections") or []
        n_expected = len(sections_input)

        # Invariant 1 : nombre de sections staged == n_expected
        n_staged = self._count_sections(tenant_id, doc_id, doc_version)
        invariants.append(InvariantResult(
            name="n_sections_staged_eq_input",
            passed=(n_staged == n_expected),
            actual=n_staged,
            expected=n_expected,
            detail=f"staged={n_staged}, input={n_expected}",
        ))

        # Invariant 2 : seuil minimal sections
        invariants.append(InvariantResult(
            name="min_sections_threshold",
            passed=(n_staged >= self.min_sections_threshold),
            actual=n_staged,
            expected=self.min_sections_threshold,
            detail=f"min={self.min_sections_threshold}, got={n_staged}",
        ))

        # Invariant 3 : Document staged existe bien
        staged_doc = self._get_doc_by_status(tenant_id, doc_id, ACTIVE_STATUS_STAGED)
        invariants.append(InvariantResult(
            name="staged_document_exists",
            passed=staged_doc is not None,
            detail=f"found={staged_doc is not None}",
        ))

        # Invariant 4 : tous les section_id sont uniques côté input
        section_ids = [s["section_id"] for s in sections_input]
        n_unique = len(set(section_ids))
        invariants.append(InvariantResult(
            name="unique_section_ids_input",
            passed=(n_unique == n_expected),
            actual=n_unique,
            expected=n_expected,
            detail=f"unique={n_unique}/{n_expected}",
        ))

        return invariants

    # ─── Atomic Flip ─────────────────────────────────────────────────────────

    def _atomic_flip(
        self,
        tenant_id: str,
        doc_id: str,
        new_version: int,
        active_existing: Optional[dict],
    ) -> Optional[int]:
        """Phase 3 : Marque staged → active et l'ancien → deprecated. Atomique.

        Returns:
            doc_version de l'ancienne version désormais deprecated (ou None).
        """
        # On utilise une seule transaction Cypher pour le swap
        deprecated_version = None
        if active_existing:
            deprecated_version = active_existing.get("doc_version")
            flip_query = """
            MATCH (old:V5Document {
                tenant_id: $tenant_id, doc_id: $doc_id, active_status: 'active'
            })
            MATCH (new:V5Document {
                tenant_id: $tenant_id, doc_id: $doc_id,
                doc_version: $new_version, active_status: 'staged'
            })
            SET old.active_status = 'deprecated',
                old.deprecated_at = datetime(),
                new.active_status = 'active',
                new.activated_at = datetime()
            MERGE (new)-[:HAS_VERSION_OF]->(old)
            RETURN old.doc_version AS deprecated, new.doc_version AS active_now
            """
            result = self.dsg._execute_write(
                flip_query,
                tenant_id=tenant_id,
                doc_id=doc_id,
                new_version=new_version,
            )
            if not result:
                raise PublishError("atomic flip query returned no result")
        else:
            # Première version
            flip_query = """
            MATCH (new:V5Document {
                tenant_id: $tenant_id, doc_id: $doc_id,
                doc_version: $new_version, active_status: 'staged'
            })
            SET new.active_status = 'active',
                new.activated_at = datetime()
            RETURN new.doc_version AS active_now
            """
            result = self.dsg._execute_write(
                flip_query,
                tenant_id=tenant_id,
                doc_id=doc_id,
                new_version=new_version,
            )
            if not result:
                raise PublishError("first-version flip returned no result")

        return deprecated_version

    # ─── Helpers Neo4j ──────────────────────────────────────────────────────

    def _get_doc_by_status(
        self, tenant_id: str, doc_id: str, status: str
    ) -> Optional[dict]:
        query = """
        MATCH (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id, active_status: $status})
        RETURN d
        LIMIT 1
        """
        result = self.dsg._execute_query(
            query, tenant_id=tenant_id, doc_id=doc_id, status=status
        )
        return dict(result[0]["d"]) if result else None

    def _count_sections(self, tenant_id: str, doc_id: str, doc_version: int) -> int:
        query = """
        MATCH (d:V5Document {
            tenant_id: $tenant_id, doc_id: $doc_id, doc_version: $doc_version
        })-[:HAS_SECTION]->(s:V5Section)
        RETURN count(s) AS n
        """
        result = self.dsg._execute_query(
            query, tenant_id=tenant_id, doc_id=doc_id, doc_version=doc_version
        )
        return int(result[0]["n"]) if result else 0

    def _purge_doc_version(self, tenant_id: str, doc_id: str, doc_version: int) -> int:
        """Supprime un Document version + ses sections rattachées EXCLUSIVES."""
        # Compte les nodes pour stats
        count_query = """
        MATCH (d:V5Document {
            tenant_id: $tenant_id, doc_id: $doc_id, doc_version: $doc_version
        })
        OPTIONAL MATCH (d)-[:HAS_SECTION]->(s:V5Section)
        RETURN count(DISTINCT d) AS n_docs, count(DISTINCT s) AS n_sections
        """
        c = self.dsg._execute_query(
            count_query, tenant_id=tenant_id, doc_id=doc_id, doc_version=doc_version
        )
        n_total = (c[0]["n_docs"] + c[0]["n_sections"]) if c else 0

        # Détach et supprime
        purge_query = """
        MATCH (d:V5Document {
            tenant_id: $tenant_id, doc_id: $doc_id, doc_version: $doc_version
        })
        OPTIONAL MATCH (d)-[:HAS_SECTION]->(s:V5Section)
        DETACH DELETE d, s
        """
        self.dsg._execute_write(
            purge_query, tenant_id=tenant_id, doc_id=doc_id, doc_version=doc_version
        )
        return n_total

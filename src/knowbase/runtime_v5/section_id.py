"""V5 DSG — Stable section_id deterministic hashing.

ADR V1.5 §3c (Sprint S2.1) : `sha256(doc_id, parent_path, normalized_title, page_start)`
garantit la stabilité du `section_id` across re-extractions Docling (sauf si le titre
ou la page changent radicalement).

Pourquoi :
- Si Docling renomme/renumérote des sections entre 2 versions, les liens (citations
  utilisateur, workspace replays, embeddings Qdrant) ne doivent PAS se rompre.
- Hash déterministe = même section → même ID, peu importe l'ordre d'extraction.
- Alias map (SectionIdAliasMap) pour les cas où le titre change légèrement
  (typo correction, casse) mais sémantiquement c'est la même section.

Implémentation :
- `compute_section_id(doc_id, parent_path, title, page_start)` → "sec_<24chars hex>"
- `normalize_title(title)` → lowercase, strip punct, collapse whitespace
- `SectionIdAliasMap.add(old_section_id, new_section_id, reason)` → Neo4j V5SectionAlias node
- `SectionIdAliasMap.resolve(section_id)` → toujours retourne l'ID courant

Domain-agnostic strict : aucune liste, regex ou heuristique corpus-spécifique.
La normalisation des titres n'utilise QUE des opérations universelles (case, punct, ws).
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Normalization (domain-agnostic) ─────────────────────────────────────────

# Punctuation à strip — limité à ponctuation Unicode catégorie P*, pas de liste
# corpus-spécifique. Compilé une fois.
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)


def normalize_title(title: str) -> str:
    """Normalise un titre pour hashage stable.

    Opérations universelles uniquement :
    - NFKC unicode normalize (compatibilité formes)
    - lowercase
    - strip ponctuation (catégorie P* Unicode)
    - collapse whitespace
    - trim

    Args:
        title: titre brut (peut contenir accents, ponctuation, casse mixte)

    Returns:
        titre normalisé. Chaîne vide si input None/vide.
    """
    if not title:
        return ""
    # NFKC : normalise les caractères composés (e.g. é → e + accent recombiné)
    t = unicodedata.normalize("NFKC", title)
    t = t.lower()
    # Remplace ponctuation par espace (sépare mots collés par tiret/slash)
    t = _PUNCT_RE.sub(" ", t)
    # Collapse whitespace + trim
    t = _WS_RE.sub(" ", t).strip()
    return t


def compute_section_id(
    doc_id: str,
    parent_path: str,
    title: str,
    page_start: int,
) -> str:
    """Calcule un section_id stable par sha256.

    Args:
        doc_id: ID du document parent (composite key V5Document)
        parent_path: chemin hiérarchique (ex: "/3/3.1" ou "" pour racine).
                     Peut être section_path du JSON Docling (ex: "/Page 4").
        title: titre de la section (sera normalisé)
        page_start: page de début (0-indexed)

    Returns:
        section_id format "sec_<24 chars hex>".
        Déterministe : même tuple → même ID.

    Exemples :
        >>> compute_section_id("doc_test", "/3", "Upgrade Process", 4)
        'sec_a1b2c3d4...'  # toujours identique pour cet input
    """
    if not doc_id:
        raise ValueError("doc_id required")
    normalized = normalize_title(title or "")
    # Components séparés par un délimiteur non-printable pour éviter collisions
    # (ex: doc_id="A|B" + parent_path="C" vs doc_id="A" + parent_path="B|C")
    payload = "\x1f".join([
        doc_id,
        parent_path or "",
        normalized,
        str(page_start or 0),
    ])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return "sec_" + digest[:24]


# ─── Alias map (Neo4j-backed) ────────────────────────────────────────────────

# V5SectionAlias node :
# {alias_id: "alias_<hash>", old_section_id, new_section_id, tenant_id,
#  reason, created_at}

ALIAS_SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT v5_alias_unique IF NOT EXISTS "
    "FOR (a:V5SectionAlias) REQUIRE (a.tenant_id, a.old_section_id) IS UNIQUE",

    "CREATE INDEX v5_alias_new IF NOT EXISTS "
    "FOR (a:V5SectionAlias) ON (a.tenant_id, a.new_section_id)",
]


class SectionIdAliasMap:
    """Mapping persistent section_id legacy → section_id actuel.

    Use case : Docling v1 a généré sec_abc123. Docling v2 sur le même doc
    (mêmes contenus mais avec correction OCR d'un titre) génère sec_xyz789.
    Pour ne pas casser les citations utilisateur historiques :
        alias_map.add(old="sec_abc123", new="sec_xyz789", reason="ocr_fix_v2")
    Puis runtime appelle alias_map.resolve("sec_abc123") → "sec_xyz789".

    Hors scope du TenantQueryGuard : V5SectionAlias n'est pas V5* prefixed
    au sens DSG (V5Document/Section/Table). On gère le tenant_id manuellement
    dans toutes les requêtes.
    """

    def __init__(self, neo4j_client):
        self.client = neo4j_client

    def setup_schema(self) -> dict:
        """Applique constraints + indexes V5SectionAlias (idempotent)."""
        applied = 0
        errors = []
        for stmt in ALIAS_SCHEMA_STATEMENTS:
            try:
                self.client.execute_write(stmt)
                applied += 1
            except Exception as e:
                errors.append({"stmt": stmt[:120], "error": str(e)})
                logger.error(f"[SectionIdAliasMap] Failed: {stmt[:80]} — {e}")
        return {"applied": applied, "total": len(ALIAS_SCHEMA_STATEMENTS), "errors": errors}

    def add(
        self,
        tenant_id: str,
        old_section_id: str,
        new_section_id: str,
        reason: str = "",
    ) -> dict:
        """Enregistre un alias old_section_id → new_section_id.

        Args:
            tenant_id: tenant isolation key
            old_section_id: ID legacy (peut ne plus exister en DSG)
            new_section_id: ID actuel cible
            reason: motif libre (audit, ex: 'docling_v2_title_fix')

        Returns:
            dict avec alias_id
        """
        if not tenant_id or not old_section_id or not new_section_id:
            raise ValueError("tenant_id, old_section_id, new_section_id required")
        if old_section_id == new_section_id:
            raise ValueError("old_section_id must differ from new_section_id")

        alias_id = "alias_" + hashlib.sha256(
            f"{tenant_id}|{old_section_id}".encode("utf-8")
        ).hexdigest()[:24]

        query = """
        MERGE (a:V5SectionAlias {tenant_id: $tenant_id, old_section_id: $old_section_id})
        ON CREATE SET
            a.alias_id = $alias_id,
            a.new_section_id = $new_section_id,
            a.reason = $reason,
            a.created_at = datetime()
        ON MATCH SET
            a.new_section_id = $new_section_id,
            a.reason = $reason,
            a.updated_at = datetime()
        RETURN a.alias_id AS alias_id
        """
        result = self.client.execute_write(
            query,
            tenant_id=tenant_id,
            old_section_id=old_section_id,
            new_section_id=new_section_id,
            alias_id=alias_id,
            reason=reason,
        )
        return result[0] if result else {"alias_id": alias_id}

    def resolve(self, tenant_id: str, section_id: str) -> str:
        """Résout un section_id en suivant la chaîne d'alias jusqu'au plus récent.

        Limite anti-cycle : max 10 hops.

        Args:
            tenant_id: tenant isolation key
            section_id: ID à résoudre

        Returns:
            section_id actuel (ou l'input si pas d'alias)
        """
        if not tenant_id or not section_id:
            raise ValueError("tenant_id and section_id required")
        current = section_id
        visited = {current}
        for _ in range(10):
            query = """
            MATCH (a:V5SectionAlias {tenant_id: $tenant_id, old_section_id: $section_id})
            RETURN a.new_section_id AS new_id
            LIMIT 1
            """
            result = self.client.execute_query(
                query, tenant_id=tenant_id, section_id=current
            )
            if not result:
                return current
            new_id = result[0]["new_id"]
            if new_id in visited:
                logger.warning(
                    f"[SectionIdAliasMap] Cycle detected for {section_id} → {new_id}"
                )
                return current
            visited.add(new_id)
            current = new_id
        logger.warning(
            f"[SectionIdAliasMap] Max alias hops (10) reached for {section_id}"
        )
        return current

    def get_aliases(self, tenant_id: str, new_section_id: str) -> list[dict]:
        """Liste tous les old_section_id pointant vers ce new_section_id."""
        if not tenant_id or not new_section_id:
            raise ValueError("tenant_id and new_section_id required")
        query = """
        MATCH (a:V5SectionAlias {tenant_id: $tenant_id, new_section_id: $new_section_id})
        RETURN a
        ORDER BY a.created_at DESC
        """
        result = self.client.execute_query(
            query, tenant_id=tenant_id, new_section_id=new_section_id
        )
        return [dict(r["a"]) for r in result]

    def remove(self, tenant_id: str, old_section_id: str) -> bool:
        """Supprime un alias (use case : correction administrative)."""
        if not tenant_id or not old_section_id:
            raise ValueError("tenant_id and old_section_id required")
        query = """
        MATCH (a:V5SectionAlias {tenant_id: $tenant_id, old_section_id: $old_section_id})
        DELETE a
        RETURN count(a) AS deleted
        """
        result = self.client.execute_write(
            query, tenant_id=tenant_id, old_section_id=old_section_id
        )
        return bool(result and result[0].get("deleted", 0) > 0)

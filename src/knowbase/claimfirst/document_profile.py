"""
Document Profiling (B1 + B2) — chantier « En-tête de nature documentaire ».

Module AUTONOME et flag-gé (`V6_DOC_PROFILE`, défaut ON). Conçu pour être
désactivable / supprimable sans toucher au reste du pipeline ClaimFirst (cf.
`doc/ongoing/CH_ENTETE_NATURE_DOC.md`). La seule greffe est un appel unique en
Phase 7.7 de `orchestrator.process_and_persist`, encadré try/except non-bloquant.

But : restituer au point d'usage (le panneau de sources du chat) la NATURE/RÔLE
de chaque document, pour permettre un pré-filtrage sans ouvrir les fichiers.

- **B1** : classifieur de rôle documentaire OUVERT et domain-agnostic (INV-10).
  Un SEUL appel LLM retourne ``{summary, role, role_confidence, role_rationale}``.
  Le rôle est un libellé libre (« regulation », « standard », « specification »,
  « guidance »… mais NON limité à une liste figée), normalisé via un registre par
  tenant (``:DocRole``) pour collapser les variantes et éviter la dérive de libellés.
- **B2** : persistance ``role`` + ``summary`` + ``title`` sur le nœud ``:Document``.

Remplace au passage le hardcode SAP-logiciel de
``context_extractor.DOCUMENT_TYPE_PATTERNS`` pour cet usage d'affichage (le rôle
est désormais découvert par LLM, pas par regex orientée un domaine).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Feature flag
# ──────────────────────────────────────────────────────────────────────────────
def doc_profile_enabled() -> bool:
    """Profiling actif par défaut ; ``V6_DOC_PROFILE=0`` pour le désactiver."""
    return os.getenv("V6_DOC_PROFILE", "1") not in ("0", "false", "False")


# ──────────────────────────────────────────────────────────────────────────────
# B1 — Registre de rôles par tenant (normalisation, anti-dérive)
# ──────────────────────────────────────────────────────────────────────────────
def _role_key(label: str) -> str:
    """Clé de normalisation : minuscule, alphanumérique, pluriel léger replié."""
    k = re.sub(r"[^a-z0-9]+", "", (label or "").lower())
    if len(k) > 4 and k.endswith("s"):
        k = k[:-1]
    return k


def _role_display(label: str) -> str:
    """Forme d'affichage canonique (Title Case, espaces normalisés)."""
    cleaned = re.sub(r"\s+", " ", (label or "").strip())
    return cleaned.title() if cleaned else ""


class DocumentRoleRegistry:
    """Registre gouverné des rôles documentaires d'un tenant.

    Modelé sur ``FacetRegistry`` : cache mémoire + persistance Neo4j (``:DocRole``).
    Découvre les rôles du corpus (pas d'enum figé) tout en collapsant les variantes
    morphologiques via ``_role_key``. Partagé sur l'instance orchestrateur (donc sur
    tout le batch d'un import).
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self._by_key: Dict[str, str] = {}  # role_key → canonical display
        self._loaded = False

    def load(self, neo4j_driver: Any) -> None:
        """Charge les rôles canoniques existants depuis Neo4j (best-effort)."""
        if neo4j_driver is None:
            self._loaded = True
            return
        try:
            with neo4j_driver.session() as session:
                rows = session.run(
                    "MATCH (r:DocRole {tenant_id: $tid}) RETURN r.canonical AS canonical",
                    tid=self.tenant_id,
                )
                for row in rows:
                    canonical = row.get("canonical")
                    if canonical:
                        self._by_key[_role_key(canonical)] = canonical
            self._loaded = True
            logger.info(
                "[OSMOSE:DocProfile] Role registry loaded: %d canonical role(s) for tenant=%s",
                len(self._by_key), self.tenant_id,
            )
        except Exception as exc:  # noqa: BLE001 — non-bloquant
            logger.warning("[OSMOSE:DocProfile] Role registry load failed: %s", exc)
            self._loaded = True

    def normalize(self, raw_label: Optional[str], neo4j_driver: Any = None) -> Optional[str]:
        """Renvoie le rôle canonique pour ``raw_label`` ; en enregistre un nouveau si inédit."""
        if not raw_label:
            return None
        key = _role_key(raw_label)
        if not key:
            return None
        if key in self._by_key:
            return self._by_key[key]
        canonical = _role_display(raw_label)
        if not canonical:
            return None
        self._by_key[key] = canonical
        self._persist_new_role(neo4j_driver, canonical)
        return canonical

    def _persist_new_role(self, neo4j_driver: Any, canonical: str) -> None:
        if neo4j_driver is None:
            return
        try:
            with neo4j_driver.session() as session:
                session.run(
                    """
                    MERGE (r:DocRole {tenant_id: $tid, canonical: $canonical})
                    ON CREATE SET r.created_at = datetime()
                    """,
                    tid=self.tenant_id, canonical=canonical,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OSMOSE:DocProfile] Role registry persist failed: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# B1 — Profileur LLM (résumé + rôle, en UN appel)
# ──────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are a document analyst. You receive a document's title and the beginning of its text. Return STRICT JSON only, with exactly these fields:
- "summary": a concise 1-2 sentence summary (max 320 characters) of what the document is ABOUT (its topic/scope). No preamble, no markdown.
- "role": a SHORT label (1-3 words, lowercase) naming the NATURE / KIND of the document — i.e. what TYPE of document it is, NOT its subject matter. Use the most natural category term. Cross-domain examples (non-exhaustive, do not feel limited to these): "regulation", "standard", "specification", "guidance", "advisory circular", "technical manual", "user guide", "contract", "policy", "research paper", "report", "white paper", "release notes". If the kind is genuinely unclear from the text, use "document".
- "role_confidence": a number between 0.0 and 1.0.
- "role_rationale": one short sentence justifying the role, citing the textual cue (a header, a phrase, an identifier).

Hard rules:
- "role" describes the document's CATEGORY, never its topic. ("regulation", not "aircraft seats".)
- Be domain-agnostic: do not assume any particular industry.
- Do not invent a type unsupported by the text.
- Output ONLY the JSON object, nothing else."""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse tolérant : retire d'éventuelles fences puis isole le 1er objet JSON."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    return None


class DocumentProfiler:
    """Produit ``{summary, role, role_confidence, role_rationale}`` en un appel LLM.

    Le routeur est résolu paresseusement via ``get_llm_router()`` (même pattern que
    la classification métadonnées de l'orchestrateur). Un routeur peut être injecté
    pour les tests (objet exposant ``complete(...) -> str``).
    """

    def __init__(self, router: Any = None) -> None:
        self._router = router

    def _get_router(self) -> Any:
        if self._router is not None:
            return self._router
        from knowbase.common.llm_router import get_llm_router
        self._router = get_llm_router()
        return self._router

    def profile(
        self,
        title: Optional[str],
        text: Optional[str],
        authority: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retourne le profil ou ``None`` si l'appel/parse échoue."""
        from knowbase.common.llm_router import TaskType

        user_prompt = (
            f"TITLE: {title or '(unknown)'}\n"
            f"AUTHORITY: {authority or 'unknown'}\n\n"
            f"TEXT (beginning):\n{(text or '')[:3500]}"
        )
        try:
            raw = self._get_router().complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OSMOSE:DocProfile] LLM profile call failed: %s", exc)
            return None

        data = _extract_json(raw if isinstance(raw, str) else str(raw))
        if not data:
            logger.warning("[OSMOSE:DocProfile] Could not parse profile JSON")
            return None

        summary = (data.get("summary") or "").strip()[:320] or None
        role_raw = (data.get("role") or "").strip() or None
        try:
            conf = float(data.get("role_confidence"))
        except (TypeError, ValueError):
            conf = None
        rationale = (data.get("role_rationale") or "").strip()[:300] or None
        return {
            "summary": summary,
            "role_raw": role_raw,
            "role_confidence": conf,
            "role_rationale": rationale,
        }


# ──────────────────────────────────────────────────────────────────────────────
# B2 — Persistance sur le nœud :Document
# ──────────────────────────────────────────────────────────────────────────────
def persist_document_profile(
    neo4j_driver: Any,
    doc_id: str,
    tenant_id: str,
    *,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    role: Optional[str] = None,
    role_confidence: Optional[float] = None,
    role_rationale: Optional[str] = None,
) -> None:
    """``MERGE (d:Document) SET role/summary/title`` — idempotent, non destructif.

    Le titre n'écrase un titre existant que s'il apporte mieux que ``doc_id``.
    """
    safe_title = title if (title and title != doc_id) else None
    with neo4j_driver.session() as session:
        session.run(
            """
            MERGE (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
            SET d.role = $role,
                d.role_confidence = $role_confidence,
                d.role_rationale = $role_rationale,
                d.summary = $summary,
                d.title = coalesce($title, d.title),
                d.profiled_at = datetime()
            """,
            doc_id=doc_id,
            tenant_id=tenant_id,
            role=role,
            role_confidence=role_confidence,
            role_rationale=role_rationale,
            summary=summary,
            title=safe_title,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration B1 → normalize → B2 (point d'entrée appelé par l'orchestrateur)
# ──────────────────────────────────────────────────────────────────────────────
def run_document_profiling(
    *,
    neo4j_driver: Any,
    registry: DocumentRoleRegistry,
    doc_id: str,
    tenant_id: str,
    title: Optional[str],
    full_text: Optional[str],
    authority: Optional[str] = None,
    router: Any = None,
) -> Optional[str]:
    """Profile un document (B1), normalise son rôle, le persiste (B2).

    Retourne le rôle canonique persisté, ou ``None`` si rien n'a pu être produit.
    Tout échec est avalé en amont par l'appelant (non-bloquant).
    """
    profile = DocumentProfiler(router=router).profile(
        title=title, text=full_text, authority=authority
    )
    if not profile:
        return None

    canonical_role = registry.normalize(profile.get("role_raw"), neo4j_driver=neo4j_driver)
    persist_document_profile(
        neo4j_driver,
        doc_id,
        tenant_id,
        title=title,
        summary=profile.get("summary"),
        role=canonical_role,
        role_confidence=profile.get("role_confidence"),
        role_rationale=profile.get("role_rationale"),
    )
    return canonical_role

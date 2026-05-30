"""PremiseVerifier — détection des faux présupposés (runtime_v6, 2026-05-30).

Cf ADR_PREMISE_VERIFIER.md. Problème : le pipeline confabule sur les questions à
faux présupposé (ex : « Comment activer le module X ? » alors que X n'existe pas)
en récupérant des claims sur les *parties réelles* de la question puis en
fabriquant une réponse plausible.

Le retrieval vectoriel ne distingue PAS un faux présupposé d'une vraie question
(les entités fausses scorent aussi haut que les vraies — partie fausse diluée dans
le vecteur). Donc on ne peut pas se fier au score de retrieval.

Approche validée par la littérature (Kim 2021 ; CREPE 2023 ; FalseQA 2023 ;
Premise Verification via RAG Logical Reasoning 2025 ; Google Sufficient Context 2024) :

    1. EXTRAIRE les présupposés de la question (LLM few-shot CoT).
    2. RETRIEVAL DÉDIÉ PAR PRÉSUPPOSÉ (clé : preuve du présupposé, pas de la surface).
    3. VÉRIFIER 3-voies, ancré sur l'evidence dédiée :
        - OK              : présupposés supportés/plausibles → pipeline normal.
        - FALSE_CONTRADICTED : un présupposé est contredit → réponse corrective.
        - FALSE_UNSUPPORTED  : l'entité spécifique n'est pas attestée → note honnête.

Handling asymétrique anti-sur-abstention : seul CONTREDIT (ou entité principale
clairement absente) déclenche une correction ; jamais sur « réponse incomplète ».

Toggle env : V6_PREMISE_VERIFIER_ENABLED (défaut "0"). Fail-open (OK) sur erreur.
Domain-agnostic strict : aucun token corpus-spécifique.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Literal, Optional

logger = logging.getLogger("knowbase.runtime_a3.premise_verifier")

PremiseStatus = Literal["OK", "FALSE_CONTRADICTED", "FALSE_UNSUPPORTED"]

DEFAULT_QDRANT_COLLECTION = "knowbase_chunks_v2"


# ============================================================================
# Prompts (few-shot CoT, domain-agnostic — exemples INVENTÉS, jamais SAP)
# ============================================================================

_EXTRACT_SYSTEM = """You extract the PRESUPPOSITIONS of a user question — the factual
propositions the question takes for granted (the existence of an entity, a capability,
a feature, a relationship, or a procedure). These are what must be TRUE for the question
to be well-posed.

Rules:
- Focus on the SPECIFIC, checkable propositions, especially the existence of the named
  entity/feature and the relationship the question assumes.
- Keep each presupposition a short standalone declarative sentence.
- Do NOT include trivially-true general facts.
- Also output "focal_entity": the SINGLE most specific named entity/feature/identifier
  whose existence the question presupposes (verbatim as in the question), or "" if none.
- Output JSON ONLY: {"presuppositions": ["...", "..."], "focal_entity": "..."}
  (1 to 3 presuppositions, most specific first).

Examples:
Q: "How do I enable the Quantum Cache module in ProductX 2024?"
{"presuppositions": ["ProductX has a feature called the Quantum Cache module", "The Quantum Cache module can be enabled in ProductX 2024"], "focal_entity": "Quantum Cache module"}

Q: "How does native Oracle database support work in SystemY?"
{"presuppositions": ["SystemY natively supports the Oracle database"], "focal_entity": "native Oracle database support"}

Q: "What is the maximum payload of the Falcon-9 rocket?"
{"presuppositions": ["The Falcon-9 rocket has a defined maximum payload"], "focal_entity": "Falcon-9 rocket"}

Q: "What is the procedure to migrate directly from AppA to AppB-Cloud?"
{"presuppositions": ["A direct migration path from AppA to AppB-Cloud exists"], "focal_entity": "direct migration from AppA to AppB-Cloud"}
"""

_VERIFY_SYSTEM = """You verify whether a question's PRESUPPOSITIONS hold, given EVIDENCE
passages that were retrieved specifically to check those presuppositions.

Decide ONE overall status:
- "OK": the presuppositions are supported by the evidence, OR are plausible and NOT
  contradicted. Choose OK when the specific entity/feature/relationship is actually
  attested in the evidence, or when the evidence is simply silent about a plausible claim.
- "FALSE_CONTRADICTED": the evidence DIRECTLY contradicts a presupposition (states the
  opposite, or an incompatible requirement). Example: question assumes "system supports
  Oracle natively" but evidence says "the system requires database HANA".
- "FALSE_UNSUPPORTED": the question presupposes a SPECIFIC named entity/feature/procedure
  that does NOT appear in the evidence at all — only DIFFERENT or merely adjacent things
  appear (e.g. the question asks about "Reporting Studio" but evidence only mentions
  "analytics", never that exact feature). The specific thing is very likely non-existent
  or out of the documented scope.

CRITICAL (avoid false alarms):
- Be CONSERVATIVE. Prefer "OK" unless there is a CLEAR contradiction, or the core named
  entity is CLEARLY absent (only adjacent/different things present).
- Do NOT answer "FALSE_*" merely because the evidence does not fully answer the question.
  Incompleteness is NOT a false premise.
- "adjacent but different" (e.g. asks X, evidence shows a related-but-distinct Y) supports
  FALSE_UNSUPPORTED only when the SPECIFIC asked-about entity is the thing missing.

If status is FALSE_*, write a SHORT correction (1-2 sentences) grounded ONLY in the
evidence: state what the evidence actually says (the contradicting fact, or that the
specific thing is not documented). Never invent.

Output JSON ONLY:
{"status": "OK"|"FALSE_CONTRADICTED"|"FALSE_UNSUPPORTED", "reasoning": "<short>", "correction": "<short, only if FALSE_*>"}

Examples:
PRESUPPOSITIONS: ["SystemY natively supports the Oracle database"]
EVIDENCE: ["A new installation of SystemY needs to run on the HANA database.", "SystemY connects to external systems via standard connectors."]
{"status": "FALSE_CONTRADICTED", "reasoning": "Evidence states SystemY requires HANA; native Oracle support is incompatible.", "correction": "SystemY does not natively support Oracle; a new installation must run on the HANA database."}

PRESUPPOSITIONS: ["ProductX has a feature called the Quantum Cache module"]
EVIDENCE: ["ProductX provides in-memory analytics.", "ProductX caching is configured in the admin console."]
{"status": "FALSE_UNSUPPORTED", "reasoning": "No 'Quantum Cache module' appears; only generic caching/analytics, a different thing.", "correction": "The documentation does not mention a 'Quantum Cache module' in ProductX; only general caching and analytics features are documented."}

PRESUPPOSITIONS: ["The Falcon-9 rocket has a defined maximum payload"]
EVIDENCE: ["Falcon-9 can lift up to 22,800 kg to low Earth orbit."]
{"status": "OK", "reasoning": "Evidence attests the payload capacity.", "correction": ""}
"""


# ============================================================================
# Result dataclass
# ============================================================================


@dataclass
class PremiseResult:
    status: PremiseStatus
    presuppositions: List[str] = field(default_factory=list)
    reasoning: str = ""
    correction: str = ""
    duration_s: float = 0.0
    llm_failed: bool = False

    @property
    def is_false_premise(self) -> bool:
        return self.status in ("FALSE_CONTRADICTED", "FALSE_UNSUPPORTED")


# ============================================================================
# Verifier
# ============================================================================


class PremiseVerifier:
    """Détecte les faux présupposés via extraction + retrieval dédié + vérif 3-voies.

    Dependency injection (tests) :
        - llm_client : objet exposant `.complete(system, user) -> str`
        - embedder   : callable `(text) -> List[float]`
        - qdrant_search : callable signature search_with_tenant_filter
    """

    def __init__(
        self,
        llm_client: Any = None,
        embedder: Optional[Callable] = None,
        qdrant_search: Optional[Callable] = None,
        neo4j_client: Any = None,
        collection: str = DEFAULT_QDRANT_COLLECTION,
        top_k_per_premise: int = 5,
        max_premises: int = 3,
        max_evidence: int = 10,
        tenant_id: str = "default",
    ):
        self._llm_client = llm_client
        self._embedder = embedder
        self._qdrant_search = qdrant_search
        self._neo4j = neo4j_client
        self._collection = collection
        self._top_k = top_k_per_premise
        self._max_premises = max_premises
        self._max_evidence = max_evidence
        self._tenant_id = tenant_id

    # -- lazy clients ----------------------------------------------------
    def _get_llm(self):
        if self._llm_client is None:
            from knowbase.common.llm_router import get_llm_router, TaskType

            class _RouterClient:
                def __init__(self):
                    self._router = get_llm_router()

                def complete(self, system: str, user: str) -> str:
                    return self._router.complete(
                        task_type=TaskType.RUNTIME_PARSE_EVALUATE,  # DeepSeek-V3.1 (raisonnement)
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.0,
                        max_tokens=400,
                    ).strip()
            self._llm_client = _RouterClient()
        return self._llm_client

    def _get_embedder(self):
        if self._embedder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            mgr = EmbeddingModelManager()
            self._embedder = lambda text: mgr.encode([text])[0].tolist()
        return self._embedder

    def _get_search(self):
        if self._qdrant_search is None:
            from knowbase.common.clients.qdrant_client import search_with_tenant_filter
            self._qdrant_search = search_with_tenant_filter
        return self._qdrant_search

    def _get_neo4j(self):
        if self._neo4j is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            self._neo4j = get_neo4j_client()
        return self._neo4j

    # -- steps -----------------------------------------------------------
    def _extract_presuppositions(self, question: str) -> tuple[List[str], str]:
        raw = self._get_llm().complete(_EXTRACT_SYSTEM, f"Q: {question}\n\nRespond with JSON only.")
        data = _parse_json(raw) or {}
        pres = data.get("presuppositions")
        focal = str(data.get("focal_entity", "") or "").strip()
        if not isinstance(pres, list):
            return [], focal
        out = [str(p).strip() for p in pres if str(p).strip()]
        return out[: self._max_premises], focal

    def _entity_attested(self, entity: str) -> bool:
        """Confirmation lexicale : le nom exact de l'entité apparaît-il dans le corpus ?

        Anti-faux-positif UNSUPPORTED (papier 2025 : exiger une absence réelle, pas un
        simple raté de retrieval). Retrieval ciblé sur le nom seul + match lexical
        (substring OU tous les mots de contenu présents dans un même passage).
        """
        entity = (entity or "").strip()
        if len(entity) < 3:
            return False
        try:
            vec = self._get_embedder()(entity)
            hits = self._get_search()(
                collection_name=self._collection, query_vector=vec,
                tenant_id=self._tenant_id, limit=25,
            )
        except Exception:
            logger.exception("entity attestation retrieval failed for: %s", entity[:60])
            return False  # fail-safe : ne pas rétrograder si on ne peut pas confirmer

        ent_norm = _norm(entity)
        content_words = [w for w in ent_norm.split() if len(w) > 3]
        for h in hits:
            p = h.get("payload", {}) or {}
            txt = _norm((p.get("text") or p.get("content") or ""))
            if not txt:
                continue
            if ent_norm and ent_norm in txt:
                return True
            # fallback : tous les mots de contenu (≥4 lettres) présents dans le passage
            if content_words and all(w in txt for w in content_words):
                return True

        # Le savoir d'OSMOSIS vit aussi (surtout) dans les claims KG, pas seulement les
        # chunks (ex : « Labeling Workbench » présent dans 3 claims mais absent des
        # chunks). On vérifie donc aussi le KG par match lexical.
        return self._entity_attested_in_kg(ent_norm)

    def _entity_attested_in_kg(self, ent_norm: str) -> bool:
        """Le nom de l'entité apparaît-il littéralement dans le texte d'un claim KG ?"""
        if not ent_norm or len(ent_norm) < 3:
            return False
        try:
            rows = self._get_neo4j().execute_query(
                "MATCH (c:Claim) WHERE c.text IS NOT NULL AND toLower(c.text) CONTAINS $ent "
                "RETURN count(c) AS n LIMIT 1",
                ent=ent_norm,
            )
        except Exception:
            logger.exception("entity KG attestation failed for: %s", ent_norm[:60])
            return False  # fail-safe : ne pas rétrograder si on ne peut pas confirmer
        try:
            return bool(rows and (rows[0].get("n") or 0) > 0)
        except Exception:
            return False

    def _retrieve_for_premise(self, premise: str) -> List[str]:
        try:
            vec = self._get_embedder()(premise)
            hits = self._get_search()(
                collection_name=self._collection, query_vector=vec,
                tenant_id=self._tenant_id, limit=self._top_k,
            )
        except Exception:
            logger.exception("premise retrieval failed for: %s", premise[:80])
            return []
        passages = []
        for h in hits:
            p = h.get("payload", {}) or {}
            txt = (p.get("text") or p.get("content") or "").strip()
            if txt:
                passages.append(txt[:600])
        return passages

    def _verify(self, presuppositions: List[str], evidence: List[str]) -> dict:
        pres_block = json.dumps(presuppositions, ensure_ascii=False)
        ev_block = "\n".join(f"  - {e}" for e in evidence) if evidence else "  (no evidence retrieved)"
        user = (
            f"PRESUPPOSITIONS: {pres_block}\n\n"
            f"EVIDENCE:\n{ev_block}\n\n"
            "Respond with JSON only."
        )
        raw = self._get_llm().complete(_VERIFY_SYSTEM, user)
        return _parse_json(raw) or {}

    # -- public ----------------------------------------------------------
    def verify(self, question: str) -> PremiseResult:
        """Retourne un PremiseResult. Fail-open OK sur toute erreur."""
        t0 = time.perf_counter()
        if not question or not question.strip():
            return PremiseResult("OK", duration_s=time.perf_counter() - t0)

        try:
            presuppositions, focal_entity = self._extract_presuppositions(question)
        except Exception:
            logger.exception("premise extraction failed, fail-open OK")
            return PremiseResult("OK", duration_s=time.perf_counter() - t0, llm_failed=True)

        if not presuppositions:
            return PremiseResult("OK", reasoning="no_presupposition_extracted",
                                 duration_s=time.perf_counter() - t0)

        # Retrieval dédié par présupposé, pool dédupliqué
        seen, evidence = set(), []
        for p in presuppositions:
            for psg in self._retrieve_for_premise(p):
                key = psg[:120].lower()
                if key not in seen:
                    seen.add(key)
                    evidence.append(psg)
        evidence = evidence[: self._max_evidence]

        try:
            v = self._verify(presuppositions, evidence)
        except Exception:
            logger.exception("premise verification failed, fail-open OK")
            return PremiseResult("OK", presuppositions=presuppositions,
                                 duration_s=time.perf_counter() - t0, llm_failed=True)

        status = str(v.get("status", "OK")).upper()
        if status not in ("OK", "FALSE_CONTRADICTED", "FALSE_UNSUPPORTED"):
            status = "OK"

        # Confirmation lexicale anti-faux-positif : UNSUPPORTED = « non attesté ». Mais si
        # le nom exact de l'entité existe pourtant dans le corpus, c'était un raté de
        # retrieval (ex : « Labeling Workbench » existe → transaction CBGLWB) → on
        # rétrograde en OK. CONTRADICTED (contradiction explicite) n'est PAS concerné.
        if status == "FALSE_UNSUPPORTED" and focal_entity and self._entity_attested(focal_entity):
            logger.info("[PREMISE] UNSUPPORTED downgraded to OK — entity attested in corpus: %s",
                        focal_entity[:80])
            status = "OK"

        dt = time.perf_counter() - t0
        result = PremiseResult(
            status=status,  # type: ignore[arg-type]
            presuppositions=presuppositions,
            reasoning=str(v.get("reasoning", ""))[:300],
            correction=str(v.get("correction", ""))[:600],
            duration_s=dt,
        )
        logger.info("[PREMISE] status=%s dur=%.2fs n_pres=%d n_evidence=%d reasoning=%s",
                    status, dt, len(presuppositions), len(evidence), result.reasoning[:120])
        return result


# ============================================================================
# Parsing tolérant
# ============================================================================


def _norm(s: str) -> str:
    """Normalise pour match lexical : minuscules + espaces compactés."""
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _parse_json(raw: str) -> Optional[dict]:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    # fallback : isoler le premier objet {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
    return None


def is_enabled() -> bool:
    """Toggle env. Défaut OFF — activer pour bench A/B."""
    return os.getenv("V6_PREMISE_VERIFIER_ENABLED", "0") == "1"

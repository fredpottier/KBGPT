"""
QuestionSubjectResolver — Subject Resolver V2 vrai pour les questions utilisateur.

Remplace `ClaimRetriever.topic_with_coherence` (heuristique préfixe doc_id) par
une vraie résolution sémantique :
1. LLM extrait le sujet implicite/explicite de la question (1 call)
2. Match contre les primary_subject existants du KG via embedding cosine
3. Retourne le subject_id avec confidence + alternatives + ambiguity flag

CH-35.A3 — anchor tie-breaker :
Quand plusieurs matches sont proches en score (<0.05 d'écart), prioriser celui
dont le doc_id contient une mention explicite de la question (ex: "amdt 27"
mentionné → prefer cs25_amdt_27_*). Corrige les off-topic "amdt 25 au lieu de
amdt 27 demandé" identifiés en CH-34 audit.

Conformément à VISION_RECENTREE §3 étape 1 (Subject Resolver).
Domain-agnostic, pas de regex/keywords métier — les anchors sont extraits par
patterns numériques/structurels uniquement (numéros, versions, années).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx
from neo4j import Driver
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# CH-35.A3 — Patterns d'extraction d'anchor depuis la question
# DOMAIN-AGNOSTIC : capture les tokens structurels/numériques universels.
# Patterns domain-specific (CS codes, NPA aerospace, ATC codes biomédical, etc.)
# pourraient être ajoutés via Domain Pack si nécessaire.
_ANCHOR_PATTERNS = [
    # Numéros normés "X/Y" : régulations EU, ISO 27001/2022, brevets US 10/123456
    re.compile(r"\b\d{1,5}/\d{2,5}\b"),
    # Versions : v1.2.3, version 2.0
    re.compile(r"\bv(?:ersion)?\s*\d+(?:\.\d+){1,3}\b", re.IGNORECASE),
    # Amendments / revisions / updates
    re.compile(r"\b(?:amdt|amendment|amd|revision|rev|update)[\s_-]?(\d{1,3})\b", re.IGNORECASE),
    # Articles / sections / paragraphes
    re.compile(r"\b(?:art(?:icle)?\.?|section|sect\.?|§|paragraph|para\.?|clause|chapter|chap\.?)[\s_-]?(\d{1,4}(?:\.\d+)*(?:\([a-z\d]+\))?)\b", re.IGNORECASE),
    # Annexes / appendices (Annex I-V, Appendix A-Z) — universel legal
    re.compile(r"\b(?:annex|annexe|appendix|appendice|appendice)[\s_-]?(?:iv|iii|ii|vi+|ix|xi*|i|v|x|\d+|[a-z])\b", re.IGNORECASE),
    # Standard IDs : ISO 27001, RFC 7231, CVE-2024-1234
    re.compile(r"\b(?:CVE|ISO|IEC|IEEE|RFC|ANSI|DIN|EN|ASTM)[-\s]?\d+(?:[-\s/]\d+)*\b", re.IGNORECASE),
]


# Patterns domain-specific (chargés conditionnellement via Domain Pack)
# Pour aerospace_compliance — extraits de la question pour matcher les doc_ids type cs25_amdt_*
_DOMAIN_ANCHOR_PATTERNS = {
    "aerospace_compliance": [
        re.compile(r"\bcs[\s_-]?\d{1,3}(?:\.\d{1,4})?(?:\([a-z\d]+\))?\b", re.IGNORECASE),  # CS 25.788
        re.compile(r"\bnpa[\s_-]?\d{4}-\d{1,3}\b", re.IGNORECASE),  # NPA 2015-19
    ],
    "biomedical": [
        re.compile(r"\b[A-Z]\d{2}[A-Z]{2}\d{2}\b"),  # ATC code
    ],
    "enterprise_sap": [
        re.compile(r"\b(?:SAP\s+Note|note)\s+\d{6,8}\b", re.IGNORECASE),  # SAP Note 1234567
    ],
}


def _extract_anchors_from_question(question: str, domain: Optional[str] = None) -> list[str]:
    """Extrait les ancres numériques/structurelles de la question.

    Ancres typiques (domain-agnostic) : numéros de régulations/normes, amendments,
    articles/sections, versions logiciel, standard IDs (ISO/CVE/RFC).
    Avec un Domain Pack actif, ajoute des patterns domain-specific (CS/NPA pour
    aerospace, ATC pour biomédical, SAP Note pour enterprise SAP).
    """
    patterns = list(_ANCHOR_PATTERNS)
    if domain and domain in _DOMAIN_ANCHOR_PATTERNS:
        patterns.extend(_DOMAIN_ANCHOR_PATTERNS[domain])
    anchors = []
    for pattern in patterns:
        for m in pattern.finditer(question):
            full = m.group(0).lower()
            anchors.append(full)
            # Aussi capturer le numéro brut pour permettre des matches sur "27" etc.
            for grp in m.groups():
                if grp and grp.isdigit():
                    anchors.append(grp.lower())
    # Dedupe en préservant l'ordre
    seen = set()
    out = []
    for a in anchors:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _doc_id_matches_anchor(doc_id: str, anchors: list[str]) -> int:
    """Compte combien d'anchors sont présents dans le doc_id (case-insensitive)."""
    did_lower = doc_id.lower()
    n = 0
    for a in anchors:
        # Normalisation : "amdt 27" → "amdt_27" pour matcher cs25_amdt_27_*
        a_norm = a.replace(" ", "_").replace("-", "_")
        # Test variantes : token brut, token normalisé, et chiffres seuls
        if a_norm in did_lower or a in did_lower:
            n += 1
    return n


SUBJECT_EXTRACTION_PROMPT = """You are a question analyst. Given a user question, identify what SUBJECT (entity, document, product, regulation, system, protocol) the question is fundamentally about.

The subject is the core thing being asked about — what would stay constant if the question were rephrased.

Examples (cross-domain):
- "What is the encryption mode of S/4HANA Cloud Private Edition?" → subject = "S/4HANA Cloud Private Edition"
- "How did EU dual-use export control evolve?" → subject = "EU dual-use export control"
- "What does Regulation 2021/821 say about brokering?" → subject = "Regulation (EU) 2021/821"
- "Quelles sont les exigences CS-25 ?" → subject = "CS-25"
- "What is the recommended dose for biomarker X?" → subject = "biomarker X"

Output JSON only:
{
  "subject_label": "<short descriptive label of the subject>",
  "confidence": 0.0-1.0,
  "is_ambiguous": false | true,
  "alternative_subjects": ["<alt 1>", "<alt 2>"],
  "reasoning": "<brief>"
}

Rules:
1. Subject_label must be SHORT (2-8 words max) and CAPTURE THE ESSENCE.
2. If the question could legitimately concern multiple distinct subjects → set is_ambiguous=true and list them in alternative_subjects.
3. If the question is too vague to identify a subject → confidence < 0.5.
4. Multilingual: same logic regardless of question language."""


class SubjectExtraction(BaseModel):
    """Extraction LLM brute du sujet de la question."""

    subject_label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    is_ambiguous: bool = False
    alternative_subjects: list[str] = Field(default_factory=list)
    reasoning: Optional[str] = None


class SubjectMatch(BaseModel):
    """Match d'un sujet extrait contre un sujet connu du KG."""

    matched_doc_ids: list[str]
    primary_subject: str
    cosine_score: float


class QuestionSubjectResolverResult(BaseModel):
    """Résultat complet du Subject Resolver V2 pour une question."""

    extraction: SubjectExtraction
    matches: list[SubjectMatch] = Field(default_factory=list)
    consolidated_doc_ids: list[str] = Field(default_factory=list)
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None


class QuestionSubjectResolver:
    """Subject Resolver V2 pour le pipeline runtime V2.

    Utilise :
    - LLM Qwen3-235B (DeepInfra) pour extraire le sujet de la question (~1300 tokens)
    - Embedding cosine pour matcher contre primary_subject du KG
    """

    def __init__(
        self,
        driver: Driver,
        embedder,
        vllm_url: str,
        tenant_id: str = "default",
        vllm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout: float = 120.0,
    ) -> None:
        self.driver = driver
        self.embedder = embedder
        self.vllm_url = vllm_url.rstrip("/")
        self.tenant_id = tenant_id
        self.vllm_model = vllm_model
        self.timeout = timeout
        self._subjects_cache: Optional[list[dict]] = None

    def resolve(
        self,
        question: str,
        cosine_threshold: float = 0.55,
        top_k: int = 5,
    ) -> QuestionSubjectResolverResult:
        """Résout le sujet d'une question.

        Pipeline :
        1. LLM extrait le sujet de la question
        2. Embed le subject_label
        3. Cosine vs primary_subject embeddings du KG (top_k)
        4. Si top score < threshold → fallback vers recherche par tokens (lighter version of topic_with_coherence)
        5. Si extraction.is_ambiguous OR multiple matches forts → flag ambiguity
        """
        # 1. LLM extraction
        extraction = self._extract_subject_llm(question)
        if extraction.confidence < 0.4:
            return QuestionSubjectResolverResult(
                extraction=extraction,
                consolidated_doc_ids=[],
                is_ambiguous=True,
                ambiguity_reason=(
                    f"Subject extraction confidence too low ({extraction.confidence:.2f}). "
                    f"Question may be too vague."
                ),
            )

        # 2-3. Embed + match
        matches = self._match_subjects(extraction.subject_label, top_k=top_k)
        strong_matches = [m for m in matches if m.cosine_score >= cosine_threshold]

        # CH-35.A3 — Anchor tie-breaker : quand le top score est proche d'un autre,
        # prioriser le match dont les doc_ids contiennent une ancre explicite de la question
        anchors = _extract_anchors_from_question(question)
        if anchors and len(strong_matches) > 1:
            top_score = strong_matches[0].cosine_score
            # Détecter les "proches" du top (within 0.08 cosine)
            close = [(i, m) for i, m in enumerate(strong_matches) if m.cosine_score >= top_score - 0.08]
            if len(close) > 1:
                # Re-scorer avec anchor boost : compter les anchors présents dans les doc_ids
                rescored = []
                for i, m in close:
                    n_anchors = max((_doc_id_matches_anchor(did, anchors) for did in m.matched_doc_ids), default=0)
                    rescored.append((n_anchors, m.cosine_score, i, m))
                # Tri : plus d'anchors d'abord, puis cosine
                rescored.sort(key=lambda t: (-t[0], -t[1]))
                # Si le top après rescoring n'est PAS le top initial, et qu'il a au moins 1 anchor →
                # promouvoir ce match au top
                new_top_anchor_count = rescored[0][0]
                old_top_anchor_count = next((n for n, _, i, _ in rescored if i == 0), 0)
                if new_top_anchor_count > old_top_anchor_count:
                    promoted = rescored[0][3]
                    logger.info(
                        f"[SubjectResolver:anchor] Tie-breaker: promoting '{promoted.primary_subject}' "
                        f"(anchors={new_top_anchor_count}) over '{strong_matches[0].primary_subject}' "
                        f"(anchors={old_top_anchor_count}) | question_anchors={anchors[:5]}"
                    )
                    # Réordonner strong_matches : promoted en tête, le reste préserve l'ordre original
                    new_order = [promoted]
                    for m in strong_matches:
                        if m is not promoted:
                            new_order.append(m)
                    strong_matches = new_order

        # 4. Si pas de strong match, retourne tout pour fallback Anchor Filter
        if not strong_matches:
            return QuestionSubjectResolverResult(
                extraction=extraction,
                matches=matches,
                consolidated_doc_ids=[],
                is_ambiguous=False,
                ambiguity_reason="No strong subject match in KG; pipeline will use full corpus.",
            )

        # 5. Consolider les doc_ids des strong matches
        consolidated = []
        seen = set()
        for m in strong_matches:
            for did in m.matched_doc_ids:
                if did not in seen:
                    seen.add(did)
                    consolidated.append(did)

        # 6. Détection ambiguity : LLM dit ambigu OU plusieurs subjects distincts en haut
        is_ambig = extraction.is_ambiguous
        ambig_reason = None
        if not is_ambig and len(strong_matches) > 1:
            # Plusieurs subjects distincts détectés (top_score similaires)
            # Note CH-35.A3 : si l'anchor tie-breaker a déjà tranché, on ne flag plus comme ambigu
            top1 = strong_matches[0].cosine_score
            anchor_resolved = bool(anchors) and _doc_id_matches_anchor(
                strong_matches[0].matched_doc_ids[0] if strong_matches[0].matched_doc_ids else "",
                anchors,
            ) > 0
            if not anchor_resolved and any(
                m.cosine_score >= top1 - 0.05 and m.primary_subject != strong_matches[0].primary_subject
                for m in strong_matches[1:]
            ):
                is_ambig = True
                ambig_reason = (
                    f"Multiple subjects matched: "
                    f"{', '.join(m.primary_subject for m in strong_matches[:3])}"
                )

        return QuestionSubjectResolverResult(
            extraction=extraction,
            matches=matches,
            consolidated_doc_ids=consolidated,
            is_ambiguous=is_ambig,
            ambiguity_reason=ambig_reason,
        )

    # ------------------------------------------------------------------

    def _extract_subject_llm(self, question: str) -> SubjectExtraction:
        """Single LLM call pour extraire le subject_label de la question."""
        try:
            from knowbase.runtime_v2.llm_client import get_runtime_llm_client
            client = get_runtime_llm_client()
            content = client.chat_completion(
                messages=[
                    {"role": "system", "content": SUBJECT_EXTRACTION_PROMPT},
                    {"role": "user", "content": f"Question: {question}\n\nExtract subject as JSON:"},
                ],
                temperature=0.1,
                max_tokens=250,
                json_mode=True,
                timeout=self.timeout,
                model_override="mistralai/Mistral-Small-3.1-24B-Instruct-2503",
            )
            data = json.loads(content)
            return SubjectExtraction(
                subject_label=data.get("subject_label", ""),
                confidence=float(data.get("confidence", 0.0)),
                is_ambiguous=bool(data.get("is_ambiguous", False)),
                alternative_subjects=data.get("alternative_subjects", []) or [],
                reasoning=data.get("reasoning"),
            )
        except Exception as exc:
            logger.warning(f"QuestionSubjectResolver LLM call failed: {exc}")
            return SubjectExtraction(
                subject_label="",
                confidence=0.0,
                is_ambiguous=False,
                reasoning=f"LLM extraction failed: {exc}",
            )

    def _match_subjects(self, subject_label: str, top_k: int = 5) -> list[SubjectMatch]:
        """Embed le subject_label + cosine vs tous les primary_subject du KG."""
        if not subject_label:
            return []
        try:
            target_vec = self.embedder.encode(f"query: {subject_label}").tolist()
        except Exception as exc:
            logger.warning(f"Embedder failed: {exc}")
            return []

        # Charger les primary_subject + leurs doc_ids (avec cache local)
        subjects = self._load_subjects()
        if not subjects:
            return []

        # Embed primary_subjects (mémoization soft : on encode tous d'un coup)
        if any("vec" not in s for s in subjects):
            try:
                texts = [f"passage: {s['primary_subject']}" for s in subjects]
                vecs = self.embedder.encode(texts)
                for s, v in zip(subjects, vecs):
                    s["vec"] = v.tolist()
            except Exception as exc:
                logger.warning(f"Subject embedding batch failed: {exc}")
                return []

        # Cosine similarity
        import numpy as np

        target = np.array(target_vec)
        target_norm = float(np.linalg.norm(target))
        if target_norm == 0:
            return []

        scored = []
        for s in subjects:
            vec = np.array(s["vec"])
            vec_norm = float(np.linalg.norm(vec))
            if vec_norm == 0:
                continue
            cos = float(np.dot(target, vec) / (target_norm * vec_norm))
            scored.append((cos, s))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SubjectMatch(
                primary_subject=s["primary_subject"],
                matched_doc_ids=s["doc_ids"],
                cosine_score=round(cos, 4),
            )
            for cos, s in scored[:top_k]
        ]

    def _load_subjects(self) -> list[dict]:
        """Charge primary_subject distincts + leurs doc_ids depuis Neo4j (avec cache)."""
        if self._subjects_cache is not None:
            return self._subjects_cache
        cypher = """
        MATCH (dc:DocumentContext)
        WHERE dc.tenant_id = $tenant_id AND dc.primary_subject IS NOT NULL AND dc.primary_subject <> ''
        WITH dc.primary_subject AS subject, collect(dc.doc_id) AS doc_ids
        RETURN subject AS primary_subject, doc_ids
        ORDER BY size(doc_ids) DESC
        """
        with self.driver.session() as session:
            rows = session.run(cypher, tenant_id=self.tenant_id).data()
        self._subjects_cache = [
            {"primary_subject": r["primary_subject"], "doc_ids": r["doc_ids"]}
            for r in rows
        ]
        logger.info(f"QuestionSubjectResolver: loaded {len(self._subjects_cache)} distinct primary_subjects")
        return self._subjects_cache

    def invalidate_cache(self) -> None:
        """Force reload (utile après ingestion nouvelle)."""
        self._subjects_cache = None

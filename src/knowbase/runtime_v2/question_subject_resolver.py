"""
QuestionSubjectResolver — Subject Resolver V2 vrai pour les questions utilisateur.

Remplace `ClaimRetriever.topic_with_coherence` (heuristique préfixe doc_id) par
une vraie résolution sémantique :
1. LLM extrait le sujet implicite/explicite de la question (1 call)
2. Match contre les primary_subject existants du KG via embedding cosine
3. Retourne le subject_id avec confidence + alternatives + ambiguity flag

Conformément à VISION_RECENTREE §3 étape 1 (Subject Resolver).
Domain-agnostic, pas de regex/keywords.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from neo4j import Driver
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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
        timeout: float = 30.0,
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
            top1 = strong_matches[0].cosine_score
            if any(m.cosine_score >= top1 - 0.05 and m.primary_subject != strong_matches[0].primary_subject for m in strong_matches[1:]):
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
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.vllm_url}/v1/chat/completions",
                    json={
                        "model": self.vllm_model,
                        "messages": [
                            {"role": "system", "content": SUBJECT_EXTRACTION_PROMPT},
                            {"role": "user", "content": f"Question: {question}\n\nExtract subject as JSON:"},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 300,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
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

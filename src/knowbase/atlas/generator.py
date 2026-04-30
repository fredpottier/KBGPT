"""
AtlasGenerator — pipeline LLM qui génère un Atlas narratif depuis les Perspectives V2.

Pour chaque Perspective :
1. LLM rédige un titre narratif + executive_summary 3-5 phrases + 2-4 sections
2. Persiste comme NarrativeTopic en Neo4j

Plus :
- 1 LLM call pour rédiger AtlasHomepage.introduction
- Group les NarrativeTopics en AtlasRoots (par dominant_facet)

Coût ~$0.02 par génération complète sur 60 Perspectives.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

import httpx
from neo4j import Driver
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


TOPIC_PROMPT = """You are a documentary editor producing one section of a narrative atlas.

Given a "perspective" (a coherent cluster of claims sharing subjects/facets), write:
- title : 4-8 words, descriptive (not generic)
- executive_summary : 3-5 sentences explaining what this perspective covers and why it matters
- sections : 2-4 sub-sections, each with title (3-6 words) + content (2-4 sentences)

Rules:
1. Write in the SAME language as the input (English/French detected from labels).
2. Use ONLY the provided perspective metadata. Do not invent facts.
3. Cite document categories (e.g., "EU regulations", "EASA certifications") when relevant.
4. Tone: neutral, factual, narrative (not bullet points).

Output JSON only:
{
  "title": "<4-8 words>",
  "executive_summary": "<3-5 sentences>",
  "sections": [
    {"title": "<3-6 words>", "content": "<2-4 sentences>"}
  ]
}"""


HOMEPAGE_PROMPT = """You are writing the homepage introduction for a documentary atlas.

Given a list of narrative topics, write a 4-6 sentences introduction that:
- Describes what this atlas covers (domains, types of documents)
- Highlights 2-3 key themes
- Invites the reader to navigate

Rules:
1. Same language as the topics.
2. Concise. Inviting tone.
3. No technical jargon unless from the topics themselves.

Output JSON only:
{"introduction": "<4-6 sentences>"}"""


class AtlasGenerationStats(BaseModel):
    """Statistiques d'une génération Atlas."""

    n_perspectives_processed: int = 0
    n_topics_generated: int = 0
    n_topics_persisted: int = 0
    n_roots_created: int = 0
    homepage_generated: bool = False
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    estimated_cost_usd: float = 0.0


class AtlasGenerator:
    """Pipeline LLM de génération Atlas narratif depuis Perspectives V2.

    Args:
        driver: Neo4j driver
        vllm_url: URL vLLM EC2
        tenant_id: tenant
        vllm_model: modèle LLM
        timeout: timeout HTTP (par call)
    """

    def __init__(
        self,
        driver: Driver,
        vllm_url: str,
        tenant_id: str = "default",
        vllm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout: float = 30.0,
    ) -> None:
        self.driver = driver
        self.vllm_url = vllm_url.rstrip("/")
        self.tenant_id = tenant_id
        self.vllm_model = vllm_model
        self.timeout = timeout

    def generate_all(
        self,
        max_perspectives: int = 60,
        wipe_existing: bool = False,
    ) -> AtlasGenerationStats:
        """Génère tout l'Atlas en boucle.

        Args:
            max_perspectives: borne supérieure de Perspectives traitées
            wipe_existing: si True, supprime AtlasHomepage/Root/NarrativeTopic existants avant

        Returns stats détaillées.
        """
        import time as _time
        t_start = _time.time()
        stats = AtlasGenerationStats()

        if wipe_existing:
            self._wipe_existing()

        # 1. Charger les Perspectives
        perspectives = self._load_perspectives(max_perspectives)
        stats.n_perspectives_processed = len(perspectives)
        logger.info(f"AtlasGenerator: processing {len(perspectives)} perspectives")

        # 2. Générer un NarrativeTopic par Perspective
        topics: list[dict] = []
        for i, p in enumerate(perspectives, 1):
            try:
                topic = self._generate_topic(p)
                if topic is not None:
                    topics.append({**topic, "perspective_id": p["perspective_id"], "facets": p.get("facets", [])})
                    stats.n_topics_generated += 1
                    logger.info(f"  [{i}/{len(perspectives)}] {topic.get('title', '?')[:50]}")
            except Exception as exc:
                stats.errors.append(f"topic_{p.get('perspective_id', '?')}: {exc}")
                logger.warning(f"  [{i}/{len(perspectives)}] FAILED: {exc}")

        # 3. Group topics → AtlasRoots (par dominant_facet du group)
        roots = self._group_into_roots(topics)
        stats.n_roots_created = len(roots)
        logger.info(f"AtlasGenerator: grouped into {len(roots)} roots")

        # 4. Persist topics + roots
        for root_id, root_data in roots.items():
            self._persist_root(root_id, root_data)
        for topic in topics:
            self._persist_topic(topic, root_id=self._get_root_for_topic(topic, roots))
            stats.n_topics_persisted += 1

        # 5. AtlasHomepage intro
        try:
            intro = self._generate_homepage_intro(topics)
            self._persist_homepage(intro)
            stats.homepage_generated = True
        except Exception as exc:
            stats.errors.append(f"homepage: {exc}")

        stats.duration_seconds = round(_time.time() - t_start, 1)
        # Estimation coût : ~1500 tokens/topic × $0.000171/k = ~$0.000257/topic + 1 homepage call
        stats.estimated_cost_usd = round(stats.n_topics_generated * 0.000257 + 0.0005, 4)
        return stats

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_perspectives(self, limit: int) -> list[dict]:
        cypher = """
        MATCH (p:Perspective)
        WHERE p.tenant_id = $tid
        RETURN p.perspective_id AS perspective_id,
               coalesce(p.label, '') AS label,
               coalesce(p.description, '') AS description,
               coalesce(p.linked_subject_names, []) AS subjects,
               coalesce(p.dominant_facet_names, []) AS facets,
               coalesce(p.keywords, []) AS keywords,
               coalesce(p.claim_count, 0) AS claim_count,
               coalesce(p.doc_count, 0) AS doc_count,
               coalesce(p.importance_score, 0.0) AS importance_score
        ORDER BY p.importance_score DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            rows = session.run(cypher, tid=self.tenant_id, limit=limit).data()
        return rows

    # ------------------------------------------------------------------
    # LLM generation
    # ------------------------------------------------------------------

    def _generate_topic(self, perspective: dict) -> Optional[dict]:
        """1 LLM call pour rédiger title + summary + sections."""
        user_input = (
            f"Perspective metadata:\n"
            f"- label: {perspective['label']}\n"
            f"- description: {perspective['description']}\n"
            f"- subjects ({len(perspective.get('subjects', []))}): "
            f"{', '.join((perspective.get('subjects') or [])[:8])}\n"
            f"- dominant facets: {', '.join((perspective.get('facets') or [])[:5])}\n"
            f"- keywords: {', '.join((perspective.get('keywords') or [])[:8])}\n"
            f"- claim count: {perspective['claim_count']}, doc count: {perspective['doc_count']}\n\n"
            f"Now write the narrative topic JSON:"
        )
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.vllm_url}/v1/chat/completions",
                    json={
                        "model": self.vllm_model,
                        "messages": [
                            {"role": "system", "content": TOPIC_PROMPT},
                            {"role": "user", "content": user_input},
                        ],
                        "temperature": 0.4,
                        "max_tokens": 600,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = json.loads(resp.json()["choices"][0]["message"]["content"])
                if not data.get("title") or not data.get("executive_summary"):
                    return None
                return data
        except Exception as exc:
            logger.warning(f"Topic LLM call failed: {exc}")
            return None

    def _generate_homepage_intro(self, topics: list[dict]) -> str:
        """1 LLM call pour rédiger l'intro de l'AtlasHomepage."""
        if not topics:
            return "Atlas documentaire vide."
        sample_titles = [t.get("title", "?") for t in topics[:10]]
        user_input = (
            f"Sample topic titles ({len(topics)} total):\n"
            + "\n".join(f"- {t}" for t in sample_titles)
            + "\n\nWrite the homepage introduction JSON:"
        )
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.vllm_url}/v1/chat/completions",
                    json={
                        "model": self.vllm_model,
                        "messages": [
                            {"role": "system", "content": HOMEPAGE_PROMPT},
                            {"role": "user", "content": user_input},
                        ],
                        "temperature": 0.4,
                        "max_tokens": 400,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = json.loads(resp.json()["choices"][0]["message"]["content"])
                return data.get("introduction", "")
        except Exception as exc:
            logger.warning(f"Homepage intro LLM call failed: {exc}")
            return "Cet atlas regroupe les perspectives narratives extraites du corpus documentaire."

    # ------------------------------------------------------------------
    # Grouping into roots
    # ------------------------------------------------------------------

    def _group_into_roots(self, topics: list[dict]) -> dict[str, dict]:
        """Group topics par dominant_facet majoritaire → AtlasRoot."""
        roots: dict[str, dict] = {}
        for t in topics:
            facets = t.get("facets") or []
            root_name = facets[0] if facets else "General"
            root_id = "root_" + "".join(c if c.isalnum() else "_" for c in root_name.lower())[:40]
            if root_id not in roots:
                roots[root_id] = {"name": root_name, "topics": [], "claim_count": 0}
            roots[root_id]["topics"].append(t)
        return roots

    def _get_root_for_topic(self, topic: dict, roots: dict[str, dict]) -> str:
        facets = topic.get("facets") or []
        root_name = facets[0] if facets else "General"
        return "root_" + "".join(c if c.isalnum() else "_" for c in root_name.lower())[:40]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _wipe_existing(self) -> None:
        """Supprime AtlasHomepage + AtlasRoot + NarrativeTopic (idempotent)."""
        with self.driver.session() as session:
            for label in ("AtlasHomepage", "AtlasRoot", "NarrativeTopic"):
                session.run(f"MATCH (n:{label} {{tenant_id: $tid}}) DETACH DELETE n", tid=self.tenant_id)
        logger.info("AtlasGenerator: wiped existing AtlasHomepage / AtlasRoot / NarrativeTopic")

    def _persist_root(self, root_id: str, root_data: dict) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (r:AtlasRoot {root_id: $rid, tenant_id: $tid})
                SET r.name = $name, r.created_at = datetime()
                """,
                rid=root_id, tid=self.tenant_id, name=root_data["name"],
            )

    def _persist_topic(self, topic: dict, root_id: str) -> None:
        topic_id = "topic_" + topic["perspective_id"][-12:]
        sections_json = json.dumps(topic.get("sections") or [], ensure_ascii=False)
        with self.driver.session() as session:
            session.run(
                """
                MATCH (r:AtlasRoot {root_id: $rid, tenant_id: $tid})
                MERGE (t:NarrativeTopic {topic_id: $topic_id, tenant_id: $tid})
                SET t.title = $title,
                    t.executive_summary = $summary,
                    t.sections_json = $sections,
                    t.perspective_id = $pid,
                    t.created_at = datetime()
                MERGE (r)-[:HAS_CHAPTER]->(t)
                """,
                rid=root_id, tid=self.tenant_id, topic_id=topic_id,
                title=topic.get("title") or "Untitled",
                summary=topic.get("executive_summary") or "",
                sections=sections_json,
                pid=topic.get("perspective_id", ""),
            )

    def _persist_homepage(self, introduction: str) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (h:AtlasHomepage {tenant_id: $tid})
                SET h.introduction = $intro,
                    h.generated_at = datetime()
                """,
                tid=self.tenant_id, intro=introduction,
            )

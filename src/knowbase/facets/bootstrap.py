"""
FacetEngine V2 — Bootstrap (Pass F1).

Extrait les facettes candidates depuis les documents via LLM.
Produit des facettes avec description + exemples, SANS keywords.

Le LLM voit un echantillon de claims par document et propose
les dimensions transverses du corpus.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from knowbase.facets.models import Facet, FacetCandidate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a document analyst. Your task is to identify the main CROSS-CUTTING DIMENSIONS
(facets) that organize the knowledge in a corpus of technical documents.

A facet is NOT a topic or a document title. It is a TRANSVERSE ANGLE that groups
information from multiple documents. Examples: "Security", "Compliance", "Operations".

Rules:
- Output 5-10 facets maximum
- Each facet must have a clear, short label (1-3 words)
- Each facet must have a description (1-2 sentences)
- Each facet must have a family: "thematic" | "normative" | "operational"
- Do NOT use document titles, version numbers, or product names as facets
- Do NOT use vague labels like "General", "Other", "Miscellaneous"
- Facets should be UNIVERSAL (applicable across different domains)

Output JSON format:
{
  "facets": [
    {
      "label": "Security",
      "description": "Controls, protective mechanisms, identity management, access policies, encryption, and defensive configurations.",
      "family": "normative",
      "example_claims": ["claim text 1", "claim text 2", "claim text 3"]
    }
  ]
}
"""


def bootstrap_facets_from_claims(
    claims_by_doc: Dict[str, List[str]],
    llm_fn,
    max_sample_per_doc: int = 15,
    max_docs: int = 10,
) -> List[FacetCandidate]:
    """
    Extrait les facettes candidates depuis un echantillon de claims.

    Au lieu d'un appel LLM par document (V1), fait UN SEUL appel
    avec un echantillon representatif de tout le corpus.
    Cela produit des facettes plus transverses et moins document-specifiques.

    Args:
        claims_by_doc: Dict doc_id → [claim texts]
        llm_fn: Fonction LLM (prompt → response text)
        max_sample_per_doc: Claims echantillonnees par doc
        max_docs: Nombre max de docs dans l'echantillon

    Returns:
        Liste de FacetCandidate
    """
    # Construire un echantillon representatif
    sample_lines = []
    docs_sampled = 0
    for doc_id, claims in sorted(claims_by_doc.items()):
        if docs_sampled >= max_docs:
            break
        doc_short = doc_id[:50]
        sampled = claims[:max_sample_per_doc]
        for claim in sampled:
            sample_lines.append(f"[{doc_short}] {claim[:200]}")
        docs_sampled += 1

    user_prompt = (
        f"Here are {len(sample_lines)} sample claims from {docs_sampled} documents:\n\n"
        + "\n".join(sample_lines)
        + "\n\nIdentify the main cross-cutting facets that organize this corpus."
    )

    logger.info(
        f"[FacetEngine:Bootstrap] Sending {len(sample_lines)} sample claims "
        f"from {docs_sampled} docs to LLM"
    )

    try:
        response = llm_fn(SYSTEM_PROMPT, user_prompt)
        if not response:
            logger.warning("[FacetEngine:Bootstrap] LLM returned empty response")
            return []

        candidates = _parse_response(response)
        logger.info(
            f"[FacetEngine:Bootstrap] Extracted {len(candidates)} facet candidates"
        )
        return candidates

    except Exception as e:
        logger.error(f"[FacetEngine:Bootstrap] LLM call failed: {e}")
        return []


def _parse_response(response: str) -> List[FacetCandidate]:
    """Parse la reponse JSON du LLM."""
    # Nettoyer markdown
    text = response.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Essayer de trouver un objet JSON dans le texte
        import re
        match = re.search(r'\{[\s\S]*"facets"[\s\S]*\}', text)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning("[FacetEngine:Bootstrap] Cannot parse LLM JSON response")
                return []
        else:
            return []

    facets_data = data.get("facets", [])
    candidates = []

    for f in facets_data:
        label = f.get("label", "").strip()
        if not label or len(label) < 2:
            continue

        # Rejeter les labels vagues
        if label.lower() in {"general", "other", "misc", "miscellaneous", "n/a",
                              "introduction", "conclusion", "summary", "overview"}:
            continue

        description = f.get("description", "")
        family = f.get("family", "thematic")
        if family not in {"thematic", "normative", "operational"}:
            family = "thematic"

        candidates.append(FacetCandidate(
            label=label,
            description=description,
            facet_family=family,
        ))

    # Deduplication par label normalise
    seen = set()
    deduped = []
    for c in candidates:
        key = c.label.lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped[:10]  # Max 10 facettes


def bootstrap_from_existing_facets(
    driver,
    tenant_id: str,
) -> List[Facet]:
    """
    Charge les facettes existantes et les enrichit avec des descriptions
    si elles n'en ont pas (pour les facettes V1 sans description).
    """
    facets = []
    with driver.session() as session:
        result = session.run(
            """
            MATCH (f:Facet {tenant_id: $tid})
            RETURN DISTINCT f.facet_id AS fid, f.facet_name AS name,
                   f.description AS desc, f.facet_family AS family,
                   f.lifecycle AS lifecycle, f.status AS status
            """,
            tid=tenant_id,
        )
        seen = set()
        for r in result:
            fid = r["fid"]
            if fid in seen:
                continue
            seen.add(fid)

            name = r["name"] or fid.replace("facet_", "").replace("_", " ").title()
            desc = r["desc"] or ""

            # Generer une description par defaut si absente
            if not desc:
                desc = _default_description(name)

            facets.append(Facet(
                facet_id=fid,
                canonical_label=name,
                description=desc,
                facet_family=r["family"] or "cross_cutting_concern",
                status=r["status"] or r["lifecycle"] or "candidate",
            ))

    return facets


def _default_description(label: str) -> str:
    """Genere une description par defaut pour une facette sans description."""
    descriptions = {
        "security": "Controls, protective mechanisms, identity management, access policies, encryption, authentication, authorization, and defensive configurations.",
        "compliance": "Regulatory requirements, data protection laws, privacy policies, audit trails, retention rules, and legal obligations.",
        "configuration": "System setup, parameter configuration, customization settings, Customizing activities, and environment configuration.",
        "operations": "Operational procedures, monitoring, maintenance, job scheduling, system health checks, performance tuning, and runtime administration.",
        "infrastructure": "System architecture, hardware requirements, network topology, cloud deployment, storage, and platform components.",
        "deployment & migration": "Installation, upgrade, conversion, migration procedures, deployment strategies, and system lifecycle management.",
        "integration": "APIs, interfaces, data exchange, system integration, middleware, and inter-system communication.",
        "business functionality": "Business processes, features, capabilities, functional modules, and application-specific functionality.",
        "data management": "Data quality, master data, data migration, archiving, data lifecycle, and information management.",
    }
    return descriptions.get(label.lower(), f"Documents and information related to {label.lower()}.")

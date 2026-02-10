from __future__ import annotations

import time
import logging
from typing import Any, Dict, List

from knowbase.common.llm_router import TaskType, get_llm_router

logger = logging.getLogger(__name__)


SYNTHESIS_PROMPT = """Tu es un assistant expert qui aide les utilisateurs à trouver des informations pertinentes dans la base de connaissances.
{session_context}
## Question actuelle de l'utilisateur
{question}

## Sources disponibles
{chunks_content}
{graph_context}

## Règles de réponse

1. **Synthétise** les informations des sources pour répondre à la question de manière claire et structurée.

2. **Raisonnement cross-document (PRIORITAIRE)** : Si une section "Raisonnement cross-document" est fournie, elle contient des chaînes de faits reliant plusieurs documents. Ces chaînes constituent **LA réponse principale** à la question — elles révèlent des liens architecturaux qu'aucun document seul ne contient. Tu DOIS :
   - **Structurer ta réponse autour de ces chaînes** (pas autour des chunks individuels)
   - **Expliquer la chaîne complète** : "A repose sur B (source 1), qui lui-même s'appuie sur C (source 2)"
   - **Citer tous les documents de la chaîne** pour montrer le raisonnement multi-source
   - Les chunks individuels servent de **complément**, pas de base de la réponse

3. **Contexte conversationnel** : Si un contexte de conversation précédente est fourni, utilise-le pour comprendre les références implicites ("cela", "cette personne", "ce document", etc.) et maintenir la continuité de la discussion.

4. **Citations obligatoires** : Pour chaque information importante dont la source est connue, cite-la ainsi :
   - Format simple : *(Source : Document ABC, slide 12)*
   - Si plusieurs slides d'un même document : *(Source : Document ABC, slides 12-15)*
   - Si plusieurs documents : indique le nom du document à chaque citation

5. **Ne jamais** utiliser "Bloc #X", "Extrait X", "Document inconnu" ou "Source inconnue" - cite UNIQUEMENT les documents dont le nom est explicitement fourni dans les sources. Si une source n'a pas de nom de document clair, n'ajoute pas de citation pour cette information.

6. **Structure** ta réponse avec des sections ou puces si approprié.

7. Si les sources sont **insuffisantes** pour répondre complètement, indique-le clairement.

8. Si des informations sont **contradictoires**, mentionne les deux versions avec leurs sources.

9. Réponds en **français**.

Réponse :"""


def format_chunks_for_synthesis(chunks: List[Dict[str, Any]]) -> str:
    """
    Formate les chunks pour inclusion dans le prompt de synthèse.

    Args:
        chunks: Liste des chunks avec métadonnées

    Returns:
        Texte formaté des chunks pour le prompt
    """
    # Extrait les documents uniques pour donner du contexte au LLM
    unique_docs = set()
    for chunk in chunks:
        source_file = chunk.get('source_file', '')
        if source_file and source_file != 'Source inconnue':
            doc_name = source_file.split('/')[-1].replace('.pptx', '').replace('.pdf', '')
            unique_docs.add(doc_name)

    formatted_chunks = []

    # Ajoute un header avec les documents disponibles si plus d'un
    if len(unique_docs) > 1:
        docs_list = ", ".join(sorted(unique_docs))
        formatted_chunks.append(f"DOCUMENTS DISPONIBLES : {docs_list}")
        formatted_chunks.append("=" * 50)

    for idx, chunk in enumerate(chunks, 1):
        chunk_text = chunk.get('text', '').strip()
        source_file = chunk.get('source_file', 'Source inconnue')
        slide_index = chunk.get('slide_index')
        score = chunk.get('score')
        rerank = chunk.get('rerank_score')

        if slide_index not in (None, ''):
            slide_ref = f"Slide {slide_index}"
        else:
            slide_ref = "Slide non spécifié"

        if source_file and source_file != 'Source inconnue':
            document_name = source_file.split('/')[-1].replace('.pptx', '').replace('.pdf', '')
        else:
            document_name = 'Document inconnu'

        # Format clair : Document + Slide en premier pour que le LLM cite correctement
        header = f"### Source {idx}: {document_name}, {slide_ref}"

        block_lines = [header, "", chunk_text]
        formatted_chunks.append("\n".join(block_lines))

    return "\n\n".join(formatted_chunks)


def synthesize_response(
    question: str,
    chunks: List[Dict[str, Any]],
    graph_context_text: str = "",
    session_context_text: str = "",
    kg_signals: Dict[str, Any] = None,
    chain_signals: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Génère une réponse synthétisée à partir des chunks et de la question.

    Args:
        question: Question de l'utilisateur
        chunks: Liste des chunks reranqués
        graph_context_text: Contexte Knowledge Graph formaté (OSMOSE)
        session_context_text: Contexte conversationnel formaté (Memory Layer Phase 2.5)
        kg_signals: Signaux KG optionnels pour le calcul de confiance
                   {"concepts_count", "relations_count", "sources_count", "avg_confidence"}
        chain_signals: Signaux de qualité des chaînes CHAINS_TO multi-doc
                      {"chain_count", "distinct_docs_count", "max_hops", "avg_hops"}

    Returns:
        Dictionnaire contenant la réponse synthétisée et les métadonnées
    """
    if not chunks:
        return {
            "synthesized_answer": "Aucune information pertinente n'a été trouvée dans la base de connaissances pour répondre à votre question.",
            "sources_used": [],
            "confidence": 0.0
        }

    # Formate les chunks pour le prompt
    chunks_content = format_chunks_for_synthesis(chunks)

    # Construit le prompt avec contextes optionnels (KG et Session)
    prompt = SYNTHESIS_PROMPT.format(
        question=question,
        chunks_content=chunks_content,
        graph_context=graph_context_text,
        session_context=session_context_text
    )

    # Appel LLM via le routeur
    router = get_llm_router()
    messages = [
        {"role": "system", "content": "Tu es un assistant expert SAP qui synthétise des informations pour répondre aux questions des utilisateurs."},
        {"role": "user", "content": prompt}
    ]

    # Log prompt size for debugging
    prompt_size = len(prompt)
    logger.info(f"[SYNTHESIS] Starting LLM call, prompt size: {prompt_size} chars")
    start_time = time.time()

    try:
        synthesized_answer = router.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=messages,
            temperature=0.3,
            max_tokens=2000
        )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[SYNTHESIS] LLM call completed in {elapsed_ms:.0f}ms, response: {len(synthesized_answer)} chars")

        # Extrait les sources utilisées
        sources_used = []
        for chunk in chunks:
            source_file = chunk.get('source_file', '')
            slide_index = chunk.get('slide_index', '')
            if source_file and source_file not in sources_used:
                sources_used.append(source_file)

        # Calcule un score de confiance basé sur les scores de reranking et Qdrant
        rerank_scores = [chunk.get('rerank_score', 0) for chunk in chunks]
        qdrant_scores = [chunk.get('score', 0) for chunk in chunks]

        # Méthode améliorée pour calculer la confiance
        import math

        # 1. Normalise les scores Qdrant (généralement entre 0.5-1.0) vers 0-1
        if qdrant_scores:
            min_qdrant = min(qdrant_scores)
            max_qdrant = max(qdrant_scores)
            if max_qdrant > min_qdrant:
                normalized_qdrant = [(score - min_qdrant) / (max_qdrant - min_qdrant) for score in qdrant_scores]
            else:
                normalized_qdrant = [0.8 if score > 0.7 else 0.5 for score in qdrant_scores]  # Fallback
        else:
            normalized_qdrant = [0.5]

        # 2. Transforme les scores de reranking avec sigmoid adapté et centré
        if rerank_scores:
            # Utilise le score max comme référence positive
            max_rerank = max(rerank_scores)
            adjusted_rerank = [score - max_rerank + 2 for score in rerank_scores]  # Shift pour avoir des valeurs positives
            normalized_rerank = [1 / (1 + math.exp(-score)) for score in adjusted_rerank]
        else:
            normalized_rerank = [0.5]

        # 3. Combine avec pondération équilibrée et bonus pour cohérence
        avg_qdrant = sum(normalized_qdrant) / len(normalized_qdrant)
        avg_rerank = sum(normalized_rerank) / len(normalized_rerank)

        # Score de base (50% Qdrant, 50% reranking)
        base_confidence = (0.5 * avg_qdrant + 0.5 * avg_rerank)

        # Bonus pour nombre de sources cohérentes
        num_chunks = len(chunks)
        diversity_bonus = min(0.1, num_chunks * 0.02)  # +2% par chunk, max +10%

        # Score final base (sans KG)
        base_confidence_final = min(base_confidence + diversity_bonus, 1.0)

        # Bonus KG si signaux disponibles (le KG doit AMÉLIORER la confiance)
        kg_bonus = 0.0
        if kg_signals:
            concepts_count = kg_signals.get("concepts_count", 0)
            relations_count = kg_signals.get("relations_count", 0)
            kg_sources = kg_signals.get("sources_count", 0)
            kg_avg_conf = kg_signals.get("avg_confidence", 0.0)

            # Bonus si le KG apporte des concepts pertinents
            if concepts_count > 0:
                kg_bonus += min(0.05, concepts_count * 0.01)  # +1% par concept, max +5%

            # Bonus si le KG apporte des relations typées
            if relations_count > 0:
                kg_bonus += min(0.08, relations_count * 0.02)  # +2% par relation, max +8%

            # Bonus si multi-sources dans le KG
            if kg_sources >= 2:
                kg_bonus += 0.05  # +5% pour multi-sources

            # Modulation par la confiance moyenne des relations KG
            if kg_avg_conf > 0:
                kg_bonus *= kg_avg_conf  # Pondère par la qualité

            logger.debug(
                f"[SYNTHESIS] KG bonus: {kg_bonus:.2%} "
                f"(concepts={concepts_count}, relations={relations_count}, sources={kg_sources})"
            )

        # Bonus chaînes multi-doc CHAINS_TO (raisonnement transitif cross-document)
        chain_bonus = 0.0
        if chain_signals:
            distinct_docs = chain_signals.get("distinct_docs_count", 0)
            chain_count = chain_signals.get("chain_count", 0)
            max_hops = chain_signals.get("max_hops", 0)

            # Bonus proportionnel au nombre de docs distincts traversés
            if distinct_docs >= 4:
                chain_bonus += 0.12  # +12% pour 4+ docs (raisonnement riche)
            elif distinct_docs >= 3:
                chain_bonus += 0.08  # +8% pour 3 docs
            elif distinct_docs >= 2:
                chain_bonus += 0.05  # +5% pour 2 docs

            # Bonus pour chaînes longues (plus de hops = raisonnement plus profond)
            if max_hops >= 3:
                chain_bonus += 0.05  # +5% pour chaînes à 3+ hops
            elif max_hops >= 2:
                chain_bonus += 0.03  # +3% pour chaînes à 2 hops

            # Bonus pour multiplicité des chaînes (corroboration)
            if chain_count >= 3:
                chain_bonus += 0.05  # +5% pour 3+ chaînes distinctes
            elif chain_count >= 2:
                chain_bonus += 0.03  # +3% pour 2 chaînes

            logger.debug(
                f"[SYNTHESIS] Chain bonus: {chain_bonus:.2%} "
                f"(docs={distinct_docs}, chains={chain_count}, max_hops={max_hops})"
            )

        # Plafonner le chain_bonus : la confiance totale ne doit pas dépasser 90%
        # (un système de connaissance ne devrait jamais être "certain à 99%")
        max_chain = max(0, 0.90 - base_confidence_final - kg_bonus)
        chain_bonus = min(chain_bonus, max_chain)

        # Score final = base + KG bonus + chain bonus (plafonné à 90%)
        confidence = min(base_confidence_final + kg_bonus + chain_bonus, 0.90)

        return {
            "synthesized_answer": synthesized_answer.strip(),
            "sources_used": sources_used,
            "confidence": confidence,
            "confidence_breakdown": {
                "base_score": round(base_confidence_final, 3),
                "kg_bonus": round(kg_bonus, 3),
                "chain_bonus": round(chain_bonus, 3),
                "final_score": round(confidence, 3)
            }
        }

    except Exception as e:
        return {
            "synthesized_answer": f"Erreur lors de la génération de la réponse : {str(e)}",
            "sources_used": [],
            "confidence": 0.0
        }


__all__ = ["synthesize_response", "format_chunks_for_synthesis"]
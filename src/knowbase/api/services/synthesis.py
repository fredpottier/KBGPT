from __future__ import annotations

from typing import Any, Dict, List

from knowbase.common.llm_router import TaskType, get_llm_router


SYNTHESIS_PROMPT = """Tu es un assistant expert en SAP qui aide les utilisateurs à trouver des informations pertinentes dans la base de connaissances SAP.

Voici la question de l'utilisateur :
{question}

Voici les extraits pertinents (classés par ordre de pertinence). Chaque bloc indique obligatoirement le document et le numéro de slide disponibles :

{chunks_content}

Règles STRICTES :
1. Analyse uniquement ces extraits et synthétise une réponse cohérente qui répond directement à la question de l'utilisateur.
2. Tu ne peux référencer que les slides explicitement listés dans les blocs ci-dessus. Ignore toute mention textuelle qui ferait référence à d'autres slides.
3. Structure ta réponse de manière claire et organisée avec des sections numérotées ou à puces si approprié.
4. Pour chaque point important, indique précisément la référence slide en respectant ces formats :
   - Si un seul document : « slide 71 » ou « slides 113-115 » (en restant dans les indices fournis).
   - Si plusieurs documents sont utilisés : « slide 36 du document ABC » ou « slides 71-73 du document XYZ ».
5. Ne mentionne jamais « Extrait X » – utilise toujours des références de slides autorisées.
6. Si des informations contradictoires existent, mentionne-le explicitement.
7. Si les slides ne contiennent pas assez d'informations pour répondre complètement, indique-le clairement.
8. Reste concis mais informatif.
9. Réponds en français.

IMPORTANT : Toute référence à un slide non listé dans les extraits est interdite. Ne reformule pas en inventant d'autres numéros de slides.

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

        meta_lines = [
            f"[Bloc #{idx}] Document : {document_name}",
            f"Slide disponible : {slide_ref}"
        ]
        if score is not None:
            try:
                meta_lines.append(f"Score Qdrant : {float(score):.3f}")
            except (TypeError, ValueError):
                pass
        if rerank is not None:
            try:
                meta_lines.append(f"Score rerank : {float(rerank):.3f}")
            except (TypeError, ValueError):
                pass

        block_lines = meta_lines + ['Contenu :', chunk_text]
        formatted_chunks.append("\n".join(block_lines))

    return "\n\n".join(formatted_chunks)


def synthesize_response(question: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Génère une réponse synthétisée à partir des chunks et de la question.

    Args:
        question: Question de l'utilisateur
        chunks: Liste des chunks reranqués

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

    # Construit le prompt
    prompt = SYNTHESIS_PROMPT.format(
        question=question,
        chunks_content=chunks_content
    )

    # Appel LLM via le routeur
    router = get_llm_router()
    messages = [
        {"role": "system", "content": "Tu es un assistant expert SAP qui synthétise des informations pour répondre aux questions des utilisateurs."},
        {"role": "user", "content": prompt}
    ]

    try:
        synthesized_answer = router.complete(
            task_type=TaskType.LONG_TEXT_SUMMARY,
            messages=messages,
            temperature=0.3,
            max_tokens=2000
        )

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

        # Score final
        confidence = min(base_confidence + diversity_bonus, 1.0)

        return {
            "synthesized_answer": synthesized_answer.strip(),
            "sources_used": sources_used,
            "confidence": min(confidence, 1.0)  # Cap à 1.0
        }

    except Exception as e:
        return {
            "synthesized_answer": f"Erreur lors de la génération de la réponse : {str(e)}",
            "sources_used": [],
            "confidence": 0.0
        }


__all__ = ["synthesize_response", "format_chunks_for_synthesis"]
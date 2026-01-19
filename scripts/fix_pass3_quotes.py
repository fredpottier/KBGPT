#!/usr/bin/env python3
"""
Script de correction des quotes Pass 3.

Corrige les quotes tronquées ou malformées en:
1. Récupérant le texte source depuis Qdrant
2. Étendant aux limites de phrase
3. Supprimant les artefacts de formatage
"""

import re
import logging
from typing import Optional, List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    import os
    from neo4j import GraphDatabase
    # Utilise le nom du service Docker si dans container, sinon localhost
    neo4j_host = os.getenv("NEO4J_HOST", "neo4j")
    return GraphDatabase.driver(
        f"bolt://{neo4j_host}:7687",
        auth=("neo4j", "graphiti_neo4j_pass")
    )


def get_qdrant_client():
    """Crée un client Qdrant."""
    import os
    from qdrant_client import QdrantClient
    # Utilise le nom du service Docker si dans container, sinon localhost
    qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
    return QdrantClient(host=qdrant_host, port=6333)


def clean_quote(quote: str) -> str:
    """Nettoie une quote des artefacts de formatage."""
    if not quote:
        return quote

    # Supprimer les marqueurs de section
    quote = re.sub(r'\[Section:.*?\]', '', quote)
    quote = re.sub(r'\[PARAGRAPH\]', '', quote)
    quote = re.sub(r'\[GRAPH\]', '', quote)
    quote = re.sub(r'\[TABLE\]', '', quote)
    quote = re.sub(r'\[LIST\]', '', quote)

    # Supprimer les IDs de section (sec:xxx...)
    quote = re.sub(r'sec:[a-zA-Z0-9_\-]+', '', quote)

    # Supprimer les artefacts de formatage Markdown
    quote = re.sub(r'\[e\d+\|label\]', '', quote)
    quote = re.sub(r'ible_elements:', '', quote)

    # Nettoyer les espaces multiples
    quote = re.sub(r'\s+', ' ', quote)
    quote = quote.strip()

    return quote


def extend_to_sentence_boundaries(quote: str, full_text: str) -> Optional[str]:
    """
    Étend une quote aux limites de phrase dans le texte source.

    Args:
        quote: Quote potentiellement tronquée
        full_text: Texte source complet

    Returns:
        Quote étendue ou None si non trouvée
    """
    if not quote or not full_text:
        return None

    # Nettoyer la quote pour la recherche
    clean_q = clean_quote(quote)
    if len(clean_q) < 15:
        return None

    # Prendre un fragment central de la quote pour la recherche
    # (évite les problèmes de début/fin tronqués)
    mid_start = len(clean_q) // 4
    mid_end = 3 * len(clean_q) // 4
    search_fragment = clean_q[mid_start:mid_end]

    if len(search_fragment) < 10:
        search_fragment = clean_q[:50]

    # Chercher dans le texte source
    pos = full_text.find(search_fragment)
    if pos == -1:
        # Essayer en lowercase
        pos = full_text.lower().find(search_fragment.lower())
        if pos == -1:
            return None

    # Étendre vers le début de la phrase
    start = pos
    sentence_delimiters = '.!?\n'
    while start > 0 and full_text[start - 1] not in sentence_delimiters:
        start -= 1
    # Sauter les espaces au début
    while start < pos and full_text[start] in ' \t\n':
        start += 1

    # Étendre vers la fin de la phrase
    end = pos + len(search_fragment)
    while end < len(full_text) and full_text[end] not in sentence_delimiters:
        end += 1
    # Inclure le délimiteur
    if end < len(full_text):
        end += 1

    # Extraire et nettoyer
    extended = full_text[start:end].strip()
    extended = clean_quote(extended)

    # Limiter la longueur
    if len(extended) > 500:
        # Tronquer à la dernière phrase complète
        last_delim = max(extended.rfind('.'), extended.rfind('!'), extended.rfind('?'))
        if last_delim > 50:
            extended = extended[:last_delim + 1]
        else:
            extended = extended[:500]

    return extended if len(extended) >= 20 else None


def get_source_text_for_relation(qdrant, relation_data: Dict) -> Optional[str]:
    """
    Récupère le texte source depuis Qdrant pour une relation.
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    # Essayer de trouver le document via les context_ids si disponibles
    evidence_context_ids = relation_data.get('evidence_context_ids', [])

    texts = []

    # Chercher par context_id
    for ctx_id in evidence_context_ids[:3]:  # Max 3 contextes
        try:
            results = qdrant.scroll(
                collection_name="knowbase",
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="context_id", match=MatchValue(value=ctx_id))
                    ]
                ),
                limit=10,
                with_payload=True,
                with_vectors=False
            )

            if results and results[0]:
                for point in results[0]:
                    if point.payload and point.payload.get("text"):
                        texts.append(point.payload["text"])
        except Exception as e:
            logger.debug(f"Error fetching context {ctx_id}: {e}")

    # Si pas de résultats, chercher par le texte de la quote elle-même
    if not texts:
        quote = relation_data.get('evidence_quote', '')
        if quote and len(quote) > 20:
            # Prendre un fragment pour la recherche vectorielle
            search_text = clean_quote(quote)[:100]
            try:
                # Recherche full-text simple via scroll
                results = qdrant.scroll(
                    collection_name="knowbase",
                    limit=50,
                    with_payload=True,
                    with_vectors=False
                )

                if results and results[0]:
                    for point in results[0]:
                        if point.payload and point.payload.get("text"):
                            text = point.payload["text"]
                            # Vérifier si le fragment est dans ce chunk
                            if search_text.lower()[:30] in text.lower():
                                texts.append(text)
            except Exception as e:
                logger.debug(f"Error in fallback search: {e}")

    if texts:
        return "\n\n".join(texts)
    return None


def fix_relation_quote(neo4j_driver, qdrant, relation: Dict) -> bool:
    """
    Corrige la quote d'une relation.

    Returns:
        True si corrigée, False sinon
    """
    rel_id = relation.get('rel_id')
    original_quote = relation.get('evidence_quote', '')
    from_label = relation.get('from_label', '')
    to_label = relation.get('to_label', '')
    rel_type = relation.get('rel_type', '')

    # Vérifier si la quote a besoin de correction
    needs_fix = False

    # Quote trop courte
    if len(original_quote) < 30:
        needs_fix = True

    # Quote ne finit pas par ponctuation
    if original_quote and not original_quote.rstrip()[-1] in '.!?':
        needs_fix = True

    # Quote contient des artefacts
    if '[PARAGRAPH]' in original_quote or '[GRAPH]' in original_quote:
        needs_fix = True

    if 'sec:' in original_quote.lower():
        needs_fix = True

    # Quote commence de façon suspecte (mid-word)
    if original_quote and original_quote[0].islower():
        needs_fix = True

    if not needs_fix:
        return False

    logger.info(f"Fixing: {from_label} -[{rel_type}]-> {to_label}")
    logger.debug(f"  Original: {original_quote[:80]}...")

    # Récupérer le texte source
    source_text = get_source_text_for_relation(qdrant, relation)

    if not source_text:
        # Pas de source, juste nettoyer la quote
        cleaned = clean_quote(original_quote)
        if cleaned != original_quote and len(cleaned) >= 20:
            # Mettre à jour avec la version nettoyée
            update_quote_in_neo4j(neo4j_driver, rel_id, rel_type, cleaned)
            logger.info(f"  Cleaned (no source): {cleaned[:80]}...")
            return True
        return False

    # Étendre aux limites de phrase
    extended = extend_to_sentence_boundaries(original_quote, source_text)

    if extended and extended != original_quote and len(extended) >= 20:
        update_quote_in_neo4j(neo4j_driver, rel_id, rel_type, extended)
        logger.info(f"  Extended: {extended[:80]}...")
        return True

    # Au minimum, nettoyer
    cleaned = clean_quote(original_quote)
    if cleaned != original_quote and len(cleaned) >= 20:
        update_quote_in_neo4j(neo4j_driver, rel_id, rel_type, cleaned)
        logger.info(f"  Cleaned: {cleaned[:80]}...")
        return True

    return False


def update_quote_in_neo4j(driver, rel_id: int, rel_type: str, new_quote: str):
    """Met à jour la quote dans Neo4j."""
    with driver.session() as session:
        # Utiliser une requête dynamique car le type de relation varie
        query = f"""
        MATCH ()-[r]->()
        WHERE id(r) = $rel_id
        SET r.evidence_quote = $new_quote,
            r.quote_fixed = true,
            r.quote_fixed_at = datetime()
        RETURN r
        """
        session.run(query, rel_id=rel_id, new_quote=new_quote)


def get_all_relations_with_quotes(driver) -> List[Dict]:
    """Récupère toutes les relations avec evidence_quote."""
    with driver.session() as session:
        result = session.run("""
            MATCH (c1:CanonicalConcept)-[r]->(c2:CanonicalConcept)
            WHERE r.evidence_quote IS NOT NULL
            RETURN id(r) AS rel_id,
                   type(r) AS rel_type,
                   c1.canonical_name AS from_label,
                   c2.canonical_name AS to_label,
                   r.evidence_quote AS evidence_quote,
                   r.evidence_context_ids AS evidence_context_ids
        """)

        return [dict(record) for record in result]


def main():
    """Point d'entrée principal."""
    logger.info("=== Pass 3 Quote Fixer ===")

    # Connexions
    neo4j_driver = get_neo4j_driver()
    qdrant = get_qdrant_client()

    try:
        # Récupérer toutes les relations
        relations = get_all_relations_with_quotes(neo4j_driver)
        logger.info(f"Found {len(relations)} relations with quotes")

        fixed_count = 0
        error_count = 0

        for relation in relations:
            try:
                if fix_relation_quote(neo4j_driver, qdrant, relation):
                    fixed_count += 1
            except Exception as e:
                logger.error(f"Error fixing relation: {e}")
                error_count += 1

        logger.info(f"=== Complete ===")
        logger.info(f"Fixed: {fixed_count}")
        logger.info(f"Errors: {error_count}")
        logger.info(f"Unchanged: {len(relations) - fixed_count - error_count}")

    finally:
        neo4j_driver.close()


if __name__ == "__main__":
    main()

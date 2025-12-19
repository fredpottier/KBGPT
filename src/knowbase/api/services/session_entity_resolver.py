"""
🧠 OSMOSE Phase 2.5 - Session Entity Resolver

Service pour résoudre les entités mentionnées dans le contexte de session
et récupérer les chunks associés via le Knowledge Graph.

Cas d'usage:
- L'utilisateur demande "qui a travaillé sur les études COVID?"
- Le système répond avec une liste de noms (Richard Davies, etc.)
- L'utilisateur demande "sur quelle étude a travaillé Richard Davies?"
- Ce service permet de:
  1. Identifier "Richard Davies" comme entité du contexte précédent
  2. Trouver le concept correspondant dans le KG
  3. Récupérer les chunks qui mentionnent ce concept
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.neo4j_custom.client import get_neo4j_client
from knowbase.common.clients.qdrant_client import get_chunks_by_concept

settings = get_settings()
logger = setup_logging(settings.logs_dir, "session_entity_resolver.log")


class SessionEntityResolver:
    """
    Résout les entités du contexte de session vers des concepts KG
    et récupère les chunks associés.
    """

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self._neo4j_client = None

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    def extract_entities_from_text(self, text: str) -> List[str]:
        """
        Extrait les entités potentielles (noms propres, termes techniques) d'un texte.

        Utilise des heuristiques simples:
        - Mots commençant par majuscule
        - Séquences de mots majuscules consécutifs (noms composés)
        - Termes entre guillemets
        """
        entities = set()

        # Patterns pour extraire des entités
        # 1. Noms propres (séquences de mots commençant par majuscule)
        # Ex: "Richard Davies", "SAP S/4HANA", "COVID-19"
        proper_noun_pattern = r'\b([A-Z][a-zàâäéèêëïîôùûüç]*(?:\s+[A-Z][a-zàâäéèêëïîôùûüç]*)*)\b'

        for match in re.finditer(proper_noun_pattern, text):
            entity = match.group(1).strip()
            # Ignorer les mots trop courts ou les articles/prépositions
            if len(entity) > 2 and entity.lower() not in {
                'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de',
                'the', 'a', 'an', 'is', 'are', 'was', 'were',
                'source', 'document', 'slide', 'référence'
            }:
                entities.add(entity)

        # 2. Termes entre guillemets
        quoted_pattern = r'[""«]([^""»]+)[""»]'
        for match in re.finditer(quoted_pattern, text):
            entity = match.group(1).strip()
            if len(entity) > 2:
                entities.add(entity)

        # 3. Termes avec tirets (souvent des noms techniques)
        hyphenated_pattern = r'\b([A-Za-z]+-[A-Za-z0-9-]+)\b'
        for match in re.finditer(hyphenated_pattern, text):
            entity = match.group(1).strip()
            if len(entity) > 3:
                entities.add(entity)

        return list(entities)

    def extract_entities_from_session(
        self,
        session_messages: List[Any],
        focus_on_assistant: bool = True
    ) -> List[str]:
        """
        Extrait les entités des messages de session.

        Args:
            session_messages: Liste des messages de session
            focus_on_assistant: Si True, se concentre sur les réponses assistant
                               (qui contiennent les entités mentionnées)

        Returns:
            Liste des entités extraites (dédupliquées)
        """
        all_entities = set()

        for msg in session_messages:
            # Accéder au contenu selon le type d'objet
            content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
            role = msg.role if hasattr(msg, 'role') else msg.get('role', '')

            # Se concentrer sur les réponses assistant pour les entités mentionnées
            if focus_on_assistant and role != 'assistant':
                continue

            entities = self.extract_entities_from_text(content)
            all_entities.update(entities)

        logger.debug(f"[SESSION-ENTITY] Extracted {len(all_entities)} entities from session")
        return list(all_entities)

    def find_matching_concepts(
        self,
        entity_names: List[str],
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Recherche les concepts du KG qui correspondent aux entités.

        Utilise une recherche fuzzy:
        - Match exact sur canonical_name
        - Match partiel (contient)
        - Match sur aliases

        Returns:
            Liste de concepts trouvés avec leurs IDs et noms
        """
        if not entity_names:
            return []

        # Construire une requête Cypher pour recherche fuzzy
        # Normaliser les noms pour la recherche
        search_terms = [name.lower() for name in entity_names]

        cypher = """
        MATCH (c:CanonicalConcept)
        WHERE c.tenant_id = $tenant_id
        WITH c, toLower(c.canonical_name) AS name_lower
        WHERE ANY(term IN $search_terms WHERE
            name_lower CONTAINS term OR
            term CONTAINS name_lower OR
            ANY(alias IN COALESCE(c.aliases, []) WHERE toLower(alias) CONTAINS term OR term CONTAINS toLower(alias))
        )
        RETURN
            c.canonical_id AS canonical_id,
            c.canonical_name AS canonical_name,
            c.concept_type AS concept_type,
            c.aliases AS aliases,
            c.chunk_ids AS chunk_ids
        LIMIT $limit
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "tenant_id": self.tenant_id,
                "search_terms": search_terms,
                "limit": max_results
            })

            concepts = []
            for record in results:
                concepts.append({
                    "canonical_id": record.get("canonical_id"),
                    "canonical_name": record.get("canonical_name"),
                    "concept_type": record.get("concept_type"),
                    "aliases": record.get("aliases") or [],
                    "chunk_ids": record.get("chunk_ids") or []
                })

            logger.info(
                f"[SESSION-ENTITY] Found {len(concepts)} concepts matching "
                f"{len(entity_names)} entities"
            )

            return concepts

        except Exception as e:
            logger.warning(f"[SESSION-ENTITY] Failed to find concepts: {e}")
            return []

    def find_concept_by_query_entity(
        self,
        query: str,
        session_entities: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Identifie les entités de la requête qui correspondent à des entités
        connues du contexte de session, puis trouve les concepts KG correspondants.

        Args:
            query: Question de l'utilisateur
            session_entities: Entités extraites du contexte de session

        Returns:
            Liste de concepts KG correspondants
        """
        query_lower = query.lower()

        # Trouver les entités de session mentionnées dans la query
        mentioned_entities = []
        for entity in session_entities:
            entity_lower = entity.lower()
            if entity_lower in query_lower or query_lower in entity_lower:
                mentioned_entities.append(entity)

        if not mentioned_entities:
            # Essayer une recherche plus large: extraire entités de la query
            query_entities = self.extract_entities_from_text(query)
            # Chercher parmi les entités de session
            for q_entity in query_entities:
                for s_entity in session_entities:
                    # Match fuzzy
                    if (q_entity.lower() in s_entity.lower() or
                        s_entity.lower() in q_entity.lower()):
                        mentioned_entities.append(s_entity)

        if not mentioned_entities:
            logger.debug("[SESSION-ENTITY] No session entities found in query")
            return []

        logger.info(
            f"[SESSION-ENTITY] Found {len(mentioned_entities)} session entities "
            f"in query: {mentioned_entities[:5]}"
        )

        # Chercher les concepts correspondants dans le KG
        return self.find_matching_concepts(mentioned_entities)

    def get_chunks_for_concepts(
        self,
        concepts: List[Dict[str, Any]],
        max_chunks_per_concept: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Récupère les chunks Qdrant associés aux concepts.

        Args:
            concepts: Liste de concepts avec leurs canonical_id
            max_chunks_per_concept: Nombre max de chunks par concept

        Returns:
            Liste de chunks formatés pour la recherche
        """
        all_chunks = []
        seen_chunk_ids = set()

        for concept in concepts:
            canonical_id = concept.get("canonical_id")
            if not canonical_id:
                continue

            try:
                chunks = get_chunks_by_concept(
                    canonical_concept_id=canonical_id,
                    collection_name=settings.qdrant_collection,
                    tenant_id=self.tenant_id,
                    limit=max_chunks_per_concept
                )

                for chunk in chunks:
                    chunk_id = chunk.get("id")
                    if chunk_id and chunk_id not in seen_chunk_ids:
                        seen_chunk_ids.add(chunk_id)

                        payload = chunk.get("payload", {})

                        # Formater comme les résultats de recherche standard
                        formatted_chunk = {
                            "text": payload.get("text", ""),
                            "source_file": payload.get("document", {}).get("source_file_url", "") or payload.get("source_file_url", ""),
                            "slide_index": payload.get("chunk", {}).get("slide_index", "") or payload.get("slide_index", ""),
                            "score": 0.85,  # Score fictif pour les chunks KG
                            "slide_image_url": payload.get("document", {}).get("slide_image_url", "") or payload.get("slide_image_url", ""),
                            "kg_source": True,  # Marquer comme provenant du KG
                            "matched_concept": concept.get("canonical_name")
                        }
                        all_chunks.append(formatted_chunk)

            except Exception as e:
                logger.warning(
                    f"[SESSION-ENTITY] Failed to get chunks for concept "
                    f"{canonical_id}: {e}"
                )

        logger.info(
            f"[SESSION-ENTITY] Retrieved {len(all_chunks)} chunks "
            f"for {len(concepts)} concepts"
        )

        return all_chunks

    def resolve_and_get_chunks(
        self,
        query: str,
        session_messages: List[Any],
        max_chunks: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Pipeline complet: extrait entités de session, trouve concepts KG,
        récupère chunks associés.

        Args:
            query: Question de l'utilisateur
            session_messages: Messages de la session
            max_chunks: Nombre max de chunks à retourner

        Returns:
            Liste de chunks provenant du KG
        """
        # 1. Extraire entités des messages de session
        session_entities = self.extract_entities_from_session(session_messages)

        if not session_entities:
            logger.debug("[SESSION-ENTITY] No entities found in session")
            return []

        # 2. Trouver les concepts KG correspondant aux entités de la query
        concepts = self.find_concept_by_query_entity(query, session_entities)

        if not concepts:
            logger.debug("[SESSION-ENTITY] No matching concepts found in KG")
            return []

        # 3. Récupérer les chunks pour ces concepts
        chunks = self.get_chunks_for_concepts(
            concepts,
            max_chunks_per_concept=max(2, max_chunks // len(concepts))
        )

        return chunks[:max_chunks]


# Singleton instance
_resolver: Optional[SessionEntityResolver] = None


def get_session_entity_resolver(tenant_id: str = "default") -> SessionEntityResolver:
    """Retourne l'instance du resolver (créée si nécessaire)."""
    global _resolver
    if _resolver is None or _resolver.tenant_id != tenant_id:
        _resolver = SessionEntityResolver(tenant_id)
    return _resolver


__all__ = [
    "SessionEntityResolver",
    "get_session_entity_resolver",
]

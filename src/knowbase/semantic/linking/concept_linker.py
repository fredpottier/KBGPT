"""
🌊 OSMOSE Semantic Intelligence V2.1 - ConceptLinker

Cross-document concept linking et DocumentRole classification.

Responsabilités:
- Trouver documents mentionnant un concept
- Classifier rôle document (DEFINES, IMPLEMENTS, AUDITS, PROVES, REFERENCES)
- Construire graph de connexions cross-documents

Semaine 10 Phase 1 V2.1
"""

from typing import List, Dict, Optional
import logging
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from knowbase.semantic.models import (
    CanonicalConcept,
    ConceptConnection,
    DocumentRole
)
from knowbase.semantic.config import SemanticConfig, LinkingConfig
from knowbase.semantic.utils.embeddings import get_embedder
from knowbase.common.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class ConceptLinker:
    """
    Lie concepts à travers documents.

    Responsabilités:
    - Identifier documents mentionnant un concept canonique
    - Classifier rôle du document par rapport au concept
    - Construire graph de connexions concept ↔ documents

    DocumentRole types:
    - DEFINES: Document définit le concept (standards, guidelines)
    - IMPLEMENTS: Document implémente le concept (projects, solutions)
    - AUDITS: Document audite le concept (audit reports, compliance)
    - PROVES: Document prouve conformité (certificates, attestations)
    - REFERENCES: Document mentionne le concept (general reference)

    Exemple:
    Concept: "ISO 27001"
    Documents:
    - "ISO 27001 Standard.pdf" → DEFINES
    - "Security Implementation Project.pdf" → IMPLEMENTS
    - "2024 Security Audit Report.pdf" → AUDITS
    - "ISO 27001 Certificate.pdf" → PROVES
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        config: SemanticConfig
    ):
        """
        Initialise le ConceptLinker.

        Args:
            llm_router: Router LLM pour classification avancée
            config: Configuration globale semantic V2.1
        """
        self.llm_router = llm_router
        self.config = config
        self.linking_config: LinkingConfig = config.linking
        self.embedder = get_embedder(config)

        logger.info("[OSMOSE] ConceptLinker V2.1 initialized")

    def link_concepts_to_documents(
        self,
        canonical_concepts: List[CanonicalConcept],
        document_id: str,
        document_title: str,
        document_text: str
    ) -> List[ConceptConnection]:
        """
        Lie concepts canoniques à un document.

        Pour chaque concept:
        1. Vérifier si le document mentionne ce concept (via embeddings)
        2. Classifier le rôle du document par rapport au concept
        3. Créer une ConceptConnection

        Args:
            canonical_concepts: Liste de concepts canoniques
            document_id: ID du document
            document_title: Titre du document
            document_text: Texte complet du document

        Returns:
            Liste de connexions concept ↔ document
        """
        if not canonical_concepts:
            logger.warning("[OSMOSE] No canonical concepts to link")
            return []

        logger.info(
            f"[OSMOSE] Linking {len(canonical_concepts)} concepts to document "
            f"'{document_title}'"
        )

        connections = []

        # Embedding du document
        doc_embedding = self.embedder.encode([document_text])[0]

        for concept in canonical_concepts:
            # Embedding du concept (canonical name)
            concept_embedding = self.embedder.encode([concept.canonical_name])[0]

            # Similarité
            similarity = float(
                cosine_similarity(
                    [concept_embedding],
                    [doc_embedding]
                )[0][0]
            )

            # Seuil
            if similarity < self.linking_config.similarity_threshold:
                continue

            # Classifier rôle
            role = self._classify_document_role(
                document_title=document_title,
                document_text=document_text,
                concept_name=concept.canonical_name
            )

            # Extraire contexte mention
            context = self._extract_context_mention(
                document_text,
                concept.canonical_name,
                concept.aliases
            )

            # Créer connexion
            connection = ConceptConnection(
                document_id=document_id,
                document_title=document_title,
                document_role=role,
                canonical_concept_name=concept.canonical_name,
                similarity=similarity,
                context=context
            )

            connections.append(connection)

            logger.debug(
                f"[OSMOSE] Linked concept '{concept.canonical_name}' to document "
                f"(role={role.value}, similarity={similarity:.2f})"
            )

        # Limiter nombre de connexions
        if len(connections) > self.linking_config.max_connections_per_doc:
            # Garder les plus similaires
            connections = sorted(
                connections,
                key=lambda c: c.similarity,
                reverse=True
            )[:self.linking_config.max_connections_per_doc]

        logger.info(
            f"[OSMOSE] ✅ Created {len(connections)} concept-document connections"
        )

        return connections

    def _classify_document_role(
        self,
        document_title: str,
        document_text: str,
        concept_name: str
    ) -> DocumentRole:
        """
        Classifie le rôle du document par rapport au concept.

        Stratégie:
        1. Heuristique basée sur le titre (rapide)
        2. Si incertain, analyse du texte (keywords)
        3. Si toujours incertain, LLM (optionnel, pas implémenté Phase 1)

        Args:
            document_title: Titre du document
            document_text: Texte du document
            concept_name: Nom du concept

        Returns:
            DocumentRole classifié
        """
        title_lower = document_title.lower()
        text_lower = document_text.lower()[:1000]  # Analyse début document

        # DEFINES: Standards, guidelines, specifications
        if any(keyword in title_lower for keyword in [
            "standard", "guideline", "specification", "policy",
            "norme", "directive", "règlement"
        ]):
            return DocumentRole.DEFINES

        # PROVES: Certificates, attestations
        if any(keyword in title_lower for keyword in [
            "certificate", "certification", "attestation",
            "certificat", "attestation"
        ]):
            return DocumentRole.PROVES

        # AUDITS: Audit reports, compliance checks
        if any(keyword in title_lower for keyword in [
            "audit", "compliance", "assessment", "evaluation",
            "contrôle", "évaluation"
        ]):
            return DocumentRole.AUDITS

        # IMPLEMENTS: Implementation, projects, solutions
        if any(keyword in title_lower for keyword in [
            "implementation", "project", "solution", "deployment",
            "implémentation", "projet", "déploiement"
        ]):
            return DocumentRole.IMPLEMENTS

        # Analyse texte pour affiner
        # DEFINES: Document explique/définit le concept
        if any(keyword in text_lower for keyword in [
            f"{concept_name.lower()} is defined as",
            f"{concept_name.lower()} refers to",
            f"{concept_name.lower()} means",
            "définit comme", "fait référence"
        ]):
            return DocumentRole.DEFINES

        # IMPLEMENTS: Document décrit implémentation
        if any(keyword in text_lower for keyword in [
            f"implement {concept_name.lower()}",
            f"implementing {concept_name.lower()}",
            f"deployed {concept_name.lower()}",
            "implémentation de", "déploiement de"
        ]):
            return DocumentRole.IMPLEMENTS

        # Default: REFERENCES
        return DocumentRole.REFERENCES

    def _extract_context_mention(
        self,
        document_text: str,
        concept_name: str,
        aliases: List[str],
        context_window: int = 150
    ) -> str:
        """
        Extrait le contexte où le concept est mentionné dans le document.

        Recherche le concept (ou ses aliases) et extrait N caractères autour.

        Args:
            document_text: Texte du document
            concept_name: Nom canonique du concept
            aliases: Variantes du concept (multilingues)
            context_window: Taille fenêtre contexte (chars)

        Returns:
            Contexte de mention (ou vide si non trouvé)
        """
        text_lower = document_text.lower()

        # Chercher concept ou aliases
        search_terms = [concept_name.lower()] + [a.lower() for a in aliases]

        for term in search_terms:
            pos = text_lower.find(term)
            if pos != -1:
                # Extraire contexte autour
                start = max(0, pos - context_window // 2)
                end = min(len(document_text), pos + len(term) + context_window // 2)

                context = document_text[start:end].strip()

                # Ajouter ellipses si tronqué
                if start > 0:
                    context = "..." + context
                if end < len(document_text):
                    context = context + "..."

                return context

        # Pas trouvé (peut arriver si similarity via embeddings seulement)
        return ""

    async def find_documents_for_concept(
        self,
        concept_name: str,
        all_documents: List[Dict],
        min_similarity: float = None
    ) -> List[ConceptConnection]:
        """
        Trouve tous les documents mentionnant un concept.

        Utile pour query-time: "Quels documents parlent de ISO 27001?"

        Args:
            concept_name: Nom du concept recherché
            all_documents: Liste de documents avec {id, title, text}
            min_similarity: Seuil similarité (défaut: config)

        Returns:
            Liste de connexions concept ↔ documents
        """
        if min_similarity is None:
            min_similarity = self.linking_config.similarity_threshold

        logger.info(
            f"[OSMOSE] Finding documents for concept '{concept_name}' "
            f"(threshold={min_similarity})"
        )

        # Embedding concept
        concept_embedding = self.embedder.encode([concept_name])[0]

        connections = []

        for doc in all_documents:
            # Embedding document
            doc_embedding = self.embedder.encode([doc["text"]])[0]

            # Similarité
            similarity = float(
                cosine_similarity(
                    [concept_embedding],
                    [doc_embedding]
                )[0][0]
            )

            if similarity >= min_similarity:
                # Classifier rôle
                role = self._classify_document_role(
                    document_title=doc["title"],
                    document_text=doc["text"],
                    concept_name=concept_name
                )

                # Context
                context = self._extract_context_mention(
                    doc["text"],
                    concept_name,
                    []
                )

                connection = ConceptConnection(
                    document_id=doc["id"],
                    document_title=doc["title"],
                    document_role=role,
                    canonical_concept_name=concept_name,
                    similarity=similarity,
                    context=context
                )

                connections.append(connection)

        # Trier par similarité
        connections = sorted(
            connections,
            key=lambda c: c.similarity,
            reverse=True
        )

        logger.info(
            f"[OSMOSE] ✅ Found {len(connections)} documents for concept "
            f"'{concept_name}'"
        )

        return connections

    def build_concept_document_graph(
        self,
        canonical_concepts: List[CanonicalConcept],
        all_connections: List[ConceptConnection]
    ) -> Dict:
        """
        Construit un graph concept ↔ documents.

        Structure:
        {
            "concepts": {
                "concept_name": {
                    "documents": [doc_id1, doc_id2, ...],
                    "roles": {
                        "DEFINES": [doc_id1],
                        "IMPLEMENTS": [doc_id2],
                        ...
                    }
                }
            },
            "documents": {
                "doc_id": {
                    "concepts": [concept_name1, concept_name2, ...],
                    "concept_count": N
                }
            }
        }

        Args:
            canonical_concepts: Liste de concepts canoniques
            all_connections: Toutes les connexions concept ↔ documents

        Returns:
            Graph structuré
        """
        graph = {
            "concepts": {},
            "documents": {}
        }

        # Index concepts
        for concept in canonical_concepts:
            graph["concepts"][concept.canonical_name] = {
                "documents": [],
                "roles": {role.value: [] for role in DocumentRole}
            }

        # Remplir connexions
        for conn in all_connections:
            concept_name = conn.canonical_concept_name
            doc_id = conn.document_id
            role = conn.document_role.value

            # Concept → Documents
            if concept_name in graph["concepts"]:
                if doc_id not in graph["concepts"][concept_name]["documents"]:
                    graph["concepts"][concept_name]["documents"].append(doc_id)
                graph["concepts"][concept_name]["roles"][role].append(doc_id)

            # Document → Concepts
            if doc_id not in graph["documents"]:
                graph["documents"][doc_id] = {
                    "concepts": [],
                    "concept_count": 0
                }

            if concept_name not in graph["documents"][doc_id]["concepts"]:
                graph["documents"][doc_id]["concepts"].append(concept_name)
                graph["documents"][doc_id]["concept_count"] += 1

        logger.info(
            f"[OSMOSE] ✅ Graph built: {len(graph['concepts'])} concepts, "
            f"{len(graph['documents'])} documents"
        )

        return graph

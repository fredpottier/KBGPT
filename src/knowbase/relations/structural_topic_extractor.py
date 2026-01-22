"""
OSMOSE Pass 2a: Structural Topic Extractor

ADR_GRAPH_FIRST_ARCHITECTURE - Phase B.1

Extrait les Topics documentaires depuis la structure (H1/H2 headers) et crée:
- CanonicalConcept type=TOPIC (noeud Topic Neo4j)
- HAS_TOPIC (Document → Topic)
- COVERS (Topic → Concept) via règles déterministes

IMPORTANT - Clarification sémantique:
- Topic/COVERS = SCOPE documentaire (périmètre), JAMAIS lien conceptuel
- "A et B couverts par même Topic" ≠ "A et B sont liés conceptuellement"
- COVERS répond à "De quoi parle ce document/section?" = filtre de périmètre
- Mode Anchored = réduction espace de recherche, pas moteur logique

Date: 2026-01-06
"""

import re
import hashlib
import logging
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class StructuralTopic:
    """
    Topic extrait de la structure documentaire.

    Un StructuralTopic représente une section/chapitre du document
    identifié par son header H1/H2.
    """
    topic_id: str
    title: str                          # Titre du header (H1/H2)
    normalized_title: str               # Titre normalisé pour matching
    level: int                          # 1 = H1, 2 = H2
    document_id: str
    section_path: str                   # Chemin hiérarchique (ex: "1.2 Security")
    char_start: int                     # Position début dans le document
    char_end: int                       # Position fin dans le document
    parent_topic_id: Optional[str] = None  # Topic parent (H1 pour H2)


@dataclass
class TopicExtractionResult:
    """Résultat de l'extraction de topics structurels."""
    document_id: str
    topics: List[StructuralTopic]
    has_topic_relations: List[Tuple[str, str]]  # (document_id, topic_id)
    topic_hierarchy: Dict[str, List[str]]       # {parent_id: [child_ids]}
    extraction_time_ms: float


class StructuralTopicExtractor:
    """
    Extracteur de Topics depuis la structure documentaire (H1/H2).

    ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a

    Pipeline:
    1. Parse document pour identifier headers H1/H2
    2. Normalise titres pour matching cross-document
    3. Crée StructuralTopic avec hiérarchie parent/child
    4. Prépare relations HAS_TOPIC pour Neo4j

    Note: La création des COVERS est faite séparément par CoversBuilder
    car elle dépend des MENTIONED_IN existants + salience.
    """

    # Patterns pour extraction headers
    H1_MARKDOWN_PATTERN = re.compile(r'^#\s+(.+)$', re.MULTILINE)
    H2_MARKDOWN_PATTERN = re.compile(r'^##\s+(.+)$', re.MULTILINE)

    # Pattern numérotation niveau 1 (1., 2., pas 1.1)
    NUMBERING_L1_PATTERN = re.compile(r'^(\d+)\.\s+([A-Z].+)$', re.MULTILINE)
    # Pattern numérotation niveau 2 (1.1, 2.3, etc.)
    NUMBERING_L2_PATTERN = re.compile(r'^(\d+\.\d+)\.\s+(.+)$', re.MULTILINE)

    # Stop-words à ignorer dans normalisation
    TITLE_STOP_WORDS = {
        'the', 'a', 'an', 'and', 'or', 'of', 'in', 'to', 'for',
        'le', 'la', 'les', 'un', 'une', 'des', 'et', 'ou', 'de', 'du',
        'der', 'die', 'das', 'und', 'oder', 'von', 'zu'
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialise l'extracteur.

        Args:
            config: Configuration optionnelle
        """
        self.config = config or {}
        self.min_title_length = self.config.get("min_title_length", 3)
        self.max_title_length = self.config.get("max_title_length", 200)

        logger.info("[OSMOSE:Pass2a] StructuralTopicExtractor initialisé")

    def extract_topics(
        self,
        document_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TopicExtractionResult:
        """
        Extrait les topics structurels d'un document.

        Args:
            document_id: ID unique du document
            text: Contenu textuel complet
            metadata: Métadonnées optionnelles (ex: titre document)

        Returns:
            TopicExtractionResult avec topics et relations
        """
        start_time = datetime.now()

        logger.info(f"[OSMOSE:Pass2a] Extracting structural topics from {document_id}")

        # 1. Extraire tous les headers
        headers = self._extract_headers(text)

        if not headers:
            logger.info(f"[OSMOSE:Pass2a] No structural headers found in {document_id}")
            # Créer un topic par défaut pour tout le document
            default_topic = self._create_document_level_topic(document_id, metadata)

            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            return TopicExtractionResult(
                document_id=document_id,
                topics=[default_topic],
                has_topic_relations=[(document_id, default_topic.topic_id)],
                topic_hierarchy={},
                extraction_time_ms=elapsed_ms
            )

        # 2. Construire hiérarchie et StructuralTopics
        topics, hierarchy = self._build_topic_hierarchy(document_id, headers, text)

        # 3. Préparer relations HAS_TOPIC
        has_topic_relations = [(document_id, t.topic_id) for t in topics]

        elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

        logger.info(
            f"[OSMOSE:Pass2a] Extracted {len(topics)} topics from {document_id} "
            f"(H1: {len([t for t in topics if t.level == 1])}, "
            f"H2: {len([t for t in topics if t.level == 2])}) "
            f"in {elapsed_ms:.1f}ms"
        )

        return TopicExtractionResult(
            document_id=document_id,
            topics=topics,
            has_topic_relations=has_topic_relations,
            topic_hierarchy=hierarchy,
            extraction_time_ms=elapsed_ms
        )

    def _extract_headers(self, text: str) -> List[Dict[str, Any]]:
        """
        Extrait tous les headers (H1/H2) du texte.

        Returns:
            Liste de {title, level, start, end, numbering}
        """
        headers = []

        # H1 Markdown: # Title
        for match in self.H1_MARKDOWN_PATTERN.finditer(text):
            title = match.group(1).strip()
            if self._is_valid_title(title):
                headers.append({
                    "title": title,
                    "level": 1,
                    "start": match.start(),
                    "end": match.end(),
                    "numbering": None
                })

        # H2 Markdown: ## Title
        for match in self.H2_MARKDOWN_PATTERN.finditer(text):
            title = match.group(1).strip()
            if self._is_valid_title(title):
                headers.append({
                    "title": title,
                    "level": 2,
                    "start": match.start(),
                    "end": match.end(),
                    "numbering": None
                })

        # Numérotation niveau 1: 1. Title
        for match in self.NUMBERING_L1_PATTERN.finditer(text):
            numbering = match.group(1)
            title = match.group(2).strip()
            if self._is_valid_title(title):
                headers.append({
                    "title": title,
                    "level": 1,
                    "start": match.start(),
                    "end": match.end(),
                    "numbering": numbering
                })

        # Numérotation niveau 2: 1.1. Title
        for match in self.NUMBERING_L2_PATTERN.finditer(text):
            numbering = match.group(1)
            title = match.group(2).strip()
            if self._is_valid_title(title):
                headers.append({
                    "title": title,
                    "level": 2,
                    "start": match.start(),
                    "end": match.end(),
                    "numbering": numbering
                })

        # Trier par position dans le document
        headers.sort(key=lambda h: h["start"])

        # Dédupliquer headers très proches (même position ± 10 chars)
        deduplicated = []
        for h in headers:
            if not deduplicated:
                deduplicated.append(h)
            elif abs(h["start"] - deduplicated[-1]["start"]) > 10:
                deduplicated.append(h)

        return deduplicated

    def _is_valid_title(self, title: str) -> bool:
        """Vérifie si un titre est valide."""
        if not title:
            return False
        if len(title) < self.min_title_length:
            return False
        if len(title) > self.max_title_length:
            return False
        # Ignorer les titres qui sont juste des numéros
        if title.replace(".", "").replace(" ", "").isdigit():
            return False
        return True

    def _build_topic_hierarchy(
        self,
        document_id: str,
        headers: List[Dict[str, Any]],
        text: str
    ) -> Tuple[List[StructuralTopic], Dict[str, List[str]]]:
        """
        Construit la hiérarchie de topics depuis les headers.

        Returns:
            (topics, hierarchy_dict)
        """
        topics = []
        hierarchy = {}

        current_h1_id = None
        current_h1_title = None

        for i, header in enumerate(headers):
            # Calculer section_path
            if header["numbering"]:
                section_path = f"{header['numbering']}. {header['title']}"
            else:
                section_path = header["title"]

            if header["level"] == 2 and current_h1_title:
                section_path = f"{current_h1_title} / {section_path}"

            # Calculer char_end (jusqu'au prochain header ou fin)
            if i + 1 < len(headers):
                char_end = headers[i + 1]["start"]
            else:
                char_end = len(text)

            # Normaliser titre pour matching cross-document
            normalized = self._normalize_title(header["title"])

            # Générer topic_id stable (hash du titre normalisé)
            topic_id = self._generate_topic_id(document_id, normalized, header["level"])

            # Déterminer parent
            parent_id = None
            if header["level"] == 2:
                parent_id = current_h1_id

            topic = StructuralTopic(
                topic_id=topic_id,
                title=header["title"],
                normalized_title=normalized,
                level=header["level"],
                document_id=document_id,
                section_path=section_path,
                char_start=header["start"],
                char_end=char_end,
                parent_topic_id=parent_id
            )

            topics.append(topic)

            # Mettre à jour le H1 courant pour les H2 suivants
            if header["level"] == 1:
                current_h1_id = topic_id
                current_h1_title = header["title"]
                hierarchy[topic_id] = []
            elif header["level"] == 2 and current_h1_id:
                hierarchy[current_h1_id].append(topic_id)

        return topics, hierarchy

    def _normalize_title(self, title: str) -> str:
        """
        Normalise un titre pour matching cross-document.

        Ex: "1.2. Introduction to Security" → "introduction security"
        """
        # Lowercase
        normalized = title.lower()

        # Supprimer numérotation en début
        normalized = re.sub(r'^\d+(\.\d+)*\.?\s*', '', normalized)

        # Supprimer ponctuation sauf espaces
        normalized = re.sub(r'[^\w\s]', ' ', normalized)

        # Supprimer stop-words
        words = normalized.split()
        words = [w for w in words if w not in self.TITLE_STOP_WORDS]

        # Rejoindre
        normalized = ' '.join(words)

        # Collapse espaces multiples
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized

    def _generate_topic_id(
        self,
        document_id: str,
        normalized_title: str,
        level: int
    ) -> str:
        """
        Génère un ID stable pour le topic.

        L'ID est basé sur le document + titre normalisé pour permettre
        le matching entre documents différents ayant des topics similaires.
        """
        # Hash du titre normalisé (pour matching cross-doc)
        title_hash = hashlib.md5(normalized_title.encode()).hexdigest()[:8]

        # ID unique dans le document
        return f"topic:{document_id}:{level}:{title_hash}"

    def _create_document_level_topic(
        self,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> StructuralTopic:
        """
        Crée un topic par défaut pour tout le document.

        Utilisé quand aucun header H1/H2 n'est trouvé.
        """
        title = "Document"
        if metadata:
            title = metadata.get("title", metadata.get("filename", "Document"))

        normalized = self._normalize_title(title)
        topic_id = f"topic:{document_id}:0:root"

        return StructuralTopic(
            topic_id=topic_id,
            title=title,
            normalized_title=normalized,
            level=0,  # Document-level
            document_id=document_id,
            section_path=title,
            char_start=0,
            char_end=-1,  # Tout le document
            parent_topic_id=None
        )

    def extract_topics_from_section_contexts(
        self,
        document_id: str,
        neo4j_driver,
        tenant_id: str = "default",
        max_topics: int = 30,
        max_level: int = 2
    ) -> TopicExtractionResult:
        """
        Extrait les topics depuis les SectionContext existants dans Neo4j.

        Cette méthode est préférée à extract_topics() car elle utilise
        la structure documentaire déjà extraite lors de l'ingestion,
        plutôt que de parser le texte brut.

        ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a (refactored)

        Args:
            document_id: ID du document
            neo4j_driver: Driver Neo4j connecté
            tenant_id: Tenant ID
            max_topics: Gating anti-explosion (défaut: 30)
            max_level: Niveau max de section à inclure (1=H1, 2=H2)

        Returns:
            TopicExtractionResult avec topics dédupliqués et normalisés
        """
        start_time = datetime.now()

        logger.info(
            f"[OSMOSE:Pass2a] Extracting topics from SectionContext for {document_id}"
        )

        # 1. Récupérer SectionContext depuis Neo4j
        query = """
        MATCH (sc:SectionContext {tenant_id: $tenant_id, doc_id: $document_id})
        WHERE sc.section_level IS NOT NULL
          AND sc.section_level <= $max_level
          AND sc.section_level > 0
          AND sc.section_path IS NOT NULL
          AND sc.section_path <> 'root'
        RETURN DISTINCT
            sc.context_id AS context_id,
            sc.section_path AS section_path,
            sc.section_level AS level
        ORDER BY sc.section_level, sc.section_path
        """

        sections = []
        with neo4j_driver.session(database="neo4j") as session:
            result = session.run(
                query,
                tenant_id=tenant_id,
                document_id=document_id,
                max_level=max_level
            )
            sections = [dict(r) for r in result]

        if not sections:
            logger.info(
                f"[OSMOSE:Pass2a] No SectionContext found for {document_id}, "
                "creating document-level topic"
            )
            default_topic = self._create_document_level_topic(document_id)
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            return TopicExtractionResult(
                document_id=document_id,
                topics=[default_topic],
                has_topic_relations=[(document_id, default_topic.topic_id)],
                topic_hierarchy={},
                extraction_time_ms=elapsed_ms
            )

        # 2. Dédupliquer par topic_key normalisé
        seen_keys = {}  # {normalized_key: StructuralTopic}
        hierarchy = {}

        for sec in sections:
            # Extraire le titre depuis section_path
            # Format: "Parent / Child" ou "Title"
            path_parts = sec["section_path"].split(" / ")
            title = path_parts[-1].strip()

            # Ignorer les sections génériques
            if title.lower() in {"note", "caution", "recommendation", "tip", "warning"}:
                continue

            # Normaliser pour déduplication
            topic_key = self._normalize_title(title)

            if not topic_key:
                continue

            # Skip si déjà vu avec même topic_key
            if topic_key in seen_keys:
                continue

            # Créer le topic
            level = sec["level"]
            topic_id = self._generate_topic_id(document_id, topic_key, level)

            topic = StructuralTopic(
                topic_id=topic_id,
                title=title,
                normalized_title=topic_key,
                level=level,
                document_id=document_id,
                section_path=sec["section_path"],
                char_start=0,  # Non disponible depuis SectionContext
                char_end=-1,
                parent_topic_id=None  # Pourrait être enrichi avec parent H1
            )

            seen_keys[topic_key] = topic

            # Gating: arrêter si on atteint le max
            if len(seen_keys) >= max_topics:
                logger.warning(
                    f"[OSMOSE:Pass2a] Gating: max {max_topics} topics reached for {document_id}"
                )
                break

        topics = list(seen_keys.values())

        # 3. Préparer relations HAS_TOPIC
        has_topic_relations = [(document_id, t.topic_id) for t in topics]

        elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

        logger.info(
            f"[OSMOSE:Pass2a] Extracted {len(topics)} topics from SectionContext "
            f"(L1: {len([t for t in topics if t.level == 1])}, "
            f"L2: {len([t for t in topics if t.level == 2])}) "
            f"in {elapsed_ms:.1f}ms"
        )

        return TopicExtractionResult(
            document_id=document_id,
            topics=topics,
            has_topic_relations=has_topic_relations,
            topic_hierarchy=hierarchy,
            extraction_time_ms=elapsed_ms
        )


class TopicNeo4jWriter:
    """
    Écrit les Topics structurels dans Neo4j.

    Crée:
    - CanonicalConcept avec concept_type='TOPIC'
    - Relations HAS_TOPIC (Document → Topic)
    """

    def __init__(self, neo4j_client, tenant_id: str = "default"):
        """
        Initialise le writer.

        Args:
            neo4j_client: Client Neo4j connecté
            tenant_id: ID du tenant
        """
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id

        self._stats = {
            "topics_created": 0,
            "topics_updated": 0,
            "has_topic_created": 0
        }

    def write_topics(
        self,
        document_id: str,
        topics: List[StructuralTopic]
    ) -> Dict[str, Any]:
        """
        Écrit les topics dans Neo4j.

        Args:
            document_id: ID du document source
            topics: Liste de StructuralTopic à écrire

        Returns:
            Statistiques d'écriture
        """
        if not topics:
            return self._stats

        logger.info(f"[OSMOSE:Pass2a] Writing {len(topics)} topics to Neo4j")

        for topic in topics:
            # 1. Créer/Mettre à jour CanonicalConcept type=TOPIC
            self._upsert_topic_concept(topic)

            # 2. Créer HAS_TOPIC (Document → Topic)
            self._create_has_topic_relation(document_id, topic)

            # 3. Si topic a un parent, créer relation hiérarchique
            if topic.parent_topic_id:
                self._create_topic_hierarchy_relation(topic)

        logger.info(
            f"[OSMOSE:Pass2a] Neo4j write complete: "
            f"{self._stats['topics_created']} created, "
            f"{self._stats['topics_updated']} updated, "
            f"{self._stats['has_topic_created']} HAS_TOPIC"
        )

        return self._stats

    def _upsert_topic_concept(self, topic: StructuralTopic) -> str:
        """
        Crée ou met à jour un CanonicalConcept de type TOPIC.

        Returns:
            canonical_id du topic
        """
        query = """
        MERGE (t:CanonicalConcept {
            canonical_id: $topic_id,
            tenant_id: $tenant_id
        })
        ON CREATE SET
            t.canonical_name = $title,
            t.concept_type = 'TOPIC',
            t.type = 'TOPIC',
            t.normalized_title = $normalized_title,
            t.level = $level,
            t.section_path = $section_path,
            t.first_document_id = $document_id,
            t.document_ids = [$document_id],
            t.support = 1,
            t.created_at = datetime()
        ON MATCH SET
            t.support = t.support + 1,
            t.document_ids = CASE
                WHEN NOT $document_id IN t.document_ids
                THEN t.document_ids + $document_id
                ELSE t.document_ids
            END,
            t.updated_at = datetime()

        RETURN t.canonical_id AS canonical_id,
               CASE WHEN t.created_at = t.updated_at THEN true ELSE false END AS created
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    topic_id=topic.topic_id,
                    tenant_id=self.tenant_id,
                    title=topic.title,
                    normalized_title=topic.normalized_title,
                    level=topic.level,
                    section_path=topic.section_path,
                    document_id=topic.document_id
                )
                record = result.single()

                if record:
                    if record.get("created", False):
                        self._stats["topics_created"] += 1
                    else:
                        self._stats["topics_updated"] += 1
                    return record["canonical_id"]

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2a] Error upserting topic: {e}")

        return ""

    def _create_has_topic_relation(
        self,
        document_id: str,
        topic: StructuralTopic
    ) -> bool:
        """
        Crée relation HAS_TOPIC entre Document et Topic.
        """
        query = """
        MATCH (d:Document {doc_id: $document_id, tenant_id: $tenant_id})
        MATCH (t:CanonicalConcept {canonical_id: $topic_id, tenant_id: $tenant_id})

        MERGE (d)-[r:HAS_TOPIC]->(t)
        ON CREATE SET
            r.level = $level,
            r.section_path = $section_path,
            r.char_start = $char_start,
            r.char_end = $char_end,
            r.created_at = datetime()

        RETURN type(r) AS rel_type
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=self.tenant_id,
                    topic_id=topic.topic_id,
                    level=topic.level,
                    section_path=topic.section_path,
                    char_start=topic.char_start,
                    char_end=topic.char_end
                )
                record = result.single()

                if record:
                    self._stats["has_topic_created"] += 1
                    return True

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2a] Error creating HAS_TOPIC: {e}")

        return False

    def _create_topic_hierarchy_relation(self, topic: StructuralTopic) -> bool:
        """
        Crée relation SUBTOPIC_OF entre Topic enfant et parent.
        """
        if not topic.parent_topic_id:
            return False

        query = """
        MATCH (child:CanonicalConcept {canonical_id: $child_id, tenant_id: $tenant_id})
        MATCH (parent:CanonicalConcept {canonical_id: $parent_id, tenant_id: $tenant_id})

        MERGE (child)-[r:SUBTOPIC_OF]->(parent)
        ON CREATE SET
            r.created_at = datetime()

        RETURN type(r) AS rel_type
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    child_id=topic.topic_id,
                    parent_id=topic.parent_topic_id,
                    tenant_id=self.tenant_id
                )
                return result.single() is not None

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2a] Error creating SUBTOPIC_OF: {e}")

        return False


class CoversBuilder:
    """
    Construit les relations COVERS entre Topics et Concepts.

    ADR_GRAPH_FIRST_ARCHITECTURE - Pass 2a

    IMPORTANT - Règles COVERS (déterministes, PAS de LLM):
    1. Concept MENTIONED_IN une section rattachée au Topic
    2. ET salience suffisante (TF-IDF doc-level, spread)
    3. ET pas un concept générique (stop-concept)
    4. TOP-K(15) concepts par topic (anti-explosion)

    COVERS = périmètre documentaire, JAMAIS lien conceptuel.

    Scoring déterministe: salience = mention_count / max_count_in_doc
    """

    # Seuil de salience minimum pour COVERS (ChatGPT spec: 0.25)
    DEFAULT_SALIENCE_THRESHOLD = 0.25

    # Top-K: max concepts par topic (ChatGPT spec: 15)
    DEFAULT_TOP_K = 15

    # Version pour traçabilité
    VERSION = "2.0.0"
    METHOD = "mention_count_normalized"

    # Concepts génériques à exclure (stop-concepts)
    STOP_CONCEPTS = {
        'document', 'section', 'chapter', 'introduction', 'conclusion',
        'summary', 'overview', 'exemple', 'example', 'figure', 'table',
        'annexe', 'appendix', 'référence', 'reference', 'note', 'remarque'
    }

    def __init__(
        self,
        neo4j_client,
        tenant_id: str = "default",
        salience_threshold: float = None,
        top_k: int = None
    ):
        """
        Initialise le builder.

        Args:
            neo4j_client: Client Neo4j connecté
            tenant_id: ID du tenant
            salience_threshold: Seuil de salience pour COVERS (défaut: 0.25)
            top_k: Max concepts par topic (défaut: 15)
        """
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id
        self.salience_threshold = salience_threshold or self.DEFAULT_SALIENCE_THRESHOLD
        self.top_k = top_k or self.DEFAULT_TOP_K

        self._stats = {
            "covers_created": 0,
            "concepts_evaluated": 0,
            "concepts_excluded_salience": 0,
            "concepts_excluded_stop": 0,
            "concepts_excluded_topk": 0
        }

    def build_covers_for_document(
        self,
        document_id: str,
        topics: List[StructuralTopic]
    ) -> Dict[str, Any]:
        """
        Construit les relations COVERS pour un document.

        Pour chaque Topic, trouve les concepts MENTIONED_IN les sections
        couvertes par le topic et qui ont une salience suffisante.

        Args:
            document_id: ID du document
            topics: Topics du document

        Returns:
            Statistiques de construction
        """
        if not topics:
            return self._stats

        logger.info(f"[OSMOSE:Pass2a] Building COVERS for {len(topics)} topics")

        for topic in topics:
            self._build_covers_for_topic(document_id, topic)

        logger.info(
            f"[OSMOSE:Pass2a] COVERS build complete: "
            f"{self._stats['covers_created']} created, "
            f"{self._stats['concepts_excluded_salience']} excluded (salience), "
            f"{self._stats['concepts_excluded_stop']} excluded (stop-concept)"
        )

        return self._stats

    def _build_covers_for_topic(
        self,
        document_id: str,
        topic: StructuralTopic
    ) -> int:
        """
        Construit COVERS pour un topic spécifique.

        Règles:
        1. Trouver tous les concepts MENTIONED_IN des sections dans [char_start, char_end]
        2. Calculer salience (count / max_count dans le doc)
        3. Filtrer par seuil de salience
        4. Exclure stop-concepts
        5. Créer COVERS
        """
        # Requête pour trouver concepts avec leur salience dans le scope du topic
        # NOTE: SectionContext utilise 'doc_id' (pas 'document_id')
        # ChatGPT spec: top-K(15) + min_threshold(0.25) + scoring déterministe
        query = """
        // Calculer max mentions pour normalisation (une seule fois)
        MATCH (any_c:CanonicalConcept {tenant_id: $tenant_id})
              -[any_m:MENTIONED_IN]->
              (any_ctx:SectionContext {doc_id: $document_id, tenant_id: $tenant_id})
        WITH max(any_m.count) AS max_count

        // Trouver tous les concepts mentionnés dans les sections du document
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
              -[m:MENTIONED_IN]->
              (ctx:SectionContext {tenant_id: $tenant_id})
        WHERE ctx.doc_id = $document_id

        // Calculer salience (scoring déterministe: count / max_count)
        WITH c,
             ctx,
             m.count AS mention_count,
             max_count,
             toFloat(m.count) / max_count AS salience
        WHERE salience >= $salience_threshold

        RETURN c.canonical_id AS concept_id,
               c.canonical_name AS concept_name,
               c.concept_type AS concept_type,
               salience,
               mention_count
        ORDER BY salience DESC
        LIMIT $top_k
        """

        try:
            # Debug: vérifier le driver
            if not self.neo4j.driver:
                logger.error("[OSMOSE:Pass2a] CoversBuilder: neo4j.driver is None!")
                return 0

            logger.info(
                f"[OSMOSE:Pass2a] CoversBuilder query params: "
                f"document_id={document_id}, tenant_id={self.tenant_id}, "
                f"salience_threshold={self.salience_threshold}, "
                f"top_k={self.top_k}, neo4j_database={self.neo4j.database}"
            )

            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    document_id=document_id,
                    tenant_id=self.tenant_id,
                    salience_threshold=self.salience_threshold,
                    top_k=self.top_k
                )

                candidates = list(result)
                logger.info(f"[OSMOSE:Pass2a] CoversBuilder found {len(candidates)} candidates")
                self._stats["concepts_evaluated"] += len(candidates)

                for record in candidates:
                    concept_name = record["concept_name"] or ""
                    concept_type = record.get("concept_type", "")

                    # Filtrer stop-concepts
                    if self._is_stop_concept(concept_name):
                        self._stats["concepts_excluded_stop"] += 1
                        continue

                    # Créer COVERS
                    if self._create_covers_relation(
                        topic.topic_id,
                        record["concept_id"],
                        record["salience"],
                        record["mention_count"]
                    ):
                        self._stats["covers_created"] += 1

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2a] Error building COVERS for topic: {e}")

        return self._stats["covers_created"]

    def _is_stop_concept(self, concept_name: str) -> bool:
        """Vérifie si le concept est un stop-concept générique."""
        if not concept_name:
            return True

        normalized = concept_name.lower().strip()
        return normalized in self.STOP_CONCEPTS

    def _create_covers_relation(
        self,
        topic_id: str,
        concept_id: str,
        salience: float,
        mention_count: int
    ) -> bool:
        """
        Crée une relation COVERS entre Topic et Concept.

        COVERS signifie "ce topic couvre ce concept" = périmètre documentaire.
        """
        # ChatGPT spec: method/version pour traçabilité
        query = """
        MATCH (t:CanonicalConcept {canonical_id: $topic_id, tenant_id: $tenant_id})
        WHERE t.concept_type = 'TOPIC'
        MATCH (c:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})

        MERGE (t)-[r:COVERS]->(c)
        ON CREATE SET
            r.salience = $salience,
            r.mention_count = $mention_count,
            r.method = $method,
            r.version = $version,
            r.created_at = datetime()
        ON MATCH SET
            r.salience = CASE WHEN $salience > r.salience THEN $salience ELSE r.salience END,
            r.mention_count = r.mention_count + $mention_count,
            r.method = $method,
            r.version = $version,
            r.updated_at = datetime()

        RETURN type(r) AS rel_type
        """

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(
                    query,
                    topic_id=topic_id,
                    concept_id=concept_id,
                    tenant_id=self.tenant_id,
                    salience=salience,
                    mention_count=mention_count,
                    method=self.METHOD,
                    version=self.VERSION
                )
                return result.single() is not None

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2a] Error creating COVERS: {e}")

        return False


# ========================================================================
# CONVENIENCE FUNCTIONS
# ========================================================================

def process_document_topics(
    document_id: str,
    text: str,
    neo4j_client,
    tenant_id: str = "default",
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Fonction principale Pass 2a: extrait et persiste les topics structurels.

    Args:
        document_id: ID du document
        text: Contenu textuel
        neo4j_client: Client Neo4j
        tenant_id: ID du tenant
        metadata: Métadonnées optionnelles

    Returns:
        Résultats combinés extraction + écriture
    """
    # 1. Extraction des topics structurels
    extractor = StructuralTopicExtractor()
    extraction_result = extractor.extract_topics(document_id, text, metadata)

    # 2. Écriture dans Neo4j
    writer = TopicNeo4jWriter(neo4j_client, tenant_id)
    write_stats = writer.write_topics(document_id, extraction_result.topics)

    # 3. Construction des COVERS
    covers_builder = CoversBuilder(neo4j_client, tenant_id)
    covers_stats = covers_builder.build_covers_for_document(
        document_id,
        extraction_result.topics
    )

    return {
        "document_id": document_id,
        "topics_count": len(extraction_result.topics),
        "topics": [
            {
                "topic_id": t.topic_id,
                "title": t.title,
                "level": t.level,
                "section_path": t.section_path
            }
            for t in extraction_result.topics
        ],
        "extraction_time_ms": extraction_result.extraction_time_ms,
        "write_stats": write_stats,
        "covers_stats": covers_stats
    }


def process_document_topics_v2(
    document_id: str,
    neo4j_client,
    tenant_id: str = "default",
    max_topics: int = 30,
    max_level: int = 2
) -> Dict[str, Any]:
    """
    Fonction Pass 2a V2: extrait topics depuis SectionContext (pas texte H1/H2).

    Version refactored qui utilise les SectionContext existants dans Neo4j
    au lieu de parser le texte brut.

    Args:
        document_id: ID du document
        neo4j_client: Client Neo4j avec driver
        tenant_id: ID du tenant
        max_topics: Gating anti-explosion (défaut: 30)
        max_level: Niveau max de section (1=H1, 2=H2)

    Returns:
        Résultats combinés extraction + écriture
    """
    # 1. Extraction des topics depuis SectionContext
    extractor = StructuralTopicExtractor()
    extraction_result = extractor.extract_topics_from_section_contexts(
        document_id=document_id,
        neo4j_driver=neo4j_client.driver,
        tenant_id=tenant_id,
        max_topics=max_topics,
        max_level=max_level
    )

    # 2. Écriture dans Neo4j
    writer = TopicNeo4jWriter(neo4j_client, tenant_id)
    write_stats = writer.write_topics(document_id, extraction_result.topics)

    # 3. Construction des COVERS
    covers_builder = CoversBuilder(neo4j_client, tenant_id)
    covers_stats = covers_builder.build_covers_for_document(
        document_id,
        extraction_result.topics
    )

    return {
        "document_id": document_id,
        "topics_count": len(extraction_result.topics),
        "topics": [
            {
                "topic_id": t.topic_id,
                "title": t.title,
                "level": t.level,
                "section_path": t.section_path
            }
            for t in extraction_result.topics
        ],
        "extraction_time_ms": extraction_result.extraction_time_ms,
        "write_stats": write_stats,
        "covers_stats": covers_stats,
        "method": "section_context_v2"
    }

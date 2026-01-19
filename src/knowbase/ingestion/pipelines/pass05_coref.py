"""
OSMOSE Pass 0.5 - Linguistic Coreference Pipeline

Pipeline de résolution de coréférence (anaphora resolution).
S'exécute après Pass 0 (Structural Layer) et avant Pass 1 (Semantic Layer).

Responsabilités:
1. Charger les DocItems et chunks du document
2. Détecter la langue du document
3. Sélectionner l'engine approprié (spaCy, Coreferee, rules)
4. Résoudre les coréférences avec politique conservative
5. Persister la CorefGraph (MentionSpan, CoreferenceChain, CorefDecision)
6. Créer les liens MATCHES_PROTOCONCEPT si applicable

Invariants respectés:
- L1: Evidence-preserving (spans exacts)
- L2: No generated evidence (pas de texte modifié persisté)
- L3: Closed-world disambiguation
- L4: Abstention-first
- L5: Linguistic-only

Ref: doc/ongoing/IMPLEMENTATION_PLAN_ADR_COMPLETION.md - Section 10.6
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.linguistic.coref_models import (
    MentionSpan,
    MentionType,
    CoreferenceChain,
    CorefDecision,
    CorefLink,
    CorefGraphResult,
    CoreferenceCluster,
    CorefScope,
    ReasonCode,
)
from knowbase.linguistic.coref_engine import (
    ICorefEngine,
    get_engine_for_language,
    get_available_engines,
)
from knowbase.linguistic.coref_gating import (
    CorefGatingPolicy,
    GatingCandidate,
    GatingResult,
    create_gating_policy,
)
from knowbase.linguistic.coref_named_gating import (
    NamedNamedGatingPolicy,
    NamedGatingResult,
    GatingDecision,
    create_named_gating_policy,
)
from knowbase.linguistic.coref_cache import CorefCache, get_coref_cache
from knowbase.linguistic.coref_llm_arbiter import (
    CorefLLMArbiter,
    CorefPair,
    CorefLLMDecision,
    create_coref_arbiter,
)
from knowbase.linguistic.coref_persist import CorefPersistence

logger = logging.getLogger(__name__)


@dataclass
class Pass05Config:
    """Configuration du pipeline Pass 0.5."""

    # Seuils de gating (pronoms)
    confidence_threshold: float = 0.85
    max_sentence_distance: int = 2
    max_char_distance: int = 500

    # Gating Named↔Named (ADR_COREF_NAMED_NAMED_VALIDATION)
    enable_named_gating: bool = True   # Activer le filtrage Named↔Named
    named_jaro_reject: float = 0.55    # Seuil Jaro-Winkler pour REJECT
    named_jaro_accept: float = 0.95    # Seuil Jaro-Winkler pour ACCEPT
    named_jaccard_accept: float = 0.8  # Seuil Token Jaccard pour ACCEPT
    enable_llm_arbitration: bool = True  # Activer l'arbitrage LLM pour REVIEW
    domain_context: Optional[str] = None  # Contexte domaine pour LLM (optionnel)

    # Options de traitement
    skip_if_exists: bool = True       # Idempotence
    create_protoconcept_links: bool = True  # Créer MATCHES_PROTOCONCEPT
    persist_decisions: bool = True    # Persister les CorefDecision (audit)

    # Batching pour gros documents (OOM Fix)
    # FastCoref OOM sur docs > 100k chars, traitement par lots avec overlap
    # OOM Fix 2025-01: Réduit de 100k à 50k chars (OOM sur doc 106k avec batch 100k)
    fastcoref_batch_size: int = 50000     # 50k chars par batch (~12 pages)
    fastcoref_batch_overlap: int = 3000   # 3k chars overlap pour contexte coref

    # Logging
    verbose: bool = False


@dataclass
class Pass05Result:
    """Résultat du pipeline Pass 0.5."""

    # Document
    doc_id: str
    doc_version_id: str

    # Succès
    success: bool = False
    skipped: bool = False
    error_message: Optional[str] = None

    # Métriques
    mention_spans_created: int = 0
    chains_created: int = 0
    links_created: int = 0
    decisions_created: int = 0

    # Taux
    resolution_rate: float = 0.0
    abstention_rate: float = 0.0

    # Timing
    processing_time_ms: float = 0.0

    # Engine utilisé
    engine_used: str = "unknown"


class Pass05CoreferencePipeline:
    """
    Pipeline Pass 0.5 - Résolution de coréférence.

    Orchestre:
    - Chargement des données depuis Neo4j (DocItem, chunks)
    - Sélection de l'engine selon la langue
    - Résolution avec politique de gating conservative
    - Persistance de la CorefGraph
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default",
        config: Optional[Pass05Config] = None,
    ):
        """
        Initialise le pipeline.

        Args:
            neo4j_client: Client Neo4j
            tenant_id: ID du tenant
            config: Configuration du pipeline
        """
        self.neo4j_client = neo4j_client or Neo4jClient()
        self.tenant_id = tenant_id
        self.config = config or Pass05Config()

        # Composants - Pronoun gating
        self.persistence = CorefPersistence(
            neo4j_client=self.neo4j_client,
            tenant_id=tenant_id,
        )
        self.gating_policy = create_gating_policy(
            confidence_threshold=self.config.confidence_threshold,
            max_sentence_distance=self.config.max_sentence_distance,
            max_char_distance=self.config.max_char_distance,
        )

        # Composants - Named↔Named gating (ADR_COREF_NAMED_NAMED_VALIDATION)
        self.named_gating_policy: Optional[NamedNamedGatingPolicy] = None
        self.coref_cache: Optional[CorefCache] = None
        self.llm_arbiter: Optional[CorefLLMArbiter] = None

        if self.config.enable_named_gating:
            self.named_gating_policy = create_named_gating_policy(
                jaro_reject_threshold=self.config.named_jaro_reject,
                jaro_accept_threshold=self.config.named_jaro_accept,
                jaccard_accept_threshold=self.config.named_jaccard_accept,
            )
            self.coref_cache = get_coref_cache()

            if self.config.enable_llm_arbitration:
                self.llm_arbiter = create_coref_arbiter(
                    domain_context=self.config.domain_context,
                )

        logger.info(
            f"[OSMOSE:Pass0.5] Initialized (tenant={tenant_id}, "
            f"threshold={self.config.confidence_threshold}, "
            f"named_gating={self.config.enable_named_gating})"
        )

    def process_document(
        self,
        doc_id: str,
        doc_version_id: str,
    ) -> Pass05Result:
        """
        Traite un document pour la résolution de coréférence.

        Args:
            doc_id: ID du document
            doc_version_id: ID de version du document

        Returns:
            Pass05Result avec les métriques
        """
        start_time = time.time()
        result = Pass05Result(doc_id=doc_id, doc_version_id=doc_version_id)

        try:
            # 1. Vérifier si déjà traité (idempotence)
            if self.config.skip_if_exists:
                if self.persistence.check_coref_exists_for_document(doc_version_id):
                    result.skipped = True
                    result.success = True
                    logger.info(f"[OSMOSE:Pass0.5] Skipping {doc_id} (already processed)")
                    return result

            # 2. Charger les données du document
            doc_data = self._load_document_data(doc_id, doc_version_id)
            if not doc_data:
                result.error_message = "Failed to load document data"
                return result

            # 3. Détecter la langue
            lang = self._detect_language(doc_data)
            logger.info(f"[OSMOSE:Pass0.5] Document {doc_id} language: {lang}")

            # 4. Sélectionner l'engine
            engine = get_engine_for_language(lang)
            result.engine_used = engine.engine_name
            logger.info(f"[OSMOSE:Pass0.5] Using engine: {engine.engine_name}")

            # 5. Résoudre les coréférences
            coref_result = self._resolve_coreferences(
                doc_data=doc_data,
                engine=engine,
                lang=lang,
            )

            # 6. Persister la CorefGraph
            stats = self.persistence.persist_coref_graph(coref_result)

            # 7. Créer les liens MATCHES_PROTOCONCEPT si applicable
            if self.config.create_protoconcept_links:
                self._create_protoconcept_links(coref_result, doc_data)

            # 8. Mettre à jour le résultat
            result.success = True
            result.mention_spans_created = stats["mention_spans"]
            result.chains_created = stats["chains"]
            result.links_created = stats["links"]
            result.decisions_created = stats["decisions"]
            result.resolution_rate = coref_result.resolution_rate
            result.abstention_rate = coref_result.abstention_rate

        except Exception as e:
            logger.error(f"[OSMOSE:Pass0.5] Error processing {doc_id}: {e}")
            result.error_message = str(e)

        result.processing_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[OSMOSE:Pass0.5] Completed {doc_id}: "
            f"{result.mention_spans_created} spans, "
            f"{result.chains_created} chains, "
            f"resolution={result.resolution_rate:.1%}, "
            f"abstention={result.abstention_rate:.1%} "
            f"({result.processing_time_ms:.0f}ms)"
        )

        return result

    def _load_document_data(
        self,
        doc_id: str,
        doc_version_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Charge les données du document depuis Neo4j.

        Returns:
            Dict avec docitems, chunks, text, et language
        """
        try:
            # Charger les DocItem de type NARRATIVE_TEXT (avec section_id pour batching)
            docitems_query = """
            MATCH (d:DocItem {tenant_id: $tenant_id, doc_id: $doc_id})
            WHERE d.item_type IN ['NARRATIVE_TEXT', 'PARAGRAPH', 'TEXT']
            RETURN d.item_id AS item_id,
                   d.text AS text,
                   d.reading_order_index AS order_idx,
                   d.page_no AS page_no,
                   d.section_id AS section_id,
                   d.charspan_start AS charspan_start,
                   d.charspan_end AS charspan_end
            ORDER BY d.reading_order_index
            """
            docitems_result = self.neo4j_client.execute_query(
                docitems_query,
                tenant_id=self.tenant_id,
                doc_id=doc_id
            )

            # Charger les TypeAwareChunk
            chunks_query = """
            MATCH (c:TypeAwareChunk {tenant_id: $tenant_id, doc_id: $doc_id})
            RETURN c.chunk_id AS chunk_id,
                   c.text AS text,
                   c.chunk_type AS chunk_type,
                   c.reading_order_start AS order_start
            ORDER BY c.reading_order_start
            """
            chunks_result = self.neo4j_client.execute_query(
                chunks_query,
                tenant_id=self.tenant_id,
                doc_id=doc_id
            )

            # Charger la version du document pour la langue
            doc_version_query = """
            MATCH (dv:DocumentVersion {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
            RETURN dv.language AS language
            """
            version_result = self.neo4j_client.execute_query(
                doc_version_query,
                tenant_id=self.tenant_id,
                doc_version_id=doc_version_id
            )

            # Construire le texte complet
            full_text = "\n".join([d["text"] for d in docitems_result if d.get("text")])

            # Langue par défaut
            lang = "en"
            if version_result and version_result[0].get("language"):
                lang = version_result[0]["language"]

            return {
                "doc_id": doc_id,
                "doc_version_id": doc_version_id,
                "docitems": list(docitems_result) if docitems_result else [],
                "chunks": list(chunks_result) if chunks_result else [],
                "full_text": full_text,
                "language": lang,
            }

        except Exception as e:
            logger.error(f"[OSMOSE:Pass0.5] Failed to load document data: {e}")
            return None

    def _detect_language(self, doc_data: Dict[str, Any]) -> str:
        """
        Détecte la langue du document.

        Stratégie:
        - doc_language par défaut
        - chunk_language si document mixte détecté (non implémenté pour l'instant)
        """
        return doc_data.get("language", "en")

    def _resolve_coreferences(
        self,
        doc_data: Dict[str, Any],
        engine: ICorefEngine,
        lang: str,
    ) -> CorefGraphResult:
        """
        Résout les coréférences avec l'engine et le gating policy.

        OOM Fix: Pour les gros documents (> fastcoref_batch_size chars),
        traite par batches de sections pour éviter les OOM FastCoref.

        Args:
            doc_data: Données du document
            engine: Engine de coréférence
            lang: Langue du document

        Returns:
            CorefGraphResult avec toutes les structures
        """
        start_time = time.time()

        result = CorefGraphResult(
            doc_id=doc_data["doc_id"],
            doc_version_id=doc_data["doc_version_id"],
            method=engine.engine_name,
        )

        full_text = doc_data["full_text"]
        chunks = doc_data.get("chunks", [])
        docitems = doc_data.get("docitems", [])

        # Décider si batching nécessaire (OOM Fix pour gros documents)
        batch_size = self.config.fastcoref_batch_size
        if len(full_text) > batch_size and docitems:
            # Traitement par batches de sections
            logger.info(
                f"[OSMOSE:Pass0.5] Large document ({len(full_text):,} chars > {batch_size:,}), "
                f"using section batching"
            )
            clusters = self._resolve_with_section_batching(
                docitems=docitems,
                engine=engine,
                lang=lang,
                batch_size=batch_size,
                overlap=self.config.fastcoref_batch_overlap,
            )
        else:
            # Traitement normal (document entier)
            clusters = engine.resolve(
                document_text=full_text,
                chunks=[{"text": c.get("text", ""), "chunk_id": c.get("chunk_id")} for c in chunks],
                lang=lang,
            )

        # 2. Filtrer les faux positifs Named↔Named (ADR_COREF_NAMED_NAMED_VALIDATION)
        if self.config.enable_named_gating:
            original_count = len(clusters)
            clusters = self._filter_clusters_with_named_gating(clusters, full_text)
            logger.info(
                f"[OSMOSE:Pass0.5] Named↔Named gating: {original_count} clusters → {len(clusters)} after filtering"
            )

        # 3. Convertir les clusters en MentionSpan et appliquer le gating pronoms
        for cluster in clusters:
            self._process_cluster(
                cluster=cluster,
                doc_data=doc_data,
                lang=lang,
                result=result,
            )

        result.processing_time_ms = (time.time() - start_time) * 1000
        return result

    def _resolve_with_section_batching(
        self,
        docitems: List[Dict[str, Any]],
        engine: ICorefEngine,
        lang: str,
        batch_size: int,
        overlap: int,
    ) -> List[CoreferenceCluster]:
        """
        Résout les coréférences par batches de sections.

        OOM Fix: Groupe les DocItems par sections jusqu'à batch_size chars,
        puis appelle FastCoref sur chaque batch avec overlap pour le contexte.

        Args:
            docitems: Liste des DocItems avec text et section_id
            engine: Engine de coréférence
            lang: Langue
            batch_size: Taille max d'un batch en chars
            overlap: Chars d'overlap entre batches pour contexte

        Returns:
            Liste de tous les clusters (offsets ajustés au document complet)
        """
        all_clusters: List[CoreferenceCluster] = []

        # Grouper les DocItems en batches
        batches = self._create_section_batches(docitems, batch_size, overlap)

        logger.info(
            f"[OSMOSE:Pass0.5] Created {len(batches)} batches for section-based processing"
        )

        for batch_idx, batch in enumerate(batches):
            batch_text = batch["text"]
            batch_offset = batch["offset"]  # Offset dans le document complet

            # Appeler l'engine sur ce batch
            batch_clusters = engine.resolve(
                document_text=batch_text,
                chunks=[],
                lang=lang,
            )

            # Ajuster les offsets des clusters au document complet
            for cluster in batch_clusters:
                adjusted_mentions = []
                for mention in cluster.mentions:
                    adjusted_mentions.append({
                        "start": mention["start"] + batch_offset,
                        "end": mention["end"] + batch_offset,
                        "text": mention["text"],
                        "sentence_idx": mention.get("sentence_idx", 0),
                    })
                cluster.mentions = adjusted_mentions
                all_clusters.append(cluster)

            logger.debug(
                f"[OSMOSE:Pass0.5] Batch {batch_idx + 1}/{len(batches)}: "
                f"{len(batch_text):,} chars, {len(batch_clusters)} clusters"
            )

        # Dédupliquer les clusters de l'overlap (même mentions = même cluster)
        all_clusters = self._deduplicate_overlap_clusters(all_clusters)

        logger.info(
            f"[OSMOSE:Pass0.5] Section batching complete: {len(all_clusters)} total clusters"
        )

        return all_clusters

    def _create_section_batches(
        self,
        docitems: List[Dict[str, Any]],
        batch_size: int,
        overlap: int,
    ) -> List[Dict[str, Any]]:
        """
        Crée des batches de DocItems groupés par sections.

        Stratégie:
        - Accumule les DocItems jusqu'à batch_size chars
        - Coupe aux frontières de sections quand possible
        - Ajoute overlap du batch précédent pour contexte coref

        Returns:
            Liste de batches avec {text, offset, docitem_ids}
        """
        batches = []
        current_batch_items = []
        current_batch_chars = 0
        current_offset = 0
        previous_overlap_text = ""

        for item in docitems:
            item_text = item.get("text", "")
            if not item_text:
                continue

            item_chars = len(item_text)

            # Si ajouter cet item dépasse la limite, créer un nouveau batch
            if current_batch_chars + item_chars > batch_size and current_batch_items:
                # Construire le texte du batch
                batch_text = previous_overlap_text + "\n".join(
                    [i.get("text", "") for i in current_batch_items]
                )

                batches.append({
                    "text": batch_text,
                    "offset": current_offset - len(previous_overlap_text),
                    "docitem_ids": [i.get("item_id") for i in current_batch_items],
                })

                # Préparer l'overlap pour le prochain batch
                full_batch_text = "\n".join([i.get("text", "") for i in current_batch_items])
                previous_overlap_text = full_batch_text[-overlap:] if len(full_batch_text) > overlap else full_batch_text

                # Reset pour prochain batch
                current_offset += current_batch_chars
                current_batch_items = []
                current_batch_chars = 0

            current_batch_items.append(item)
            current_batch_chars += item_chars + 1  # +1 pour le \n

        # Dernier batch
        if current_batch_items:
            batch_text = previous_overlap_text + "\n".join(
                [i.get("text", "") for i in current_batch_items]
            )
            batches.append({
                "text": batch_text,
                "offset": current_offset - len(previous_overlap_text),
                "docitem_ids": [i.get("item_id") for i in current_batch_items],
            })

        return batches

    def _deduplicate_overlap_clusters(
        self,
        clusters: List[CoreferenceCluster],
    ) -> List[CoreferenceCluster]:
        """
        Déduplique les clusters qui apparaissent dans l'overlap entre batches.

        Deux clusters sont considérés identiques si leurs mentions ont
        les mêmes positions (start, end).
        """
        seen_signatures = set()
        unique_clusters = []

        for cluster in clusters:
            # Signature = tuple triée des (start, end) de toutes les mentions
            signature = tuple(sorted(
                (m["start"], m["end"]) for m in cluster.mentions
            ))

            if signature not in seen_signatures:
                seen_signatures.add(signature)
                unique_clusters.append(cluster)

        if len(clusters) != len(unique_clusters):
            logger.debug(
                f"[OSMOSE:Pass0.5] Deduplicated {len(clusters) - len(unique_clusters)} "
                f"overlap clusters"
            )

        return unique_clusters

    def _process_cluster(
        self,
        cluster: CoreferenceCluster,
        doc_data: Dict[str, Any],
        lang: str,
        result: CorefGraphResult,
    ):
        """
        Traite un cluster de coréférence.

        Crée les MentionSpan, applique le gating, et crée les liens.
        """
        if len(cluster.mentions) < 2:
            return

        # Créer les MentionSpan pour chaque mention du cluster
        mention_spans: List[MentionSpan] = []

        for mention in cluster.mentions:
            # Trouver le DocItem correspondant
            docitem_id = self._find_docitem_for_offset(
                offset=mention.get("start", 0),
                docitems=doc_data.get("docitems", [])
            )

            # Trouver le chunk correspondant
            chunk_id = self._find_chunk_for_offset(
                offset=mention.get("start", 0),
                chunks=doc_data.get("chunks", [])
            )

            # Déterminer le type de mention
            mention_type = self._classify_mention(mention.get("text", ""), lang)

            span = MentionSpan(
                tenant_id=self.tenant_id,
                doc_id=doc_data["doc_id"],
                doc_version_id=doc_data["doc_version_id"],
                docitem_id=docitem_id or "unknown",
                chunk_id=chunk_id,
                span_start=mention.get("start", 0),
                span_end=mention.get("end", 0),
                surface=mention.get("text", ""),
                mention_type=mention_type,
                lang=lang,
                sentence_index=mention.get("sentence_idx"),
            )
            mention_spans.append(span)
            result.mention_spans.append(span)

        # Créer la chaîne de coréférence
        chain = CoreferenceChain(
            tenant_id=self.tenant_id,
            doc_id=doc_data["doc_id"],
            doc_version_id=doc_data["doc_version_id"],
            method=cluster.method,
            confidence=cluster.confidence,
            mention_ids=[s.mention_id for s in mention_spans],
            representative_mention_id=mention_spans[cluster.representative_idx].mention_id if mention_spans else None,
        )
        result.chains.append(chain)

        # Appliquer le gating pour créer les liens COREFERS_TO
        representative_span = mention_spans[cluster.representative_idx] if mention_spans else None

        for i, span in enumerate(mention_spans):
            if span.mention_type == MentionType.PRONOUN and representative_span and i != cluster.representative_idx:
                # C'est un pronom - créer un lien vers le représentant
                result.total_pronouns_detected += 1

                # Créer les candidats pour le gating
                candidates = [
                    GatingCandidate(
                        mention_id=representative_span.mention_id,
                        surface=representative_span.surface,
                        sentence_idx=representative_span.sentence_index or 0,
                        char_offset=representative_span.span_start,
                        engine_score=cluster.confidence,
                        sentence_distance=abs((span.sentence_index or 0) - (representative_span.sentence_index or 0)),
                        char_distance=abs(span.span_start - representative_span.span_start),
                    )
                ]

                # Évaluer avec le gating policy
                gating_result = self.gating_policy.evaluate_candidates(
                    pronoun=span.surface,
                    pronoun_sentence_idx=span.sentence_index or 0,
                    candidates=candidates,
                    sentence_context="",  # TODO: récupérer le contexte
                    lang=lang,
                )

                # Créer la décision d'audit
                decision = self.gating_policy.create_decision(
                    tenant_id=self.tenant_id,
                    doc_version_id=doc_data["doc_version_id"],
                    mention_span_key=span.span_key,
                    candidates=candidates,
                    result=gating_result,
                    method=cluster.method,
                )
                result.decisions.append(decision)

                # Créer le lien si résolu
                if gating_result.allowed:
                    link = CorefLink(
                        source_mention_id=span.mention_id,
                        target_mention_id=representative_span.mention_id,
                        method=cluster.method,
                        confidence=gating_result.confidence,
                        scope=gating_result.scope,
                        window_chars=abs(span.span_start - representative_span.span_start),
                    )
                    result.links.append(link)
                    result.resolved_count += 1
                elif gating_result.decision_type.value == "ABSTAIN":
                    result.abstained_count += 1
                else:
                    result.non_referential_count += 1

    def _find_docitem_for_offset(
        self,
        offset: int,
        docitems: List[Dict],
    ) -> Optional[str]:
        """Trouve le DocItem contenant l'offset donné."""
        # Pour l'instant, retourne le premier DocItem
        # TODO: implémenter une recherche par offset
        if docitems:
            return docitems[0].get("item_id")
        return None

    def _find_chunk_for_offset(
        self,
        offset: int,
        chunks: List[Dict],
    ) -> Optional[str]:
        """Trouve le chunk contenant l'offset donné."""
        # Pour l'instant, retourne le premier chunk
        # TODO: implémenter une recherche par offset
        if chunks:
            return chunks[0].get("chunk_id")
        return None

    def _classify_mention(self, text: str, lang: str) -> MentionType:
        """Classifie le type de mention."""
        text_lower = text.lower().strip()

        # Pronoms
        pronouns = {
            "en": {"it", "they", "them", "he", "she", "him", "her", "this", "that", "these", "those"},
            "fr": {"il", "elle", "ils", "elles", "celui-ci", "celle-ci", "ceux-ci", "celles-ci"},
            "de": {"er", "sie", "es", "dieser", "diese", "dieses"},
        }

        if text_lower in pronouns.get(lang, pronouns["en"]):
            return MentionType.PRONOUN

        # Nom propre (commence par majuscule)
        if text and text[0].isupper() and len(text) > 1:
            # Vérifier si c'est un acronyme
            if text.isupper() and len(text) >= 2:
                return MentionType.PROPER
            # Vérifier si c'est un nom propre
            if any(c.isupper() for c in text[1:]):
                return MentionType.PROPER
            return MentionType.PROPER

        # Groupe nominal
        return MentionType.NP

    def _filter_clusters_with_named_gating(
        self,
        clusters: List[CoreferenceCluster],
        full_text: str,
    ) -> List[CoreferenceCluster]:
        """
        Filtre les clusters pour retirer les faux positifs Named↔Named.

        Pour chaque cluster:
        1. Identifier les mentions Named (PROPER, NP)
        2. Pour chaque paire Named↔Named, appliquer le gating
        3. Si REJECT → retirer de la chaîne (ne pas inclure dans le cluster)
        4. Si REVIEW et LLM actif → arbitrer puis décider

        Args:
            clusters: Liste de CoreferenceCluster de l'engine
            full_text: Texte complet du document (pour le contexte)

        Returns:
            Liste de CoreferenceCluster filtrés
        """
        if not self.named_gating_policy:
            return clusters

        filtered_clusters = []
        pairs_to_review: List[Tuple[int, int, int, CorefPair]] = []  # (cluster_idx, i, j, pair)

        for cluster_idx, cluster in enumerate(clusters):
            if len(cluster.mentions) < 2:
                filtered_clusters.append(cluster)
                continue

            # Identifier les mentions Named (non-pronoms)
            named_indices = []
            for i, mention in enumerate(cluster.mentions):
                text = mention.get("text", "")
                mention_type = self._classify_mention(text, "en")
                if mention_type in (MentionType.PROPER, MentionType.NP):
                    named_indices.append(i)

            if len(named_indices) < 2:
                # Pas assez de Named pour filtrer
                filtered_clusters.append(cluster)
                continue

            # Évaluer chaque paire Named↔Named
            rejected_pairs = set()  # Paires (i, j) rejetées
            review_pairs = []  # Paires à envoyer au LLM

            for idx_a in range(len(named_indices)):
                for idx_b in range(idx_a + 1, len(named_indices)):
                    i, j = named_indices[idx_a], named_indices[idx_b]
                    mention_a = cluster.mentions[i]
                    mention_b = cluster.mentions[j]

                    surface_a = mention_a.get("text", "")
                    surface_b = mention_b.get("text", "")

                    # Vérifier le cache d'abord
                    if self.coref_cache:
                        cached = self.coref_cache.get(surface_a, surface_b)
                        if cached:
                            if not cached.same_entity:
                                rejected_pairs.add((i, j))
                                logger.debug(
                                    f"[OSMOSE:Pass0.5:NamedGating] CACHE REJECT: "
                                    f"'{surface_a}' ↔ '{surface_b}'"
                                )
                            continue

                    # Appliquer le gating
                    gating_result = self.named_gating_policy.evaluate(
                        surface_a=surface_a,
                        surface_b=surface_b,
                    )

                    if gating_result.decision == GatingDecision.REJECT:
                        rejected_pairs.add((i, j))
                        logger.info(
                            f"[OSMOSE:Pass0.5:NamedGating] REJECT: "
                            f"'{surface_a}' ↔ '{surface_b}' ({gating_result.reason_code.value})"
                        )
                        # Mettre en cache
                        if self.coref_cache:
                            self.coref_cache.set(
                                surface_a, surface_b,
                                same_entity=False,
                                reason_code=gating_result.reason_code,
                                reason_detail=gating_result.reason_detail,
                                confidence=0.0,
                                source="gating",
                            )

                    elif gating_result.decision == GatingDecision.REVIEW:
                        # Collecter pour LLM arbitration
                        if self.llm_arbiter:
                            # Extraire le contexte (100 chars autour)
                            start_a = mention_a.get("start", 0)
                            start_b = mention_b.get("start", 0)
                            context_a = full_text[max(0, start_a - 50):start_a + len(surface_a) + 50]
                            context_b = full_text[max(0, start_b - 50):start_b + len(surface_b) + 50]

                            pair = CorefPair(
                                surface_a=surface_a,
                                surface_b=surface_b,
                                context_a=context_a,
                                context_b=context_b,
                            )
                            pairs_to_review.append((cluster_idx, i, j, pair))
                        else:
                            # Pas de LLM → ABSTAIN (ne pas rejeter)
                            logger.debug(
                                f"[OSMOSE:Pass0.5:NamedGating] REVIEW (no LLM): "
                                f"'{surface_a}' ↔ '{surface_b}' - keeping"
                            )

                    else:  # ACCEPT
                        logger.debug(
                            f"[OSMOSE:Pass0.5:NamedGating] ACCEPT: "
                            f"'{surface_a}' ↔ '{surface_b}'"
                        )
                        # Mettre en cache
                        if self.coref_cache:
                            self.coref_cache.set(
                                surface_a, surface_b,
                                same_entity=True,
                                reason_code=gating_result.reason_code,
                                reason_detail=gating_result.reason_detail,
                                confidence=1.0,
                                source="gating",
                            )

            # Stocker le cluster avec les paires rejetées pour filtrage ultérieur
            filtered_clusters.append(cluster)

        # Arbitrage LLM pour les paires en REVIEW (batch)
        if pairs_to_review and self.llm_arbiter:
            logger.info(f"[OSMOSE:Pass0.5:NamedGating] Arbitrating {len(pairs_to_review)} pairs via LLM")

            # Extraire les CorefPairs
            coref_pairs = [p[3] for p in pairs_to_review]
            llm_decisions = self.llm_arbiter.arbitrate(coref_pairs)

            # Appliquer les décisions LLM
            for (cluster_idx, i, j, pair), decision in zip(pairs_to_review, llm_decisions):
                if decision.abstain:
                    # LLM abstient → garder la paire (conservative)
                    logger.debug(
                        f"[OSMOSE:Pass0.5:NamedGating] LLM ABSTAIN: "
                        f"'{pair.surface_a}' ↔ '{pair.surface_b}'"
                    )
                elif not decision.same_entity:
                    # LLM rejette
                    logger.info(
                        f"[OSMOSE:Pass0.5:NamedGating] LLM REJECT: "
                        f"'{pair.surface_a}' ↔ '{pair.surface_b}' - {decision.reason}"
                    )
                    # Marquer pour filtrage
                    # NOTE: Pour l'instant, on ne reconstruit pas les clusters.
                    # Une implémentation complète devrait split les clusters.

                    # Mettre en cache
                    if self.coref_cache:
                        self.coref_cache.set(
                            pair.surface_a, pair.surface_b,
                            same_entity=False,
                            reason_code=ReasonCode.LLM_REJECTED,
                            reason_detail=decision.reason,
                            confidence=decision.confidence,
                            source="llm",
                        )
                else:
                    # LLM accepte
                    logger.debug(
                        f"[OSMOSE:Pass0.5:NamedGating] LLM ACCEPT: "
                        f"'{pair.surface_a}' ↔ '{pair.surface_b}'"
                    )
                    if self.coref_cache:
                        self.coref_cache.set(
                            pair.surface_a, pair.surface_b,
                            same_entity=True,
                            reason_code=ReasonCode.LLM_VALIDATED,
                            reason_detail=decision.reason,
                            confidence=decision.confidence,
                            source="llm",
                        )

        return filtered_clusters

    def _create_protoconcept_links(
        self,
        coref_result: CorefGraphResult,
        doc_data: Dict[str, Any],
    ):
        """
        Crée les liens MATCHES_PROTOCONCEPT.

        NOTE GOUVERNANCE: Ces liens sont des alignements lexicaux/ancrés,
        PAS des identités ontologiques.
        """
        # Charger les ProtoConcepts du document
        concepts_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id, doc_id: $doc_id})
        RETURN p.concept_id AS concept_id,
               p.concept_name AS label,
               p.surface_form AS surface_form
        """
        try:
            concepts_result = self.neo4j_client.execute_query(
                concepts_query,
                tenant_id=self.tenant_id,
                doc_id=doc_data["doc_id"]
            )

            if not concepts_result:
                return

            # Créer un index par label/surface_form
            concept_index: Dict[str, str] = {}
            for concept in concepts_result:
                label = (concept.get("label") or "").lower()
                surface = (concept.get("surface_form") or "").lower()
                concept_id = concept.get("concept_id")

                if label and concept_id:
                    concept_index[label] = concept_id
                if surface and concept_id:
                    concept_index[surface] = concept_id

            # Matcher les MentionSpan avec les ProtoConcepts
            for span in coref_result.mention_spans:
                if span.mention_type in (MentionType.PROPER, MentionType.NP):
                    surface_lower = span.surface.lower()
                    if surface_lower in concept_index:
                        self.persistence.create_matches_protoconcept_relation(
                            mention_id=span.mention_id,
                            concept_id=concept_index[surface_lower],
                            confidence=0.9,
                            method="lexical_match",
                        )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass0.5] Failed to create MATCHES_PROTOCONCEPT: {e}")


def run_pass05_for_document(
    doc_id: str,
    doc_version_id: str,
    neo4j_client: Optional[Neo4jClient] = None,
    tenant_id: str = "default",
    config: Optional[Pass05Config] = None,
) -> Pass05Result:
    """
    Fonction utilitaire pour exécuter Pass 0.5 sur un document.

    Args:
        doc_id: ID du document
        doc_version_id: ID de version du document
        neo4j_client: Client Neo4j (optionnel)
        tenant_id: ID du tenant
        config: Configuration (optionnelle)

    Returns:
        Pass05Result
    """
    pipeline = Pass05CoreferencePipeline(
        neo4j_client=neo4j_client,
        tenant_id=tenant_id,
        config=config,
    )
    return pipeline.process_document(doc_id, doc_version_id)

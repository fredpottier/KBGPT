"""
Coverage Map Service - OSMOSE Answer+Proof Bloc D

Genere la carte de couverture qui montre ce qui est couvert ET ce qui ne l'est pas.
C'est LA vraie differenciation vs RAG standard.

Regle fondamentale:
La taxonomie provient EXCLUSIVEMENT de DomainContextStore.
Aucun domaine hardcode dans le code.

Architecture matching v2 (robuste, agnostique):
- IDF-lite base sur les domaines du tenant (anti-faux-positifs)
- Seuil minimum 2 hits distincts
- Expansion acronymes depuis DomainContextStore
- Deduplication stable (pas de set() pour l'ordre UI)
"""

from __future__ import annotations

import math
import re
import asyncio
import unicodedata
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from knowbase.config.settings import Settings
from knowbase.common.logging import setup_logging
from .confidence_engine import EpistemicState

_settings = Settings()
logger = setup_logging(_settings.logs_dir, "coverage_map_service.log")


# =============================================================================
# UTILITAIRES MATCHING (agnostiques, stables, deterministes)
# =============================================================================

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def strip_accents(s: str) -> str:
    """
    Supprime les accents d'une chaine de maniere agnostique.

    Ex: "données" -> "donnees", "José" -> "Jose"
    Fonctionne pour toutes les langues avec diacritiques.
    """
    # NFD decompose les caractères accentués (é -> e + accent combinant)
    # On garde uniquement les caractères non-combinants
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"  # Mn = Mark, Nonspacing (accents)
    )


def normalize_text(s: str) -> str:
    """Normalise le texte de maniere stable et agnostique."""
    s = s.lower()
    s = strip_accents(s)  # Supprimer les accents AVANT la tokenisation
    s = s.replace("'", "'").replace("-", " ").replace("'", " ")
    return " ".join(_WORD_RE.findall(s))


def tokenize(s: str) -> List[str]:
    """Tokenise le texte. Garde tokens >= 3 chars (agnostique)."""
    toks = normalize_text(s).split()
    return [t for t in toks if len(t) >= 3]


def ordered_unique(items: List[str]) -> List[str]:
    """Deduplique en conservant l'ordre (pas de set())."""
    seen = OrderedDict()
    for x in items:
        if x not in seen:
            seen[x] = True
    return list(seen.keys())


def bigrams(tokens: List[str]) -> List[str]:
    """Genere les bigrammes consecutifs."""
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


def expand_acronyms_in_text(text: str, common_acronyms: Dict[str, str]) -> str:
    """
    Enrichit le texte avec les expansions d'acronymes.

    Agnostique: tout vient du DomainContextStore, aucun hardcode.
    """
    if not common_acronyms:
        return text

    expanded = text
    text_norm = normalize_text(text)

    for acr, full in common_acronyms.items():
        if not acr or not full:
            continue
        acr_norm = normalize_text(acr)
        if not acr_norm:
            continue
        # Match acronyme avec word boundary
        if re.search(rf"\b{re.escape(acr_norm)}\b", text_norm):
            expanded += " " + full

    return expanded


def build_token_df(sub_domains: List[str]) -> Tuple[int, Dict[str, int]]:
    """
    Construit la frequence documentaire (df) des tokens sur les domaines.

    Permet de penaliser les tokens trop communs (anti-faux-positifs agnostique).
    """
    N = len(sub_domains)
    df: Dict[str, int] = defaultdict(int)

    for d in sub_domains:
        # set() OK ici car interne, n'affecte pas l'ordre UI
        toks = set(tokenize(d))
        for t in toks:
            df[t] += 1

    return N, dict(df)


def token_weight(t: str, N: int, df: Dict[str, int]) -> float:
    """
    Calcule le poids IDF-lite d'un token.

    Tokens tres frequents dans les domaines = poids faible.
    """
    return math.log((N + 1) / (df.get(t, 0) + 1))


def domain_keywords(domain_name: str) -> Dict[str, List[str]]:
    """
    Genere les keywords pour un domaine (stable, deterministe).

    Returns:
        Dict avec "phrase", "tokens", "bigrams"
    """
    phrase = normalize_text(domain_name)
    toks = tokenize(domain_name)
    bgs = bigrams(toks)

    return {
        "phrase": [phrase] if phrase else [],
        "tokens": ordered_unique(toks),
        "bigrams": ordered_unique(bgs),
    }


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class DomainMatch:
    """Resultat de matching pour un domaine."""
    domain: str
    domain_id: str
    score: float
    hits: List[str]  # Termes matches (pour explainability)


@dataclass
class KnowledgeDomain:
    """Un domaine de connaissance (provient de DomainContextStore)."""
    domain_id: str
    name: str
    description: str = ""
    parent_domain: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    required_for_completeness: bool = False


@dataclass
class DomainCoverage:
    """Couverture d'un domaine specifique."""
    domain_id: str
    domain_name: str
    status: str                           # "covered", "partial", "debate", "not_covered"
    epistemic_state: EpistemicState = EpistemicState.INCOMPLETE
    relations_count: int = 0
    concepts_found: List[str] = field(default_factory=list)
    confidence: float = 0.0
    note: Optional[str] = None            # "Debat doctrinal", etc.
    match_hits: List[str] = field(default_factory=list)  # Pour explainability

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "domain": self.domain_name,
            "status": self.status,
            "epistemic_state": self.epistemic_state.value,
            "relations_count": self.relations_count,
            "concepts_found": self.concepts_found[:5],
            "confidence": self.confidence,
            "note": self.note,
            "match_hits": self.match_hits[:5],  # Explainability
        }


@dataclass
class CoverageMap:
    """Carte de couverture complete (Bloc D)."""
    domains: List[DomainCoverage] = field(default_factory=list)
    coverage_percent: Optional[float] = None
    covered_count: int = 0
    total_relevant: int = 0
    recommendations: List[str] = field(default_factory=list)
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domains": [d.to_dict() for d in self.domains],
            "coverage_percent": self.coverage_percent,
            "covered_count": self.covered_count,
            "total_relevant": self.total_relevant,
            "recommendations": self.recommendations,
            "message": self.message,
        }


# =============================================================================
# MATCHING ENGINE (robuste, agnostique)
# =============================================================================

def match_domains(
    question: str,
    sub_domains: List[str],
    common_acronyms: Dict[str, str],
    key_concepts: List[str],
    min_distinct_hits: int = 2,
    min_score: float = 1.2,
) -> List[DomainMatch]:
    """
    Matching robuste question -> domaines.

    Approche:
    1. Enrichir question avec expansions d'acronymes
    2. Calculer IDF-lite sur les tokens des domaines (anti-faux-positifs)
    3. Scorer chaque domaine (phrase, bigrams, tokens ponderes)
    4. Filtrer par seuils (min_distinct_hits, min_score)

    Agnostique: aucune liste stopwords, aucun dictionnaire metier hardcode.
    """
    if not sub_domains:
        return []

    # 1) Enrichir la question avec expansions d'acronymes
    q_expanded = expand_acronyms_in_text(question, common_acronyms or {})

    # 2) Query normalisee + tokens
    q_norm = normalize_text(q_expanded)
    q_tokens = tokenize(q_expanded)
    q_token_set = set(q_tokens)

    # 3) IDF-lite sur les domaines (anti-faux-positifs agnostique)
    N, df = build_token_df(sub_domains)

    # 4) Enrichir avec key_concepts si presents dans la question
    for kc in key_concepts or []:
        kc_norm = normalize_text(kc)
        if kc_norm and re.search(rf"\b{re.escape(kc_norm)}\b", q_norm):
            q_token_set.update(tokenize(kc_norm))

    results: List[DomainMatch] = []

    for d in sub_domains:
        kws = domain_keywords(d)

        hits: List[str] = []
        score = 0.0

        # Hit phrase complete (rare mais fort)
        for p in kws["phrase"]:
            if p and p in q_norm:
                hits.append(f"[phrase] {p}")
                score += 1.0

        # Hit bigrams (tres discriminant)
        for bg in kws["bigrams"]:
            if bg and bg in q_norm:
                hits.append(f"[bigram] {bg}")
                score += 0.8

        # Hit tokens ponderes (IDF-lite)
        for t in kws["tokens"]:
            if t in q_token_set:
                w = token_weight(t, N, df)
                # Cap pour eviter qu'un token rare suffise a tout
                score += min(0.6, w)
                hits.append(f"[token] {t}")

        # Dedup stable des hits
        hits = ordered_unique(hits)

        # Filtrer par seuils
        if len(hits) >= min_distinct_hits and score >= min_score:
            results.append(DomainMatch(
                domain=d,
                domain_id=d.lower().replace(" ", "_"),
                score=score,
                hits=hits,
            ))

    # Tri stable: score desc, puis ordre dans sub_domains
    domain_index = {d: i for i, d in enumerate(sub_domains)}
    results.sort(key=lambda r: (-r.score, domain_index.get(r.domain, 10**9)))

    return results


# =============================================================================
# SERVICE PRINCIPAL
# =============================================================================

class CoverageMapService:
    """Service pour construire le Coverage Map (Bloc D)."""

    def __init__(self, neo4j_driver=None):
        """Initialise le service."""
        self._neo4j_driver = neo4j_driver
        self._domain_context_store = None

    def _get_neo4j_driver(self):
        """Recupere le driver Neo4j (lazy loading)."""
        if self._neo4j_driver is None:
            try:
                from knowbase.semantic.clients.neo4j_client import get_neo4j_driver
                self._neo4j_driver = get_neo4j_driver()
            except Exception as e:
                logger.warning(f"Could not get Neo4j driver: {e}")
                return None
        return self._neo4j_driver

    def _get_domain_context_store(self):
        """Recupere le DomainContextStore (lazy loading)."""
        if self._domain_context_store is None:
            try:
                from knowbase.ontology.domain_context_store import get_domain_context_store
                self._domain_context_store = get_domain_context_store()
            except Exception as e:
                logger.warning(f"Could not get DomainContextStore: {e}")
                return None
        return self._domain_context_store

    async def build_coverage_map(
        self,
        query: str,
        query_concepts: List[str],
        kg_relations: List[Dict[str, Any]],
        tenant_id: str = "default",
    ) -> CoverageMap:
        """
        Construit la carte de couverture.

        Args:
            query: Question de l'utilisateur
            query_concepts: Concepts identifies dans la question
            kg_relations: Relations du graph_context
            tenant_id: Tenant ID

        Returns:
            CoverageMap
        """
        # 1. Charger le profil complet depuis DomainContextStore
        store = self._get_domain_context_store()
        if not store:
            return CoverageMap(
                domains=[],
                coverage_percent=None,
                message="DomainContextStore non disponible.",
            )

        profile = store.get_profile(tenant_id)
        if not profile or not profile.sub_domains:
            return CoverageMap(
                domains=[],
                coverage_percent=None,
                message="DomainContext non configure pour ce tenant.",
            )

        sub_domains = profile.sub_domains
        common_acronyms = profile.common_acronyms or {}
        key_concepts = profile.key_concepts or []

        # 2. Matcher les domaines avec le nouveau matching robuste
        matches = match_domains(
            question=query,
            sub_domains=sub_domains,
            common_acronyms=common_acronyms,
            key_concepts=key_concepts,
            min_distinct_hits=2,
            min_score=1.2,
        )

        # 3. Construire la liste des domaines avec couverture
        matched_domain_ids = {m.domain_id for m in matches}
        match_by_id = {m.domain_id: m for m in matches}

        coverages = []
        for sub_domain in sub_domains:
            domain_id = sub_domain.lower().replace(" ", "_")

            if domain_id in matched_domain_ids:
                # Domaine matche -> analyser couverture KG
                match = match_by_id[domain_id]
                coverage = await self._analyze_domain_coverage(
                    domain_id=domain_id,
                    domain_name=sub_domain,
                    match_hits=match.hits,
                    query_concepts=query_concepts,
                    kg_relations=kg_relations,
                    tenant_id=tenant_id,
                )
            else:
                # Domaine non matche
                coverage = DomainCoverage(
                    domain_id=domain_id,
                    domain_name=sub_domain,
                    status="not_covered",
                    epistemic_state=EpistemicState.INCOMPLETE,
                    match_hits=[],
                )

            coverages.append(coverage)

        # 4. Calculer les stats
        covered = [c for c in coverages if c.status in ["covered", "partial"]]
        coverage_percent = (len(covered) / len(coverages) * 100) if coverages else 0

        # 5. Generer les recommandations (domaines non couverts)
        recommendations = [
            c.domain_name for c in coverages
            if c.status == "not_covered"
        ][:5]

        return CoverageMap(
            domains=coverages,
            coverage_percent=round(coverage_percent, 1),
            covered_count=len(covered),
            total_relevant=len(coverages),
            recommendations=recommendations,
        )

    async def _analyze_domain_coverage(
        self,
        domain_id: str,
        domain_name: str,
        match_hits: List[str],
        query_concepts: List[str],
        kg_relations: List[Dict[str, Any]],
        tenant_id: str,
    ) -> DomainCoverage:
        """
        Analyse la couverture d'un domaine matche.
        """
        # Tenter Neo4j d'abord
        neo4j_result = await self._query_domain_coverage_neo4j(
            domain_id, domain_name, match_hits, tenant_id
        )

        if neo4j_result:
            return neo4j_result

        # Fallback: analyser depuis kg_relations
        return self._analyze_from_relations(
            domain_id, domain_name, match_hits, kg_relations
        )

    async def _query_domain_coverage_neo4j(
        self,
        domain_id: str,
        domain_name: str,
        match_hits: List[str],
        tenant_id: str,
    ) -> Optional[DomainCoverage]:
        """
        Interroge Neo4j pour la couverture d'un domaine.
        """
        driver = self._get_neo4j_driver()
        if not driver:
            return None

        # Extraire les tokens des hits pour la requete Neo4j
        search_terms = []
        for hit in match_hits:
            # Enlever le prefixe [phrase], [bigram], [token]
            term = re.sub(r"^\[(phrase|bigram|token)\]\s*", "", hit)
            if term:
                search_terms.append(term)

        if not search_terms:
            search_terms = tokenize(domain_name)

        if not search_terms:
            return None

        try:
            cypher = """
            MATCH (c:CanonicalConcept {tenant_id: $tid})
            WHERE any(term IN $terms WHERE toLower(c.canonical_name) CONTAINS toLower(term))
            OPTIONAL MATCH (c)-[r]-(other:CanonicalConcept {tenant_id: $tid})
            WHERE type(r) <> 'ASSOCIATED_WITH'

            WITH
                collect(DISTINCT c.canonical_name) AS concepts,
                count(DISTINCT r) AS relations_count,
                avg(r.confidence) AS avg_confidence,
                sum(CASE WHEN type(r) = 'CONFLICTS_WITH' THEN 1 ELSE 0 END) AS conflicts

            RETURN
                concepts,
                relations_count,
                avg_confidence,
                conflicts
            """

            with driver.session() as session:
                result = session.run(cypher, {
                    "tid": tenant_id,
                    "terms": search_terms,
                })
                record = result.single()

                if not record:
                    return DomainCoverage(
                        domain_id=domain_id,
                        domain_name=domain_name,
                        status="partial",
                        epistemic_state=EpistemicState.PARTIAL,
                        relations_count=0,
                        concepts_found=[],
                        confidence=0.0,
                        match_hits=match_hits,
                    )

                concepts = record.get("concepts", []) or []
                relations_count = record.get("relations_count", 0) or 0
                avg_confidence = record.get("avg_confidence", 0.0) or 0.0
                conflicts = record.get("conflicts", 0) or 0

                status, epistemic_state, note = self._determine_status(
                    relations_count, avg_confidence, conflicts
                )

                return DomainCoverage(
                    domain_id=domain_id,
                    domain_name=domain_name,
                    status=status,
                    epistemic_state=epistemic_state,
                    relations_count=relations_count,
                    concepts_found=concepts[:5],
                    confidence=avg_confidence,
                    note=note,
                    match_hits=match_hits,
                )

        except Exception as e:
            logger.warning(f"Neo4j domain coverage query failed: {e}")
            return None

    def _analyze_from_relations(
        self,
        domain_id: str,
        domain_name: str,
        match_hits: List[str],
        kg_relations: List[Dict[str, Any]],
    ) -> DomainCoverage:
        """
        Analyse la couverture depuis les relations du graph_context.

        Fallback quand Neo4j n'est pas disponible.
        """
        if not kg_relations:
            return DomainCoverage(
                domain_id=domain_id,
                domain_name=domain_name,
                status="partial",
                epistemic_state=EpistemicState.PARTIAL,
                match_hits=match_hits,
            )

        # Extraire les termes des hits
        search_terms = []
        for hit in match_hits:
            term = re.sub(r"^\[(phrase|bigram|token)\]\s*", "", hit)
            if term:
                search_terms.append(term.lower())

        if not search_terms:
            search_terms = [t.lower() for t in tokenize(domain_name)]

        # Chercher les relations qui matchent
        matching_concepts = []
        matching_relations = 0
        confidences = []
        conflicts = 0

        for rel in kg_relations:
            source = (rel.get("source", "") or "").lower()
            target = (rel.get("concept", "") or "").lower()
            rel_type = rel.get("relation", "")

            matched = any(term in source or term in target for term in search_terms)

            if matched:
                matching_relations += 1
                if rel.get("source"):
                    matching_concepts.append(rel["source"])
                if rel.get("concept"):
                    matching_concepts.append(rel["concept"])
                if rel.get("confidence"):
                    confidences.append(rel["confidence"])
                if rel_type == "CONFLICTS_WITH":
                    conflicts += 1

        # Dedup stable des concepts
        matching_concepts = ordered_unique(matching_concepts)

        if matching_relations == 0:
            return DomainCoverage(
                domain_id=domain_id,
                domain_name=domain_name,
                status="partial",
                epistemic_state=EpistemicState.PARTIAL,
                match_hits=match_hits,
            )

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        status, epistemic_state, note = self._determine_status(
            matching_relations, avg_conf, conflicts
        )

        return DomainCoverage(
            domain_id=domain_id,
            domain_name=domain_name,
            status=status,
            epistemic_state=epistemic_state,
            relations_count=matching_relations,
            concepts_found=matching_concepts[:5],
            confidence=avg_conf,
            note=note,
            match_hits=match_hits,
        )

    def _determine_status(
        self,
        relations_count: int,
        avg_confidence: float,
        conflicts: int,
    ) -> Tuple[str, EpistemicState, Optional[str]]:
        """
        Determine le statut de couverture d'un domaine.

        Returns:
            (status, epistemic_state, note)
        """
        # Conflit detecte
        if conflicts > 0:
            return "debate", EpistemicState.DEBATE, f"{conflicts} contradiction(s) detectee(s)"

        # Bien couvert
        if relations_count >= 3 and avg_confidence >= 0.7:
            return "covered", EpistemicState.ESTABLISHED, None

        # Partiellement couvert
        if relations_count >= 1:
            return "partial", EpistemicState.PARTIAL, None

        # Considere comme partial si matche (on a passe les seuils de matching)
        return "partial", EpistemicState.PARTIAL, None


# =============================================================================
# WRAPPER SYNCHRONE
# =============================================================================

def build_coverage_map_sync(
    query: str,
    query_concepts: List[str],
    kg_relations: List[Dict[str, Any]],
    tenant_id: str = "default",
) -> CoverageMap:
    """
    Version synchrone de build_coverage_map.

    Utilisee pour l'integration dans search.py (synchrone).
    """
    service = get_coverage_map_service()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            service.build_coverage_map(
                query=query,
                query_concepts=query_concepts,
                kg_relations=kg_relations,
                tenant_id=tenant_id,
            )
        )
    finally:
        loop.close()


# =============================================================================
# SINGLETON
# =============================================================================

_coverage_map_service: Optional[CoverageMapService] = None


def get_coverage_map_service() -> CoverageMapService:
    """Retourne l'instance singleton du CoverageMapService."""
    global _coverage_map_service
    if _coverage_map_service is None:
        _coverage_map_service = CoverageMapService()
    return _coverage_map_service


__all__ = [
    "KnowledgeDomain",
    "DomainMatch",
    "DomainCoverage",
    "CoverageMap",
    "CoverageMapService",
    "get_coverage_map_service",
    "build_coverage_map_sync",
    "match_domains",
]

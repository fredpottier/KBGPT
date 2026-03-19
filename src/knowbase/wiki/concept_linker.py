"""
ConceptLinker — Linking batch inter-concepts pour le Knowledge Atlas.

3 briques :
1. ConceptRegistryBuilder : construit le registre global depuis Neo4j
2. ConceptCandidateSelector : pré-sélection déterministe des candidats par article
3. ConceptLinker : appelle le LLM pour injecter les liens contextuels

Le LLM ne reçoit jamais tout le registre — uniquement un sous-ensemble pertinent (~30-50 max).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import yaml

logger = logging.getLogger("[OSMOSE] concept_linker")

# ── Mots trop génériques pour être des alias safe ─────────────────────────

WEAK_WORDS = {
    "article", "age", "model", "personnel", "measures", "risks", "testing",
    "controls", "attacks", "provider", "macros", "parties", "processing",
    "standards", "services", "management", "systems", "security", "protection",
    "compliance", "assessment", "information", "data", "access", "rights",
    "obligations", "framework", "policy", "audit", "governance", "platform",
    "private", "gateway", "cloud", "public", "general", "common",
}


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class ConceptEntry:
    """Un concept du registre avec ses alias classés safe/weak."""
    title: str
    slug: str
    entity_type: str
    safe_aliases: List[str] = field(default_factory=list)
    weak_aliases: List[str] = field(default_factory=list)


@dataclass
class LinkingResult:
    """Résultat du linking d'un article."""
    slug: str
    linked_markdown: str
    outgoing_links: List[str] = field(default_factory=list)
    link_count: int = 0
    unresolved_mentions: List[str] = field(default_factory=list)
    ambiguous_mentions: List[str] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


@dataclass
class BatchLinkingResult:
    """Résultat global du linking batch."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    results: List[LinkingResult] = field(default_factory=list)


# ── Brique 1 : ConceptRegistryBuilder ────────────────────────────────────


class ConceptRegistryBuilder:
    """Construit le registre global des concepts depuis Neo4j."""

    @staticmethod
    def _classify_alias(alias: str) -> str:
        """Classifie un alias en 'safe' ou 'weak'."""
        stripped = alias.strip()
        if len(stripped) < 3:
            return "weak"
        # Termes composés (>= 2 mots) → safe
        if " " in stripped or "-" in stripped or "/" in stripped:
            return "safe"
        # Acronymes (>= 2 chars majuscules) → safe
        if re.match(r"^[A-Z]{2,}$", stripped):
            return "safe"
        # Mots simples dans la liste noire → weak
        if stripped.lower() in WEAK_WORDS:
            return "weak"
        # Mots simples >= 6 chars et pas dans WEAK_WORDS → safe
        if len(stripped) >= 6:
            return "safe"
        # Reste → weak
        return "weak"

    @staticmethod
    def build_from_neo4j(neo4j_driver, tenant_id: str) -> List[ConceptEntry]:
        """
        Construit le registre des concepts depuis Neo4j.

        Requête les WikiArticle avec leurs Entity liées pour récupérer les aliases.
        Classifie chaque alias en safe ou weak.
        """
        query = """
        MATCH (wa:WikiArticle {tenant_id: $tid, status: 'published'})
        OPTIONAL MATCH (wa)-[:ABOUT]->(e:Entity)
        RETURN wa.slug AS slug, wa.title AS title, wa.entity_type AS entity_type,
               collect(e.aliases) AS entity_aliases
        """

        registry: List[ConceptEntry] = []

        with neo4j_driver.session() as session:
            result = session.run(query, tid=tenant_id)
            for record in result:
                slug = record["slug"]
                title = record["title"]
                entity_type = record["entity_type"] or "concept"
                raw_aliases = record["entity_aliases"] or []

                # Flatten (collect retourne liste de listes potentiellement)
                flat_aliases: List[str] = []
                for item in raw_aliases:
                    if isinstance(item, list):
                        flat_aliases.extend(item)
                    elif isinstance(item, str):
                        # Les aliases sont parfois stockés en JSON string
                        try:
                            parsed = json.loads(item)
                            if isinstance(parsed, list):
                                flat_aliases.extend(parsed)
                            else:
                                flat_aliases.append(item)
                        except (json.JSONDecodeError, TypeError):
                            flat_aliases.append(item)
                    elif item is not None:
                        flat_aliases.append(str(item))

                # Strip + dedup case-insensitive
                seen_lower: set[str] = set()
                unique_aliases: List[str] = []
                title_lower = title.lower() if title else ""

                for alias in flat_aliases:
                    cleaned = alias.strip()
                    if not cleaned or len(cleaned) < 3:
                        continue
                    lower = cleaned.lower()
                    # Supprimer le canonical title
                    if lower == title_lower:
                        continue
                    if lower not in seen_lower:
                        seen_lower.add(lower)
                        unique_aliases.append(cleaned)

                # Classer safe vs weak
                safe_aliases: List[str] = []
                weak_aliases: List[str] = []
                for alias in unique_aliases:
                    classification = ConceptRegistryBuilder._classify_alias(alias)
                    if classification == "safe":
                        safe_aliases.append(alias)
                    else:
                        weak_aliases.append(alias)

                registry.append(ConceptEntry(
                    title=title,
                    slug=slug,
                    entity_type=entity_type,
                    safe_aliases=safe_aliases,
                    weak_aliases=weak_aliases,
                ))

        logger.info(
            f"[OSMOSE:ConceptLinker] Registre construit : {len(registry)} concepts, "
            f"{sum(len(c.safe_aliases) for c in registry)} safe aliases"
        )
        return registry


# ── Brique 2 : ConceptCandidateSelector ──────────────────────────────────


class ConceptCandidateSelector:
    """Pré-sélection déterministe des concepts candidats pour un article."""

    def select_candidates(
        self,
        article_text: str,
        registry: List[ConceptEntry],
        exclude_slug: str,
        max_candidates: int = 50,
    ) -> List[ConceptEntry]:
        """
        Sélectionne les concepts candidats pour un article donné.

        Pipeline :
        1. Exclure l'article courant
        2. Match exact du title (case-insensitive)
        3. Match exact des safe_aliases
        4. NE PAS matcher les weak_aliases
        5. Trier par spécificité (longueur du match décroissante)
        6. Limiter à max_candidates
        """
        text_lower = article_text.lower()
        matches: List[tuple[ConceptEntry, int]] = []  # (entry, longest_match_len)

        for entry in registry:
            if entry.slug == exclude_slug:
                continue

            best_match_len = 0

            # Match title
            if entry.title and entry.title.lower() in text_lower:
                best_match_len = max(best_match_len, len(entry.title))

            # Match safe_aliases
            for alias in entry.safe_aliases:
                if alias.lower() in text_lower:
                    best_match_len = max(best_match_len, len(alias))

            if best_match_len > 0:
                matches.append((entry, best_match_len))

        # Trier par spécificité (longueur du match décroissante)
        matches.sort(key=lambda x: x[1], reverse=True)

        candidates = [entry for entry, _ in matches[:max_candidates]]

        logger.debug(
            f"[OSMOSE:ConceptLinker] Article '{exclude_slug}' : "
            f"{len(candidates)} candidats sélectionnés sur {len(registry)} concepts"
        )
        return candidates


# ── Brique 3 : ConceptLinker ─────────────────────────────────────────────


class ConceptLinker:
    """Appelle le LLM pour injecter les liens contextuels dans les articles."""

    def __init__(self, neo4j_driver, tenant_id: str = "default"):
        self._driver = neo4j_driver
        self._tenant_id = tenant_id
        self._registry_builder = ConceptRegistryBuilder()
        self._candidate_selector = ConceptCandidateSelector()

    def _format_concept_list(self, candidates: List[ConceptEntry]) -> str:
        """Formate la liste des concepts candidats pour le prompt LLM."""
        lines = []
        for c in candidates:
            aliases_str = ""
            if c.safe_aliases:
                aliases_str = f" (aliases: {', '.join(c.safe_aliases[:5])})"
            lines.append(f"- {c.title} → /wiki/{c.slug}{aliases_str}")
        return "\n".join(lines)

    def _load_prompt(self) -> dict:
        """Charge le prompt wiki.linking depuis prompts.yaml."""
        from pathlib import Path
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "prompts.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f)
        return prompts.get("wiki_linking", {})

    async def link_article(
        self,
        slug: str,
        markdown: str,
        candidates: List[ConceptEntry],
    ) -> LinkingResult:
        """Appelle le LLM pour injecter les liens contextuels dans un article."""
        if not candidates:
            return LinkingResult(
                slug=slug,
                linked_markdown=markdown,
                link_count=0,
                success=True,
            )

        concept_list = self._format_concept_list(candidates)
        prompt_config = self._load_prompt()

        system_prompt = prompt_config.get("system", "")
        template = prompt_config.get("template", "")
        user_prompt = template.replace("{concept_list}", concept_list).replace("{markdown}", markdown)

        try:
            from knowbase.common.llm_router import TaskType, get_llm_router

            router = get_llm_router()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            response = router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
            )

            linked_markdown = response.strip()

            # Garde-fou : si le LLM a tronqué le markdown (perte > 20%), on
            # reporte les liens trouvés sur le markdown original au lieu
            # d'utiliser la sortie tronquée du LLM.
            if len(linked_markdown) < len(markdown) * 0.80:
                logger.warning(
                    f"[OSMOSE:ConceptLinker] linked_markdown tronqué "
                    f"({len(linked_markdown)} vs {len(markdown)} chars) — "
                    f"application des liens sur le markdown original"
                )
                linked_markdown = self._transplant_links(markdown, linked_markdown)

            # Extraire les liens effectivement insérés
            link_pattern = re.compile(r'\[([^\]]+)\]\(/wiki/([^)]+)\)')
            found_links = link_pattern.findall(linked_markdown)
            outgoing_slugs = list(dict.fromkeys(slug for _, slug in found_links))

            # Calculer les candidats non liés
            candidate_slugs = {c.slug for c in candidates}
            linked_slugs = set(outgoing_slugs)
            unresolved = [c.title for c in candidates if c.slug not in linked_slugs]

            return LinkingResult(
                slug=slug,
                linked_markdown=linked_markdown,
                outgoing_links=outgoing_slugs,
                link_count=len(found_links),
                unresolved_mentions=unresolved[:20],
                success=True,
            )

        except Exception as e:
            # Propager VLLMUnavailableError
            from knowbase.common.llm_router import VLLMUnavailableError
            if isinstance(e, VLLMUnavailableError):
                raise
            logger.error(
                f"[OSMOSE:ConceptLinker] Erreur linking article '{slug}': {e}",
                exc_info=True,
            )
            return LinkingResult(
                slug=slug,
                linked_markdown=markdown,
                success=False,
                error=str(e),
            )

    @staticmethod
    def _transplant_links(original_md: str, linked_md: str) -> str:
        """Transplante les liens wiki trouvés dans linked_md vers original_md.

        Quand le LLM tronque le markdown, on récupère les liens qu'il a insérés
        et on les applique sur le markdown original par remplacement textuel.
        """
        link_pattern = re.compile(r'\[([^\]]+)\]\(/wiki/([^)]+)\)')
        links = link_pattern.findall(linked_md)

        result = original_md
        for display_text, slug in links:
            # Remplacer la première occurrence du texte brut par le lien
            # (seulement si le texte n'est pas déjà un lien)
            plain = display_text
            linked = f"[{display_text}](/wiki/{slug})"
            if linked not in result and plain in result:
                result = result.replace(plain, linked, 1)

        return result

    def _link_and_persist_one(
        self,
        slug: str,
        markdown: str,
        registry: List[ConceptEntry],
        persister,
    ) -> Optional[LinkingResult]:
        """
        Linke un article et persiste le résultat. Méthode synchrone interne.
        Retourne le LinkingResult ou None en cas d'erreur.
        """
        import asyncio

        candidates = self._candidate_selector.select_candidates(
            markdown, registry, slug
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.link_article(slug, markdown, candidates)
            )
        finally:
            loop.close()

        if result.success:
            persister.update_linked_markdown(
                slug=slug,
                tenant_id=self._tenant_id,
                linked_markdown=result.linked_markdown,
                outgoing_links=result.outgoing_links,
                linking_metadata={
                    "registry_size": len(registry),
                    "candidates_count": len(candidates),
                    "unresolved_mentions": result.unresolved_mentions,
                    "ambiguous_mentions": result.ambiguous_mentions,
                },
            )
            logger.info(
                f"[OSMOSE:ConceptLinker] '{slug}' linké : "
                f"{result.link_count} liens, {len(candidates)} candidats"
            )
        return result

    def link_incrementally(self, new_slug: str) -> Dict[str, Any]:
        """
        Linking incrémental V2 : appelé après génération d'un nouvel article.

        1. Construit le registre (inclut le nouvel article)
        2. Linke le nouvel article lui-même
        3. Trouve les articles existants qui mentionnent le nouveau concept
           (titre ou safe_aliases) dans leur markdown
        4. Re-linke ces articles impactés

        Retourne un résumé { new_article: LinkingResult, impacted: [...] }
        """
        from knowbase.wiki.persistence import WikiArticlePersister

        persister = WikiArticlePersister(self._driver)
        registry = ConceptRegistryBuilder.build_from_neo4j(self._driver, self._tenant_id)

        if not registry:
            logger.warning("[OSMOSE:ConceptLinker:V2] Registre vide — skip linking incrémental")
            return {"new_article": None, "impacted": []}

        # Récupérer le nouvel article
        new_article = persister.get_by_slug(new_slug, self._tenant_id)
        if not new_article or not new_article.get("markdown"):
            logger.warning(f"[OSMOSE:ConceptLinker:V2] Article '{new_slug}' introuvable — skip")
            return {"new_article": None, "impacted": []}

        # Trouver l'entry du nouveau concept dans le registre
        new_entry = next((e for e in registry if e.slug == new_slug), None)

        # 1. Linker le nouvel article
        new_result = self._link_and_persist_one(
            new_slug, new_article["markdown"], registry, persister
        )

        # 2. Trouver les articles existants qui mentionnent le nouveau concept
        impacted_results: List[LinkingResult] = []

        if new_entry:
            # Termes à chercher : titre + safe_aliases
            search_terms = [new_entry.title.lower()]
            search_terms.extend(a.lower() for a in new_entry.safe_aliases)

            # Parcourir les articles existants (déjà linkés)
            articles_data = persister.list_articles(self._tenant_id, limit=5000)
            for a in articles_data.get("articles", []):
                slug = a.get("slug", "")
                if not slug or slug == new_slug:
                    continue

                full = persister.get_by_slug(slug, self._tenant_id)
                if not full or not full.get("markdown"):
                    continue

                # Vérifier si le markdown mentionne le nouveau concept
                md_lower = full["markdown"].lower()
                mentioned = any(term in md_lower for term in search_terms if term)

                if not mentioned:
                    continue

                # Cet article mentionne le nouveau concept → re-linker
                logger.info(
                    f"[OSMOSE:ConceptLinker:V2] Article '{slug}' mentionne "
                    f"'{new_entry.title}' → re-linking"
                )
                try:
                    result = self._link_and_persist_one(
                        slug, full["markdown"], registry, persister
                    )
                    if result:
                        impacted_results.append(result)
                except Exception as e:
                    logger.warning(
                        f"[OSMOSE:ConceptLinker:V2] Erreur re-linking '{slug}': {e}"
                    )

        total_impacted = len(impacted_results)
        logger.info(
            f"[OSMOSE:ConceptLinker:V2] Linking incrémental pour '{new_slug}' : "
            f"1 nouveau + {total_impacted} articles impactés re-linkés"
        )

        return {
            "new_article": new_result,
            "impacted": impacted_results,
        }

    async def batch_link_all(
        self,
        max_concurrent: int = 3,
        force: bool = False,
        callback: Optional[Callable[[str, str, int], None]] = None,
    ) -> BatchLinkingResult:
        """
        Lie tous les articles avec parallélisme borné.

        Args:
            max_concurrent: nombre max de requêtes LLM simultanées
            force: re-linker même les articles déjà linkés
            callback: fn(slug, status, link_count) appelée après chaque article
        """
        from knowbase.wiki.persistence import WikiArticlePersister

        persister = WikiArticlePersister(self._driver)
        registry = ConceptRegistryBuilder.build_from_neo4j(self._driver, self._tenant_id)

        if not registry:
            logger.warning("[OSMOSE:ConceptLinker] Registre vide — rien à linker")
            return BatchLinkingResult()

        # Récupérer tous les articles
        articles_data = persister.list_articles(self._tenant_id, limit=5000)
        all_articles = articles_data.get("articles", [])

        # Filtrer : si pas force, exclure ceux déjà linkés
        slugs_to_link = []
        for a in all_articles:
            slug = a.get("slug", "")
            if not slug:
                continue
            if not force:
                full = persister.get_by_slug(slug, self._tenant_id)
                if full and full.get("linked_markdown"):
                    continue
            slugs_to_link.append(slug)

        if not slugs_to_link:
            logger.info("[OSMOSE:ConceptLinker] Tous les articles sont déjà linkés")
            return BatchLinkingResult()

        batch_result = BatchLinkingResult(total=len(slugs_to_link))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _link_one(slug: str) -> None:
            from knowbase.common.llm_router import VLLMUnavailableError

            async with semaphore:
                article = persister.get_by_slug(slug, self._tenant_id)
                if not article or not article.get("markdown"):
                    batch_result.skipped += 1
                    if callback:
                        callback(slug, "skipped", 0)
                    return

                markdown = article["markdown"]
                candidates = self._candidate_selector.select_candidates(
                    markdown, registry, slug
                )

                try:
                    result = await self.link_article(slug, markdown, candidates)
                except VLLMUnavailableError:
                    raise

                if result.success:
                    # Persister le résultat
                    persister.update_linked_markdown(
                        slug=slug,
                        tenant_id=self._tenant_id,
                        linked_markdown=result.linked_markdown,
                        outgoing_links=result.outgoing_links,
                        linking_metadata={
                            "registry_size": len(registry),
                            "candidates_count": len(candidates),
                            "unresolved_mentions": result.unresolved_mentions,
                            "ambiguous_mentions": result.ambiguous_mentions,
                        },
                    )
                    batch_result.completed += 1
                    batch_result.results.append(result)
                    if callback:
                        callback(slug, "completed", result.link_count)

                    logger.info(
                        f"[OSMOSE:ConceptLinker] '{slug}' linké : "
                        f"{result.link_count} liens, {len(candidates)} candidats"
                    )
                else:
                    batch_result.failed += 1
                    batch_result.results.append(result)
                    if callback:
                        callback(slug, "failed", 0)

        # Exécuter avec parallélisme borné
        from knowbase.common.llm_router import VLLMUnavailableError

        for slug in slugs_to_link:
            try:
                await _link_one(slug)
            except VLLMUnavailableError:
                logger.error(
                    "[OSMOSE:ConceptLinker] vLLM DOWN — batch linking suspendu"
                )
                raise

        logger.info(
            f"[OSMOSE:ConceptLinker] Batch terminé : "
            f"{batch_result.completed} OK, {batch_result.failed} échecs, "
            f"{batch_result.skipped} ignorés sur {batch_result.total}"
        )
        return batch_result

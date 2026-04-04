from __future__ import annotations

import os
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING

import yaml

from knowbase.common.llm_router import TaskType, get_llm_router

if TYPE_CHECKING:
    from .search import ContradictionEnvelope

logger = logging.getLogger(__name__)

# ── Chargement des prompts externalises ────────────────────────────────

_synthesis_prompts_cache = None

def _load_synthesis_prompts() -> dict:
    """Charge les prompts de synthese depuis config/synthesis_prompts.yaml."""
    global _synthesis_prompts_cache
    if _synthesis_prompts_cache is not None:
        return _synthesis_prompts_cache

    config_paths = [
        Path("/app/config/synthesis_prompts.yaml"),
        Path(__file__).parent.parent.parent.parent / "config" / "synthesis_prompts.yaml",
    ]
    for p in config_paths:
        if p.exists():
            _synthesis_prompts_cache = yaml.safe_load(p.read_text(encoding="utf-8"))
            logger.info(f"[SYNTHESIS] Loaded prompts from {p}")
            return _synthesis_prompts_cache

    logger.warning("[SYNTHESIS] No synthesis_prompts.yaml found, using hardcoded defaults")
    _synthesis_prompts_cache = {}
    return _synthesis_prompts_cache


def _load_mode_prompt(mode: str) -> str | None:
    """Charge le prompt specialise pour un mode de reponse (V3 architecture).

    Retourne None si le mode n'est pas dans le YAML (fallback vers prompt existant).
    """
    prompts = _load_synthesis_prompts()
    modes = prompts.get("response_modes", {})
    return modes.get(mode)


def get_rule_7_for_provider(provider: str = "") -> str:
    """Retourne la regle 7 adaptee au provider de synthese actif."""
    if not provider:
        provider = os.environ.get("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")

    prompts = _load_synthesis_prompts()
    provider_config = prompts.get(provider, prompts.get("default", {}))

    # Provider-specific rule_7 override
    override = provider_config.get("rule_7_override")
    if override:
        return override.strip()

    # Default rule_7
    default_rules = prompts.get("default", {}).get("rules", "")
    if default_rules:
        # Extract rule 7 from default rules
        for line in default_rules.split("\n\n"):
            if line.strip().startswith("7."):
                return line.strip()

    return ""


SYNTHESIS_PROMPT = """You are a precise document analysis assistant that synthesizes information from provided sources.
{session_context}
## User question
{question}

## Available sources
{chunks_content}
{graph_context}

## Response rules

0. **Source priority (CRITICAL)**: The "Available sources" section above is your PRIMARY evidence. Read it FIRST. Any "Reading instructions" section below provides diagnostic guidance from knowledge graph analysis — use it to ADJUST your answer, not to replace your source-based reasoning.

1. **Synthesize** information from sources to answer clearly and in a structured manner.

2. **Cross-document reasoning**: If a "Cross-document reasoning" section is provided, it contains supplementary fact chains linking multiple documents. Use these chains ONLY if they are directly relevant to the user's question. If they are relevant:
   - Weave them naturally into your source-based answer
   - Explain the chain: "A relies on B (source 1), which itself builds on C (source 2)"
   - If the chains are NOT relevant to the question, IGNORE them entirely — do NOT force irrelevant cross-document links into your answer

3. **Conversational context**: If previous conversation context is provided, use it to resolve implicit references and maintain discussion continuity.

4. **Mandatory citations**: For each important piece of information, cite it as:
   - Simple format: *(Source: Document ABC, slide 12)*
   - Multiple slides: *(Source: Document ABC, slides 12-15)*
   - Multiple documents: indicate document name for each citation

5. **Never** use "Block #X", "Extract X", "Unknown document" or "Unknown source" — cite ONLY documents whose name is explicitly provided in sources.

6. **Structure** your response with sections or bullet points when appropriate.

{rule_7}

8. If information is **contradictory**, present BOTH versions with their sources explicitly.

9. **Cross-document comparisons**: If a "Cross-document comparisons" section is provided, it contains automatically detected comparable facts across documents. Include this information ONLY when directly relevant to the question:
   - For **EVOLUTION**: explain what changed, between which documents
   - For **CONTRADICTION**: flag the divergence with precise sources
   - For **AGREEMENT**: mention cross-doc confirmation briefly
   - If these comparisons are NOT related to the user's question, IGNORE them

10. **Visual content interpretation (IMPORTANT)**: Source texts between "═══ VISUAL CONTENT" and "═══ END VISUAL CONTENT" markers are **AI-generated interpretations of diagrams and visual elements**, NOT author text. When your answer uses visual content:
   - **Always use hedging language**: "The diagram appears to show...", "Based on visual interpretation of the slide..."
   - **Never present it as a documented fact** — it is a machine reading of a visual, not a verbatim statement
   - **Prefer author text** (bullets, speaker notes) over visual interpretation when both cover the same topic
   - **Cite the source slide** so the reader can verify the visual themselves

11. Answer in the **SAME LANGUAGE as the question**.

12. **Premise verification**: If the question contains an assumption or claim that CONTRADICTS what the sources say, you MUST point this out explicitly before answering. Start with "Contrary to what the question suggests, the sources indicate that..." then provide the correct information. Do NOT silently accept a false premise.

Answer:"""


import math


def _compute_logprob_entropy(response) -> float:
    """Calcule l'entropie moyenne des top logprobs de la reponse.

    Haute entropie = le modele est incertain = probable hallucination.
    Basse entropie = le modele est confiant = reponse probablement fondee.

    Ref: HALT (arXiv 2602.02888), EPR (arXiv 2509.04492)
    """
    try:
        logprobs_content = response.choices[0].logprobs
        if not logprobs_content or not logprobs_content.content:
            return 0.0

        entropies = []
        for token_info in logprobs_content.content:
            top = token_info.top_logprobs
            if not top or len(top) < 2:
                continue

            # Convertir logprobs en probabilites et calculer l'entropie
            probs = [math.exp(t.logprob) for t in top]
            total = sum(probs)
            if total <= 0:
                continue
            probs = [p / total for p in probs]  # normaliser

            entropy = -sum(p * math.log(p + 1e-10) for p in probs if p > 0)
            entropies.append(entropy)

        if not entropies:
            return 0.0

        return sum(entropies) / len(entropies)

    except Exception:
        return 0.0


# Seuil d'entropie au-dessus duquel la reponse est consideree incertaine.
# A calibrer sur le benchmark (25 questions unanswerable).
# log(5) = 1.609 = entropie maximale avec 5 tokens equiprobables.
# Valeur initiale conservatrice — a ajuster empiriquement.
ENTROPY_HIGH_THRESHOLD = 1.0  # A calibrer


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


def _clean_source_name(source_file: str) -> str:
    """Transforme un nom de fichier brut en nom lisible.

    '027_SAP_S4HANA_2023_Security_Guide_c160af0e' → 'SAP S4HANA 2023 Security Guide'
    """
    import re
    name = source_file.split("/")[-1]
    # Retirer hash final
    name = re.sub(r"_[a-f0-9]{6,}$", "", name, flags=re.IGNORECASE)
    # Retirer prefixe numerique
    name = re.sub(r"^\d{3}_(\d+_)?", "", name)
    # Retirer extension
    name = re.sub(r"\.\w+$", "", name)
    # Underscores et tirets → espaces
    name = name.replace("_", " ").replace("-", " ").strip()
    # Nettoyer les espaces multiples
    name = re.sub(r"\s+", " ", name)
    return name


def _reformat_source_citations(answer: str, sources_used: list[str]) -> str:
    """Post-traite la reponse LLM pour normaliser les citations de sources.

    Cherche les mentions de noms de sources dans le texte et les reformate
    en *(Nom lisible, p.XX)* pour que le frontend les affiche en SourcePill.

    Strategie : on travaille en un seul passage pour eviter les doubles substitutions.
    """
    import re

    if not answer or not sources_used:
        return answer

    # Construire les noms lisibles
    clean_names = []
    for src in sources_used:
        clean = _clean_source_name(src)
        if clean and len(clean) >= 15:
            clean_names.append(clean)

    if not clean_names:
        return answer

    # Trier par longueur decroissante (matcher les noms les plus longs d'abord)
    clean_names.sort(key=len, reverse=True)

    # Construire un mega-pattern qui capture toutes les variantes en un passage :
    # 1. *(Doc, p.XX)* → deja formate, on ne touche pas
    # 2. (Doc, p.XX) → on ajoute les *
    # 3. Doc, p.XX → on wrappe en *()*
    # 4. Doc (p.XX) → on reformate
    names_alt = "|".join(re.escape(n) for n in clean_names)

    # Pattern unifie : capture nom + page dans toutes les variantes
    # Groupe 1 = nom du document, Groupe 2 = page
    unified = re.compile(
        r"\*?\(?(" + names_alt + r")\s*[,;]\s*(p\.?\s*\d+(?:\s*(?:[-–]\s*\d+|(?:et|and)\s*p?\.?\s*\d+))?)\)?\*?",
        re.IGNORECASE,
    )

    def replacer(m):
        doc = m.group(1).strip()
        page = m.group(2).strip()
        return f"*({doc}, {page})*"

    answer = unified.sub(replacer, answer)

    return answer


def _build_tension_prompt_section(envelope: "ContradictionEnvelope") -> str:
    """Construit la section MANDATORY du prompt pour forcer la divulgation des tensions."""
    lines = [
        "\n## MANDATORY: Tension disclosure",
        "The following divergences have been detected between documents. "
        "You MUST address each one in your response.",
        "For each divergence, present BOTH positions with their respective sources.\n",
    ]
    for pair in envelope.pairs:
        lines.append(
            f"- {pair['doc_a']} says: \"{pair['claim_a'][:150]}\" "
            f"vs {pair.get('doc_b', 'another source')} says: \"{pair['claim_b'][:150]}\""
        )
    lines.append(
        "\nYour response MUST contain a \"## Divergences\" or \"## Points d'attention\" "
        "section addressing these tensions."
    )
    return "\n".join(lines)


def _validate_tension_disclosure(answer: str, envelope: "ContradictionEnvelope") -> bool:
    """Verifie si la reponse mentionne les tensions detectees.

    Heuristique simple : presence de mots-cles lies aux divergences.
    """
    if not envelope.requires_disclosure:
        return True
    tension_keywords = [
        "divergen", "contradict", "differ", "disagree", "however",
        "en revanche", "toutefois", "cependant", "attention",
        "divergence", "contradiction", "unlike", "while",
        "points d'attention", "points of attention",
    ]
    answer_lower = answer.lower()
    return any(kw in answer_lower for kw in tension_keywords)


def _build_tension_fallback(envelope: "ContradictionEnvelope") -> str:
    """Construit un fallback deterministe (sans LLM) garantissant la divulgation."""
    fallback = (
        "\n\n## Points d'attention\n"
        "Les sources ne sont pas homogènes sur ce point. "
    )
    for pair in envelope.pairs[:3]:
        fallback += (
            f"\n- {pair['doc_a']} indique : \"{pair['claim_a'][:100]}\" "
            f"tandis que {pair.get('doc_b', 'une autre source')} indique : "
            f"\"{pair['claim_b'][:100]}\""
        )
    return fallback


def synthesize_response(
    question: str,
    chunks: List[Dict[str, Any]],
    graph_context_text: str = "",
    session_context_text: str = "",
    kg_signals: Dict[str, Any] = None,
    chain_signals: Dict[str, Any] = None,
    contradiction_envelope: "ContradictionEnvelope | None" = None,
    response_mode: str = "DIRECT",
) -> Dict[str, Any]:
    """
    Génère une réponse synthétisée à partir des chunks et de la question.

    Args:
        question: Question de l'utilisateur
        chunks: Liste des chunks reranqués
        graph_context_text: Contexte Knowledge Graph formaté (OSMOSE)
        session_context_text: Contexte conversationnel formaté (Memory Layer Phase 2.5)
        kg_signals: Signaux KG optionnels pour le calcul de confiance
        chain_signals: Signaux de qualité des chaînes CHAINS_TO multi-doc
        contradiction_envelope: Enveloppe de tensions KG
        response_mode: Mode de reponse V3 (DIRECT, AUGMENTED, TENSION, STRUCTURED_FACT)

    Returns:
        Dictionnaire contenant la réponse synthétisée et les métadonnées
    """
    if not chunks:
        return {
            "synthesized_answer": "No relevant information was found in the knowledge base to answer your question.",
            "sources_used": [],
            "confidence": 0.0
        }

    # Formate les chunks pour le prompt
    chunks_content = format_chunks_for_synthesis(chunks)

    # V3 : Prompt specialise par mode (si feature flag actif)
    modes_enabled = os.environ.get("OSMOSIS_RESPONSE_MODES", "false").lower() == "true"
    mode_prompt = None
    if modes_enabled and response_mode != "DIRECT":
        mode_prompt = _load_mode_prompt(response_mode)
        if mode_prompt:
            logger.info(f"[SYNTHESIS] Using mode-specific prompt: {response_mode}")

    if mode_prompt:
        # Prompt specialise V3 — pas de graph_context pour AUGMENTED
        # Pour TENSION : graph_context = contraintes courtes
        # Pour STRUCTURED_FACT : graph_context = faits structures
        if response_mode == "TENSION" and contradiction_envelope and contradiction_envelope.requires_disclosure:
            # Injecter les contraintes de tension dans graph_context
            graph_context_text += _build_tension_prompt_section(contradiction_envelope)

        prompt = mode_prompt.format(
            question=question,
            chunks_content=chunks_content,
            graph_context=graph_context_text,
            session_context=session_context_text,
        )
    else:
        # Prompt existant (mode DIRECT ou feature flag off)
        # Injecter la section tension MANDATORY si l'enveloppe l'exige
        if contradiction_envelope and contradiction_envelope.requires_disclosure:
            graph_context_text += _build_tension_prompt_section(contradiction_envelope)
            logger.info(
                f"[SYNTHESIS] ContradictionEnvelope injected: "
                f"{len(contradiction_envelope.pairs)} tension pairs, mode={contradiction_envelope.synthesis_mode}"
            )

        # Charger la regle 7 adaptee au provider actif
        rule_7 = get_rule_7_for_provider()

        prompt = SYNTHESIS_PROMPT.format(
            question=question,
            chunks_content=chunks_content,
            graph_context=graph_context_text,
            session_context=session_context_text,
            rule_7=rule_7,
    )

    # Appel LLM — Architecture tiered :
    # 1. Claude Haiku (API) si ANTHROPIC_API_KEY disponible — meilleur pour la synthese
    # 2. Fallback : routeur LLM local (Qwen via Ollama/vLLM)

    SYSTEM_MSG = (
        "You are a precise document analysis assistant. You synthesize information "
        "from provided sources to answer user questions. Lead with facts. "
        "When sources DISAGREE or present DIFFERENT information, you MUST present "
        "ALL positions with their respective sources — never silently pick one side. "
        "Contradictions and evolutions between document versions are valuable information."
    )

    prompt_size = len(prompt)
    logger.info(f"[SYNTHESIS] Starting LLM call, prompt size: {prompt_size} chars")
    start_time = time.time()

    try:
        # Choix du provider de synthese via env (default: anthropic)
        synthesis_provider = os.environ.get("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

        synthesized_via = None

        # Tier 0 : OpenAI (si configure comme provider principal)
        if synthesis_provider == "openai" and openai_key:
            try:
                from openai import OpenAI
                oai_client = OpenAI(api_key=openai_key)
                oai_model = os.environ.get("OSMOSIS_SYNTHESIS_MODEL", "gpt-4o-mini")
                response = oai_client.chat.completions.create(
                    model=oai_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_MSG},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=2000,
                    temperature=0.3,
                    logprobs=True,
                    top_logprobs=5,
                )
                synthesized_answer = response.choices[0].message.content or ""
                synthesized_via = "openai"

                # Calcul entropie logprobs pour detection hallucination
                entropy_score = _compute_logprob_entropy(response)

                logger.info(
                    f"[SYNTHESIS] OpenAI {oai_model} completed in "
                    f"{(time.time() - start_time) * 1000:.0f}ms, "
                    f"{len(synthesized_answer)} chars, entropy={entropy_score:.3f}"
                )
                try:
                    from knowbase.common.token_tracker import track_tokens
                    track_tokens(
                        model=oai_model,
                        task_type="synthesis",
                        input_tokens=response.usage.prompt_tokens if response.usage else 0,
                        output_tokens=response.usage.completion_tokens if response.usage else 0,
                        context="synthesis_chat",
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"[SYNTHESIS] OpenAI failed, falling back: {e}")

        # Tier 1 : Claude Haiku (default ou fallback)
        if not synthesized_via and anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                haiku_model = os.environ.get("OSMOSIS_SYNTHESIS_MODEL" if synthesis_provider == "anthropic" else "_IGNORE_", "claude-haiku-4-5-20251001")
                response = client.messages.create(
                    model=haiku_model,
                    max_tokens=2000,
                    system=SYSTEM_MSG,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )
                synthesized_answer = response.content[0].text if response.content else ""
                synthesized_via = "anthropic"
                logger.info(
                    f"[SYNTHESIS] Claude {haiku_model} completed in "
                    f"{(time.time() - start_time) * 1000:.0f}ms, "
                    f"{len(synthesized_answer)} chars"
                )
                # Track tokens pour le cockpit
                try:
                    from knowbase.common.token_tracker import track_tokens
                    track_tokens(
                        model=haiku_model,
                        task_type="synthesis",
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        context="synthesis_chat",
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"[SYNTHESIS] Claude API failed, falling back to local LLM: {e}")
                pass  # Fall through to Tier 2

        if not synthesized_via:
            # Tier 2 : Fallback LLM local (Qwen via routeur)
            router = get_llm_router()
            messages = [
                {"role": "system", "content": SYSTEM_MSG},
                {"role": "user", "content": prompt}
            ]
            synthesized_answer = router.complete(
                task_type=TaskType.LONG_TEXT_SUMMARY,
                messages=messages,
                temperature=0.3,
                max_tokens=2000
            )
            logger.info(
                f"[SYNTHESIS] Local LLM completed in "
                f"{(time.time() - start_time) * 1000:.0f}ms, "
                f"{len(synthesized_answer)} chars"
            )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[SYNTHESIS] LLM call completed in {elapsed_ms:.0f}ms, response: {len(synthesized_answer)} chars")

        # ContradictionEnvelope : validation + fallback deterministe
        tension_disclosed = True
        if contradiction_envelope and contradiction_envelope.requires_disclosure:
            tension_disclosed = _validate_tension_disclosure(synthesized_answer, contradiction_envelope)
            if not tension_disclosed:
                fallback_text = _build_tension_fallback(contradiction_envelope)
                synthesized_answer += fallback_text
                logger.warning(
                    f"[SYNTHESIS] Tension disclosure FAILED validation — "
                    f"appended deterministic fallback ({len(contradiction_envelope.pairs)} pairs)"
                )
            else:
                logger.info("[SYNTHESIS] Tension disclosure validated OK — LLM addressed divergences")

        # Extrait les sources utilisées
        sources_used = []
        for chunk in chunks:
            source_file = chunk.get('source_file', '')
            slide_index = chunk.get('slide_index', '')
            if source_file and source_file not in sources_used:
                sources_used.append(source_file)

        # Post-traitement : reformater les mentions de sources dans la reponse
        # Le LLM cite les sources de maniere inconsistante. On normalise vers le format
        # *(Nom lisible, p.XX)* pour que le frontend les affiche en SourcePill.
        synthesized_answer = _reformat_source_citations(synthesized_answer, sources_used)

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

        # Entropie logprob (si disponible) — indicateur d'incertitude
        _entropy = locals().get("entropy_score", 0.0)
        entropy_flag = "high" if _entropy > ENTROPY_HIGH_THRESHOLD else "normal"
        if _entropy > ENTROPY_HIGH_THRESHOLD:
            logger.info(f"[SYNTHESIS:ENTROPY] HIGH entropy={_entropy:.3f} — reponse potentiellement non fondee")

        result = {
            "synthesized_answer": synthesized_answer.strip(),
            "sources_used": sources_used,
            "confidence": confidence,
            "confidence_breakdown": {
                "base_score": round(base_confidence_final, 3),
                "kg_bonus": round(kg_bonus, 3),
                "chain_bonus": round(chain_bonus, 3),
                "final_score": round(confidence, 3)
            },
            "entropy": {
                "score": round(_entropy, 4),
                "flag": entropy_flag,
                "threshold": ENTROPY_HIGH_THRESHOLD,
            },
            "response_mode": response_mode,
        }

        # Ajouter les metadonnees ContradictionEnvelope si applicable
        if contradiction_envelope and contradiction_envelope.has_tension:
            result["contradiction_envelope"] = {
                "has_tension": True,
                "requires_disclosure": contradiction_envelope.requires_disclosure,
                "pairs_count": len(contradiction_envelope.pairs),
                "synthesis_mode": contradiction_envelope.synthesis_mode,
                "tension_disclosed": tension_disclosed,
                "fallback_appended": not tension_disclosed,
            }

        return result

    except Exception as e:
        return {
            "synthesized_answer": f"Erreur lors de la génération de la réponse : {str(e)}",
            "sources_used": [],
            "confidence": 0.0
        }


__all__ = ["synthesize_response", "format_chunks_for_synthesis"]
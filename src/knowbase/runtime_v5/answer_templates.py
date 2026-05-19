"""V5.1 Voie A — Templates par answer_shape (pattern EKX P3).

Format de sortie déterministe par type de question, pour guider l'agent
Reading Agent V5.1 vers une réponse structurée et compacte plutôt qu'une
production libre.

Pattern EKX P3 (mémoire `project_ekx_inspiring_patterns`) :
"Templates adapted by question type" → quick win UX presales.

Charte universelle : aucune mention de domaine, du vocabulaire SAP, etc.
Le mécanisme est universel ; les shapes (factual, list, ...) sont des
catégories abstraites.

Toggle : env var V5_TEMPLATES_ENABLED=1 active la feature.

Les shapes supportées correspondent au classifier S0.5 / gold_set_sap_v2 :
factual, comparison, multi_hop, contextual, false_premise, causal,
listing, negation, lifecycle, quantitative, unanswerable.
"""
from __future__ import annotations

import os


# ─────────────────────────────────────────────────────────────────────────────
# Templates universels par shape
# ─────────────────────────────────────────────────────────────────────────────


_TEMPLATES: dict[str, str] = {
    "factual": (
        "Expected answer format: 1-3 short sentences stating the fact.\n"
        "Each sentence ends with its source citation in the form [doc=<doc_id>].\n"
        "Do not paraphrase identifiers, codes, or numeric values — quote them verbatim."
    ),
    "listing": (
        "Expected answer format: a bulleted list, one item per line, starting with '- '.\n"
        "Each item ends with its source citation [doc=<doc_id>].\n"
        "Include every item the question asks for; do not summarize the list.\n"
        "If no items can be supported by evidence, state so explicitly and abstain."
    ),
    "comparison": (
        "Expected answer format: a markdown table comparing the items along the relevant criteria.\n"
        "Columns = the items compared. Rows = the criteria of comparison.\n"
        "Each cell ends with its source citation [doc=<doc_id>].\n"
        "After the table, a 1-2 sentence summary of the key differences."
    ),
    "multi_hop": (
        "Expected answer format: 2-4 short sentences chaining the reasoning steps explicitly.\n"
        "Each step references its evidence [doc=<doc_id>].\n"
        "Make the chain visible: 'A leads to B [doc=X]. B implies C [doc=Y]. Therefore C [doc=Z].'\n"
        "Do not collapse intermediate steps."
    ),
    "causal": (
        "Expected answer format: a cause → effect chain in 2-4 sentences.\n"
        "Each link in the chain ends with its source citation [doc=<doc_id>].\n"
        "Structure: 'X causes Y because <reason> [doc=<X>]. Y in turn produces Z [doc=<Y>].'\n"
        "Do not assert a cause that is not supported by evidence."
    ),
    "contextual": (
        "Expected answer format: state the conditions or context first, then the fact dependent on them.\n"
        "Format: 'Under condition C [doc=<X>], the answer is A [doc=<Y>].'\n"
        "If multiple contexts apply, enumerate them with bullets, each with its [doc=<doc_id>]."
    ),
    "false_premise": (
        "Expected answer format: identify the false or unsupported premise FIRST in 1 sentence.\n"
        "Then state what the evidence actually supports.\n"
        "Format: 'The premise that X is incorrect [doc=<source>]. According to the documents, "
        "Y is what holds [doc=<source>].'\n"
        "Do NOT answer as if the false premise were true."
    ),
    "negation": (
        "Expected answer format: state the negated fact directly, marking the negation.\n"
        "Use explicit negation markers: 'X does NOT do Y [doc=<source>]'.\n"
        "Do not soften or rephrase negation as 'X may not always do Y'."
    ),
    "lifecycle": (
        "Expected answer format: a chronological sequence of states or versions.\n"
        "Format: 'In version V1 [doc=<X>], state was S1. In version V2 [doc=<Y>], state changed to S2.'\n"
        "Always cite the document version that supports each state."
    ),
    "quantitative": (
        "Expected answer format: state the numeric value with its unit, verbatim from the source.\n"
        "Format: '<value> <unit> [doc=<source>]'.\n"
        "If a range or interval is given, quote both bounds.\n"
        "Do not round, convert, or paraphrase the numeric value."
    ),
    "unanswerable": (
        "Expected answer format: explicitly state that the documents do not support an answer.\n"
        "Format: 'The provided documents do not contain information to answer this question.'\n"
        "Briefly list (1-2 items) what aspects WERE searched, to demonstrate due diligence.\n"
        "Do NOT speculate or pad the answer with adjacent information."
    ),
    "lookup": (
        "Expected answer format: key-value pairs, one per line.\n"
        "Format: '<Field>: <Value> [doc=<source>]'.\n"
        "Provide only the fields directly asked; do not enumerate adjacent attributes."
    ),
}


_FALLBACK_TEMPLATE = (
    "Expected answer format: a concise, evidence-grounded answer.\n"
    "Each claim ends with its source citation [doc=<doc_id>].\n"
    "Do not invent or paraphrase identifiers, numeric values, or quoted text — extract them verbatim."
)


def get_template(shape: str | None) -> str:
    """Retourne le template texte pour une shape donnée.

    Si shape est None ou inconnue, retourne le template fallback générique.
    """
    if not shape:
        return _FALLBACK_TEMPLATE
    normalized = shape.strip().lower()
    return _TEMPLATES.get(normalized, _FALLBACK_TEMPLATE)


def format_template_block(shape: str | None) -> str:
    """Format le block à injecter dans le user_prompt.

    Retourne une chaîne vide si templates désactivés via env.
    """
    if not is_enabled():
        return ""
    template = get_template(shape)
    label = (shape or "default").strip().lower()
    return f"Answer format (shape={label}):\n{template}"


def is_enabled() -> bool:
    return os.getenv("V5_TEMPLATES_ENABLED", "0").lower() in ("1", "true", "yes")


def list_supported_shapes() -> list[str]:
    return list(_TEMPLATES.keys())

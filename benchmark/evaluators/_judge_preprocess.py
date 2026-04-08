"""
Helper partage pour le pre-traitement des reponses OSMOSIS avant envoi
aux LLM-juges des benchmarks.

CONTRAT IMPORTANT :
-------------------
Ce module est une BOITE NOIRE LOCALE AU PIPELINE D'EVALUATION.
Il ne modifie EN AUCUN CAS la reponse retournee a l'utilisateur final.
Il ne modifie pas non plus la reponse stockee dans les rapports (per_sample).
Il transforme UNIQUEMENT la copie qui est injectee dans le prompt du juge.

POURQUOI ?
----------
La reponse OSMOSIS contient des marqueurs `[[SOURCE:Doc|p.X]]` qui sont
utilises par le frontend pour afficher des SourcePills cliquables. C'est
une fonctionnalite UI valide qu'on ne doit pas supprimer. Mais les LLM-juges
(GPT-4o-mini) ne connaissent pas ce format et ne les reconnaissent pas comme
des citations valides, ce qui fausse les scores.

La solution : avant d'envoyer la reponse au juge, on convertit les marqueurs
en format lisible universel `(Doc, p. X)`. Le juge comprend alors que ce
sont des citations et note correctement.

Ce pre-traitement est :
- LOCAL au pipeline d'evaluation (ne sort jamais d'ici)
- REVERSIBLE (la reponse originale est preservee dans les rapports)
- DOMAIN-AGNOSTIC (ne depend d'aucune langue, d'aucun domaine)
- DELEGUE au LLM-juge (qui reste un LLM et peut s'adapter)

Si demain le backend change le format du marqueur, il suffira d'ajouter
une ligne a preprocess_answer_for_judge() sans toucher aux juges eux-memes.
"""
from __future__ import annotations

import re


# Marqueur principal du backend OSMOSIS : `[[SOURCE:Doc Name|p. X]]`
# Peut avoir ou ne pas avoir de page, peut avoir des variantes `p.XX`, `p. XX`, `slide X`
_SOURCE_MARKER_RE = re.compile(r"\[\[SOURCE:([^\]|]+?)(?:\|([^\]]+?))?\]\]")


def preprocess_answer_for_judge(answer: str) -> str:
    """Convertit les marqueurs techniques d'OSMOSIS en citations lisibles.

    Ne touche pas au texte en dehors des marqueurs.

    Transformations :
        [[SOURCE:Doc Name|p. 82]]  ->  (Doc Name, p. 82)
        [[SOURCE:Doc Name|slide 12]]  ->  (Doc Name, slide 12)
        [[SOURCE:Doc Name]]  ->  (Doc Name)

    Args:
        answer: reponse brute OSMOSIS telle que stockee dans le rapport

    Returns:
        reponse avec citations en format lisible, prete a etre injectee
        dans le prompt d'un LLM-juge
    """
    if not answer:
        return answer

    def _replace(m: re.Match) -> str:
        doc = m.group(1).strip()
        page = m.group(2).strip() if m.group(2) else ""
        if page:
            return f"({doc}, {page})"
        return f"({doc})"

    return _SOURCE_MARKER_RE.sub(_replace, answer)

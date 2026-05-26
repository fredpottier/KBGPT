"""
enumeration_detector.py — Détecteur d'énumération DÉTERMINISTE basé sur la syntaxe.

P1.4b-1 (ADR_P1_4_BIS_EXTRACTION_REFACTOR.md). But : décider si une phrase est une
**énumération d'objets partageant un prédicat** (« supports A, B and C ») — auquel cas
le segmenteur ne doit PAS la fragmenter (elle deviendra 1 claim avec une liste côté LLM),
à distinguer de coordinations NON-énumératives qu'il ne faut pas mal-structurer :
  - sujets coordonnés (« the pilot and the copilot must verify »),
  - alternative / disjonction (« A or B may be used »),
  - séquence multi-verbes (« checks X, validates Y, processes Z »).

Approche SYNTAXE (spaCy dépendances), PAS regex — validé au spike `p1_enum_detector_spike.py`
(0 faux positif sur 8 pièges EN+FR). Domain-agnostic (structure grammaticale universelle).

Défaut SÛR : en cas de doute, d'erreur, de langue/modèle indisponible → retourne False
(le segmenteur garde son comportement, et le schéma `objects[]` côté LLM rattrape).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# rôles "objet/complément" (couvre labels OntoNotes EN + UD FR)
_OBJECT_DEPS = {"dobj", "obj", "pobj", "obl", "attr", "dative", "oprd", "nmod", "acomp"}
_SUBJECT_DEPS = {"nsubj", "nsubjpass", "nsubj:pass"}
# un conjoint verbe possédant un de ces enfants = vraie clause (pas un gérondif nominal)
_ARG_DEPS = {"dobj", "obj", "iobj", "dative", "nsubj", "nsubjpass", "nsubj:pass",
             "ccomp", "xcomp", "obl"}

# langue → modèle spaCy installé
_SPACY_MODELS = {
    "en": "en_core_web_md",
    "fr": "fr_core_news_md",
}

_LID_MODEL_PATH = os.getenv("FASTTEXT_LID_PATH", "/app/models/lid.176.bin")


class EnumerationDetector:
    """Détecteur d'énumération d'objets (lazy, multilingue, fallback sûr)."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._nlp_cache: dict = {}
        self._lid = None
        self._lid_tried = False

    # ── détection de langue (fasttext lid.176) ────────────────────────────────
    def _get_lid(self):
        if self._lid_tried:
            return self._lid
        self._lid_tried = True
        try:
            import fasttext
            if os.path.exists(_LID_MODEL_PATH):
                # fasttext bavarde sur stderr au load ; sans incidence
                self._lid = fasttext.load_model(_LID_MODEL_PATH)
        except Exception as exc:  # pragma: no cover
            logger.warning("[EnumDetector] fasttext LID indisponible: %s", exc)
            self._lid = None
        return self._lid

    def detect_language(self, text: str) -> Optional[str]:
        lid = self._get_lid()
        if lid is None:
            return None
        try:
            # fasttext n'aime pas les newlines
            label = lid.predict(text.replace("\n", " ").strip()[:1000])[0][0]
            return label.replace("__label__", "")
        except Exception:  # pragma: no cover
            return None

    # ── modèle spaCy (cache + fallback) ───────────────────────────────────────
    def _get_nlp(self, lang: Optional[str]):
        model_name = _SPACY_MODELS.get(lang or "")
        if model_name is None:
            return None  # langue non supportée → fallback sûr
        if model_name in self._nlp_cache:
            return self._nlp_cache[model_name]
        try:
            import spacy
            nlp = spacy.load(model_name, disable=["ner", "lemmatizer"])
            self._nlp_cache[model_name] = nlp
            return nlp
        except Exception as exc:  # pragma: no cover
            logger.warning("[EnumDetector] spaCy %s indisponible: %s", model_name, exc)
            self._nlp_cache[model_name] = None
            return None

    # ── API principale ────────────────────────────────────────────────────────
    def is_object_enumeration(self, text: str, lang: Optional[str] = None) -> bool:
        """True si `text` est une énumération d'objets partageant un prédicat.

        Ordre CONSERVATEUR : les cas dangereux (alternative, sujets, verbes coordonnés)
        sont écartés AVANT de pouvoir conclure « enum ». Tout échec → False (sûr).
        """
        if not self.enabled or not text or len(text) < 3:
            return False
        # fast path : sans virgule ni 'and'/'et' coordination, pas une énumération
        low = text.lower()
        if "," not in text and " and " not in low and " et " not in low:
            return False

        if lang is None:
            lang = self.detect_language(text)
        nlp = self._get_nlp(lang)
        if nlp is None:
            return False

        try:
            doc = nlp(text)
        except Exception:  # pragma: no cover
            return False

        conj_tokens = [t for t in doc if t.dep_ == "conj"]
        if not conj_tokens:
            return False

        # alternative / disjonction → pas une énumération
        cc_lemmas = {t.lower_ for t in doc if t.dep_ == "cc"}
        lowers = {t.lower_ for t in doc}
        if (cc_lemmas & {"or", "ou"}) or ("either" in lowers) or ("soit" in lowers):
            return False

        # parcours des têtes de coordination
        for ct in conj_tokens:
            head = ct.head
            while head.dep_ == "conj":
                head = head.head
            # séquence multi-verbes : un conjoint VERBE AYANT ses propres arguments
            # (sujet/objet) = vraie clause coordonnée. Un gérondif/nom verbal sans
            # argument propre (« audit logging », « reporting ») est un NOM dans une
            # liste, PAS une séquence de verbes → ne déclenche pas.
            if ct.pos_ in {"VERB", "AUX"} and any(
                c.dep_ in _ARG_DEPS for c in ct.children
            ):
                return False
            # sujets coordonnés → pas une énumération d'objets
            if head.dep_ in _SUBJECT_DEPS:
                return False

        # au moins un groupe de coordination en position objet/complément
        for ct in conj_tokens:
            head = ct.head
            while head.dep_ == "conj":
                head = head.head
            if head.dep_ in _OBJECT_DEPS:
                return True

        return False  # défaut sûr


# singleton process-wide (réutilise les modèles chargés)
_DEFAULT_DETECTOR: Optional[EnumerationDetector] = None


def get_enumeration_detector(enabled: bool = True) -> EnumerationDetector:
    global _DEFAULT_DETECTOR
    if _DEFAULT_DETECTOR is None:
        _DEFAULT_DETECTOR = EnumerationDetector(enabled=enabled)
    return _DEFAULT_DETECTOR

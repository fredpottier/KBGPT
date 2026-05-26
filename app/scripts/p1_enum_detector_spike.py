#!/usr/bin/env python
"""
p1_enum_detector_spike.py — SPIKE (P1.4b-1) : un détecteur d'énumération DÉTERMINISTE
peut-il atteindre 0 FAUX POSITIF sur les pièges (sujets coordonnés, alternative,
séquence d'actions) ?

Contexte : Claude Web (26/05) avertit qu'un regex naïf sur « X, Y, and Z » sur-classerait
des coordinations NON-énumératives (« the pilot AND the copilot must verify » = sujets,
« A or B may be used » = alternative). On teste un détecteur basé sur la SYNTAXE (spaCy
dépendances, EN + FR) plutôt qu'un regex, et on mesure les faux positifs sur ces pièges.

Rôle visé du détecteur : décider si une phrase est une **énumération d'objets partageant
un prédicat** (→ représentable en 1 claim avec `objects[]`), à distinguer de :
sujets coordonnés / disjonction-alternative / séquence multi-verbes / pas de coordination.

Défaut SÛR = ne PAS classer « enum » si ambigu (les cas dangereux sont attrapés AVANT).

GATE : 0 faux positif sur l'ensemble « non-enum » avant de passer à P1.4b-2.

Usage:
    docker compose exec app python scripts/p1_enum_detector_spike.py
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] enum_spike")

# rôles "objet/complément" (couvre labels OntoNotes EN + UD FR)
OBJECT_DEPS = {"dobj", "obj", "pobj", "obl", "attr", "dative", "oprd", "nmod", "acomp"}
SUBJECT_DEPS = {"nsubj", "nsubjpass", "nsubj:pass"}

# (phrase, langue, attendu)  attendu: True = énumération d'objets, False = NON
CASES = [
    # — énumérations d'objets (devrait classer ENUM) —
    ("The system supports SSO, LDAP, and OAuth.", "en", True),
    ("Supply elements include stock, purchase orders, and production orders.", "en", True),
    ("Available editions are Standard, Professional, and Enterprise.", "en", True),
    ("The drug treats fever, inflammation, and mild pain.", "en", True),
    ("Le module gère les taxes, les douanes et les accises.", "fr", True),
    ("Les éditions disponibles sont Standard, Professionnel et Entreprise.", "fr", True),

    # — PIÈGES : ne DOIT PAS classer enum (faux positifs à éviter) —
    ("The pilot and the copilot must verify the landing gear.", "en", False),   # sujets coordonnés
    ("Procedure A or B may be used.", "en", False),                              # alternative
    ("The system checks the input, validates the schema, and processes the record.", "en", False),  # séquence verbes
    ("The engine weighs 500 kilograms.", "en", False),                           # pas de coordination
    ("Water boils at 100 degrees Celsius at sea level.", "en", False),           # pas de coordination
    ("Le pilote et le copilote doivent vérifier le train d'atterrissage.", "fr", False),  # sujets FR
    ("La procédure A ou B peut être utilisée.", "fr", False),                    # alternative FR
    ("Either the primary or the backup server handles the request.", "en", False),  # alternative either/or
]


def get_nlp(lang: str):
    import spacy
    name = "fr_core_news_md" if lang == "fr" else "en_core_web_md"
    if not hasattr(get_nlp, "_cache"):
        get_nlp._cache = {}
    if name not in get_nlp._cache:
        get_nlp._cache[name] = spacy.load(name, disable=["ner", "lemmatizer"])
    return get_nlp._cache[name]


def classify(sentence: str, lang: str):
    """Retourne (is_enum: bool, reason: str, items: list[str]).

    Ordre CONSERVATEUR : les cas dangereux (alternative, sujets, séquence verbes) sont
    testés AVANT de pouvoir conclure « enum ».
    """
    nlp = get_nlp(lang)
    doc = nlp(sentence)

    # collecter les groupes de coordination : token avec dep_ == conj + sa tête
    conj_tokens = [t for t in doc if t.dep_ == "conj"]
    if not conj_tokens:
        return False, "no_coordination", []

    # le(s) coordinateur(s) cc présents (and/or/et/ou/,)
    cc_lemmas = {t.lower_ for t in doc if t.dep_ == "cc"}
    is_disjunction = bool(cc_lemmas & {"or", "ou"}) or "either" in {t.lower_ for t in doc} or "soit" in {t.lower_ for t in doc}
    if is_disjunction:
        return False, "alternative_disjunction", []

    # pour chaque conj, la tête de coordination = conj.head ; rôle = head.dep_
    for ct in conj_tokens:
        head = ct.head
        # remonter à la tête de la chaîne de conj (head peut être lui-même un conj)
        while head.dep_ == "conj":
            head = head.head
        role = head.dep_

        # coordination de VERBES → séquence multi-prédicats (pas une liste de valeurs)
        if ct.pos_ in {"VERB", "AUX"} or head.pos_ in {"VERB", "AUX"}:
            return False, "verb_sequence", []

        # coordination de SUJETS → pas une énumération d'objets
        if role in SUBJECT_DEPS:
            return False, "coordinated_subjects", []

    # arrivé ici : conjonction (and/et/virgule), pas de sujet/verbe/alternative coordonnés
    # → chercher au moins un groupe de conj en position objet/complément
    for ct in conj_tokens:
        head = ct.head
        while head.dep_ == "conj":
            head = head.head
        if head.dep_ in OBJECT_DEPS:
            items = [head.text] + [t.text for t in conj_tokens]
            return True, f"object_enumeration(head_dep={head.dep_})", items

    return False, "uncertain_default_safe", []


def main():
    print("\n" + "=" * 100)
    print(f"{'PHRASE':<70} {'attendu':>8} {'détecté':>8}  verdict")
    print("=" * 100)
    fp = fn = ok = 0
    for sent, lang, expected in CASES:
        is_enum, reason, items = classify(sent, lang)
        correct = (is_enum == expected)
        if correct:
            ok += 1
            mark = "✅"
        elif is_enum and not expected:
            fp += 1
            mark = "❌ FAUX POSITIF"
        else:
            fn += 1
            mark = "⚠️ faux négatif"
        print(f"{sent[:68]:<70} {('ENUM' if expected else 'non'):>8} {('ENUM' if is_enum else 'non'):>8}  {mark}  [{reason}]")

    print("=" * 100)
    n_neg = sum(1 for _, _, e in CASES if not e)
    n_pos = sum(1 for _, _, e in CASES if e)
    print(f"Total {len(CASES)} | OK {ok} | FAUX POSITIFS {fp}/{n_neg} (pièges) | faux négatifs {fn}/{n_pos}")
    gate = "✅ GATE PASS (0 faux positif)" if fp == 0 else f"❌ GATE FAIL ({fp} faux positifs)"
    print(gate)
    print("=" * 100)
    print("Rappel design : 0 FP = critique (ne pas mal-structurer) ; les faux négatifs")
    print("sont rattrapés par le schéma objects[] côté LLM Stage B (le détecteur n'est qu'un HINT).")


if __name__ == "__main__":
    main()

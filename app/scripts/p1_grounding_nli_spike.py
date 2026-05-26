#!/usr/bin/env python
"""
p1_grounding_nli_spike.py — SPIKE décisif (read-only, hors KG) : quel modèle pour le
grounding gate (Q4/Q5) de P1.4-bis ?

Contexte : Claude Web (26/05) souligne à raison que bge-reranker est un RERANKER
(pertinence query-doc), PAS un NLI (entailment premise-hypothesis) → il scorerait haut
sur la proximité sémantique même quand le claim AJOUTE un détail absent de la source.
HHEM-2.1 est cassé (remote code incompat transformers 5.5.0). On teste donc les vrais
modèles NLI DÉJÀ en cache local, sur un mini-set étiqueté fidèles vs hallucinations.

Objectif : voir lequel SÉPARE le mieux (claim fidèle = score haut, hallucination = bas),
et démontrer empiriquement si bge-reranker échoue.

Set étiqueté CROSS-DOMAIN (médical / aerospace / générique / logiciel) — domain-agnostic.

Usage:
    docker compose exec app python scripts/p1_grounding_nli_spike.py
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] grounding_spike")

# (source_passage, claim, label)  label: True = fidèle (claim ⊨ source), False = hallucination
PAIRS = [
    # — fidèles (claim entailé / paraphrase / décontextualisation correcte) —
    ("Water boils at 100 degrees Celsius at standard atmospheric pressure.",
     "At sea level, water boils at 100 degrees Celsius.", True),
    ("The booster dose is recommended six months after the second injection.",
     "A booster is recommended six months after the second injection.", True),
    ("The landing gear must be verified before takeoff by the first officer.",
     "The landing gear must be verified before takeoff.", True),
    ("SAP NetWeaver Application Server supports single sign-on with X.509 certificates.",
     "SAP NetWeaver Application Server supports SSO using X.509 certificates.", True),
    ("Supply elements include stock, purchase orders, and production orders.",
     "Production orders are a type of supply element.", True),
    ("The engine weighs 500 kg and runs on kerosene.",
     "The engine weighs 500 kg.", True),
    ("Transaction CG5Z is used to delete batch records in the system.",
     "Batch records can be deleted using transaction CG5Z.", True),

    # — hallucinations (détail ajouté / valeur changée / sujet changé / non supporté) —
    ("SAP NetWeaver Application Server supports single sign-on.",
     "SAP NetWeaver Application Server supports single sign-on with X.509 certificates.", False),
    ("The engine weighs 500 kg and runs on kerosene.",
     "The engine weighs 600 kg.", False),
    ("Aspirin reduces fever in adult patients.",
     "Ibuprofen reduces fever in adult patients.", False),
    ("The system stores reservations of stock at plant level.",
     "The system stores reservations of stock at batch level.", False),
    ("Freight unit building creates freight units from order-based requirements.",
     "Freight unit building creates freight units from delivery-based requirements.", False),
    ("The report can be scheduled to run weekly.",
     "The report can be scheduled to run weekly or monthly.", False),
    ("Confirmations are transferred to Time Management from Production Planning.",
     "Confirmations are transferred to Time Management from Process Control.", False),
]


def softmax(x):
    import numpy as np
    e = np.exp(x - np.max(x))
    return e / e.sum()


def run_moritz(pairs):
    """MoritzLaurer/mDeBERTa-v3-base-xnli — labels [entailment, neutral, contradiction]."""
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    name = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name)
    model.eval()
    id2label = model.config.id2label
    ent_idx = next(i for i, l in id2label.items() if "entail" in l.lower())
    scores = []
    with torch.no_grad():
        for src, claim, _ in pairs:
            inp = tok(src, claim, return_tensors="pt", truncation=True, max_length=512)
            logits = model(**inp).logits[0]
            p = softmax(logits.numpy())
            scores.append(float(p[ent_idx]))
    return scores


def run_crossenc_nli(pairs):
    """cross-encoder/nli-deberta-v3-base — labels [contradiction, entailment, neutral]."""
    from sentence_transformers import CrossEncoder
    name = "cross-encoder/nli-deberta-v3-base"
    ce = CrossEncoder(name)
    import numpy as np
    logits = ce.predict([(src, claim) for src, claim, _ in pairs],
                        apply_softmax=False, convert_to_numpy=True)
    # label map de ce modèle : 0=contradiction, 1=entailment, 2=neutral
    out = []
    for row in logits:
        p = softmax(np.array(row, dtype=float))
        out.append(float(p[1]))
    return out


def run_bge(pairs):
    """bge-reranker-v2-m3 — RERANKER (pertinence), pas NLI. Pour démonstration."""
    from knowbase.common.clients.reranker import get_cross_encoder
    ce = get_cross_encoder("BAAI/bge-reranker-v2-m3")
    sc = ce.predict([(src, claim) for src, claim, _ in pairs])
    return [float(s) for s in sc]


def separation(scores, labels):
    """Marge = min(score fidèle) - max(score hallu). >0 = séparation parfaite possible."""
    faith = [s for s, l in zip(scores, labels) if l]
    hallu = [s for s, l in zip(scores, labels) if not l]
    return min(faith), max(hallu), min(faith) - max(hallu)


def main():
    labels = [l for _, _, l in PAIRS]
    runners = [
        ("mDeBERTa-v3-xnli (NLI multilingue)", run_moritz),
        ("cross-encoder/nli-deberta-v3 (NLI)", run_crossenc_nli),
        ("bge-reranker-v2-m3 (RERANKER)", run_bge),
    ]
    results = {}
    for label_name, fn in runners:
        try:
            logger.info("Scoring : %s ...", label_name)
            results[label_name] = fn(PAIRS)
        except Exception as exc:
            logger.warning("  ÉCHEC %s : %s", label_name, exc)
            results[label_name] = None

    print("\n" + "=" * 100)
    print(f"{'PAIR':<58} {'lbl':<6} " + " ".join(f"{n.split('(')[0][:14]:>15}" for n, _ in runners))
    print("=" * 100)
    for i, (src, claim, lab) in enumerate(PAIRS):
        tag = "FIDÈLE" if lab else "HALLU"
        row = f"{claim[:56]:<58} {tag:<6} "
        for n, _ in runners:
            sc = results[n]
            row += f"{(f'{sc[i]:.3f}' if sc else 'n/a'):>15} " if sc else f"{'n/a':>15} "
        print(row)

    print("\n" + "=" * 100)
    print("SÉPARATION (min fidèle − max hallu ; >0 = un seuil sépare parfaitement) :")
    for n, _ in runners:
        sc = results[n]
        if not sc:
            print(f"  {n:<40} : n/a (échec chargement)")
            continue
        mn_f, mx_h, marg = separation(sc, labels)
        verdict = "✅ SÉPARE" if marg > 0 else "❌ NE SÉPARE PAS"
        print(f"  {n:<40} : min_fidèle={mn_f:.3f} max_hallu={mx_h:.3f} marge={marg:+.3f}  {verdict}")
    print("=" * 100)


if __name__ == "__main__":
    main()

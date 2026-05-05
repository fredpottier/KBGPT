"""
Génère 3 fichiers oracle (RAGAS, T2T5, Robustness) avec verdicts Claude
au format compatible UI admin/benchmarks.

Pour chaque question, Claude (oracle) a évalué manuellement la réponse OSMOSIS
contre la ground truth ou le contexte attendu. Les scores sont entre 0.0 et 1.0
basés sur :
- Justesse factuelle de la réponse vs GT
- Couverture des éléments attendus (claims, chain, references)
- Honnêteté (abstention si info absente vs faux négatif)

Source data :
- T2T5 : C:/Projects/SAP_KB/data/benchmark/results/t2t5_run_20260504_152954.json
- RAGAS : C:/Projects/SAP_KB/app/data/benchmark/results/ragas_run_20260504_140351.json
- ROBUST : C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_133914.json
"""
import json
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# T2T5 — Verdicts oracle Claude
# ─────────────────────────────────────────────────────────────────────────────
# Format: qid -> {"score": 0-1, "reason": str, "category": str}
# Categories:
#   OK = réponse correcte et complète
#   PARTIAL = correct mais incomplet (manque un côté de la contradiction, ou un élément de la chain)
#   ABSTENTION_VALID = abstient honnêtement (info vraiment absente)
#   ABSTENTION_FAUX_NEG = abstient alors que l'info est dans le corpus
#   HALLUC = invente ou affirme une fausseté (ex: 428/2009 toujours en vigueur)
#   OFF_TOPIC = répond mais hors-sujet (mauvais doc/amdt cité)
#   PREMISE_REJECTED = bonne détection de fausse prémisse

T2T5_ORACLE = {
    # T2 Contradictions
    "q_0": {"score": 0.4, "reason": "Cite seulement amdt 28 (21J) — manque amdt 26 (3.5J) et la tension entre les 2 valeurs", "category": "PARTIAL"},
    "q_1": {"score": 0.1, "reason": "Abstention faux négatif — l'abrogation de 428/2009 par 2021/821 est dans le corpus", "category": "ABSTENTION_FAUX_NEG"},
    "q_10": {"score": 0.1, "reason": "Abstention totale — la réponse 21J (amdt 28 = latest active) est trouvable dans le corpus", "category": "ABSTENTION_FAUX_NEG"},
    "q_11": {"score": 0.7, "reason": "Bonne comparaison des définitions de global export authorisation entre 428/2009 et 2021/821", "category": "OK"},
    "q_12": {"score": 0.2, "reason": "Abstention — la réponse correcte est NON (428/2009 abrogé), info dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "q_13": {"score": 0.3, "reason": "Mentionne 2023/996 et 2024/2547 mais pas 2023/66 (sujet central de la question)", "category": "OFF_TOPIC"},
    "q_14": {"score": 0.2, "reason": "INCORRECT — affirme que 428/2009 n'avait PAS de notification, faux (Article 4(4) le prescrit)", "category": "HALLUC"},
    "q_15": {"score": 0.7, "reason": "Bonne réponse — Subpart D et E sont complémentaires, pas contradictoires", "category": "OK"},
    "q_16": {"score": 0.2, "reason": "Décrit modifications amdt 23/24 sans aborder le service history (sujet central)", "category": "OFF_TOPIC"},
    "q_17": {"score": 0.7, "reason": "Bonne différenciation des exigences EU vs hors-EU dans 2021/821", "category": "OK"},
    "q_18": {"score": 0.4, "reason": "Décrit 2021/821 mais sans confronter explicitement à 2024/2547 (sujet)", "category": "PARTIAL"},
    "q_19": {"score": 0.7, "reason": "Bonne narration de la transition 428/2009 → 2021/821 sur public domain", "category": "OK"},
    "q_2": {"score": 0.3, "reason": "Cite seulement amdt 28 — GT demandait amdt 27 + change_amdt 24 (mono-source)", "category": "PARTIAL"},
    "q_20": {"score": 0.0, "reason": "HALLUCINATION — affirme que 428/2009 reste en vigueur, complètement faux (abrogé depuis 2021)", "category": "HALLUC"},
    "q_21": {"score": 0.7, "reason": "Bonne distinction CS (normatif) vs AMC (méthode acceptable)", "category": "OK"},
    "q_22": {"score": 0.6, "reason": "Réponse correcte (pas de conflit direct) mais peu nuancée", "category": "OK"},
    "q_23": {"score": 0.2, "reason": "Confond les 2 délégués — ne traite pas 2023/66 vs 2023/996 (sujet central)", "category": "OFF_TOPIC"},
    "q_24": {"score": 0.4, "reason": "Abstention partielle — la bonne réponse est NON (CS-25 et 2021/821 régulent des domaines différents)", "category": "ABSTENTION_FAUX_NEG"},
    "q_25": {"score": 0.7, "reason": "Réponse correcte (2021/821 applicable en juin 2021)", "category": "OK"},
    "q_26": {"score": 0.2, "reason": "Abstention — la réponse OUI (articles transferts intra-Union vs export) est dans le corpus", "category": "ABSTENTION_FAUX_NEG"},
    "q_27": {"score": 0.3, "reason": "Reconnaît que 'large project auth' n'est pas explicite ; mais 2021/821 le définit (Article 12)", "category": "ABSTENTION_FAUX_NEG"},
    "q_28": {"score": 0.4, "reason": "Réponse partielle sur philosophie CS-25, sans élaboration", "category": "PARTIAL"},
    "q_29": {"score": 0.7, "reason": "Abstention correcte (AI Act hors corpus)", "category": "ABSTENTION_VALID"},
    "q_3": {"score": 0.8, "reason": "Excellent — rejette correctement la fausse prémisse 'liste figée' en mentionnant les amendements", "category": "PREMISE_REJECTED"},
    "q_30": {"score": 0.4, "reason": "Abstention partielle — bonne réponse serait NON (amdt 22-27 évolutions, pas conflits)", "category": "ABSTENTION_FAUX_NEG"},
    "q_31": {"score": 0.6, "reason": "Bonne identification — Electronic Freight Transport Information est hors dual-use", "category": "OK"},
    "q_32": {"score": 0.2, "reason": "Abstention — l'Article 8 du 2021/821 traite la notification du fournisseur tech assistance", "category": "ABSTENTION_FAUX_NEG"},
    "q_33": {"score": 0.2, "reason": "Abstention — 2021/821 cite explicitement le respect de Reg 2016/679 (RGPD)", "category": "ABSTENTION_FAUX_NEG"},
    "q_34": {"score": 0.3, "reason": "Abstention — change_amdt et amdt principaux sont distincts mais pas contradictoires", "category": "ABSTENTION_FAUX_NEG"},
    "q_35": {"score": 0.6, "reason": "Bonne réponse (pas de contradiction CS 25.795 vs 25.785)", "category": "OK"},
    "q_36": {"score": 0.2, "reason": "Abstention — la bonne réponse est NON (l'exemption précise le scope)", "category": "ABSTENTION_FAUX_NEG"},
    "q_37": {"score": 0.1, "reason": "Hors-sujet — répond avec amdt 27 (CS-25) au lieu de 2024/2547 (dual-use)", "category": "OFF_TOPIC"},
    "q_38": {"score": 0.6, "reason": "Bonne réponse — amdt antérieurs restent valides (manuels approuvés)", "category": "OK"},
    "q_39": {"score": 0.3, "reason": "Abstention — la bonne réponse est OUI signaler le conflit 21J/3.5J (info dans corpus)", "category": "ABSTENTION_FAUX_NEG"},
    "q_4": {"score": 0.7, "reason": "Bonne narration de la continuité de l'exemption public domain", "category": "OK"},
    "q_5": {"score": 0.1, "reason": "Hors-sujet — répond avec amdt 25 au lieu de amdt 27 + change_amdt 24", "category": "OFF_TOPIC"},
    "q_6": {"score": 0.3, "reason": "Réponse partielle — interprète 'consumption goods' au lieu de comparer Annex I", "category": "PARTIAL"},
    "q_7": {"score": 0.2, "reason": "Abstention — Whereas clauses du 2021/821 mentionnent l'alignement avec Code des douanes", "category": "ABSTENTION_FAUX_NEG"},
    "q_8": {"score": 0.2, "reason": "Hors-sujet — répond avec amdt 23/24 au lieu de amdt 22 + 28 sur stability augmentation", "category": "OFF_TOPIC"},
    "q_9": {"score": 0.6, "reason": "Bonne narration brokering services (évolution 428/2009 → 2021/821)", "category": "OK"},
    # T5 Cross-doc
    "q_40": {"score": 0.6, "reason": "Bonne chronologie 428/2009 → 2021/821 → délégués 2023-2024 mais coupé en milieu", "category": "PARTIAL"},
    "q_41": {"score": 0.2, "reason": "INCORRECT — dit 'amdt 28 does not modify CS 25.795' alors qu'il est dans change tables", "category": "HALLUC"},
    "q_42": {"score": 0.4, "reason": "Cite 2024/2547 mais omet 428/2009 abrogé et délégués 2023/66, 2023/996", "category": "PARTIAL"},
    "q_43": {"score": 0.5, "reason": "Compare amdt 26 et 28 sur impact glass mais valeur 80J imprécise vs GT 3.5J", "category": "PARTIAL"},
    "q_44": {"score": 0.3, "reason": "Abstention — la bonne réponse est OUI (CS-25 + 2021/821 simultanés sur export aircraft)", "category": "ABSTENTION_FAUX_NEG"},
    "q_45": {"score": 0.7, "reason": "Bonne liste des CS paragraphes amendés via amdt 22", "category": "OK"},
    "q_46": {"score": 0.5, "reason": "Bonne narration 2023 → 2024 mais omet 2023/66", "category": "PARTIAL"},
    "q_47": {"score": 0.7, "reason": "Bonne narration regulatory chain 2009 → 2021 → 2024", "category": "OK"},
    "q_48": {"score": 0.1, "reason": "Hors-sujet — parle d'amdt 25 au lieu de amdt 27 + change_amdt 24 sur CS 25.1309", "category": "OFF_TOPIC"},
    "q_49": {"score": 0.2, "reason": "Abstention — la réponse correcte (CS-25 amdt 28 + 2021/821 + 2024/2547) est dans le corpus", "category": "ABSTENTION_FAUX_NEG"},
    "q_5": {"score": 0.1, "reason": "Hors-sujet — répond amdt 25 au lieu de amdt 27 + change_amdt 24", "category": "OFF_TOPIC"},
    "q_50": {"score": 0.4, "reason": "Décrit l'évolution mais imprécise sur les exemptions exact (public domain)", "category": "PARTIAL"},
    "q_51": {"score": 0.2, "reason": "Faux négatif — CS 25.705 created via NPA 2018-12 est dans amdt 28 change tables", "category": "ABSTENTION_FAUX_NEG"},
    "q_52": {"score": 0.3, "reason": "Décrit amdt 26 et 27 mais sans aborder les paragraphes supprimés (sujet)", "category": "PARTIAL"},
    "q_53": {"score": 0.2, "reason": "Abstention — chaîne d'autorisations (Article 12) dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "q_54": {"score": 0.5, "reason": "Réponse correcte sur Wassenaar/MTCR/NSG mais courte et générique", "category": "PARTIAL"},
    "q_55": {"score": 0.2, "reason": "Hors-sujet — mentionne amdt 22-26 sans aborder service history (sujet)", "category": "OFF_TOPIC"},
    "q_56": {"score": 0.2, "reason": "Hors-sujet — décrit amdt principaux (23, 24, 25, 26) au lieu de change_amdt", "category": "OFF_TOPIC"},
    "q_57": {"score": 0.3, "reason": "Abstention partielle — mentionne 2024/2547 mais pas le parcours complet 2021/821 + Annex I", "category": "PARTIAL"},
    "q_58": {"score": 0.2, "reason": "Faux négatif — CS 25.788 created NPA 2015-19 est dans amdt 28 change tables", "category": "ABSTENTION_FAUX_NEG"},
    "q_59": {"score": 0.2, "reason": "Abstention — Article 8 du 2021/821 traite des fournisseurs assistance technique", "category": "ABSTENTION_FAUX_NEG"},
    "q_6": {"score": 0.3, "reason": "Réponse partielle (interprète 'consumption goods' au lieu de comparer Annex I differences)", "category": "PARTIAL"},
    "q_60": {"score": 0.2, "reason": "Faux négatif — CS 25.629(d), 25.671, 25.672 amendés via NPA 2014-02 dans amdt 28", "category": "ABSTENTION_FAUX_NEG"},
    "q_61": {"score": 0.2, "reason": "Faux négatif — les dates de publication 2023/66 et 2023/996 sont dans le corpus", "category": "ABSTENTION_FAUX_NEG"},
    "q_62": {"score": 0.7, "reason": "Bonne réponse (CS, AMC, AC pour CS 25.1309)", "category": "OK"},
    "q_63": {"score": 0.2, "reason": "INCORRECT — cite 2024/2547 mais en juin 2024 c'est encore 2023/996 (publié 2023-02-23)", "category": "HALLUC"},
    "q_64": {"score": 0.2, "reason": "Abstention — 2021/821 cite explicitement Reg 952/2013, 2016/679, 2018/1725", "category": "ABSTENTION_FAUX_NEG"},
    "q_65": {"score": 0.2, "reason": "Hors-sujet — décrit amdt 23-26 au lieu de amdt 27 et 28 sur AMC 25.1322", "category": "OFF_TOPIC"},
    "q_66": {"score": 0.7, "reason": "Bonne narration des définitions 'global export authorisation' 428/2009 vs 2021/821", "category": "OK"},
    "q_67": {"score": 0.4, "reason": "Décrit catégorie 0 dans 428/2009 mais imprécis sur évolution chain Annex I", "category": "PARTIAL"},
    "q_68": {"score": 0.3, "reason": "Abstention — CS-25 + 2021/821 + 2024/2547 simultanés est documenté", "category": "ABSTENTION_FAUX_NEG"},
    "q_69": {"score": 0.2, "reason": "Hors-sujet — décrit amdt 25 et 26 au lieu de amdt 26 (2020) et 28 (2024) sur impact", "category": "OFF_TOPIC"},
    "q_7": {"score": 0.2, "reason": "Abstention — 2021/821 prescrit cohérence terminologique avec Reg 952/2013", "category": "ABSTENTION_FAUX_NEG"},
    "q_8": {"score": 0.2, "reason": "Hors-sujet — répond amdt 23-26 au lieu de amdt 22 et 28 sur stability augmentation", "category": "OFF_TOPIC"},
    "q_9": {"score": 0.6, "reason": "Bonne narration brokering services entre 428/2009 et 2021/821", "category": "OK"},
}


def generate_t2t5():
    src = json.load(open(r'C:/Projects/SAP_KB/data/benchmark/results/t2t5_run_20260504_152954.json', encoding='utf-8'))
    out = dict(src)  # copie
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    out["tag"] = "ORACLE_CLAUDE"
    out["description"] = "Oracle Claude — analyse manuelle 70/70 questions (CH-34 audit)"
    out["judge_mode"] = "oracle_claude"
    out["judge_model"] = "claude-opus-4-7-1m-context-via-session"

    # Per-sample : ajouter oracle_score, oracle_reason, oracle_category
    new_ps = []
    n_with_verdict = 0
    for s in src["per_sample"]:
        qid = s["question_id"]
        v = T2T5_ORACLE.get(qid)
        s_new = dict(s)
        if v:
            n_with_verdict += 1
            s_new["oracle_score"] = v["score"]
            s_new["oracle_reason"] = v["reason"]
            s_new["oracle_category"] = v["category"]
            # Override les eval keyword-based avec le verdict oracle
            if "evaluation" in s_new and isinstance(s_new["evaluation"], dict):
                s_new["evaluation"]["oracle_score"] = v["score"]
                s_new["evaluation"]["oracle_reason"] = v["reason"]
                s_new["evaluation"]["oracle_category"] = v["category"]
        else:
            s_new["oracle_score"] = None
            s_new["oracle_reason"] = "(non jugé)"
            s_new["oracle_category"] = "MISSING"
        new_ps.append(s_new)
    out["per_sample"] = new_ps

    # Aggregated scores : moyenne par task
    t2_scores = [v["score"] for k, v in T2T5_ORACLE.items() if any(s["question_id"] == k and s.get("task_name") == "T2 Contradictions" for s in src["per_sample"])]
    t5_scores = [v["score"] for k, v in T2T5_ORACLE.items() if any(s["question_id"] == k and s.get("task_name") == "T5 Cross-doc" for s in src["per_sample"])]
    all_scores = [v["score"] for v in T2T5_ORACLE.values()]

    t2_avg = round(sum(t2_scores) / max(1, len(t2_scores)), 4) if t2_scores else 0.0
    t5_avg = round(sum(t5_scores) / max(1, len(t5_scores)), 4) if t5_scores else 0.0
    global_avg = round(sum(all_scores) / max(1, len(all_scores)), 4)

    out["scores_oracle"] = {
        "oracle_global_score": global_avg,
        "oracle_t2_score": t2_avg,
        "oracle_t2_count": len(t2_scores),
        "oracle_t5_score": t5_avg,
        "oracle_t5_count": len(t5_scores),
        "n_oracle_verdicts": n_with_verdict,
    }

    # ✅ DASHBOARD VISIBILITY : écrase les champs scores.* lus par OverviewTab
    # T2 metrics → t2_avg, T5 metrics → t5_avg
    out.setdefault("scores", {}).update({
        "both_sides_surfaced": t2_avg,
        "tension_mentioned": t2_avg,
        "both_sources_cited": t2_avg,
        "chain_coverage": t5_avg,
        "multi_doc_cited": t5_avg,
        "proactive_detection": t5_avg,
        "t2_count": len(t2_scores),
        "t5_count": len(t5_scores),
        "total_evaluated": len(all_scores),
        # Marqueur clair que ces scores sont oracle-overrides
        "_source": "oracle_claude_override",
    })

    # Distribution des catégories
    cat_dist = {}
    for v in T2T5_ORACLE.values():
        cat_dist[v["category"]] = cat_dist.get(v["category"], 0) + 1
    out["scores_oracle"]["category_distribution"] = cat_dist

    out_path = Path(r"C:/Projects/SAP_KB/data/benchmark/results/t2t5_run_20260504_ORACLE_CLAUDE.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"T2T5 oracle saved → {out_path}")
    print(f"  Global oracle: {out['scores_oracle']['oracle_global_score']}")
    print(f"  T2 oracle: {out['scores_oracle']['oracle_t2_score']} (n={out['scores_oracle']['oracle_t2_count']})")
    print(f"  T5 oracle: {out['scores_oracle']['oracle_t5_score']} (n={out['scores_oracle']['oracle_t5_count']})")
    print(f"  Categories: {cat_dist}")


# ─────────────────────────────────────────────────────────────────────────────
# RAGAS — Verdicts oracle Claude (68 questions)
# ─────────────────────────────────────────────────────────────────────────────

RAGAS_ORACLE = {
    # T1 Provenance
    "T1 Provenance_0": {"score": 0.2, "reason": "Abstention faux négatif — 'large project authorisation' défini Article 12 du 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_1": {"score": 0.0, "reason": "HALLUCINATION — répond 'Decision 2015/019/R' alors que GT = ED Decision 2018/010/R", "category": "HALLUC"},
    "T1 Provenance_2": {"score": 0.7, "reason": "Correct — 'grands avions' ≈ 'Large Aeroplanes', mais manque 'turbine powered'", "category": "OK"},
    "T1 Provenance_3": {"score": 0.2, "reason": "Abstention faux négatif — GT = 30 jours ouvrables, info dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_4": {"score": 1.0, "reason": "Réponse parfaite — 'ED Decision 2023/021/R' verbatim + bon doc", "category": "OK"},
    "T1 Provenance_5": {"score": 0.4, "reason": "Décrit le scope contrôlé mais ne mentionne PAS l'exemption public domain (sujet)", "category": "PARTIAL"},
    "T1 Provenance_6": {"score": 0.2, "reason": "Abstention faux négatif — la définition 'global export authorisation' est Article 2 du 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_7": {"score": 0.7, "reason": "Cite correctement Reg 2021/821 mais mauvais doc cité (delegation 2024 au lieu d'original)", "category": "OK"},
    "T1 Provenance_8": {"score": 0.6, "reason": "'Tous les États membres EU' ≈ 'territoire douanier' mais imprécis (territoires non-douaniers exclus)", "category": "PARTIAL"},
    "T1 Provenance_9": {"score": 0.9, "reason": "Correct — Reg 428/2009 du 5 mai 2009 cité avec date exacte", "category": "OK"},
    "T1 Provenance_10": {"score": 0.2, "reason": "Abstention faux négatif — Reg 2016/679 (RGPD) + 2018/1725 sont cités dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_11": {"score": 0.1, "reason": "HALLUCINATION — répond 'Annexe I' alors que GT = 'Annexe IV' (transferts intra-EU)", "category": "HALLUC"},
    "T1 Provenance_12": {"score": 0.7, "reason": "Description correcte de Community General Export Authorisation", "category": "OK"},
    "T1 Provenance_13": {"score": 0.9, "reason": "Correct — 21 J, balle 51 mm cités, manque mention alternative 40 mm", "category": "OK"},
    "T1 Provenance_14": {"score": 0.2, "reason": "Abstention faux négatif — Article 3 du 2021/821 dit 'authorisation required'", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_15": {"score": 0.9, "reason": "Correct — Reg délégué 2023/66 du 21 oct 2022 cité avec date exacte", "category": "OK"},
    "T1 Provenance_16": {"score": 0.3, "reason": "Abstention partielle — la définition de 'Network access controller' est dans Annex I", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_17": {"score": 0.9, "reason": "Correct — Reg 2024/2547 du 5 sept 2024 cité avec date exacte", "category": "OK"},
    "T1 Provenance_18": {"score": 0.8, "reason": "Bonne définition de 'Intrusion software'", "category": "OK"},
    "T1 Provenance_19": {"score": 0.8, "reason": "Correct — Article 17(1) actes délégués mentionné", "category": "OK"},
    "T1 Provenance_20": {"score": 0.1, "reason": "INCORRECT — affirme 'aucun paragraphe NPA 2013-02', alors que GT = CS 25.734 + AMC 25.734", "category": "HALLUC"},
    "T1 Provenance_21": {"score": 0.9, "reason": "Correct — mention des régimes internationaux et arrangements de contrôle", "category": "OK"},
    "T1 Provenance_22": {"score": 0.2, "reason": "Abstention faux négatif — la division d'autorisation globale est dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_23": {"score": 0.2, "reason": "INCORRECT — cite CS 25.1319, AMC 25.1319 etc. mais GT = CS 25.705", "category": "HALLUC"},
    "T1 Provenance_24": {"score": 0.2, "reason": "Abstention faux négatif — GT = CS 25.629(d), 25.671, 25.672 amendés via NPA 2014-02", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_25": {"score": 0.2, "reason": "Abstention faux négatif — Article 8 du 2021/821 indique l'autorité State membre du courtier/fournisseur", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_26": {"score": 0.2, "reason": "Abstention faux négatif — l'Article 11 du 2021/821 indique 'État membre depuis lequel'", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_27": {"score": 0.8, "reason": "Correct — exemption public domain + basic scientific research + minimum patent applications", "category": "OK"},
    "T1 Provenance_28": {"score": 0.2, "reason": "INCORRECT — affirme 'ne mentionne pas spécifiquement' alors que 428/2009 contrôle bien WMD brokering", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_29": {"score": 0.9, "reason": "Excellente reformulation de CS 25.1309(c) sur unsafe operating conditions", "category": "OK"},
    "T1 Provenance_30": {"score": 0.4, "reason": "Réponse générique — manque la mention spécifique de CS 25.1322 (sujet GT)", "category": "PARTIAL"},
    "T1 Provenance_31": {"score": 1.0, "reason": "Parfait — date 24 nov 2021 correcte", "category": "OK"},
    "T1 Provenance_32": {"score": 0.5, "reason": "Cite CS 25.671 mais manque CS 25.672 (les 2 sont GT)", "category": "PARTIAL"},
    "T1 Provenance_33": {"score": 1.0, "reason": "Parfait — 11 juin 2021 correct", "category": "OK"},
    "T1 Provenance_34": {"score": 0.1, "reason": "HALLUCINATION — cite CS 25.1181-1203 alors que GT = CS 25.101-25.125 (performance)", "category": "HALLUC"},
    "T1 Provenance_35": {"score": 0.2, "reason": "Abstention faux négatif — 'Communications channel controller' défini dans Annex I dual-use", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_36": {"score": 0.3, "reason": "Abstention partielle — 0B001 (uranium plant) défini dans Annex I", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_37": {"score": 0.1, "reason": "HALLUCINATION — '1A006 = projectile liquide' alors que GT = équipements pour élimination IEDs", "category": "HALLUC"},
    "T1 Provenance_38": {"score": 0.1, "reason": "HALLUCINATION — cite régimes internationaux au lieu de Reg 952/2013 (Code des douanes)", "category": "HALLUC"},
    "T1 Provenance_39": {"score": 0.6, "reason": "Description correcte mais 'paragraphe 10' à vérifier", "category": "OK"},
    "T1 Provenance_40": {"score": 0.8, "reason": "Correct — l'autorisation couvre la technology minimale pour install/maintenance", "category": "OK"},
    "T1 Provenance_41": {"score": 0.6, "reason": "Cite OPCW + NSG mais manque Wassenaar Arrangement et MTCR explicites", "category": "PARTIAL"},
    "T1 Provenance_42": {"score": 1.0, "reason": "Parfait — Reg délégué 2023/996 du 23 février 2023", "category": "OK"},
    "T1 Provenance_43": {"score": 0.1, "reason": "INCORRECT — marque 'fausse prémisse' alors que CS 25.788 a bien été créé via NPA 2015-19", "category": "PREMISE_REJECTED_WRONG"},
    "T1 Provenance_44": {"score": 0.2, "reason": "Abstention faux négatif — GT = CS 25.729(f) supprimé via NPA 2013-02", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_45": {"score": 0.1, "reason": "HALLUCINATION — affirme '428/2009 n'impose PAS notification' alors que Article 4(4) le prescrit", "category": "HALLUC"},
    "T1 Provenance_46": {"score": 0.2, "reason": "Abstention faux négatif — l'Article 17(2) du 2021/821 traite ce cas", "category": "ABSTENTION_FAUX_NEG"},
    "T1 Provenance_47": {"score": 0.2, "reason": "INCORRECT — dit 'amdt 28 does not specifically indicate changes to CS 25.795' alors qu'il l'amende NPA 2015-11", "category": "HALLUC"},
    "T1 Provenance_48": {"score": 0.2, "reason": "Abstention faux négatif — Section I de l'Annex II est dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    # T5 Cross-doc (numéroté différemment dans RAGAS)
    "T5 Cross-doc_49": {"score": 0.5, "reason": "Mentionne 2024/2547 mais ne couvre pas la chain complète (428/2009 abrogé absent)", "category": "PARTIAL"},
    "T5 Cross-doc_50": {"score": 0.2, "reason": "INCORRECT — dit 'amdt 28 does not specifically modify CS 25.795', alors qu'amended NPA 2015-11", "category": "HALLUC"},
    "T1 Provenance_51": {"score": 0.2, "reason": "Abstention faux négatif — GT = CS 25.791(d), 25.831(a), AMC 25.831(a), CS 25.853(g) via NPA 2018-05", "category": "ABSTENTION_FAUX_NEG"},
    "T5 Cross-doc_52": {"score": 0.3, "reason": "Abstention partielle — la bonne réponse est OUI (CS-25 cert + 2021/821 export controls)", "category": "ABSTENTION_FAUX_NEG"},
    "T5 Cross-doc_53": {"score": 0.3, "reason": "Abstention partielle — CS 25.705 created NPA 2018-12 dans amdt 28 change tables", "category": "ABSTENTION_FAUX_NEG"},
    "T5 Cross-doc_54": {"score": 0.2, "reason": "Abstention faux négatif — la réponse complète (CS-25 + 2021/821 + 2024/2547) est dans le corpus", "category": "ABSTENTION_FAUX_NEG"},
    "T5 Cross-doc_55": {"score": 0.4, "reason": "Description générique sans détailler les exemptions Annex II Section I", "category": "PARTIAL"},
    "T5 Cross-doc_56": {"score": 0.7, "reason": "Bonne mention Wassenaar/MTCR/NSG mais sans timeline 428/2009 → 2021/821 → délégués", "category": "OK"},
    "T5 Cross-doc_57": {"score": 0.2, "reason": "Abstention faux négatif — GT = CS 25.629(d), 25.671, 25.672 dans amdt 28", "category": "ABSTENTION_FAUX_NEG"},
    "T5 Cross-doc_58": {"score": 0.2, "reason": "INCORRECT — répond avec amdt 26 alors que CS 25.788 created NPA 2015-19 dans amdt 28 change tables", "category": "HALLUC"},
    "T5 Cross-doc_59": {"score": 0.5, "reason": "Décrit cadre 2021/821 + 2024/2547 mais sans définition Communications channel controller", "category": "PARTIAL"},
    "T5 Cross-doc_60": {"score": 0.2, "reason": "Hors-sujet — cite amdt 22-26 sans aborder service history (CS 25.1309 hazard classification)", "category": "OFF_TOPIC"},
    "T5 Cross-doc_61": {"score": 0.2, "reason": "Abstention faux négatif — 428/2009 et 2021/821 traitent tech assistance providers", "category": "ABSTENTION_FAUX_NEG"},
    "T5 Cross-doc_62": {"score": 0.2, "reason": "INCORRECT — cite 2024/2547 alors qu'en juin 2024 c'est encore 2023/996 (publié 2024-09-05)", "category": "HALLUC"},
    "T5 Cross-doc_63": {"score": 0.2, "reason": "INCORRECT — cite Article 17(1) au lieu de Reg 952/2013, 2016/679, 2018/1725", "category": "HALLUC"},
    "T5 Cross-doc_64": {"score": 0.2, "reason": "Abstention faux négatif — les dates de publication 2023/66 (2022-10-21) et 2023/996 (2023-02-23) sont dans le corpus", "category": "ABSTENTION_FAUX_NEG"},
    "T5 Cross-doc_65": {"score": 0.7, "reason": "Bonne réponse CS, AMC, AC pour CS 25.1309", "category": "OK"},
    "T5 Cross-doc_66": {"score": 0.6, "reason": "Liste extensive paragraphes amdt 22 mais sans Decision 2018/010/R ni titre Appendix K", "category": "PARTIAL"},
    "T5 Cross-doc_67": {"score": 0.3, "reason": "Abstention partielle — CS-25 amdt 28 + 2021/821 + 2024/2547 sont dans le corpus pour cryptographie", "category": "ABSTENTION_FAUX_NEG"},
}


def generate_ragas():
    src = json.load(open(r'C:/Projects/SAP_KB/app/data/benchmark/results/ragas_run_20260504_140351.json', encoding='utf-8'))
    out = dict(src)
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    out["tag"] = "ORACLE_CLAUDE"
    out["description"] = "Oracle Claude — analyse manuelle 68/68 questions (CH-34 audit)"

    new_ps = []
    n_with_verdict = 0
    for s in src["per_sample"]:
        qid = s["question_id"]
        v = RAGAS_ORACLE.get(qid)
        s_new = dict(s)
        if v:
            n_with_verdict += 1
            s_new["oracle_score"] = v["score"]
            s_new["oracle_reason"] = v["reason"]
            s_new["oracle_category"] = v["category"]
        else:
            s_new["oracle_score"] = None
            s_new["oracle_reason"] = "(non jugé)"
            s_new["oracle_category"] = "MISSING"
        new_ps.append(s_new)
    out["per_sample"] = new_ps

    # Aggregated
    t1_scores = []
    t5_scores = []
    for s in src["per_sample"]:
        v = RAGAS_ORACLE.get(s["question_id"])
        if not v:
            continue
        if s.get("_task_name") == "T1 Provenance":
            t1_scores.append(v["score"])
        elif s.get("_task_name") == "T5 Cross-doc":
            t5_scores.append(v["score"])
    all_scores = [v["score"] for v in RAGAS_ORACLE.values()]

    global_avg = round(sum(all_scores) / max(1, len(all_scores)), 4)

    out["scores_oracle"] = {
        "oracle_global_score": global_avg,
        "oracle_t1_provenance_score": round(sum(t1_scores) / max(1, len(t1_scores)), 4) if t1_scores else 0.0,
        "oracle_t1_provenance_count": len(t1_scores),
        "oracle_t5_cross_doc_score": round(sum(t5_scores) / max(1, len(t5_scores)), 4) if t5_scores else 0.0,
        "oracle_t5_cross_doc_count": len(t5_scores),
        "n_oracle_verdicts": n_with_verdict,
    }

    # ✅ DASHBOARD VISIBILITY : OverviewTab lit systems.osmosis.scores.*
    # On override les 3 métriques pour qu'elles reflètent l'oracle
    if "systems" in out and "osmosis" in out["systems"]:
        out["systems"]["osmosis"].setdefault("scores", {}).update({
            "faithfulness": global_avg,
            "faithfulness_total": global_avg,
            "context_relevance": global_avg,
            "_source": "oracle_claude_override",
        })
    out.setdefault("scores", {}).update({
        "global_score": global_avg,
        "_source": "oracle_claude_override",
    })

    cat_dist = {}
    for v in RAGAS_ORACLE.values():
        cat_dist[v["category"]] = cat_dist.get(v["category"], 0) + 1
    out["scores_oracle"]["category_distribution"] = cat_dist

    out_path = Path(r"C:/Projects/SAP_KB/app/data/benchmark/results/ragas_run_20260504_ORACLE_CLAUDE.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"RAGAS oracle saved → {out_path}")
    print(f"  Global oracle: {out['scores_oracle']['oracle_global_score']}")
    print(f"  T1 Provenance: {out['scores_oracle']['oracle_t1_provenance_score']} (n={out['scores_oracle']['oracle_t1_provenance_count']})")
    print(f"  T5 Cross-doc:  {out['scores_oracle']['oracle_t5_cross_doc_score']} (n={out['scores_oracle']['oracle_t5_cross_doc_count']})")
    print(f"  Categories: {cat_dist}")


# ─────────────────────────────────────────────────────────────────────────────
# ROBUSTNESS — Verdicts oracle Claude (170 questions, 16 catégories)
# ─────────────────────────────────────────────────────────────────────────────

ROBUST_ORACLE = {
    # anchor_applicability_temporal (12)
    "q_123": {"score": 0.1, "reason": "Abstention faux négatif — CS-25 mars 2024 = amdt 28 (active depuis dec 2023)", "category": "ABSTENTION_FAUX_NEG"},
    "q_129": {"score": 0.1, "reason": "Abstention faux négatif — CS-25 sep 2020 = amdt 24 (active jul 2019)", "category": "ABSTENTION_FAUX_NEG"},
    "q_130": {"score": 0.9, "reason": "Correct — Amdt 28 dec 2023 latest", "category": "OK"},
    "q_131": {"score": 0.1, "reason": "Abstention faux négatif — dual-use mars 2020 = 428/2009 (encore en force)", "category": "ABSTENTION_FAUX_NEG"},
    "q_147": {"score": 0.3, "reason": "PARTIEL — amdt 22 cité mais date d'entrée en vigueur (nov 2018) postérieure à juillet 2018", "category": "PARTIAL"},
    "q_148": {"score": 0.0, "reason": "HALLUCINATION — cite 2024/2547 (dual-use) au lieu de CS-25 amdt 28", "category": "HALLUC"},
    "q_149": {"score": 0.9, "reason": "Correct — 2023/66 publié après 15 oct 2022, donc non applicable", "category": "OK"},
    "q_150": {"score": 0.5, "reason": "PARTIEL — amdt 28 + 2023/996 cités, manque 2023/66 et 2021/821", "category": "PARTIAL"},
    "q_155": {"score": 0.2, "reason": "INCORRECT — dossier mai 2019, amdt 23 entré juillet 2019 donc amdt 22 applicable", "category": "HALLUC"},
    "q_159": {"score": 0.0, "reason": "HALLUCINATION — 2024/2547 publié 5 sept 2024, en juillet 2024 c'est 2023/996", "category": "HALLUC"},
    "q_162": {"score": 0.6, "reason": "Réponse correcte (3.5 J amdt 26/27 applicable en 2021)", "category": "OK"},
    "q_168": {"score": 0.1, "reason": "Abstention faux négatif — dual-use 31 dec 2020 = 428/2009", "category": "ABSTENTION_FAUX_NEG"},

    # anchor_scope_hierarchy (9)
    "q_132": {"score": 0.1, "reason": "Abstention faux négatif — Annex I plus large (controls all dual-use), Annex IV intra-Union restreint", "category": "ABSTENTION_FAUX_NEG"},
    "q_133": {"score": 0.8, "reason": "Correct — CS-25 = large aeroplanes (catégorie spécifique)", "category": "OK"},
    "q_134": {"score": 0.1, "reason": "Abstention faux négatif — 2021/821 = dual-use export, 952/2013 = code des douanes général", "category": "ABSTENTION_FAUX_NEG"},
    "q_135": {"score": 0.1, "reason": "Abstention faux négatif — 0B001 = sub-cat catégorie 0 nucléaire dans Annex I", "category": "ABSTENTION_FAUX_NEG"},
    "q_136": {"score": 0.1, "reason": "Abstention faux négatif — global vs large project = autorisations distinctes (Article 12)", "category": "ABSTENTION_FAUX_NEG"},
    "q_137": {"score": 0.1, "reason": "Abstention faux négatif — CS = normatif, AMC = méthode acceptable", "category": "ABSTENTION_FAUX_NEG"},
    "q_157": {"score": 0.1, "reason": "Abstention faux négatif — Annex II plus restreint (general union auth pour destinations spécifiques)", "category": "ABSTENTION_FAUX_NEG"},
    "q_158": {"score": 0.5, "reason": "Décrit Subpart D avec exceptions, mais inclut faux signal de contradiction", "category": "PARTIAL"},
    "q_164": {"score": 0.1, "reason": "Abstention faux négatif — 1A006 = sub-cat catégorie 1 (matériaux spéciaux)", "category": "ABSTENTION_FAUX_NEG"},

    # causal_why (12)
    "q_36": {"score": 0.1, "reason": "Abstention faux négatif — l'abrogation/modernisation est documentée dans 2021/821 préambule", "category": "ABSTENTION_FAUX_NEG"},
    "q_37": {"score": 0.7, "reason": "Bonne explication — facilite références autorités + Australia Group", "category": "OK"},
    "q_38": {"score": 0.8, "reason": "Bonne explication — permet équipage prendre mesures correctives", "category": "OK"},
    "q_39": {"score": 0.4, "reason": "PARTIEL — confusion 80 J / 21 J ; explication amdt 26 → 28 imprécise", "category": "PARTIAL"},
    "q_40": {"score": 0.1, "reason": "Abstention faux négatif — le 2021/821 cite explicitement l'alignement avec 952/2013", "category": "ABSTENTION_FAUX_NEG"},
    "q_41": {"score": 0.1, "reason": "Abstention faux négatif — exemptions public domain documentées dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "q_42": {"score": 0.7, "reason": "Bonne distinction CS = exigences vs AMC = moyens de conformité", "category": "OK"},
    "q_43": {"score": 0.1, "reason": "INCORRECT — affirme que pouvoir actes délégués pas explicite, alors qu'Article 17 le confère", "category": "HALLUC"},
    "q_44": {"score": 0.1, "reason": "Abstention faux négatif — courtage et tech assistance traités séparément (Articles 6, 8)", "category": "ABSTENTION_FAUX_NEG"},
    "q_45": {"score": 0.0, "reason": "Abstention faux négatif — Article 14(5) impose 30 jours d'extension max", "category": "ABSTENTION_FAUX_NEG"},
    "q_46": {"score": 0.0, "reason": "Abstention faux négatif — uniformité des autorisations sur territoire douanier dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "q_47": {"score": 0.7, "reason": "Bonne explication CS 25.671/672 + stab augmentation pour sécurité système", "category": "OK"},

    # conditional (14)
    "q_106": {"score": 0.7, "reason": "Bonne réponse — non-Annex I généralement pas d'auth, mais tech reste contrôlée", "category": "OK"},
    "q_107": {"score": 0.1, "reason": "Abstention faux négatif — Article 14(5) prévoit 30j extension, total 40j possible", "category": "ABSTENTION_FAUX_NEG"},
    "q_108": {"score": 0.3, "reason": "Hors-sujet — cite CS 25.679 alors que GT = CS 25.671 + 25.672", "category": "OFF_TOPIC"},
    "q_109": {"score": 0.1, "reason": "Abstention faux négatif — Article 8 indique l'autorité MS où le courtier opère", "category": "ABSTENTION_FAUX_NEG"},
    "q_110": {"score": 0.1, "reason": "Abstention faux négatif — Article 12(8) permet division des autorisations globales", "category": "ABSTENTION_FAUX_NEG"},
    "q_111": {"score": 0.2, "reason": "Abstention faux négatif — coordination Annex I/II/IV documentée dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "q_112": {"score": 0.0, "reason": "Hors-sujet — répond avec docs export controls au lieu d'amdt 28 (CS-25)", "category": "OFF_TOPIC"},
    "q_113": {"score": 0.6, "reason": "Cite RGPD, raisonnable mais aurait pu citer Reg 2018/1725 aussi", "category": "PARTIAL"},
    "q_114": {"score": 0.1, "reason": "Abstention faux négatif — Article 8 oblige notification autorité compétente", "category": "ABSTENTION_FAUX_NEG"},
    "q_115": {"score": 0.1, "reason": "Abstention faux négatif — Article 25 prévoit échange d'informations entre MS via Commission", "category": "ABSTENTION_FAUX_NEG"},
    "q_116": {"score": 0.2, "reason": "Abstention faux négatif — Annex IV Part 2 sous 428/2009 nécessitait auth individuelle", "category": "ABSTENTION_FAUX_NEG"},
    "q_117": {"score": 0.1, "reason": "Abstention faux négatif — Article 14(5) permet expressément l'extension", "category": "ABSTENTION_FAUX_NEG"},
    "q_118": {"score": 0.4, "reason": "Meta-question OSMOSIS — abstention partiellement justifiée", "category": "ABSTENTION_VALID"},
    "q_119": {"score": 0.4, "reason": "Meta-question OSMOSIS — abstention partiellement justifiée", "category": "ABSTENTION_VALID"},

    # false_premise (12)
    "q_0": {"score": 0.7, "reason": "Bonne identification de fausse prémisse + précise la nature réelle des contrôles", "category": "PREMISE_REJECTED"},
    "q_1": {"score": 0.8, "reason": "Bonne rejection — amdt 28 n'abroge pas tout, juste modifications listées", "category": "PREMISE_REJECTED"},
    "q_2": {"score": 0.8, "reason": "Bonne rejection — 2024/2547 modifie 2021/821, pas 428/2009", "category": "PREMISE_REJECTED"},
    "q_3": {"score": 0.4, "reason": "Abstention partielle — devrait rejeter explicitement (CS-25 = large aeroplanes uniquement)", "category": "ABSTENTION_FAUX_NEG"},
    "q_4": {"score": 0.9, "reason": "Excellent — rejection explicite avec citation evidence (exceptions to control)", "category": "PREMISE_REJECTED"},
    "q_5": {"score": 0.4, "reason": "Abstention — devrait rejeter explicitement le délai 60j (en réalité ~30j + 30j extension)", "category": "PARTIAL"},
    "q_6": {"score": 0.2, "reason": "Abstention faux négatif — Annex IV = transferts INTRA-Union (pas pays tiers)", "category": "ABSTENTION_FAUX_NEG"},
    "q_7": {"score": 0.9, "reason": "Excellent — rejection avec evidence (21J et non 50J)", "category": "PREMISE_REJECTED"},
    "q_8": {"score": 0.3, "reason": "Abstention partielle — devrait rejeter explicitement (procedure majoritaire/codécision pas unanimité)", "category": "ABSTENTION_FAUX_NEG"},
    "q_9": {"score": 0.2, "reason": "INCORRECT — affirme que 2021/821 n'aborde pas le sujet, alors qu'il référence RGPD", "category": "HALLUC"},
    "q_10": {"score": 0.5, "reason": "Rejection correcte mais peu nuancée — les autorités MS (pas EASA) accordent autorisations", "category": "PARTIAL"},
    "q_11": {"score": 0.0, "reason": "HALLUCINATION — affirme que amdt 22 a introduit 21J (en réalité c'est amdt 28)", "category": "HALLUC"},

    # hypothetical (10)
    "q_48": {"score": 0.5, "reason": "Abstention sur hypothétique pure, raisonnable", "category": "ABSTENTION_VALID"},
    "q_49": {"score": 0.6, "reason": "Bonne réponse abstraite — version précédente applicable", "category": "OK"},
    "q_50": {"score": 0.5, "reason": "Abstention sur hypothétique pure, raisonnable", "category": "ABSTENTION_VALID"},
    "q_51": {"score": 0.5, "reason": "Abstention sur hypothétique amdt 29, raisonnable", "category": "ABSTENTION_VALID"},
    "q_52": {"score": 0.2, "reason": "Abstention faux négatif — Article 12(4) permet à un MS de restreindre auth générale", "category": "ABSTENTION_FAUX_NEG"},
    "q_53": {"score": 0.6, "reason": "Réponse hypothétique cohérente sur la réintroduction du régime 428/2009", "category": "OK"},
    "q_54": {"score": 0.3, "reason": "Abstention partielle — recours administratif national aurait pu être mentionné", "category": "ABSTENTION_FAUX_NEG"},
    "q_55": {"score": 0.3, "reason": "Abstention partielle — concept de grandfathering non mentionné", "category": "ABSTENTION_FAUX_NEG"},
    "q_56": {"score": 0.5, "reason": "Réponse partielle — auth requise même hors Annex I (catch-all)", "category": "PARTIAL"},
    "q_57": {"score": 0.4, "reason": "Abstention sur hypothétique correction d'erreur, raisonnable", "category": "ABSTENTION_VALID"},

    # lifecycle_evolves_from (7)
    "q_121": {"score": 0.3, "reason": "PARTIEL — cite 2023/66 seulement, manque 2023/996 et 2024/2547", "category": "PARTIAL"},
    "q_126": {"score": 0.0, "reason": "Abstention totale — devrait répondre 2024/2547 (le plus récent)", "category": "ABSTENTION_FAUX_NEG"},
    "q_127": {"score": 0.6, "reason": "Bonne timeline (2021/821 → 2023/66 → 2023/996) mais manque 2024/2547", "category": "PARTIAL"},
    "q_152": {"score": 0.7, "reason": "Bonne réponse — tous les actes délégués modifient l'Annex I", "category": "OK"},
    "q_156": {"score": 0.2, "reason": "Abstention faux négatif — relation amdt 27→28 = EVOLVES_FROM (lifecycle CS-25)", "category": "ABSTENTION_FAUX_NEG"},
    "q_163": {"score": 0.3, "reason": "Abstention partielle — réponse correcte serait NON (EVOLVES_FROM ≠ DEPRECATED)", "category": "ABSTENTION_FAUX_NEG"},
    "q_166": {"score": 0.3, "reason": "Abstention partielle — change_amdt sont en lifecycle (annex à l'amdt principal)", "category": "ABSTENTION_FAUX_NEG"},

    # lifecycle_filtering_active (9)
    "q_122": {"score": 0.8, "reason": "Correct — 2024/2547 actuellement en vigueur", "category": "OK"},
    "q_128": {"score": 0.7, "reason": "Bonne réponse — Annex I de 2021/821 amendée par derniers délégués", "category": "OK"},
    "q_138": {"score": 0.0, "reason": "HALLUCINATION — affirme qu'il faut citer 428/2009 alors qu'il est DEPRECATED", "category": "HALLUC"},
    "q_139": {"score": 0.4, "reason": "PARTIEL — cite 2024/2547 mais manque 2021/821 base + délégués 2023", "category": "PARTIAL"},
    "q_140": {"score": 0.7, "reason": "Bonne réponse — Annex I originale obsolète, consulter version amendée", "category": "OK"},
    "q_141": {"score": 0.4, "reason": "Meta-question — abstention raisonnable", "category": "ABSTENTION_VALID"},
    "q_154": {"score": 0.0, "reason": "HALLUCINATION — affirme que 428/2009 est encore en vigueur (alors qu'abrogé par 2021/821)", "category": "HALLUC"},
    "q_160": {"score": 0.7, "reason": "Bonne explication du risque (info obsolète, sanctions)", "category": "OK"},
    "q_167": {"score": 0.3, "reason": "Abstention faux négatif — devrait pouvoir compter via filtre KG", "category": "ABSTENTION_FAUX_NEG"},

    # lifecycle_supersedes (5)
    "q_120": {"score": 0.1, "reason": "Abstention faux négatif — 2021/821 a explicitement remplacé 428/2009", "category": "ABSTENTION_FAUX_NEG"},
    "q_125": {"score": 0.9, "reason": "Correct — 428/2009 remplacé par 2021/821", "category": "OK"},
    "q_151": {"score": 0.3, "reason": "Abstention sur question SUPERSEDES, devrait au moins citer 428→2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "q_153": {"score": 0.2, "reason": "Abstention faux négatif — 2021/821 abroge totalement 428/2009 (Article 41)", "category": "ABSTENTION_FAUX_NEG"},
    "q_165": {"score": 0.3, "reason": "Meta-question count SUPERSEDES — abstention partiellement justifiée", "category": "ABSTENTION_FAUX_NEG"},

    # lifecycle_vs_conflict (8)
    "q_124": {"score": 0.2, "reason": "Abstention faux négatif — 3.5J→21J = lifecycle (pas vraie contradiction)", "category": "ABSTENTION_FAUX_NEG"},
    "q_142": {"score": 0.3, "reason": "Meta-question OSMOSIS — abstention raisonnable", "category": "ABSTENTION_VALID"},
    "q_143": {"score": 0.4, "reason": "Abstention partielle — devrait expliciter que c'est lifecycle, pas contradiction", "category": "PARTIAL"},
    "q_144": {"score": 0.6, "reason": "Bonne réponse — pas de contradiction (CS-25 et 2021/821 = domaines différents)", "category": "OK"},
    "q_145": {"score": 0.7, "reason": "Bonne distinction réaffirmation vs contradiction sur amdt 23/24", "category": "OK"},
    "q_146": {"score": 0.8, "reason": "Excellent — différences Annex I 2024/2547 vs 2021/821 = lifecycle update, pas contradiction", "category": "OK"},
    "q_161": {"score": 0.3, "reason": "Abstention partielle — devrait identifier amdt 27 vs change_amdt 24 comme lifecycle", "category": "ABSTENTION_FAUX_NEG"},
    "q_169": {"score": 0.3, "reason": "Meta-question bench V2 — abstention raisonnable", "category": "ABSTENTION_VALID"},

    # multi_hop (12)
    "q_80": {"score": 0.1, "reason": "Abstention faux négatif — chaîne attendue : 2024/2547 (item) → 2021/821 (auth) → DGDDI (FR)", "category": "ABSTENTION_FAUX_NEG"},
    "q_81": {"score": 0.5, "reason": "Réponse case-by-case + Agency raisonnable mais peu spécifique", "category": "PARTIAL"},
    "q_82": {"score": 0.1, "reason": "Abstention faux négatif — chaîne 0B001 (Annex I cat 0) → 2021/821 → 2023/996 → auth nucléaire", "category": "ABSTENTION_FAUX_NEG"},
    "q_83": {"score": 0.1, "reason": "Abstention faux négatif — major change 2024 = 21J pour portion modifiée (latest amdt 28)", "category": "ABSTENTION_FAUX_NEG"},
    "q_84": {"score": 0.1, "reason": "Abstention faux négatif — chaîne crypto cat 5 → 2021/821 + 2024/2547 + Annex I", "category": "ABSTENTION_FAUX_NEG"},
    "q_85": {"score": 0.1, "reason": "Abstention faux négatif — Article 8 oblige notification autorité MS si tech assistance Annex I", "category": "ABSTENTION_FAUX_NEG"},
    "q_86": {"score": 0.5, "reason": "Réponse partielle sur la validité 2020 sous 428/2009", "category": "PARTIAL"},
    "q_87": {"score": 0.6, "reason": "Bonne réponse 2023/996 applicable mai 2023", "category": "OK"},
    "q_88": {"score": 0.1, "reason": "Abstention faux négatif — devrait expliquer lifecycle 3.5J (amdt 26) → 21J (amdt 28)", "category": "ABSTENTION_FAUX_NEG"},
    "q_89": {"score": 0.2, "reason": "Hors-sujet — répond sur tests existants au lieu de cadre 428/2009 applicable 2018", "category": "OFF_TOPIC"},
    "q_90": {"score": 0.1, "reason": "Abstention faux négatif — devrait expliquer qu'il s'agit de lifecycle (pas de conflit réel)", "category": "ABSTENTION_FAUX_NEG"},
    "q_91": {"score": 0.4, "reason": "Réponse partielle — cite 2023/996 mais pas la cascade complète", "category": "PARTIAL"},

    # negation (10)
    "q_58": {"score": 0.6, "reason": "Bonne identification exemption ITU radio frequencies", "category": "OK"},
    "q_59": {"score": 0.1, "reason": "Hors-sujet — devrait répondre 'pas large aeroplanes' (helicoptères CS-29, petits CS-23)", "category": "OFF_TOPIC"},
    "q_60": {"score": 0.2, "reason": "PARTIEL — cite seulement 2023/996, manque 2021/821, 2024/2547, CS-25 amdt 28", "category": "PARTIAL"},
    "q_61": {"score": 0.4, "reason": "PARTIEL — explique 2023/66 modifie mais ne liste pas explicitement les non-modifiants", "category": "PARTIAL"},
    "q_62": {"score": 0.3, "reason": "PARTIEL — liste des AMC sans clarté sur classification 'Amended' vs 'Created'", "category": "PARTIAL"},
    "q_63": {"score": 0.2, "reason": "Abstention faux négatif — exemptions Article 9 listées dans 2021/821", "category": "ABSTENTION_FAUX_NEG"},
    "q_64": {"score": 0.3, "reason": "PARTIEL — liste des paragraphes mais explication confuse", "category": "PARTIAL"},
    "q_65": {"score": 0.7, "reason": "Bonne gestion double négation — contrôle, pas interdiction totale", "category": "OK"},
    "q_66": {"score": 0.7, "reason": "Bonne réponse — public domain, basic research, patents", "category": "OK"},
    "q_67": {"score": 0.6, "reason": "Réponse partielle sur acteurs (software, consulting) ajoutés par 2021/821", "category": "PARTIAL"},

    # set_list (14)
    "q_92": {"score": 0.2, "reason": "HALLUCINATION — liste amdts 9, 10, 11 avec dates aléatoires (le corpus ne contient que amdts 22-28)", "category": "HALLUC"},
    "q_93": {"score": 0.1, "reason": "Abstention faux négatif — devrait lister 2023/66, 2023/996, 2024/2547", "category": "ABSTENTION_FAUX_NEG"},
    "q_94": {"score": 0.2, "reason": "PARTIEL — cite NPA 2019-01 mais pas NPA 2015-19 (sujet)", "category": "PARTIAL"},
    "q_95": {"score": 0.3, "reason": "PARTIEL — vague (licences) au lieu de lister types : individual, global, large project, EU general", "category": "PARTIAL"},
    "q_96": {"score": 0.5, "reason": "PARTIEL — exemptions ITU + tech contrôlée, mais manque public domain, basic research", "category": "PARTIAL"},
    "q_97": {"score": 0.1, "reason": "Abstention faux négatif — paragraphes NPA 2015-11 sont dans amdt 28 change tables", "category": "ABSTENTION_FAUX_NEG"},
    "q_98": {"score": 0.9, "reason": "Excellent — OPCW, NSG, MTCR, Australia, Wassenaar tous cités", "category": "OK"},
    "q_99": {"score": 0.2, "reason": "Abstention faux négatif — devrait lister 428/2009 (DEPRECATED principal)", "category": "ABSTENTION_FAUX_NEG"},
    "q_100": {"score": 0.3, "reason": "PARTIEL — seulement 2015/479, manque 952/2013, 2016/679, 2018/1725", "category": "PARTIAL"},
    "q_101": {"score": 0.0, "reason": "HALLUCINATION — connecteurs missile/launcher (off-topic, pas LIFECYCLE_RELATION)", "category": "HALLUC"},
    "q_102": {"score": 0.2, "reason": "Hors-sujet — décrit subparts amdt 26 au lieu de lister change_amdt", "category": "OFF_TOPIC"},
    "q_103": {"score": 0.1, "reason": "Abstention faux négatif — public domain, basic research, patents, intra-Union (sauf Annex IV)", "category": "ABSTENTION_FAUX_NEG"},
    "q_104": {"score": 0.3, "reason": "Meta-question CONFLICTS — abstention partiellement justifiée", "category": "ABSTENTION_FAUX_NEG"},
    "q_105": {"score": 0.5, "reason": "PARTIEL — cite NPA 2008-01, 2019-01, 2008-05 (liste plausible mais incomplète)", "category": "PARTIAL"},

    # synthesis_large (12)
    "q_68": {"score": 0.5, "reason": "PARTIEL — 2024/2547 + 2021/821 + Common Military List, mais manque lifecycle/exclusions détaillées", "category": "PARTIAL"},
    "q_69": {"score": 0.5, "reason": "PARTIEL — individual + general licences mais manque global et large project", "category": "PARTIAL"},
    "q_70": {"score": 0.5, "reason": "PARTIEL — timeline amdt 25→26→27→28 décente mais ordre confus (commence par amdt 25 au lieu de 22)", "category": "PARTIAL"},
    "q_71": {"score": 0.5, "reason": "PARTIEL — 2021/821 + 2024/2547 + régimes mais manque CS-25 (sujet de la question)", "category": "PARTIAL"},
    "q_72": {"score": 0.2, "reason": "Abstention faux négatif — exemptions documentées : public domain, basic research, etc.", "category": "ABSTENTION_FAUX_NEG"},
    "q_73": {"score": 0.5, "reason": "PARTIEL — chaîne régimes → Annex I → 2024/2547 → opérateurs raisonnable", "category": "PARTIAL"},
    "q_74": {"score": 0.3, "reason": "Meta-question LIFECYCLE — abstention raisonnable", "category": "ABSTENTION_VALID"},
    "q_75": {"score": 0.7, "reason": "Bonne réponse — 2021/821 applicable avril 2022, 2023/66 pas encore en vigueur", "category": "OK"},
    "q_76": {"score": 0.0, "reason": "Abstention faux négatif — différences 2021/821 vs 428/2009 documentées (scope, brokering, tech assistance)", "category": "ABSTENTION_FAUX_NEG"},
    "q_77": {"score": 0.5, "reason": "PARTIEL — 25.561, 25.785, manuels, mais manque CS 25.795 (sujet)", "category": "PARTIAL"},
    "q_78": {"score": 0.5, "reason": "Description Annex I + cat 0 nucléaire raisonnable", "category": "PARTIAL"},
    "q_79": {"score": 0.3, "reason": "PARTIEL — exporter notification mais omet brokers et tech assistance providers", "category": "PARTIAL"},

    # temporal_evolution (12)
    "q_24": {"score": 0.7, "reason": "Correct — amdt 24 applicable juin 2020 (Decision 2020/001/R)", "category": "OK"},
    "q_25": {"score": 0.1, "reason": "Abstention faux négatif — mars 2020 = 428/2009 (encore en vigueur)", "category": "ABSTENTION_FAUX_NEG"},
    "q_26": {"score": 0.1, "reason": "INCORRECT — cite 2024/2547 (5 sept 2024) comme avant juin 2024 (date postérieure)", "category": "HALLUC"},
    "q_27": {"score": 0.1, "reason": "Abstention faux négatif — juillet 2019 = amdt 22 (publié août 2018) ou amdt 23", "category": "ABSTENTION_FAUX_NEG"},
    "q_28": {"score": 0.1, "reason": "Abstention faux négatif — nov 2022 = 3.5 J (amdt 26 active)", "category": "ABSTENTION_FAUX_NEG"},
    "q_29": {"score": 0.1, "reason": "Abstention faux négatif — 31 dec 2023 = amdt 28 (active 15 dec 2023)", "category": "ABSTENTION_FAUX_NEG"},
    "q_30": {"score": 0.1, "reason": "Abstention faux négatif — 1 jan 2022 = NON (428/2009 abrogé sept 2021)", "category": "ABSTENTION_FAUX_NEG"},
    "q_31": {"score": 0.5, "reason": "PARTIEL — Annex I 2021/821 applicable, mais 2023/66 avait déjà été publié à cette date", "category": "PARTIAL"},
    "q_32": {"score": 0.5, "reason": "PARTIEL — sept 2022 = 2021/821 original Annex I (2023/66 vient en jan 2023)", "category": "PARTIAL"},
    "q_33": {"score": 0.1, "reason": "Abstention faux négatif — aujourd'hui CS 25.795 = amdt 28 (latest)", "category": "ABSTENTION_FAUX_NEG"},
    "q_34": {"score": 0.1, "reason": "INCORRECT — répond 2021/821 (originel) au lieu de 2023/996 (publié fév 2023, juste avant 2024/2547)", "category": "HALLUC"},
    "q_35": {"score": 0.1, "reason": "Abstention faux négatif — juin 2021 = amdt 26 (publié juillet 2020)", "category": "ABSTENTION_FAUX_NEG"},

    # unanswerable (12)
    "q_12": {"score": 0.9, "reason": "Excellent — abstention correcte (info hors corpus)", "category": "ABSTENTION_VALID"},
    "q_13": {"score": 0.9, "reason": "Excellent — abstention correcte (amdt 29 inexistant)", "category": "ABSTENTION_VALID"},
    "q_14": {"score": 0.9, "reason": "Excellent — abstention correcte (statistiques hors corpus)", "category": "ABSTENTION_VALID"},
    "q_15": {"score": 0.0, "reason": "HALLUCINATION — Ursula VON DER LEYEN ne signe pas les actes délégués (ils sont signés par le Commissaire compétent)", "category": "HALLUC"},
    "q_16": {"score": 0.8, "reason": "Bonne abstention — pas de valeur unique CS-25 (établie cas par cas)", "category": "ABSTENTION_VALID"},
    "q_17": {"score": 0.9, "reason": "Excellent — abstention correcte (position politique hors corpus)", "category": "ABSTENTION_VALID"},
    "q_18": {"score": 0.9, "reason": "Excellent — abstention correcte (frais nationaux hors corpus)", "category": "ABSTENTION_VALID"},
    "q_19": {"score": 0.9, "reason": "Excellent — abstention correcte (opinion individuelle hors corpus)", "category": "ABSTENTION_VALID"},
    "q_20": {"score": 0.0, "reason": "HALLUCINATION — invente 80J pour amdt 30 (inexistant)", "category": "HALLUC"},
    "q_21": {"score": 0.2, "reason": "PARTIEL — liste partielle au lieu d'avouer ne pas avoir le décompte exact", "category": "PARTIAL"},
    "q_22": {"score": 0.7, "reason": "Bonne abstention — info hors corpus", "category": "ABSTENTION_VALID"},
    "q_23": {"score": 0.6, "reason": "Bonne abstention partielle (jurisprudence hors corpus)", "category": "ABSTENTION_VALID"},
}


def generate_robust():
    src = json.load(open(r'C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_133914.json', encoding='utf-8'))
    out = dict(src)
    out["timestamp"] = datetime.now(timezone.utc).isoformat()
    out["tag"] = "ORACLE_CLAUDE"
    out["description"] = "Oracle Claude — analyse manuelle 170/170 questions (CH-34 audit)"
    out["judge_mode"] = "oracle_claude"
    out["judge_model"] = "claude-opus-4-7-1m-context-via-session"

    # Per-sample : oracle annotations
    new_ps = []
    n_with_verdict = 0
    by_cat_scores = {}
    for s in src["per_sample"]:
        qid = s["question_id"]
        v = ROBUST_ORACLE.get(qid)
        s_new = dict(s)
        if v:
            n_with_verdict += 1
            s_new["oracle_score"] = v["score"]
            s_new["oracle_reason"] = v["reason"]
            s_new["oracle_category"] = v["category"]
            if "evaluation" in s_new and isinstance(s_new["evaluation"], dict):
                s_new["evaluation"]["oracle_score"] = v["score"]
                s_new["evaluation"]["oracle_reason"] = v["reason"]
                s_new["evaluation"]["oracle_category"] = v["category"]
            cat = s.get("category", "unknown")
            by_cat_scores.setdefault(cat, []).append(v["score"])
        else:
            s_new["oracle_score"] = None
            s_new["oracle_reason"] = "(non jugé)"
            s_new["oracle_category"] = "MISSING"
        new_ps.append(s_new)
    out["per_sample"] = new_ps

    all_scores = [v["score"] for v in ROBUST_ORACLE.values()]
    by_cat_avg = {cat: round(sum(scores) / max(1, len(scores)), 4) for cat, scores in by_cat_scores.items()}
    global_avg = round(sum(all_scores) / max(1, len(all_scores)), 4)

    out["scores_oracle"] = {
        "oracle_global_score": global_avg,
        "oracle_per_category": by_cat_avg,
        "n_oracle_verdicts": n_with_verdict,
    }

    # ✅ DASHBOARD VISIBILITY : RobustnessTab + OverviewTab lisent scores.global_score
    # et scores.<cat>_score
    scores_override = {
        "global_score": global_avg,
        "total_evaluated": len(all_scores),
        "total_errors": 0,
        "_source": "oracle_claude_override",
    }
    for cat, score in by_cat_avg.items():
        scores_override[f"{cat}_score"] = score
        scores_override[f"{cat}_count"] = len(by_cat_scores[cat])
    # Maintien des aliases dashboard (paraphrase / negation / robustness OverviewTab)
    if "negation" in by_cat_avg:
        scores_override["negation_score"] = by_cat_avg["negation"]
    out["scores"] = scores_override

    cat_dist = {}
    for v in ROBUST_ORACLE.values():
        cat_dist[v["category"]] = cat_dist.get(v["category"], 0) + 1
    out["scores_oracle"]["category_distribution"] = cat_dist

    out_path = Path(r"C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_ORACLE_CLAUDE.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"ROBUST oracle saved → {out_path}")
    print(f"  Global oracle: {out['scores_oracle']['oracle_global_score']}")
    print(f"  Per-category averages:")
    for cat, score in sorted(by_cat_avg.items(), key=lambda x: -x[1]):
        n = len(by_cat_scores[cat])
        print(f"    {cat:35s} {score:.3f} (n={n})")
    print(f"  Categories distribution: {cat_dist}")


if __name__ == "__main__":
    generate_t2t5()
    print()
    generate_ragas()
    print()
    generate_robust()

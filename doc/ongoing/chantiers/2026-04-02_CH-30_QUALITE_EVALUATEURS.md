# Chantier — Qualite des evaluateurs de benchmark

**Date** : 2 avril 2026
**Statut** : A traiter — audit necessaire avant de se fier aux scores
**Priorite** : Haute — les scores actuels peuvent etre trompeurs

---

## 1. Probleme identifie

Les evaluateurs de benchmark (robustesse, T2/T5, RAGAS) utilisent du **keyword matching** pour noter les reponses. Cette approche est rapide et deterministe mais elle mesure la **presence d'elements** (dates, mots-cles, noms de documents) et non la **qualite reelle** de la reponse.

### Exemple concret

Question : "Le scope fonctionnel du SAP S/4HANA Cloud Private Edition a-t-il change entre FPS03 et l'edition 2025 ?"

Reponse OSMOSIS : "Oui, le scope fonctionnel a change [...] mais les documents disponibles ne fournissent que des **indices partiels** de ces changements plutot qu'une comparaison exhaustive"

Evaluation :
- temporal_awareness : **100%** (mentionne "2023" et "2025")
- docs_cited : **100%** (les doc IDs apparaissent dans les sources)
- change_identified : **67%** (certains mots-cles du changement trouves)
- **Score final : 87%**

Probleme : un score de 87% pour une reponse qui admet elle-meme n'avoir que des "indices partiels" est **trompeur**. L'evaluateur ne capture pas que la reponse est incomplete.

### Consequence

Les scores de benchmark peuvent :
- **Surestimer** la qualite (un 87% qui devrait etre 50%)
- **Sous-estimer** la qualite (une bonne reponse formulee differemment qui rate les mots-cles)
- **Mal classifier** OK vs ECHEC (une reponse mediocre classee OK, une bonne reponse classee ECHEC)

Cela rend les comparaisons entre versions (V10 vs V12, Haiku vs GPT-4o-mini) potentiellement non fiables.

---

## 2. Evaluateurs concernes

### Robustesse (robustness_diagnostic.py)

10 evaluateurs, tous bases sur keyword matching :

| Evaluateur | Metriques | Fiabilite estimee |
|---|---|---|
| false_premise | premise_corrected (keywords), correct_fact_mentioned (keyword overlap), evidence_cited | Moyenne — la correction de premisse est bien detectee par keywords |
| unanswerable | admits_ignorance (keywords), likely_hallucination (longueur) | Bonne — "je ne sais pas" est bien capte par keywords |
| temporal_evolution | temporal_awareness (dates), change_identified (keyword overlap), docs_cited | **Faible** — detecte la presence de dates, pas la qualite de la comparaison |
| causal_why | evidence_coverage (keyword overlap), reasonable_length | **Faible** — ne verifie pas si le "pourquoi" est effectivement explique |
| hypothetical | evidence_coverage, mentions_consequence (keywords) | Moyenne — "risque", "consequence" sont bien des marqueurs |
| negation | evidence_coverage, mentions_negation (keywords) | Moyenne |
| synthesis_large | aspect_coverage (keywords par aspect), doc_coverage, good_length | **Faible** — longueur + mots-cles != synthese de qualite |
| conditional | evidence_coverage (keyword overlap) | **Faible** — ne verifie pas si la condition est correctement extraite |
| set_list | items_found (keyword per item), completeness | Bonne — l'enumeration d'items est bien captee |
| multi_hop | chain_coverage (keyword overlap par maillon) | Moyenne — les faits chaines sont detectes mais pas le raisonnement |

### T2/T5 (t2t5_diagnostic.py)

| Metrique | Methode | Fiabilite |
|---|---|---|
| tension_mentioned | Keywords de tension dans la reponse | Bonne |
| both_sides_surfaced | Keyword overlap avec claim1 et claim2 (>= 40%) | Moyenne — threshold 40% est arbitraire |
| both_sources_cited | Prefixes doc_id dans les sources | Bonne |
| chain_coverage | Keyword overlap par maillon de chaine | Moyenne |
| proactive_detection | Keywords de tension dans reponse a question sans mention | Bonne |

### RAGAS (ragas_diagnostic.py)

Utilise GPT-4o-mini comme evaluateur LLM — plus fiable que le keyword matching mais :
- Sujet aux null (echecs d'evaluation)
- Faithfulness decompose en "statements" — fragile sur les reponses longues
- Non deterministe (meme question = scores differents entre runs)

---

## 3. Audit a realiser

### Methode proposee

Pour chaque categorie de l'evaluateur robustesse :

1. **Echantillonner 5-10 questions** (mix de hauts scores et bas scores)
2. **Lire la question + la reponse OSMOSIS** manuellement
3. **Evaluer si le score attribue est juste** :
   - Score > 70% et reponse effectivement bonne → OK
   - Score > 70% mais reponse mediocre → **Faux positif** (evaluateur trop genereux)
   - Score < 50% et reponse effectivement mauvaise → OK
   - Score < 50% mais reponse correcte → **Faux negatif** (evaluateur trop strict)
4. **Documenter** les cas problematiques avec une note manuelle

### Livrable

Un tableau par categorie :

| Question ID | Score auto | Classification auto | Evaluation manuelle | Score juste (estime) | Verdict |
|---|---|---|---|---|---|
| T6_TE_002 | 87% | OK | Reponse partielle, pas de comparaison exhaustive | ~50% | Faux positif |
| T6_FP_001 | 85% | OK | Corrige bien la premisse | 85% | OK |
| ... | | | | | |

### Priorite d'audit

1. **temporal_evolution** — fiabilite estimee la plus faible
2. **causal_why** — idem
3. **synthesis_large** — longueur != qualite
4. **conditional** — keyword overlap insuffisant
5. **false_premise** — a verifier mais probablement OK
6. **multi_hop** — raisonnement pas capture par keywords

### Critere de decision

Si plus de 30% des questions d'une categorie sont mal classifiees (faux positif ou faux negatif), l'evaluateur de cette categorie doit etre reecrit.

---

## 4. Solutions possibles (apres audit)

### Option A — LLM-juge par categorie

Remplacer le keyword matching par un appel LLM (Qwen ou GPT-4o-mini) qui lit la question + reponse et donne un score.

Prompt type :
```
Question: "{question}"
Expected behavior: "{expected_behavior}"
Actual answer: "{answer}"

Rate the answer quality from 0 to 100. Consider:
- Does it actually answer the question?
- Is the information correct based on the expected behavior?
- Is it complete or partial?

Score (0-100):
```

**Avantage** : beaucoup plus precis que le keyword matching
**Inconvenient** : cout (1 appel LLM par question), non deterministe, plus lent
**Mitigation** : utiliser Qwen/vLLM (gratuit) comme juge

### Option B — Keyword matching ameliore

Garder l'approche deterministe mais ajouter des regles plus fines :
- Verifier la **co-occurrence** (le terme doit etre dans un contexte pertinent, pas juste present)
- Ajouter des **marqueurs negatifs** (si la reponse dit "pas d'information" ou "partiel", penaliser)
- Ajuster les seuils par categorie (pas un seuil unique de 50% pour OK/ECHEC)

**Avantage** : rapide, deterministe, gratuit
**Inconvenient** : toujours fragile, chaque regle est un cas particulier

### Option C — Hybride (recommande)

- Keyword matching pour le pre-scoring (rapide, deterministe)
- LLM-juge Qwen sur les cas ambigus (score entre 40-70%) pour confirmer
- Keyword matching seul pour les cas clairs (score > 80% ou < 20%)

**Avantage** : meilleur compromis cout/qualite
**Inconvenient** : plus complexe a implementer

---

## 5. Impact sur les decisions

Tant que l'audit n'est pas fait, les scores de benchmark robustesse doivent etre interpretes avec prudence :
- Les **tendances** (score monte ou descend entre V10 et V12) restent fiables
- Les **valeurs absolues** (56% vs 48%) ne sont pas fiables a ce stade
- Les **comparaisons entre modeles** (Haiku vs GPT-4o-mini) restent valides si le meme evaluateur est utilise

L'audit est un prerequis avant de :
- Communiquer des scores de benchmark a l'exterieur
- Prendre des decisions produit basees sur des scores absolus
- Definir des seuils de qualite "production ready"

---

*Document de reference pour le chantier qualite evaluateurs. A traiter avant la Phase 4 production.*

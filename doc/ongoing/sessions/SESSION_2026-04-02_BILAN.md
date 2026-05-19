# Bilan Session 1-2 avril 2026

**Duree** : 2 jours complets (30h+ de session Claude Code)

---

## Realisations majeures

### Phase 3 — KG Quality (C4 + C6)
- **C4 Relations Evidence-First** : 584 → 2410 relations (15.5% des claims)
  - 113 CONTRADICTS, 511 QUALIFIES, 1137 REFINES
  - Pipeline : CandidateMiner (embedding) → NLI Adjudicator (Haiku) → Persister
  - Nettoyage faux positifs (re-adjudication 109 CONTRADICTS, 8 supprimes)
  - Prompt NLI ameliore (modules paralleles, rebranding)
  
- **C6 Cross-doc Pivots** : +634 COMPLEMENTS, 12 SPECIALIZES, 3 EVOLVES_TO
  - Pipeline : PivotMiner (entites partagees) → PivotAdjudicator → Persister
  - Budget adaptatif (couverture garantie 1 paire/pivot)

- **Garbage collection** integree dans post-import (step 10)

### Benchmarking
- **Benchmark robustesse** : 246 questions, 10 categories (25q/cat)
  - false_premise, unanswerable, temporal, causal, hypothetical, negation, synthesis, conditional, set_list, multi_hop
  
- **LLM-juge** : GPT-4o-mini remplace keyword matching
  - Keyword sous-evaluait massivement (causal 39% → 75%, conditional 38% → 78%)
  - Cross-lingue resolu (question FR, corpus EN)
  - Global : 57% → **64.3%** avec LLM-juge

- **Comparaison 3 modeles** (246q) :
  - Qwen 14B AWQ : 48.6% (gratuit)
  - Claude Haiku 3.5 : 56.1% ($4.89/suite)
  - GPT-4o-mini : 56.1% ($0.84/suite) — meme score, 6x moins cher

### Multi-provider synthese
- Support OpenAI + Anthropic + vLLM dans synthesis.py
- Prompts externalises dans config/synthesis_prompts.yaml
- Switch par OSMOSIS_SYNTHESIS_PROVIDER (pas de changement de code)

### Dashboard benchmark frontend
- **4 onglets** : Vue d'ensemble, RAGAS, Contradictions, Robustesse
- ScoreGauges circulaires D3, RadarChart 10 axes
- QuestionDetailRow expandable (drill-down par question)
- MetricBars avec deltas vs baseline
- Bouton "Lancer tout" (3 benchmarks sequentiels)
- Proxy routes Next.js pour robustesse

### Cockpit operationnel
- Widget "Qualite Osmosis" (RAGAS + T2/T5 via API, pas filesystem)
- Polices agrandies pour lisibilite

### Negative rejection — exploration exhaustive
5 approches testees et eliminees :
1. Prompt honesty rule : +30pp unanswerable, -18pp false_premise
2. Gap lexical IDF : +54pp unanswerable, -67pp multi_hop (cross-lingue)
3. Dense score pre-RRF : indiscernable (ecart 0.04)
4. QA-Class Qwen/vLLM : 62 faux rejets / 246 questions
5. Logprob entropy : signal present mais overlap (AN 0.33 vs UN 0.41)

Recherche litterature : HALT, CDA, R-Tuning, GRACE documentes.
Paradoxe RAG-abstention identifie (NeurIPS 2024).

### Documentation
- ADR Corpus Vivant (philosophie documents evolutifs)
- Analyse benchmarks Phase 3 (chronologie complete)
- Analyse etape qualite (bon/fragile/mauvais)
- Chantier qualite evaluateurs
- Recherche unanswerable detection
- Spec UI benchmark dashboard
- Analyse couverture questions benchmark

---

## Scores de reference (V16, LLM-juge, GPT-4o-mini)

### Robustesse (246q)
| Categorie | Score | Verdict |
|---|---|---|
| conditional | 78.3% | BON |
| negation | 75.6% | BON |
| causal_why | 75.4% | BON |
| hypothetical | 73.5% | BON |
| temporal | 64.8% | CORRECT |
| multi_hop | 64.4% | CORRECT |
| set_list | 64.0% | CORRECT |
| synthesis_large | 60.0% | CORRECT |
| false_premise | 45.2% | FRAGILE |
| unanswerable | 43.8% | FRAGILE |
| **GLOBAL** | **64.3%** | |

### RAGAS (100q, Haiku)
- Faithfulness : 78.8%
- Context Relevance : 71.8%

### T2/T5 (150q full, Haiku)
- tension_mentioned : 100%
- proactive_detection : 100%
- both_sources_cited : 82.4%
- both_sides_surfaced : 72.8%

---

## Prochaines etapes

1. **Phase 4 produit** : Atlas Phase 1, UI tensions, Verify
2. **Indicateur entropie** dans le chat frontend (confiance faible)
3. **Unanswerable > 60%** si R-Tuning ou CDA envisage plus tard
4. **T2/T5 avec LLM-juge** quand le run propre sera termine

---

## Realisations additionnelles (apres le bilan initial)

### V17 Robustesse — Meilleur score obtenu (66.1%)

| Categorie | V16 | V17 | Delta |
|---|---|---|---|
| conditional | 78.3% | **80.4%** | +2.1pp |
| negation | 75.6% | **78.4%** | +2.8pp |
| causal_why | 75.4% | 75.8% | +0.4pp |
| hypothetical | 73.5% | 70.0% | -3.5pp |
| temporal | 64.8% | **67.2%** | +2.4pp |
| multi_hop | 64.4% | 64.8% | +0.4pp |
| set_list | 64.0% | 64.4% | +0.4pp |
| synthesis | 60.0% | 61.2% | +1.2pp |
| **unanswerable** | 43.8% | **52.5%** | **+8.7pp** |
| false_premise | 45.2% | 48.0% | +2.8pp |
| **GLOBAL** | 64.3% | **66.1%** | **+1.8pp** |

Impact de la regle 12 (premise verification) + prompt OpenAI externalise.

### Logprob entropy detection

Signal HALT/EPR implemente dans synthesis.py. AN avg=0.33, UN avg=0.41.
Signal present mais overlap (salaires 0.10 = faux negatif).
Utile en complement, pas suffisant seul. Expose dans le resultat de synthese.

### Verify V1 — Coquille OK, moteur defaillant

- Backend upload Word + frontend mode Document implementes
- python-docx 1.2.0 installe (commentaires natifs Word)
- MAIS : le pipeline verification (evidence_matcher) produit des verdicts absurdes
- Plan : refactorer pour reutiliser le pipeline search (qui fonctionne)
- Voir `doc/ongoing/CHANTIER_VERIFY_V1_ETAT.md`

### Fixes divers

- Token refresh dans T2/T5 diagnostic (70/150 erreurs resolues)
- Verify utilise OpenAI directement quand OSMOSIS_SYNTHESIS_PROVIDER=openai
- Build Docker avec python-docx
- Proxy Next.js pour /api/verify/upload-docx

### Prochain chantier identifie

Refonte page chat :
- Reponse trop complexe et prend trop de place
- KG non mis en valeur quand il produit des insights
- Organisation des informations a repenser

---

## Commits de la session

Total : ~50 commits sur la branche feat/wiki-concept-assembly-engine

*Session collaborative Fred + Claude Code (Opus 4.6 1M context) — 1-2 avril 2026*

# Audit honnête du pipeline runtime_v2 — 2026-05-05

> **But de l'audit** : avant de continuer à modifier, comprendre ce qu'on a réellement construit. Identifier le bloat, les anti-patterns (hardcoded lists, regex sur sémantique), et proposer une simplification.

## 1. Volume de code

```
runtime_v2/                            4867 lignes
├── pipeline.py                         951 lignes  ← orchestrateur
├── retriever.py                        490 lignes
├── question_subject_resolver.py        416 lignes  (15 patterns regex)
├── insight_hints.py                    344 lignes
├── faithfulness_judge.py               327 lignes
├── hallucination_guard.py              345 lignes  (30 patterns regex)
├── llm_client.py                       291 lignes
├── synthesis.py                        290 lignes
├── llm_filter.py                       278 lignes
├── premise_validator.py                354 lignes
├── lifecycle_filter.py                 246 lignes  (12 patterns regex + 5 listes mots)
├── answer_gap_detector.py              168 lignes
├── conflict_detector.py                110 lignes
├── models.py                           114 lignes
├── entropy.py                           99 lignes
└── __init__.py                          44 lignes
```

**4867 lignes pour répondre à une question**. C'est un monstre.

## 2. Pipeline complet — étapes (du pipeline.py)

Pour répondre à UNE question, le pipeline exécute **15 étapes mesurées** :

| # | Étape | Latence typique | Type |
|---|---|---|---|
| 1 | anchor_extractor | 3.4s | LLM call (Mistral-Small) |
| 2 | anchor_filter | 0.1s | Cypher query |
| 3 | subject_resolver | 2.0s | LLM call + cosine match |
| 4 | decomposer | 2.6s | LLM call |
| 5 | retrieve (hybrid+rerank) | 1.0s | Qdrant + BM25 + GPU rerank |
| 6 | verif_parallel (filter+premise) | 4.7s | 2× LLM calls (Mistral-Small) |
| 7 | conflict_detector | 0.1s | Cypher query |
| 8 | lifecycle_filter | <0.05s | Cypher query + regex hardcodés |
| 9 | synthesizer | 30s | LLM call (Qwen2.5-72B) |
| 10 | entropy check | <0.01s | logprob math |
| 11 | faithfulness_judge | 10s | LLM call (Mistral-Small) |
| 12 | faithfulness_regen | 10s (conditionnel) | LLM call (Qwen2.5-72B) |
| 13 | hallucination_guard | <0.05s | regex hardcodés |
| 14 | answer_gap_detector | <0.01s | TF-IDF |
| 15 | insight_hints | <0.1s | Cypher queries |

**Total typique : 50-65s, jusqu'à 9 LLM calls**.

## 3. Anti-pattern : hardcoded lists & regex

### CLAUDE.md mémoire dit explicitement :
> "🚨 ANTI-PATTERN — pas de regex/keywords pour extraction temporelle ou rôle (V3.3)"
> "Le LLM est le détecteur sémantique unique"

### Mais on a accumulé :

**hallucination_guard.py — 30 patterns regex** :
- regulation_id, article_ref, version_id, standard_id, amendment_ref
- value_with_unit (40+ unités hardcodées)
- date_fr, date_en, date_de, date_es, date_it, date_numeric
- Domain-specific : cs_code, npa_ref, ed_decision, atc_code, icd10_code, sap_note...

**lifecycle_filter.py — 12 patterns regex + 5 listes** :
- Markers FR (15 entries), EN (15 entries), DE (8), ES (8), IT (6)
- Past tense markers (15 entries)
- Months regex (60 mois multilingues)

**question_subject_resolver.py — 15 patterns regex** :
- Anchor patterns universels + domain-specific

**TOTAL : ~57 patterns regex + ~70 entrées dans listes hardcodées** dans le runtime.

### Ce que ça coûte
- **Multilingue cassé** : si demain on traite des docs en chinois/japonais/arabe, tout casse
- **Domain-specific** : on a déjà séparé aerospace/biomed/SAP en patterns différents → on duplique pour chaque domaine
- **Maintenance** : chaque ajout de domaine = ajouter ~10 patterns
- **Va contre la mémoire** : "Le LLM est le détecteur sémantique unique"

## 4. Vue par "couche"

### Couche 1 : Comprendre la question (5 étapes, 4 LLM calls, 8s)
- anchor_extractor (LLM)
- subject_resolver (LLM + regex anchors)
- decomposer (LLM)

### Couche 2 : Trouver les chunks (1 étape, 0 LLM, 1s)
- retrieve : hybrid BM25+vector+rerank GPU

### Couche 3 : Filtrer (3 étapes, 2 LLM calls, 5s)
- llm_filter (LLM) — souvent bypassé maintenant
- premise_validator (LLM)
- lifecycle_filter (regex hardcodés)

### Couche 4 : Construire la réponse (1 étape, 1 LLM call, 30s)
- synthesizer (LLM)

### Couche 5 : Vérifier la réponse (4 étapes, 1-2 LLM calls, 10-20s)
- entropy check
- faithfulness_judge (LLM)
- faithfulness_regen (LLM conditionnel)
- hallucination_guard (regex hardcodés)

### Couche 6 : Enrichir (3 étapes, 0 LLM, <1s)
- conflict_detector
- answer_gap_detector
- insight_hints

## 5. Diagnostic honnête

### Ce qu'on essaie de faire (la mission)
Répondre à des questions sur un corpus régulatoire avec **fidélité** (≥80%) et **faible hallucination** (≤2%).

### Ce qu'on a fait (l'implémentation)
Un système avec **6 couches**, **15 étapes**, **5-9 LLM calls par question**, **4867 lignes de code**, **57 regex hardcodés**, **70 entrées de listes hardcodées**. 50-65s/question.

### Pourquoi cette dérive ?

À chaque problème on a ajouté une couche au lieu d'améliorer une couche existante :
- "Le LLM filter rejette les bons chunks" → bypass conditionnel (au lieu de fixer le filter)
- "Le faithfulness juge est trop strict" → skip-regen conditionnel (au lieu de fixer le judge)
- "On hallucine sur les valeurs" → hallucination guard avec 30 regex (au lieu d'améliorer la synthèse)
- "Les questions current intent ratent" → lifecycle filter avec listes multilingues (au lieu de laisser le LLM décider)
- "Les false_premise régressent" → règle 10 du synthesis prompt + détection contradictions

C'est un **anti-pattern de cumul** : au lieu de retirer / refactorer, on **ajoute**.

## 6. Pipeline cible — simplification radicale possible

Une pipeline VRAIMENT minimaliste pour la même mission :

```
Question
   ↓
1. Retrieve (hybrid BM25+vector, top-K=20, rerank GPU si dispo)
   ↓
2. LLM "Reasoning Synthesis" (1 SEUL LLM call avec un bon prompt qui :
   - détecte sujet de la question
   - identifie présuppositions implicites
   - extrait la réponse en citant le doc_id
   - signale fausses prémisses si détecte une contradiction
   - signale abstention si info absente)
   ↓
3. Hallucination check (validator simple : tous les doc_ids cités existent)
   ↓
Réponse + diagnostic
```

**3 étapes, 1 LLM call, ~600 lignes de code maximum, 30s/question**.

C'est ce que fait un humain compétent : il regarde les chunks, raisonne dessus, écrit une réponse honnête.

## 7. Ce qu'il y a à garder vs jeter

### À GARDER (valeur prouvée)
- **Hybrid BM25+vector retrieval** (capture termes exacts) — domain-agnostic, ROI clair
- **Cross-encoder rerank GPU** (BGE-v2-m3 multilingue) — domain-agnostic, +5pp validé
- **Skip-regen logic** (B.3) — évite la régression "perdre la bonne réponse"
- **LLM-driven anchor/subject extraction** (mais simplifier les patterns regex de tie-breaker)

### À METTRE EN PROMPT (au lieu de code)
- Détection cross-lingual (déjà dans le prompt synthesis v3)
- Détection fausses prémisses (déjà dans le prompt synthesis v3)
- Détection lifecycle (peut être dans le prompt avec metadata claims `lifecycle_status`)
- Reconnaissance "current intent" (le LLM lit la question et décide)

### À JETER (anti-pattern)
- ❌ `lifecycle_filter.py` listes hardcodées de markers FR/EN/DE/ES/IT (donner l'info au LLM dans le prompt)
- ❌ `hallucination_guard.py` 30 regex (le faithfulness judge LLM le fait déjà mieux avec un prompt amélioré)
- ❌ `question_subject_resolver.py` regex anchors (le LLM extrait directement)
- ❌ `llm_filter.py` complet (la synthèse evidence-locked filtre déjà en lisant les claims)
- ❌ `premise_validator.py` séparé (intégrer dans synthèse prompt)
- ❌ `faithfulness_judge.py` séparé (un seul LLM call composite)

### Économie potentielle
- 4867 lignes → ~1500 lignes (-70%)
- 9 LLM calls → 1-2 LLM calls (-80%)
- 57 regex → 5 regex (-90%)
- 70 listes hardcodées → 0
- Latence 50-65s → 15-30s (-50%)
- Domain-agnostic vraiment

## 8. Recommandation

**Avant Sprint D**, faire une **refonte de simplification** :

### Étape 1 : Définir le prompt synthèse "tout-en-un"
Un prompt unique qui :
1. Lit la question
2. Lit les claims (avec metadata : doc_id, lifecycle_status, publication_date)
3. Détecte sujet + présuppositions + intention temporelle
4. Synthétise réponse OU rejette présupposition OU abstient
5. Cite doc_ids verbatim

### Étape 2 : Mesurer avec le bench actuel
- Si la pipeline simplifiée garde >90% des gains actuels → on jette les couches
- Si elle perd → on garde sélectivement

### Étape 3 : Garder uniquement ce qui a un ROI mesurable
- Pas de bypass conditionnel (= patch)
- Pas de regex sur la sémantique
- Pas de listes hardcodées (sauf en Domain Pack opt-in)

## 9. Question stratégique

Le bench actuel mesure le score sur un corpus aerospace/EU regs. **Aucun bench cross-domain**.

Question honnête : **est-ce que la pipeline marcherait sur un corpus médical ou IT ?**

Avec 70 markers FR/EN/DE/ES/IT pour le lifecycle filter, 30 regex factuels (dont aerospace-specific), et un prompt synthesis qui mentionne EU/aerospace par exemple → la réponse réelle est : **probablement pas sans rework**.

Ma proposition de simplification rend le système **vraiment domain-agnostic** par construction (pas par des regex pour chaque domaine), avec moins de code, moins de LLM calls, et probablement même score ou meilleur.

## 10. Conclusion

Tu as raison — on a créé un monstre. Les benches ont guidé chaque ajout de couche au lieu de guider la simplification.

**Proposition** : avant Sprint D, faire une "refonte simplification" qui :
- Élimine 4 modules (lifecycle_filter, hallucination_guard, question_subject_resolver tie-breaker, premise_validator séparé)
- Fusionne synthesizer + faithfulness en 1 LLM call composite
- Réduit le code de 70%
- Re-mesure pour valider

Tu veux qu'on parte sur cette simplification, ou tu préfères qu'on continue Sprint D et on simplifie après ?

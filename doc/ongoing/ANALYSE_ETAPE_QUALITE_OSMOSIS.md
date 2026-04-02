# Analyse d'etape — Qualite OSMOSIS (2 avril 2026)

**Objectif** : Identifier ce qui est bon, fragile ou mauvais pour prioriser les ameliorations.

---

## 1. Vue synthetique — 3 volets

### RAGAS (100 questions, Haiku)
| Metrique | Score | Seuil prod | Verdict |
|---|---|---|---|
| Faithfulness | **78.8%** | 85% | FRAGILE — 6pp sous la cible |
| Context Relevance | **71.8%** | 80% | FRAGILE — 8pp sous la cible |

### Contradictions T2/T5 (150 questions full, Haiku)
| Metrique | Score | Seuil prod | Verdict |
|---|---|---|---|
| tension_mentioned | **100%** | 90% | BON |
| proactive_detection | **100%** | 80% | BON |
| both_sources_cited | **82.4%** | 80% | BON |
| both_sides_surfaced | **72.8%** | 85% | FRAGILE — 12pp sous la cible |
| multi_doc_cited | **81.6%** | 80% | BON |
| chain_coverage | **52.3%** | 70% | MAUVAIS — 18pp sous la cible |

### Robustesse (246 questions, meilleur modele par categorie)
| Categorie | Haiku | GPT-4o-mini | Meilleur | Verdict |
|---|---|---|---|---|
| synthesis_large | 83.3% | **92.3%** | 92.3% | BON |
| multi_hop | 74.0% | **76.0%** | 76.0% | BON |
| unanswerable | **72.1%** | 23.8% | 72.1% | FRAGILE (Haiku) / MAUVAIS (GPT) |
| false_premise | 52.7% | **61.2%** | 61.2% | FRAGILE |
| set_list | 50.0% | **70.3%** | 70.3% | BON (GPT) / FRAGILE (Haiku) |
| hypothetical | 45.4% | **56.0%** | 56.0% | FRAGILE |
| causal_why | **57.2%** | 40.8% | 57.2% | FRAGILE |
| conditional | **50.5%** | 39.9% | 50.5% | FRAGILE |
| negation | 43.2% | **45.7%** | 45.7% | MAUVAIS |
| temporal | 32.0% | **53.4%** | 53.4% | MAUVAIS (Haiku) / FRAGILE (GPT) |

---

## 2. Classification detaillee

### BON (>= 75%, pas d'intervention urgente)

| Capacite | Score | Pourquoi ca marche |
|---|---|---|
| **tension_mentioned** | 100% | ContradictionEnvelope force la mention des tensions |
| **proactive_detection** | 100% | C4 Relations (1766 relations) detecte toutes les contradictions cachees |
| **both_sources_cited** | 82.4% | Le KG procedural cite les deux documents sources |
| **multi_doc_cited** | 81.6% | Hybrid BM25+dense recupere des chunks de plusieurs docs |
| **synthesis_large** | 83-92% | Les LLMs (Haiku et GPT-4o-mini) synthetisent bien les infos multi-doc |
| **multi_hop** | 74-76% | C4+C6 relations + KG traversal permettent le chainage cross-doc |

### FRAGILE (50-75%, ameliorable)

| Capacite | Score | Cause racine | Levier d'amelioration |
|---|---|---|---|
| **Faithfulness** | 78.8% | Le LLM hallucine des identifiants precis (SAP Notes, transactions) | Fact validation layer post-synthese |
| **Context Relevance** | 71.8% | Le retriever ramene des chunks thematiquement proches mais pas toujours cibles | Deployer COMPLEMENTS dans retrieval (code ecrit, pas benchmarke) |
| **both_sides_surfaced** | 72.8% | Le LLM mentionne la tension mais ne developpe pas toujours les 2 cotes | Injecter les claims verbatim des 2 cotes dans le prompt |
| **unanswerable** | 72.1% (Haiku) | Le QA-Class gate fonctionne avec Haiku mais pas avec GPT-4o-mini | Ameliorer le prompt QA-Class ou adapter le prompt synthese GPT-4o-mini |
| **false_premise** | 52-61% | Le LLM corrige 5/7 premisses mais accepte 2 fausses premisses | Ajouter une instruction "verify premise against sources" dans le prompt |
| **hypothetical** | 45-56% | L'inference "si X alors Y" necessite un raisonnement que le LLM fait 1 fois sur 2 | Prompt plus structure pour l'inference conditionnelle |
| **causal_why** | 40-57% | Le "pourquoi" est souvent implicite dans les docs, le LLM extrapole | Distinguer "raison documentee" vs "raison supposee" |
| **conditional** | 40-50% | L'extraction de conditions/prerequis est difficile par keyword matching | Evaluateur probablement trop strict — audit necessite |
| **set_list** | 50-70% | Varie selon le modele — GPT-4o-mini enumere mieux | L'enumeration depend de la couverture retrieval |

### MAUVAIS (< 50%, action requise)

| Capacite | Score | Cause racine | Action |
|---|---|---|---|
| **chain_coverage** | 52.3% | Questions multi-source (3+ docs) mal couvertes — le retriever ne ramene que 2 docs | Query expansion via entites KG + COMPLEMENTS |
| **negation** | 43-46% | Les questions "qu'est-ce qui n'est PAS supporte" sont mal evaluees par keyword matching OU le LLM ne repond pas aux negations | **Audit evaluateur requis** — verifier si c'est un pb de reponse ou d'evaluation |
| **temporal** | 32-53% | Les comparaisons entre versions sont partielles — le LLM ne compare pas systematiquement | Les relations EVOLVES_TO/REFINES existent dans le KG mais ne sont pas exploitees dans la synthese |
| **unanswerable GPT-4o-mini** | 23.8% | GPT-4o-mini hallucine massivement quand l'info n'est pas dans le corpus | QA-Class prompt a ameliorer pour GPT-4o-mini |

---

## 3. Priorites d'action (ordonnees par impact)

### P0 — Prerequis (fiabilite des mesures)

**Audit qualite evaluateurs** (doc: CHANTIER_QUALITE_EVALUATEURS.md)
- Passer 5-10 questions par categorie en revue manuelle
- Verifier que OK/ECHEC correspond a la realite
- Sans cet audit, les scores sont potentiellement trompeurs
- **Impact** : fiabiliser TOUTES les decisions basees sur les benchmarks

### P1 — Gains rapides (1-2h chacun)

1. **Temporal : exploiter EVOLVES_TO/REFINES dans la synthese**
   - Les relations existent dans le KG (3 EVOLVES_TO, 1137 REFINES)
   - Mais le prompt ne dit pas au LLM de comparer les versions
   - Ajouter un finding KG "temporal_comparison" quand des EVOLVES_TO sont detectes
   - Impact estime : temporal 32% → 55%+

2. **Unanswerable GPT-4o-mini : prompt specifique**
   - GPT-4o-mini a 23.8% vs Haiku 72.1%
   - Pas de routing multi-modeles — plutot adapter le prompt synthese pour GPT-4o-mini
   - Ajouter "If the sources do not address the specific question, say so clearly" (pas aussi agressif que la regle 12 revertee)
   - Impact estime : unanswerable 24% → 50%+

3. **both_sides_surfaced : claims verbatim dans le prompt**
   - Actuellement le ContradictionEnvelope donne une instruction generique
   - Injecter les textes des 2 claims concrets dans le prompt
   - Impact estime : both_sides 73% → 80%+

### P2 — Ameliorations structurelles (demi-journee chacune)

4. **Chain coverage : COMPLEMENTS dans le retrieval**
   - Code deja ecrit dans search.py (OPTIONAL MATCH COMPLEMENTS)
   - Pas encore benchmarke — deployer et mesurer
   - Impact estime : chain_coverage 52% → 60%+

5. **Faithfulness : fact validation layer**
   - Verifier post-synthese que les identifiants (codes, numeros) sont dans les chunks
   - Domain-agnostic : detecter les tokens alphanumeriques en MAJUSCULES dans la reponse et verifier leur presence dans les sources
   - Impact estime : faithfulness 79% → 83%+

6. **Context Relevance : re-ranking cross-encoder**
   - Le bi-encoder (e5-large) capture le domaine mais pas la repondabilite
   - Un cross-encoder re-rankerait les chunks par pertinence question-specifique
   - Impact estime : context_relevance 72% → 78%+

### P3 — Chantiers de fond (plusieurs jours)

7. **Evaluateurs LLM-juge** (remplacer keyword matching)
   - Utiliser Qwen/vLLM comme juge pour les categories fragiles
   - Hybride : keyword pour les cas clairs, LLM pour les ambigus
   - Prerequis : audit P0

8. **Negation : investigation root cause**
   - Est-ce un probleme de reponse (le LLM ne gere pas les negations) ou d'evaluation (le keyword matching est trop strict) ?
   - Necessite l'audit P0

---

## 4. Objectifs cibles

### Court terme (cette semaine)
| Metrique | Actuel | Cible | Levier |
|---|---|---|---|
| Faithfulness | 78.8% | **82%** | Fact validation + prompt |
| both_sides | 72.8% | **80%** | Claims verbatim |
| temporal | 32-53% | **55%** | EVOLVES_TO dans synthese |
| unanswerable | 24-72% | **65%** (sur GPT-4o-mini) | Prompt adapte |

### Moyen terme (2 semaines)
| Metrique | Actuel | Cible | Levier |
|---|---|---|---|
| Context Relevance | 71.8% | **78%** | COMPLEMENTS + re-ranking |
| chain_coverage | 52.3% | **65%** | COMPLEMENTS retrieval |
| negation | 43-46% | **60%** | Audit + fix evaluateur ou prompt |
| Global robustesse | 56.1% | **65%** | Cumul des ameliorations |

### Production ready (1 mois)
| Metrique | Cible | Condition |
|---|---|---|
| Faithfulness | **85%+** | Fact validation + re-ranking |
| Context Relevance | **80%+** | COMPLEMENTS + cross-encoder |
| both_sides | **85%+** | Claims verbatim + validation |
| unanswerable | **75%+** | QA-Class ameliore |
| Global robustesse | **70%+** | Evaluateurs fiabilises + prompt |

---

## 5. Risques

1. **Evaluateurs trompeurs** : Les scores absolus ne sont pas fiables tant que l'audit P0 n'est pas fait. Les priorites pourraient changer apres l'audit.

2. **Trade-off unanswerable vs reste** : Chaque tentative de negative rejection a degrade les autres categories (V3, V4). Le QA-Class est la seule approche qui ne degrade pas, mais il depend du vLLM.

3. **Cout vs qualite** : GPT-4o-mini est 6x moins cher mais -48pp sur unanswerable. Le choix du modele de synthese impacte fortement les resultats.

4. **Corpus de test** : 25 questions par categorie est le minimum. Pour les categories critiques (unanswerable, false_premise), 50 questions seraient plus fiables.

---

---

## 6. Mise a jour apres audit P0 (2 avril 2026)

### Resultat de l'audit

L'audit a revele que le QA-Class causait **62 faux rejets sur 246 questions (31%)** :
- temporal: 60% de faux rejets
- negation: 40%
- set_list: 36%
- false_premise: 32%
- hypothetical: 30%

Le QA-Class a ete desactive et un benchmark V14 (GPT-4o-mini sans QA-Class) a ete lance.

### V14 — Vrais scores GPT-4o-mini (246q, sans QA-Class)

| Categorie | Score | Verdict |
|---|---|---|
| synthesis_large | **91.8%** | BON |
| multi_hop | **71.3%** | BON |
| set_list | **70.0%** | BON |
| false_premise | **62.1%** | FRAGILE |
| hypothetical | **58.7%** | FRAGILE |
| temporal | **54.1%** | FRAGILE |
| negation | **44.2%** | MAUVAIS |
| causal_why | **39.0%** | MAUVAIS |
| conditional | **39.0%** | MAUVAIS |
| unanswerable | **17.9%** | MAUVAIS |
| **GLOBAL** | **54.9%** | |

### Surprise : QA-Class impact marginal

La comparaison V13 (avec QA-Class) vs V14 (sans) montre seulement -1.2pp de difference globale. Le QA-Class ne degradait pas autant qu'on pensait (les faux rejets tombaient sur des questions a scores moyens de toute facon). Mais il ne resolvait pas non plus le vrai probleme : la qualite de synthese GPT-4o-mini sur certains types de questions.

### Nouveau diagnostic

Les 4 categories MAUVAIS sont le vrai chantier :

1. **unanswerable (17.9%)** : GPT-4o-mini hallucine massivement. Le QA-Class est la bonne approche mais doit etre ameliore (trop de faux rejets actuellement). Alternative : prompt specifique pour GPT-4o-mini.

2. **causal_why (39.0%)** : GPT-4o-mini n'explique pas le "pourquoi" a partir des sources. Il repond de maniere generique au lieu de citer les raisons documentees. MAIS il faut aussi verifier l'evaluateur — `evidence_coverage` par keyword overlap est peut-etre trop strict.

3. **conditional (39.0%)** : L'extraction de conditions ("si X alors Y") est faible. L'evaluateur ne mesure que le keyword overlap, ce qui est probablement insuffisant pour cette categorie. Audit evaluateur necessaire.

4. **negation (44.2%)** : Les questions "qu'est-ce qui n'est PAS..." sont mal traitees. Possibles causes : le LLM ne repond pas aux negations, OU l'evaluateur est trop strict (keyword "ne pas" vs "cannot").

### Priorites revisees

| # | Action | Impact estime | Effort |
|---|---|---|---|
| 1 | Audit evaluateurs causal/conditional/negation (verifier si les scores refletent la realite) | Fiabiliser les mesures | 2h |
| 2 | Prompt GPT-4o-mini pour unanswerable (instruction specifique sans casser le reste) | unanswerable 18% → 40%+ | 1h |
| 3 | Temporal : injecter EVOLVES_TO dans la synthese | temporal 54% → 65%+ | 2h |
| 4 | both_sides : claims verbatim dans le prompt | both_sides 73% → 80%+ | 1h |

---

*Analyse d'etape pour guider les prochaines iterations. Mis a jour le 2 avril 2026 apres audit P0 et V14.*

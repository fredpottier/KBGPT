# ADR CH-49 — Corrections architecturales pipeline V4.1 par type de question

**Date initiale** : 2026-05-09
**Statut** : 🟡 DRAFT — amendé progressivement par type analysé
**Auteurs** : Fred + Claude (analyse), à challenger via LLM tiers (ChatGPT, Gemini, Claude web)
**Chantier** : CH-49 (suite CH-48 Together AI bake-off)

## Status updates

| Date | Status | Type couvert |
|------|--------|--------------|
| 2026-05-09 | DRAFT v0.1 | `list` (20 questions analysées) |
| 2026-05-09 | DRAFT v0.2 | + `factual` (5 questions analysées) |
| 2026-05-09 | DRAFT v0.3 | + `unanswerable` (5 questions) — D-TR.5 cross-cutting fix |
| 2026-05-09 | DRAFT v0.4 | + `temporal` (15 questions) — D-TEMP.1 temporal active version path |
| 2026-05-09 | DRAFT v0.5 | + `causal` (13 questions, 75% parfait — best type) |
| 2026-05-09 | DRAFT v0.6 | + `comparison` (8 + 40 T2), `multi_hop` (12) — gold v5 100% Robust |
| 2026-05-09 | DRAFT v0.7 | révision chiffres §1-§5 avec gold v5 (couverture 170/170 Robust) |
| TBD | REVIEW | Challenge LLM tiers |
| TBD | LOCKED | Validation Fred → start CH-49.x |

---

## §0 — Contexte CH-48 → CH-49

### 0.1 Bench global CH-48 résultats (2026-05-09)

Pipeline V4.1 (Analyzer + Structurer + Composer = Llama-3.3-70B-Instruct-Turbo via Together AI) vs baseline CH-46_POSTOPT (Qwen-72B DeepInfra) :

| Bench | Mesure | CH-46 | **CH-48** | Δ |
|---|---|---:|---:|---:|
| Robust 170q | global_score | 0.351 | **0.403** | **+5.1pp** ✅ |
| Robust 170q | duration | 179 min | **49 min** | **-72%** ✅ |
| T2T5 70q | duration | 25 min | **3.3 min** | **-86%** ✅ |
| RAGAS 132q | (en cours) | — | — | — |

**Verdict latence** : ✅ cible Test Armand atteinte (mean 17-21s/q).
**Verdict qualité** : ✅ +5.1pp global mais ⚠️ régressions par type identifiées.

### 0.2 Méthode d'analyse

**Approche "déviation au gold-set v4"** (au lieu de delta-vs-baseline) :
- Subset Robust × gold_v4 = **63 questions** avec reference
- Mesure absolue : écart à `structured_avg = 1.0` (système parfait)
- Permet de détecter **stagnations absolues** masquées par les améliorations relatives

**Résultats par type** (subset 63q, structured_avg moyen) :

| Type | n | CH-46 | CH-48 | % du parfait CH-48 | Priorité |
|---|---:|---:|---:|---:|---|
| causal | 13 | 0.265 | **0.751** | **75%** | OK ✅ |
| false_premise | 5 | 0.092 | 0.592 | 59% | Surveiller |
| temporal | 15 | 0.175 | 0.426 | 43% | À analyser |
| **list** | 20 | 0.071 | **0.160** | **16%** | **🔴 P0** |
| **factual** | 5 | 0.000 | 0.150 | **15%** | **🔴 P0** |
| **unanswerable** | 5 | 0.100 | 0.200 | **20%** | **🔴 P0** |

### 0.3 Charte stricte (rappel)

Toute correction doit respecter :
- **Domain-agnostic** : pas de regex/keywords/listes corpus-spécifiques (cf `feedback_domain_agnostic_strict`)
- **Multilingue** : EN/FR/DE/... — pas de patterns lexicaux mono-langue
- **Anti-Goodhart** : un fix doit améliorer la qualité produit pour les utilisateurs prod, pas juste passer le bench (cf `feedback_no_benchmark_overfit`)
- **Pas de MVP transitoire** : implémenter la cible, pas une regex temporaire

---

## §1 — Type LIST (20 questions, 16% du parfait)

### 1.1 Observations chiffrées

| Métrique CH-48 | Score moyen | Distance à 1.0 |
|---|---:|---:|
| `structured_avg` | 0.160 | 0.840 manque |
| `item_recall.f1` | 0.110 | 0.890 manque |
| `exact_match` | 0.054 | 0.946 manque |
| `citation_rate` | 0.290 | 0.710 manque |
| `judge_score` | 0.380 | 0.620 manque |

### 1.2 Distribution des patterns de fail (sur 20 samples, double-lus)

| Pattern | Nb | % | Description |
|---|---:|---:|---|
| **A — Items vus, hors cible** | 8 | **40%** | Pipeline retrieve + liste items présents dans corpus mais ne correspondant pas à la **catégorie ontologique** demandée |
| **E — Synthèse incomplète** | 3-4 | 15-20% | Composer démarre bien puis s'arrête après 1-2 éléments au lieu de dérouler les 5+ attendus |
| **B — Abstention erronée** | 3-4 | 15-20% | Pipeline répond "pas trouvé" alors que l'info existe (KG ou corpus) |
| **C — Hors-sujet total** | 2 | 10% | Réponse complètement déconnectée de la question |
| **D — Format incomplet** | 1 | 5% | Items OK mais sans les attributs associés (dates, titres) |
| OK partiel | 1 | 5% | recall ≥ 0.8 |

**Insight critique** : sur 19 samples comparables, CH-46 (Qwen-72B) montre les **mêmes patterns**. Le problème est **structurel au pipeline V4.1**, pas dépendant du modèle Composer.

### 1.3 Exemples emblématiques

#### Pattern A — Items vus, hors cible
**SET_009** : "Liste les **références EU externes** citées dans 2021/821"
- Attendu : `Reg 952/2013 (douanes)`, `RGPD`, `Reg 2018/1725`, `Common Military List`
- CH-48 : `Australia Group, MTCR, NSG, Wassenaar, OPCW` (= **régimes internationaux**, ≠ EU externes)
- Diagnostic : pipeline confond **catégories ontologiques adjacentes**

#### Pattern B — Abstention erronée
**SET_004** : "Types d'autorisations d'export 2021/821"
- Article 12 du règlement liste explicitement : Individuelle, Globale, Grands projets, AGEU
- CH-48 + CH-46 : "pas trouvé"
- Diagnostic : retrieval ou LLM-filter abstient à tort sur information **explicite du corpus**

#### Pattern E — Synthèse incomplète
**SYN_006** : "chaîne causalité réglementaire dual-use" (5 étapes attendues)
- CH-48 : démarre avec "régimes internationaux influencent décisions" et s'arrête
- Diagnostic : Composer ne déroule pas les chaînes/listes longues

#### Pattern C — Hors-sujet total
**SET_010** : "Liste les LIFECYCLE_RELATION dans le KG aerospace"
- CH-48 : "pas trouvé" (Pattern B/C combiné)
- Réalité : `SUPERSEDES (2021/821 → 428/2009)`, `EVOLVES_FROM (2023/66, 2023/996, 2024/2547 → 2021/821)` existent dans Neo4j
- Diagnostic : pipeline fait du **retrieval Qdrant chunks** au lieu d'**interroger Neo4j** pour les questions explicitement KG-centriques

### 1.4 Causes structurelles racines

#### Cause LIST-α : Absence de filtrage sémantique de la cible avant extraction
Le ListStructurer extrait des items à partir des chunks retrievés sans étape de **vérification que chaque item appartient bien à la catégorie ontologique demandée**. La question "EU external references" et "international regimes" déclenchent des retrievals qui se chevauchent (les régimes apparaissent souvent à côté des références EU).

#### Cause LIST-β : Pipeline non-tool-aware pour les questions KG
Le QuestionAnalyzer route toujours les questions list vers `list_path` (retrieval Qdrant + ListStructurer + ListComposer). Pour les questions explicitement KG-centriques (`LIFECYCLE_RELATION`, `claims`, `relations dans le KG`, `DEPRECATED docs`), c'est une **erreur d'architecture** : ces questions devraient être traitées par requête Cypher directe sur Neo4j.

#### Cause LIST-γ : Composer s'arrête prématurément sur listes/synthèses longues
Le ListComposer / ReasoningComposer V4.1 produit en moyenne 1-3 items quand la question demande explicitement plus (5-10 items pour les chaînes causales, listes complètes d'amendments, etc.). Hypothèse : prompt manquant d'incitation à exhaustivité + token budget Composer trop serré.

#### Cause LIST-δ : Format de sortie ne capture pas les attributs liés
Quand la question demande "X **avec leur Y**" (ex: "amendments avec leur date"), le ListComposer produit la liste des X mais omet les Y. Hypothèse : prompt + schema JSON output ne forcent pas l'inclusion des attributs.

#### Cause LIST-ε (transverse) : Métriques structurées trop strictes (problème côté gold-set)
Les `list_items_expected` du gold-set v4 contiennent des chaînes longues (ex: `"change_amdt 23 = Airplane Safety Regulations"`). Le scorer fait un match exact textuel, sans tolérance sémantique ou fuzzy. Une réponse correcte mais formulée différemment (ex: `"Amendment 23"`) score 0 au lieu de partial. **Sous-évaluation systématique des listes**.

### 1.5 Décisions LIST

#### D-LIST.1 — Étape "Target Disambiguation" avant extraction (couvre Cause α)
**Décision** : insérer une étape LLM courte entre `EvidenceCollector` et `ListStructurer` qui prend la question et produit une **définition ontologique de la cible** :
- Catégorie attendue (ex: "documents légaux EU non-2021/821")
- Critères d'inclusion explicites
- Critères d'exclusion (ex: "exclure les régimes internationaux")
- Fait la vérification sémantique chunk-par-chunk avant que le ListStructurer ne crée les atomic_facts.

**Impact estimé** : récupère 40% des fails list (Pattern A) → +0.10-0.15 sur list_score, +0.02-0.03 global Robust.
**Effort** : 2-3 jours (nouveau stage + prompt + tests).
**Risque** : ajoute ~1-2s de latence par question list.

#### D-LIST.2 — Path `kg_query` pour questions KG-centriques (couvre Cause β + partie de C)
**Décision** : ajouter au QuestionAnalyzer un signal `kg_centric=true` quand la question référence explicitement le KG (mots-clés multilingues : `LIFECYCLE_RELATION`, `relation`, `KG`, `claims`, `DEPRECATED`, `SUPERSEDES`, `EVOLVES_FROM`, équivalents EN/FR/DE). Router ces questions vers un nouveau path `kg_query_path` qui :
- Construit une requête Cypher templatée selon le type de relation demandé
- Exécute sur Neo4j
- Formate les tuples retournés en réponse list/synthèse

**Note charte** : la détection peut être domain-agnostic via mots-clés ontologiques **standards du domaine RAG/KG** (LIFECYCLE_RELATION, SUPERSEDES sont des concepts génériques, pas corpus-spécifiques). À distinguer d'une regex aerospace qui violerait la charte.

**Impact estimé** : récupère 15-20% des fails list (Pattern B-KG + C-KG) → +0.05-0.08 sur list_score.
**Effort** : 2-3 jours (path + Cypher templates + tests).

#### D-LIST.3 — Composer "Exhaustivité driven by Question" (couvre Cause γ)
**Décision** : 
- Analyzer signale au Composer le **nombre attendu d'éléments** quand la question le précise (ex: "les 4 types", "les régimes", "all amendments")
- Composer prompt explicite : "tu dois dérouler tous les éléments demandés sans abréger ; si la liste est longue, ne tronque pas"
- Augmenter `max_tokens` Composer pour les paths list/synthèse (1500 → 3000)
- Validation post-Composer : si la question demande N items et la sortie en a < N/2, **retry une seule fois** avec prompt "complete the list"

**Impact estimé** : récupère 15-20% des fails list (Pattern E) → +0.05-0.07 sur list_score.
**Effort** : 1 jour (prompt tweaks + retry logic + tests).
**Risque** : retry augmente latence ; éviter retry storms (max 1).

#### D-LIST.4 — List+Attributes structured output (couvre Cause δ)
**Décision** : enrichir le schema JSON output ListComposer pour les questions "X avec leur Y" :
```json
{
  "items": [
    {"primary": "Amendment 23", "attributes": {"date": "2019-07-15", "title": "..."}}
  ]
}
```
Detection automatique via Analyzer si la question contient un connecteur "avec/with leur/their + N (date, titre, version)".

**Impact estimé** : récupère 5% des fails list (Pattern D) → +0.02 sur list_score.
**Effort** : 0.5 jour (prompt + schema + tests).

#### D-LIST.5 — Scorer item_recall sémantique (couvre Cause ε)
**Décision** : remplacer le match exact textuel des `list_items_expected` par :
- Match exact (priorité 1)
- Match fuzzy (Levenshtein normalisé > 0.7 ou token_set_ratio > 80) sur l'item complet
- Match sémantique : embedding similarity > 0.75 (BGE-M3 multilingue déjà disponible)
- Score = `max(exact, fuzzy, semantic)` par item

**Impact** : non-produit, mais **révèle le vrai score qualité du pipeline** (estimation +0.10-0.15 sur structured_avg sans changement réel du pipeline). Permet d'éliminer la sous-évaluation systématique.

**Effort** : 0.5 jour.
**Note** : à coupler avec D-CH50.1 (gold-set complet) pour reformuler les items expected en formats plus naturels.

#### D-LIST.6 — Métriques observabilité "abstain vs off-target" (transverse)
**Décision** : enrichir `structured_metrics` avec :
- `abstain_correct` : pipeline a abstain ET le gold n'avait pas de réponse (`unanswerable=true`)
- `abstain_wrong` : pipeline a abstain MAIS le gold avait une réponse (Pattern B)
- `off_target_listing` : pipeline a listé des items MAIS aucun ne matche la cible (Pattern A/C)

**Impact** : observabilité, priorisation des corrections futures, alerte qualité prod.
**Effort** : 1 jour (instrumentation + dashboard).

### 1.6 ROI cumulé estimé Fix LIST

| Fix | Pattern couvert | Δ list_score | Δ global_score | Effort |
|---|---|---:|---:|---:|
| D-LIST.1 (Target disambig) | A (40%) | +0.10-0.15 | +0.02-0.03 | 2-3j |
| D-LIST.2 (KG path) | B-KG, C-KG (20%) | +0.05-0.08 | +0.01-0.02 | 2-3j |
| D-LIST.3 (Exhaustivité) | E (20%) | +0.05-0.07 | +0.01-0.02 | 1j |
| D-LIST.4 (Attributes) | D (5%) | +0.02 | <+0.01 | 0.5j |
| D-LIST.5 (Scorer fuzzy) | mesure | révélateur (+0.10) | (+0.02 perçu) | 0.5j |
| D-LIST.6 (Observabilité) | transverse | — | — | 1j |
| **TOTAL** | | **+0.22-0.32** | **+0.04-0.07** | **7-9j** |

**list_score cible post-fix** : 0.160 → ~0.45 (depuis 16% du parfait → 45%)

---

## §2 — Type FACTUAL (5 questions, 15% du parfait)

### 2.1 Observations chiffrées

| Métrique CH-48 | Score moyen | Distance à 1.0 |
|---|---:|---:|
| `structured_avg` | 0.150 | 0.850 manque |
| `exact_match` | 0.10 | 0.90 manque |
| `citation_rate` | 0.20 | 0.80 manque |
| `judge_score` | 0.24 | 0.76 manque |

**Particularité** : sur 5 questions, **4 stagnent à 0.0**, seule COND_011 atteint 0.75. La moyenne est tirée par 1 succès isolé.

### 2.2 Distribution des patterns

| Pattern | Nb | % | Description |
|---|---:|---:|---|
| **G — Échec sur NÉGATIONS** | 3 | **60%** | Pipeline cherche facts affirmatifs, n'a pas de représentation des exclusions/négations |
| **F — Extraction brute non-raisonnée** | 1 | 20% | Conditionnelle temporelle mis-classée factual → extraction sans raisonnement |
| **OK partiel** | 1 | 20% | COND_011 conditionnelle oui/non bien traitée (judge 0.8) |

### 2.3 Exemples emblématiques

#### Pattern G — Négations (DOMINANT 60%)
**NEG_006** : "Selon 2021/821, qu'est-ce qui **N'EST PAS** requis pour qu'une transaction de produit dual-use de l'Annex I soit légale ?"
- Attendu : exclusions Article 9 (autorisation générale Union, non-application sous certaines conditions)
- CH-48 : `"Aucun fait extractif trouvé (motif: no_atomic_facts)"` — **abstain explicite du V4.1 facts-first**
- Le pipeline ne sait pas extraire des facts négatifs ("X n'est PAS requis") ni raisonner par exclusion sur l'ensemble.

**NEG_009** : "Selon 428/2009, qu'est-ce qui **N'EST PAS** soumis à autorisation pour les transferts intra-Communautaires ?"
- Attendu : Annexe IV de 428/2009 (transferts intra-comm de l'Annex IV non soumis)
- CH-48 : "pas trouvé"
- CH-46 : invente "information dans le domaine public, basic scientific research, minimum necessary information for patent applications" (= exemptions Article 19 sur transferts technology, **mauvaise réponse** mais judge donne 0.2)

#### Pattern F — Mis-classification conditionnelle temporelle
**COND_007** : "Si un dossier de certification CS-25 a été ouvert le 1er février 2024, quelle version d'amdt est verrouillée comme certification basis ?"
- Attendu : CS-25 Amdt 28 (publié 2023-12-15, donc en vigueur au 1er fév 2024)
- CH-48 : `"CS-25 has amendment Amdt No: 25/26. CS-25 has amendment Amdt No: 25/24. Certification Basis includes FAR 25 amendment or CS 25 change no.."`
- Diagnostic : Analyzer classe en `factual` → `factual_path` extractif → ne raisonne pas la date butoir vs. publication amendments
- **Mis-tag gold-set** : la question est en réalité `conditional` (avec dimension temporelle), à corriger lors de CH-50.

#### Pattern OK partiel — Conditionnelle bien traitée
**COND_011** : "Si un transfert intra-Union concerne un item listé en Partie 2 de l'Annex IV (sous 428/2009), une autorisation générale est-elle suffisante ?"
- CH-48 : `"Si un transfert intra-Union concerne un item listé en Partie 2 de l'Annex IV, une autorisation générale peut ne pas être suffisante [doc=dualuse_reg_428_2009_original_372b7ac3]"`
- structured_avg=0.75, judge=0.8 — citation correcte, info juste, manque juste la conclusion explicite "non, individuelle requise"
- Démontre que le pipeline **peut** bien traiter les conditionnelles oui/non quand bien retrievées.

### 2.4 Causes structurelles racines

#### Cause FACT-α : Mis-classification conditionnelles dans Analyzer
COND_007 et COND_011 sont des **conditionnelles** ("Si X, alors Y") mais le gold-set v4 les a taggées `factual`. Conséquence en chaîne :
- L'Analyzer suit ce tag → route en `factual_path`
- `factual_path` = chunk-extractive fallback (D-FF13) sans raisonnement
- Pas de mobilisation du `reasoning_path` qui aurait été approprié

→ Double problème : Analyzer + gold-set.

#### Cause FACT-β : Pipeline V4.1 facts-first n'a pas de représentation des négations (DOMINANT 60%)
Le `EvidenceCollector` extrait des claims/chunks **affirmatifs**. Le `Structurer` produit des `atomic_facts` du type `"X requires Y"`. Quand la question demande "qu'est-ce qui n'est PAS X", le pipeline n'a aucun mécanisme pour :
1. Identifier l'**ensemble complet** des choses concernées
2. Identifier le **sous-ensemble qui EST X**
3. Calculer la **différence** (ce qui est dans 1 mais pas dans 2)

Symptôme observé : abstain (`no_atomic_facts`) ou hallucination par mauvais retrieval.

#### Cause FACT-γ : `factual_path` strictement extractif
Le `factual_path` actuel se contente d'extraire les facts présents dans le retrieval, sans raisonnement. Pour les questions factuelles avec **dimension temporelle** ("aujourd'hui", date donnée, "en vigueur"), cela manque de la logique "filtrer par lifecycle/date".

#### Cause FACT-δ (transverse) : Judge inconsistant sur négations
Sur NEG_007, CH-46 invente des paragraphes (CS 25.1725/1727/1729 — non vérifiés dans le corpus) et le judge donne **0.9**. Sur NEG_009 même type d'hallucination → 0.2. Le judge LLM tolère des hallucinations bien formatées sur questions négatives.

→ Risque : l'amélioration des négations pourrait être **masquée** par un judge qui valide des hallucinations. Garde-fou nécessaire.

### 2.5 Décisions FACTUAL

#### D-FACT.1 — Détection sémantique des conditionnelles dans Analyzer (couvre Cause α)
**Décision** : améliorer le QuestionAnalyzer pour détecter sémantiquement les questions conditionnelles ("Si X alors Y", "When X", "If X", équivalents multilingues). Quand détectée :
- `primary_type=conditional` (override le tag gold-set si nécessaire)
- Routage vers `reasoning_path`
- Re-tagger le gold-set v4 pour corriger les mis-tags `factual` → `conditional` (chantier CH-50)

**Note charte** : détection LLM sémantique multi-langue, PAS de regex/keywords.

**Impact estimé** : récupère ~20-30% des fails factual (les conditionnelles mis-classées) + bénéfice indirect sur le score `conditional` (déjà à 0.6 mais peut monter).
**Effort** : 1-2 jours (prompt Analyzer + tests + re-tag gold).
**Risque** : si la détection est trop sensible, risque de routage abusif vers reasoning_path (latence accrue).

#### D-FACT.2 — Path `negation_path` dédié (couvre Cause β — DOMINANT)
**Décision** : ajouter au Analyzer un signal `negation=true` quand la question contient une formulation négative ("qu'est-ce qui n'est pas", "what is not", "lesquels NE SONT PAS", "exclude", équivalents multilingues sémantiques).

Pour ces questions, activer un nouveau `negation_path` qui :
1. **Reformulation interne** : "qu'est-ce qui N'EST PAS X requis pour Y" → "quels sont les exemptions / exclusions explicites pour Y"
2. **Retrieval ciblé** : filtres sémantiques privilégiant chunks contenant `"exempted from"`, `"not subject to"`, `"exclu de"`, `"ne s'applique pas"`, `"sauf"` (multilingue)
3. **Si trouvé** : extraction directe des items exemptés via Structurer, format Composer : "Selon X, sont exclus : ..."
4. **Si non trouvé** : abstain explicite avec raison `no_explicit_exclusion_stated` (au lieu de `no_atomic_facts` ambigu)

**Limite acceptée** : ne couvre pas les questions où l'exclusion est **implicite** (à dériver par raisonnement complexe). Pour celles-là, abstain est légitime et le judge ne devrait pas pénaliser.

**Impact estimé** : récupère ~60% des fails factual (Pattern G dominant).
**Effort** : 2-3 jours (path + reformulation interne + retrieval filter + Composer prompt + tests).
**Risque charte** : la détection des négations doit être sémantique (LLM), pas regex. Les filtres retrieval sur "exempted from" etc. peuvent être génériques mais doivent rester multilingues.

#### D-FACT.3 — Routage factual+temporel vers reasoning_path (couvre Cause γ)
**Décision** : si Analyzer détecte une question factuelle MAIS avec dimension temporelle explicite (date dans la question, "aujourd'hui", "actuellement", "en vigueur", "currently", "currently in force"), router vers `reasoning_path` au lieu de `factual_path`. Le `reasoning_path` peut alors mobiliser :
- Les relations temporelles du KG (LIFECYCLE_RELATION)
- Le raisonnement comparatif "date question vs date publication"
- L'identification de la version active à la date donnée

**Impact estimé** : récupère ~10-20% des fails factual (chevauche partiellement avec D-FACT.1 pour les conditionnelles temporelles).
**Effort** : 0.5 jour (logique routage + tests).

#### D-FACT.4 — Garde-fou hallucination sur négations (couvre Cause δ — observabilité)
**Décision** : pour les questions négatives détectées (D-FACT.2 signal), ajouter une vérification post-Composer :
- Si la réponse contient des **identifiants spécifiques** (codes Annex, paragraphes CS, articles, dates)
- ET ces identifiants ne sont **pas présents dans le retrieval** (chunks_retrieved)
- → flag `negation_hallucination_risk=true`

Optionnellement : abstain plutôt qu'output si le flag est levé.

Reporting : alerter sur le dashboard les samples avec ce flag.

**Impact** : observabilité + prévention hallucinations sur questions négatives.
**Effort** : 1 jour (instrumentation + détection + dashboard).
**Risque charte** : l'extraction d'identifiants peut être genre-agnostic (regex `\b[A-Z]+\s?\d+(\.\d+)*\b` est trop spécifique). Préférer extraction sémantique des "claims spécifiques" via LLM léger.

### 2.6 ROI cumulé estimé Fix FACTUAL

| Fix | Pattern couvert | Δ factual_score | Δ global_score | Effort |
|---|---|---:|---:|---:|
| D-FACT.1 (conditionnelles) | α | +0.10-0.20 | +0.005 | 1-2j |
| D-FACT.2 (negation_path) | β (60%) | +0.15-0.25 | +0.01 | 2-3j |
| D-FACT.3 (routage temporel) | γ partiel | +0.05-0.10 | +0.003 | 0.5j |
| D-FACT.4 (judge hallucination guard) | δ (observabilité) | indirect | indirect | 1j |
| **TOTAL** | | **+0.30-0.55** | **+0.018-0.03** | **4.5-6.5j** |

**factual_score cible post-fix** : 0.150 → ~0.50 (15% du parfait → 50%)

**⚠️ Variance importante** : avec n=5 sur le subset, l'estimation a une grande incertitude. Les vrais gains seront mesurés sur le bench complet 170q post-CH-50 (gold complet).

### 2.7 Observation transverse — chevauchement type/sub-type

L'analyse factual révèle un problème plus large : le gold-set v4 utilise un seul `primary_type` par question, mais beaucoup ont **plusieurs facettes** :
- COND_007 : conditional + temporal + factual
- NEG_006 : factual + negation
- NEG_007 : list + negation

→ **D-TR.4 (proposition transverse)** : adopter un **multi-tag** dans le gold-set v5 (`primary_type`, `secondary_types[]`, `flags[]: negation, temporal, conditional`) pour permettre :
- Routage Analyzer plus précis
- Métriques par flag (taux d'échec négation toutes catégories confondues)
- Ciblage chirurgical des fixes

À ajouter en §8 décisions transverses.

---

## §3 — Type UNANSWERABLE (5 questions, 20% du parfait — RÉGRESSION CH-48 vs CH-46)

### 3.1 Observations chiffrées

| Métrique CH-48 | Score moyen | Distance à 1.0 |
|---|---:|---:|
| `structured_avg` | 0.200 | 0.800 manque |
| `judge_score` | 0.40 | 0.60 manque |
| **judge ≥ 0.8 (abstain correct ou réponse OK)** | **2/5 (40%)** | — |

**⚠️ RÉGRESSION CH-48 vs CH-46** : CH-48 score 2/5 sur judge≥0.8 vs CH-46 3/5. CH-48 régresse de **-20pp** sur ce type. Régression individuelle identifiée : UNA_011.

### 3.2 Distribution des patterns

| Pattern | Nb | % | Description |
|---|---:|---:|---|
| **U — Abstain correct** | 2 | 40% | Pipeline reconnaît absence info, abstain propre, judge=1.0 |
| **O — Dérive off-topic** | 2 | 40% | Question hors-scope → pipeline produit info adjacente au lieu d'abstain |
| **H — Hallucination par chunk semi-pertinent** | 1 | 20% | Pipeline invente un fait spécifique à partir d'un chunk lié au sujet général |

### 3.3 Exemples emblématiques

#### Pattern O — Dérive off-topic (40%)
**UNA_006** : "Quelle est la **position de la Russie** sur le règlement 2021/821 ?"
- Gold : `unanswerable` (Russie pas dans corpus EU dual-use)
- CH-48 : `"Regulation (EU) 2021/821 was adopted on 11.6.2021"`
- Diagnostic : retrieval trouve chunks sur 2021/821 (date adoption, articles...), Composer construit une réponse **sur le sujet général** au lieu de reconnaître que **la facette demandée** (position Russie) n'est pas dans le corpus.

**UNA_011** : "Le règlement 2021/821 a-t-il été **traduit dans les 24 langues officielles** ?"
- Gold : `unanswerable` (info pas dans corpus)
- CH-48 : `"Regulation (EU) 2021/821 was published on 11.6.2021. Regulation (EU) 2021/821 is applicable in all Member States."`
- CH-46 : `"La réponse à votre question n'a pas été trouvée dans les documents disponibles."` ← CH-46 fait mieux !
- Diagnostic : **régression CH-48** — le Composer Llama-Turbo accepte plus volontiers de "remplir avec ce qu'il a" alors que Qwen-72B abstient mieux.

#### Pattern H — Hallucination par chunk semi-pertinent (20%)
**UNA_004** : "Quel est le **nom du commissaire** ayant signé le règlement délégué 2024/2547 ?"
- Gold : `unanswerable` (le nom n'est pas mentionné dans le corpus)
- CH-48 : `"Commission Delegated Regulation (EU) 2024/2547 was signed by Ursula VON DER LEYEN"`
- Diagnostic : retrieval trouve un en-tête EU OJ mentionnant `"Pour la Commission, La Présidente, Ursula VON DER LEYEN"` (formule générique de tête d'acte EU). Le Composer **confond** "président de la Commission" avec "commissaire signataire d'un délégué" et l'attribue. **Hallucination par confusion catégorielle**.

#### Pattern U — Abstain correct (40%) — comportement souhaité
**UNA_003** : "Combien d'autorisations délivrées par la France en 2023 ?"
- Gold : `unanswerable` (statistiques nationales pas dans corpus)
- CH-48 : `"La réponse à votre question n'a pas été trouvée dans les documents disponibles."` ✓
- judge=1.0 ✓

### 3.4 Causes structurelles racines

#### Cause UNA-α : Pas d'étape "Question ↔ Answer Alignment Verifier" (DOMINANT)
Le pipeline V4.1 produit une réponse à partir des facts retrievés sans vérifier que **cette réponse adresse la question posée**. Quand la question demande X mais le retrieval ne trouve que Y (sujet adjacent), le Composer construit une réponse sur Y → off-topic.

**Insight transverse critique** : cette même cause explique :
- list Pattern A (items vus mais hors cible) — 40%
- factual Pattern F (extraction brute non-raisonnée) — 20%
- unanswerable Pattern O (off-topic) — 40%

→ **Un fix unique (Q↔A Alignment Verifier) peut significativement améliorer 3 types**. Promotion en D-TR.5.

#### Cause UNA-β : Pas de Source Attribution Strictness
Quand la réponse contient une affirmation **spécifique** (nom propre, code, identifiant numérique), le Composer ne vérifie pas que cette affirmation est **textuellement** présente dans les chunks retrievés et explicitement attribuée. Risque hallucinations par confusion catégorielle (UNA_004 von der Leyen).

#### Cause UNA-γ : Pas de Scope Check ontologique pré-retrieval
Le pipeline n'a pas d'étape "est-ce que cette question est conceptuellement dans le scope du corpus ?". Des questions intrinsèquement hors-scope (position d'États tiers sur un règlement EU, coût administratif jamais détaillé dans la régulation, traductions linguistiques) lancent un retrieval qui trouve des chunks vaguement liés et génèrent du off-topic.

#### Cause UNA-δ : Scorer mesure mal les abstains corrects
Sur UNA_003 et UNA_007, le pipeline abstient correctement. Le judge donne 1.0 mais le scorer `structured_metrics` donne 0.0 (aucun item à matcher, citation_rate=0). Cela **sous-évalue artificiellement** les abstains corrects.

→ Anti-Goodhart : "abstain quand on doit" est un comportement **souhaité**, qui doit scorer 1.0 en structured_avg, pas 0.0.

### 3.5 Décisions UNANSWERABLE

#### D-UNA.1 — promu en **D-TR.5** (Q↔A Alignment Verifier transverse)
*(Voir §8 D-TR.5 — couvre Cause UNA-α + list Pattern A + factual Pattern F)*

#### D-UNA.2 — Source Attribution Strictness (couvre Cause β)
**Décision** : ajouter un Verifier post-Composer qui, pour les questions où la réponse contient des **affirmations spécifiques** (noms propres, codes, dates exactes, identifiants numériques) :
1. Extraction sémantique (LLM léger) des affirmations spécifiques de la réponse
2. Pour chaque affirmation : vérifier qu'elle est **textuellement présente** dans au moins 1 chunk du retrieval ET citée par `[doc=...]`
3. Si absent → flag `unsupported_specific_claim` ou suppression de l'affirmation, possiblement abstain explicite

**Impact** : récupère ~20% fails unanswerable (Pattern H — UNA_004) + transverse anti-hallucination (~5-10% factual et list).
**Effort** : 1-2 jours (Verifier + prompt + tests).
**Risque charte** : extraction d'affirmations spécifiques par LLM sémantique, pas regex.

#### D-UNA.3 — Scope Check ontologique pré-retrieval (couvre Cause γ)
**Décision** : ajouter avant retrieval une étape `scope_check` :
- L'Analyzer reçoit la question + une description sémantique du corpus (auto-générée à partir des claims principaux et tenants/aboutissants)
- Détermine `in_scope=true/false` ou `partial_scope`
- Si `in_scope=false` → abstain explicite avec raison `out_of_corpus_scope`
- Si `partial_scope` → continuer mais marquer le sample pour observabilité

**Note charte** : la description du corpus doit être **dynamique** (générée à partir des claims/topics du KG), pas hardcodée corpus-spécifique. Multilingue.

**Impact** : récupère ~20-40% fails unanswerable (cas hors-scope intrinsèque : UNA_006 Russie, UNA_011 traductions) + bénéfice "réponses fiables" pour utilisateurs prod.
**Effort** : 2 jours (générateur description corpus + scope check LLM + tests).
**Risque** : la description corpus mal générée pourrait causer des faux positifs (rejeter des questions valides).

#### D-UNA.4 — Scorer correct-abstain reward (couvre Cause δ)
**Décision** : modifier le scorer `structured_metrics` pour traiter spécifiquement `gold.answerability == "unanswerable"` :
- Si la réponse pipeline contient les marqueurs d'abstain canoniques ("pas trouvé", "non disponible", "not found", "not available", équivalents multilingues sémantiques) → `structured_avg = 1.0`
- Si la réponse pipeline contient des affirmations factuelles → `structured_avg = 0.0` (hallucination)
- Citation_rate non applicable (`applicable=false`) sur abstain correct

**Impact** : non-produit, mais **révèle le vrai score qualité** sur unanswerable. Estimé : élève le score moyen unanswerable de 0.200 à ~0.50 (40% des questions = abstain correct → 1.0).
**Effort** : 0.5 jour (refactor scorer + tests).
**Note** : cohérence avec D-LIST.5 (scorer fuzzy) — les structured_metrics sont en train d'être généralement améliorées.

### 3.6 ROI cumulé estimé Fix UNANSWERABLE

| Fix | Pattern couvert | Δ unanswerable_score | Δ global | Effort |
|---|---|---:|---:|---:|
| **D-TR.5** (Q↔A Alignment, transverse) | O (40%) | +0.20-0.30 | +0.005 | (voir §8) |
| D-UNA.2 (Source attribution) | H (20%) | +0.10-0.15 | +0.003 | 1-2j |
| D-UNA.3 (Scope check) | γ (20-40%) | +0.15-0.25 | +0.005 | 2j |
| D-UNA.4 (Scorer abstain reward) | mesure | +0.40 (révélateur) | (+0.01 perçu) | 0.5j |
| **TOTAL** | | **+0.85** (incl. mesure) | **+0.023** | **3.5-4.5j** + D-TR.5 |

**unanswerable_score cible post-fix** : 0.200 → **~0.70+** (20% → 70%+)

### 3.7 Régression CH-48 vs CH-46 sur UNA_011 — racine identifiée

**UNA_011** : `"2021/821 traduit dans 24 langues ?"` — CH-48 régresse vs CH-46 (CH-46 abstain, CH-48 off-topic).

Hypothèse : Llama-Turbo a une tendance à "remplir" avec les facts retrievés disponibles plus que Qwen-72B. C'est **cohérent avec le signal historique** Levier 4 (06/05) où Llama-Turbo abstient massivement comme Structurer mais ici le pattern est inversé (en Composer, Llama-Turbo abstient **moins** que Qwen).

→ Confirmé que **D-TR.5 (Q↔A Alignment)** est nécessaire indépendamment du choix de Composer : sans cette vérification, n'importe quel modèle Composer peut faire du off-topic.

---

## §4 — Type TEMPORAL (15 questions, 43% du parfait — REGRESSION individuelle T7_0002)

### 4.1 Observations chiffrées

| Métrique CH-48 | Score moyen | Distance à 1.0 |
|---|---:|---:|
| `structured_avg` | 0.426 | 0.574 manque |
| `exact_match` | 0.34 | 0.66 manque |
| `citation_rate` | 0.46 | 0.54 manque |
| `judge_score` | 0.43 | 0.57 manque |

**Régression CH-48 vs CH-46** : T7_AERO_0002 (-0.445) déjà identifiée — Llama-Turbo retourne 1/3 délégués (Pattern E) là où Qwen-72B sortait 3/3.

### 4.2 Distribution des patterns

| Pattern | Nb | % | Description |
|---|---:|---:|---|
| **OK / partiel** | 5 | 33% | Réponses correctes avec citations, score ≥ 0.5 |
| **T2 — Pas de raisonnement temporel "version active à date X"** | 4 | **27%** | NOUVEAU pattern propre à temporal |
| **B-KG — Question KG-centrique** | 3 | 20% | Comptage/existence de relations KG (SUPERSEDES, LIFECYCLE_RELATION) |
| **E — Liste/synthèse incomplète** | 2 | 13% | Délégués modifiant l'Annex I incomplet |
| **G+δ — Négation et/ou dégénération** | 1 | 7% | Texte corrompu ("rep rep") sur question difficile |

### 4.3 Exemples emblématiques

#### Pattern T2 — Pas de raisonnement temporel actif (NOUVEAU 27%)
**TMP_001** : "Quelle était la version de CS-25 applicable en juin 2020 ?"
- Gold attendu : Amdt 24 (eff. 2020-01-10) ou Amdt 25 (eff. 2020-06-24) selon le jour précis de juin 2020
- CH-48 : `"CS-25 was applicable Amendment 25"` — pas de date, pas de citation, pas de raisonnement temporel
- structured_avg=0.0
- CH-46 fait mieux : "initialement Amendment 24, modifiée Amendment 25, en date du 24 juin 2020" → judge=0.8

**TMP_012** : "Quel amdt CS-25 s'appliquait au moment de la publication du 2021/821 (juin 2021) ?"
- Gold attendu : Amdt 26 (publié 2020-12-15, donc en vigueur en juin 2021)
- CH-48 : `"Amendment 24 CS-25 was effective on 10 January 2020"` — donne le **mauvais amendment** (Amdt 24 ≠ Amdt 26 actif en juin 2021)
- Diagnostic : pipeline retourne le 1er amdt vu dans le retrieval, sans raisonner "quelle version était active à la date Y"

**TMP_010** : "Si une question est posée aujourd'hui sur CS 25.795, quelle version d'amdt faut-il citer ?"
- Gold attendu : CS-25 Amendment 28 (publié 2023-12-15)
- CH-48 : `"version Amended (NPA 2015-11)"` ← **confond NPA (consultation) avec Amendment** + ne raisonne pas la version active "aujourd'hui"

#### Pattern δ — Dégénération texte Llama-Turbo
**TMP_009** : "Pour un audit retrospectif sur transaction sept 2022, quelle Annex I est applicable ?"
- CH-48 : `"Regulation (EU) 2021/821 has Annex I Annex I to Regulation (EU) 2021/821. Annex I to Regulation (EU) 2021/821 was amended 2023. Regulation (EU) 2021/821 entered into force the day following that of its publication."`
- Texte **répétitif et incohérent** : "Annex I Annex I to" × 3, pas de raisonnement temporel.
- Cohérent avec signal historique Levier 4 (06/05) : Llama-Turbo PIÈGE en certaines configurations.

**T7_AERO_0033** : "Y a-t-il un acte délégué dual-use du corpus qui ne semble PAS modifier l'Annex I de 2021/821 ?"
- CH-48 : `"Regulation (EU) 2021/821 should be amended accordingly. Annex I to Regulation (EU) 2021/821 is rep rep."` ← **garbage** ("is rep rep")
- Combo Pattern G (négation) + δ (dégénération).

#### Pattern γ — Pas d'inférence relationnelle réversible
**T7_AERO_0001** : "Quel règlement a remplacé 428/2009 ?"
- Gold attendu : 2021/821
- CH-48 : `"428/2009 a été abrogé, mais le règlement qui l'a remplacé n'est pas spécifié dans les faits fournis"` ← **incohérent** : sait que c'est abrogé, mais ne sait pas par qui (alors que le KG a la relation `2021/821 SUPERSEDES 428/2009`)
- Cause : le pipeline V4.1 facts-first traite les facts dans une seule direction. Si `2021/821 abroge 428/2009` est extrait, l'inférence inverse "428/2009 remplacé par 2021/821" n'est pas faite.

#### Pattern OK — Raisonnement conceptuel KG correct
**T7_AERO_0044** : "L'EVOLVES_FROM 2023/66 → 2021/821 implique-t-il que 2021/821 est DEPRECATED ?"
- CH-48 : `"...certaines parties de 2021/821 (Annex I) sont remplacées... mais cela ne signifie pas nécessairement que 2021/821 est entirely déprécié"` ✅
- structured_avg=1.0, judge=0.8
- Démontre que le pipeline **peut** raisonner sur la sémantique fine des relations LIFECYCLE quand le contexte est bien retrieved.

### 4.4 Causes structurelles racines

#### Cause TEMP-α : Pas de "Temporal Reasoning" pour version active à date donnée (DOMINANT 27%)
Pour les questions "version active à date X" / "aujourd'hui quelle version" / "à la publication de Y, quel amdt", il faudrait :
1. Mobiliser les LIFECYCLE_RELATION du KG (effective_date, successor)
2. Calculer la fenêtre temporelle : `effective_date ≤ date_question < successor.effective_date`
3. Output : version + dates des bornes

Ce raisonnement n'est dans aucun path V4.1 actuel. Le `reasoning_path` couvre causal/comparison/hypothetical mais pas temporal-active-version.

#### Cause TEMP-β : Questions KG-centriques (déjà identifiée — chevauche D-LIST.2)
T7_0032 (chaîne SUPERSEDES), T7_0046 (combien de SUPERSEDES), T7_0047 (CS-25 change_amdt LIFECYCLE_RELATION) demandent comptage/existence de relations KG. Pipeline fait du retrieval Qdrant chunks au lieu d'interroger Neo4j.

#### Cause TEMP-γ : Pas d'inférence relationnelle réversible (10%)
Le ListStructurer V4.1 extrait des facts unidirectionnels ("X SUPERSEDES Y"). Quand la question demande la relation inverse ("qui remplace Y" → X), l'inférence n'est pas faite. Le KG Neo4j stocke pourtant la relation dans les deux sens (`-[:SUPERSEDES]->` interrogeable inverse).

#### Cause TEMP-δ : Composer Llama-Turbo dégénération texte (5-10%)
Sur certaines questions difficiles (négation, raisonnement temporel complexe), Llama-Turbo produit des textes répétitifs ("Annex I Annex I to") ou tronqués ("rep rep"). Cohérent avec signal historique Levier 4 (mémoire `project_v4_facts_first_post_leviers_2026_05_07`).

### 4.5 Décisions TEMPORAL

#### D-TEMP.1 — Path `temporal_active_version` (couvre Cause α — DOMINANT)
**Décision** : nouveau path dédié pour les questions "version active à date X" :
1. **Détection sémantique** dans Analyzer :
   - Présence d'une **date butoir** explicite ou implicite (date dans la question, "aujourd'hui", "actuellement", "en vigueur", équivalents multilingues)
   - Sujet identifiable comme document à versions (règlement, amendment, etc.)
   - → flag `temporal_active=true`
2. **Path** :
   - Query Cypher Neo4j : récupérer toutes les versions du sujet avec leurs `effective_date` et chaîne `:NEXT_VERSION` ou `:SUPERSEDES`
   - Raisonnement (templated, pas LLM) : `active_at(date) = v WHERE v.effective_date ≤ date AND (v.successor IS NULL OR v.successor.effective_date > date)`
   - Output Composer : "À [date X], [version Y] s'applique. [version Y] est en vigueur depuis [date_eff_Y]. [Optionnel : sa version successeur [version Z] entre en vigueur le [date_eff_Z]]"

**Impact estimé** : récupère ~25% des fails temporal (Pattern T2).
**Effort** : 3 jours (path + Cypher + raisonnement + Composer prompt + tests).
**Risque charte** : la détection de "date butoir" doit être sémantique multi-langue (pas regex date), via LLM léger.

#### D-TEMP.2 — Lien D-LIST.2 (kg_query_path partagé)
*(Voir D-LIST.2 — couvre les 3 questions KG-centriques temporal aussi : T7_0032, T7_0046, T7_0047. Pas de nouveau coût.)*

#### D-TEMP.3 — Inférence relationnelle réversible (couvre Cause γ)
**Décision** : pour les questions "qui a remplacé X", "qui modifie Y", "Y dérive de quoi", quand le pipeline trouve une relation `Y :SUPERSEDED_BY: X` ou `Y :EVOLVES_FROM: X`, le Composer doit pouvoir formuler la **réponse inverse** correctement.

Implementation :
- Le Cypher peut être bidirectionnel : `MATCH (x)-[:SUPERSEDES]->(y) WHERE y.id = "428/2009" RETURN x`
- Le Composer prompt explicite "si la question demande la relation inverse, présente-la dans le bon sens" + exemples génériques

**Impact estimé** : récupère ~10% des fails temporal (Pattern γ).
**Effort** : 0.5 jour (prompt Composer + Cypher templates inversés + tests).

#### D-TEMP.4 — Composer dégénération detection + retry (couvre Cause δ — TRANSVERSE)
**Décision** : ajouter une post-validation Composer simple :
- Détection **répétitions textuelles** : si N-gramme (3-5 mots) apparaît ≥ 3 fois consécutives → flag `composer_degenerate`
- Détection **texte tronqué** : si la sortie contient des suites de tokens identiques ("rep rep", "Annex I Annex I to") → flag `composer_garbage`
- Si flag → **retry une fois** avec prompt "produce coherent answer without repetition" + temperature légèrement augmentée (0.1 → 0.3)

**Impact estimé** : couvre 5-10% des fails temporal + transverse list/factual sur questions difficiles.
**Effort** : 0.5 jour (validateur regex token-level + retry logic + tests).
**Note charte** : la détection de répétition est **lexicale neutre** (pas corpus-spécifique), c'est purement un garde-fou anti-dégénération LLM.

#### D-TEMP.5 — Lien D-TR.4 (multi-tag) — temporal+negation
T7_0033 est temporal + negation + KG. Le multi-tag (D-TR.4) permet de router avec les flags appropriés (kg_query_path + negation_path + temporal_active_path en cascade ou priorité). Pas une nouvelle décision, validation que D-TR.4 résout l'intersection.

### 4.6 ROI cumulé estimé Fix TEMPORAL

| Fix | Pattern | Δ temporal_score | Δ global | Effort spécifique |
|---|---|---:|---:|---:|
| **D-TR.5** (Q↔A Alignment) | partiel sur OK→OK | indirect | (voir §8) | (transverse) |
| D-TEMP.1 (temporal active version) | T2 (27%) | +0.10-0.15 | +0.01 | 3j |
| D-LIST.2 (kg_query partagé) | β-KG (20%) | +0.08-0.12 | +0.005 | (déjà dans LIST) |
| D-TEMP.3 (inférence inverse) | γ (10%) | +0.05 | +0.003 | 0.5j |
| D-TEMP.4 (anti-dégénération) | δ (5-10%) | +0.03 | +0.003 (transverse) | 0.5j |
| **TOTAL TEMPORAL spécifique** | | **+0.18-0.23** | **+0.018-0.022** | **4-4.5j** |

**temporal_score cible post-fix** : 0.426 → **~0.65** (43% du parfait → 65%)

### 4.7 Notes additionnelles

**Sur la régression individuelle T7_0002** : Pattern E déjà documenté (D-LIST.3 Composer exhaustivité). Le combo D-LIST.3 + D-TEMP.1 devrait également récupérer T7_0002.

**Sur Pattern δ et le choix du modèle Composer** : si la dégénération devient récurrente (>10% des questions difficiles), il faudra envisager un swap Composer (DeepSeek-V3.1, Qwen-235B) malgré les arguments cohérence bench/prod. À surveiller post-D-TEMP.4 retry : si retry corrige bien la dégénération, on garde Llama-Turbo. Sinon, swap.

---

## §5 — Type CAUSAL (13 questions, **75% du parfait** — type le plus performant)

### 5.1 Observations chiffrées

| Métrique CH-48 | Score moyen | Distance à 1.0 |
|---|---:|---:|
| `structured_avg` | 0.751 | 0.249 manque |
| `exact_match` | 0.62 | 0.38 manque |
| `citation_rate` | 0.85 | 0.15 manque |
| `judge_score` | 0.55 | 0.45 manque |

**Observation clé** : structured_avg (0.75) >> judge_score (0.55). Le scorer LLM-judge **sous-évalue** le pipeline sur causal — possiblement pénalise des réponses correctes mais non-conformes au style attendu.

**Régression individuelle** : T6_AERO_CAUS_005 (-0.500) — abstain CH-48 vs OK CH-46.

### 5.2 Distribution des patterns

| Pattern | Nb | % | Description |
|---|---:|---:|---|
| **OK / Excellent** | 7 | **54%** | Réponse correcte, citée, judge ≥ 0.7 |
| **Causal-α : Cause partielle/générique** | 4 | 31% | Cadre général au lieu de cause précise |
| **Régression individuelle CAUS_005** | 1 | 8% | Llama-Turbo Structurer manque fact |
| **Causal-δ : Réponse circulaire** | 1 | 8% | "Car le règlement le dit" |
| **Causal-γ : Hypothétique multi-étapes évité** | 1 | 8% | HYP_003 "Si X alors Y → Z ?" |

### 5.3 Exemples emblématiques

#### Pattern Causal-α — Cause partielle/générique (DOMINANT 31%)
**CAUS_006** : "Pourquoi le règlement 2021/821 prévoit-il des exemptions pour les informations dans le domaine public ?"
- Gold reference (implicite) : préserver la liberté de recherche académique + facilité de circulation des informations publiques
- CH-48 : `"...car les technologies ou logiciels dans le domaine public sont disponibles sans restrictions sur leur diffusion"` ← **explique le mécanisme**, pas la motivation profonde
- structured_avg=1.0 (exact_identifiers OK) MAIS judge=0.5 ("misses key point of preserving research freedom")
- Diagnostic : le pipeline retrieve correctement, le Composer formule mais cible **le cadre** au lieu de **la cause précise demandée**.

**CAUS_008** : "Pourquoi 2021/821 confère pouvoir d'adopter actes délégués pour Annex I ?"
- CH-48 : "garantir conformité avec obligations internationales et compétitivité"
- judge=0.4 ("misses key point") — la vraie cause est la **fréquence des changements** des listes internationales (Wassenaar, MTCR, NSG), pas la conformité abstraite.

#### Pattern Causal-δ — Réponse circulaire (8%)
**CAUS_011** : "Pourquoi les autorisations doivent-elles être valides sur l'ensemble du territoire douanier de l'Union ?"
- CH-48 : `"car cela est spécifié par le règlement [doc=...]"` ← **réponse circulaire** (le pipeline justifie l'existence d'une règle par l'existence de la règle)
- judge=0.7 (juge sympa) mais c'est faux pédagogiquement (la vraie cause = harmonisation marché unique).

#### Pattern Causal-γ — Hypothétique multi-étapes évité (8%)
**HYP_003** : "Si un délégué 2025/X était publié et abrogeait le 2024/2547, l'Annex I reviendrait-elle à la version du 2023/996 ?"
- CH-48 : `"Il n'y a pas d'informations suffisantes pour déterminer..."`
- judge=0.2 ("fails to apply hypothetical reasoning")
- Diagnostic : le reasoning_path V4.1 traite bien les hypothétiques **simples** (HYP_002 "Si Amdt 28 abrogé, version applicable ?" → réponse parfaite Amdt 27) mais **pas les multi-étapes** avec chaînage conditionnel KG.

**HYP_002** (CONTRAST) — pour rappel ce qui marche bien :
- Q : "Si CS-25 Amendment 28 était abrogé demain, quelle serait la version applicable ?"
- CH-48 : `"...la version applicable pourrait être [doc=cs25_amdt_27_992260a7] CS-25 Amendment 27"` ✅
- judge=0.9, démontre le potentiel du reasoning_path en hypothétique simple.

#### Régression CAUS_005 (β)
**CAUS_005** : "Pourquoi 2021/821 exige-t-il que la terminologie soit cohérente avec 952/2013 (Code des douanes) ?"
- CH-48 : `"Aucun fait extractif trouvé (no_atomic_facts)"` → ABSTAIN ❌
- CH-46 : `"[cause] 2021/821 doit être modifié pour assurer conformité... [effect] cohérence terminologique avec 952/2013 nécessaire pour faciliter les références..."` ✅ judge=0.7
- Diagnostic : Llama-Turbo Structurer (V4.1) ne trouve pas le fact "terminologie cohérente avec 952/2013". Qwen-72B (CH-46) le trouvait.
- **Signal architectural** : potentiel Levier 4 partiel — Llama-Turbo Structurer plus strict sur l'extraction, exclut des facts utiles.

### 5.4 Causes structurelles racines

#### Cause CAUSAL-α : Composer trouve le cadre, pas la cause précise (DOMINANT 31%)
Le pipeline V4.1 reasoning_path mobilise les facts du contexte général (recital "whereas") mais ne cible pas spécifiquement **la cause demandée**. Ex : "Pourquoi les exemptions ?" → réponse sur "comment fonctionnent les exemptions" plutôt que "quelle est la motivation profonde".

Manque une étape de **cause-targeting** : qu'est-ce que la question demande comme cause précise ? Filtrer les facts selon cette cible avant le Composer.

#### Cause CAUSAL-β : Llama-Turbo Structurer manque parfois des facts (régression CAUS_005)
Sur CAUS_005, l'EvidenceCollector + Structurer V4.1 avec Llama-Turbo n'extrait pas le fact "terminologie cohérente avec 952/2013" qu'un Qwen-72B Structurer trouvait. Hypothèse : le Llama-Turbo prompt strict + JSON output rend l'extraction trop conservatrice.

À investiguer : signal cohérent avec Levier 4 (Llama-Turbo abstient massivement comme Structurer).

#### Cause CAUSAL-γ : Pas de raisonnement hypothétique multi-étapes
Le reasoning_path V4.1 (CH-47) est calibré pour les hypothétiques simples ("Si X abrogé, quelle version active ?") mais pas pour les chaînages conditionnels multi-étapes ("Si X abrogé, alors Y revient à Z basé sur la chaîne EVOLVES_FROM ?").

#### Cause CAUSAL-δ : Composer parfois circulaire
Quand le pipeline ne trouve pas la motivation profonde, le Composer répond circulairement ("car spécifié par le règlement"). Aucun garde-fou.

### 5.5 Décisions CAUSAL

#### D-CAUSAL.1 — Cause-Targeting dans Composer (couvre Cause α — DOMINANT)
**Décision** : pour les questions causales ("Pourquoi", "Why", "What is the reason", "Warum", équivalents multilingues), le Composer V4.1 reasoning_path doit avoir une étape explicite de cause-targeting :
1. **Identification de la cible causale précise** (LLM léger) :
   - Ex: "Pourquoi exemptions information domaine public" → cible = "raison/motivation des exemptions" (pas "fonctionnement des exemptions")
   - Ex: "Pourquoi pouvoir d'adopter actes délégués" → cible = "ce qui justifie ce mécanisme de modification" (pas "l'objet de ces modifications")
2. **Filtrage des `atomic_facts` et `relational_facts`** selon leur pertinence à la cible (LLM léger sémantique)
3. **Composer prompt enrichi** : "réponds à la cible causale précise. Si la motivation profonde n'est pas explicite dans les facts, sois honnête plutôt que de répondre par un cadre général"

**Impact estimé** : récupère ~20-25% des fails causal (Pattern α — 31%, partial recovery).
**Effort** : 1.5 jour (prompt cause-targeting + filter + tests).
**Note charte** : sémantique LLM, pas patterns lexicaux causaux corpus-spécifiques.

**Note transverse** : cette même décision s'appliquera probablement à **comparison** (qui demande aussi de cibler le critère précis de comparaison). À valider en §6.

#### D-CAUSAL.2 — Détection réponse circulaire (couvre Cause δ)
**Décision** : ajouter au Composer V4.1 reasoning_path une post-validation pour les questions causales :
- Détecter circularité : "car cela est spécifié dans X", "as stated in", "comme indiqué", "according to" sans contenu causal substantiel après
- Si circularité détectée → retry une fois avec prompt "explique la motivation profonde, pas juste l'existence de la règle"

**Impact estimé** : récupère ~5-10% des fails causal (Pattern δ — peu fréquent).
**Effort** : 0.5 jour (validation pattern lexical neutre + retry + tests).
**Note charte** : la détection peut être par patterns lexicaux **multilingues universels** (marqueurs syntaxiques de citation neutre), pas du domain-specific.

#### D-CAUSAL.3 — Multi-step hypothetical reasoning (couvre Cause γ)
**Décision** : pour les questions hypothétiques **multi-étapes** ("Si X alors Y → Z ?"), le reasoning_path V4.1 doit décomposer :
1. État actuel (état du KG — ex: Annex I = version 2024/2547 modifiée, antécédent 2023/996)
2. Modélisation hypothétique (modification d'état — ex: 2024/2547 abrogé)
3. Inférence sur le nouvel état (ex: si 2024/2547 abrogé, l'antécédent EVOLVES_FROM est 2023/996, donc Annex I revient à cette version)

Implementation :
- Détection multi-step dans Analyzer (présence de chaînage conditionnel)
- Composer prompt enrichi avec template "step-by-step hypothetical reasoning" + 1-2 exemples génériques (placeholders f_a/f_b)
- Activation seulement si flag détecté (pas de surcoût sur hypothétiques simples qui marchent déjà bien)

**Impact estimé** : récupère ~5-10% des fails causal (Pattern γ).
**Effort** : 1 jour (détection + prompt + template + tests).
**Risque** : risque de hallucination cumulative sur multi-step (chaque étape ajoute de l'incertitude). Tests obligatoires sur ablation.

#### D-CAUSAL.4 — Audit Structurer Llama-Turbo vs Qwen-72B (couvre Cause β — INVESTIGATION)
**Décision** : audit ciblé sur les régressions CH-48 vs CH-46 où CH-48 abstient et CH-46 répond bien (CAUS_005 + similaires). Comparer :
1. Les `atomic_facts` extraits par Structurer Llama-Turbo vs Qwen-72B sur les mêmes chunks
2. Identifier la racine :
   - **Si Structurer** (extraction trop stricte) → fix prompt Structurer (relâcher critères)
   - **Si EvidenceCollector** (retrieval) → tune top_k_claims ou seuils de retrieval
   - **Si Composer** (utilisation des facts disponibles) → fix prompt Composer

**Impact estimé** : récupère 1-2 régressions individuelles + signal architecture (peut-être plus si Levier 4 partiel se confirme).
**Effort** : 0.5-1 jour (audit ciblé sur ~5-10 samples) + variable selon fix nécessaire.
**Output attendu** : note de diagnostic + 1-2 commits de fix ciblés.
**Lien à D-TEMP.4** : si audit confirme dégénération récurrente Llama-Turbo Structurer → considérer swap Composer/Structurer (DeepSeek-V3.1 ou Qwen-235B) malgré l'argument cohérence bench/prod.

### 5.6 ROI cumulé estimé Fix CAUSAL

| Fix | Pattern | Δ causal_score | Δ global | Effort |
|---|---|---:|---:|---:|
| **D-TR.5** (Q↔A Alignment) | partial sur OK | indirect | (voir §8) | (transverse) |
| D-CAUSAL.1 (cause-targeting) | α (31%) | +0.05-0.10 | +0.005 | 1.5j |
| D-CAUSAL.2 (anti-circularité) | δ (8%) | +0.02-0.04 | +0.002 | 0.5j |
| D-CAUSAL.3 (multi-step hypothétique) | γ (8%) | +0.03-0.05 | +0.003 | 1j |
| D-CAUSAL.4 (audit régressions Structurer) | β (8%) | +0.03-0.05 | +0.003 | 0.5-1j |
| **TOTAL CAUSAL** | | **+0.13-0.24** | **+0.013-0.018** | **3.5-4j** |

**causal_score cible post-fix** : 0.751 → **~0.90** (75% du parfait → 90%) ⭐

### 5.7 Notes additionnelles

**ROI relatif faible mais important pour le produit** : le type causal est déjà à 75%. Les fixes y apportent +0.13-0.24 absolu (+13-24pp). Mais ce type est **central pour le produit** (réponses "pourquoi" = forte valeur perçue par utilisateurs). Donc impact qualitatif élevé même si Δ global modeste.

**D-CAUSAL.4 est un investigation triggerd-by-régression** : peut révéler un problème plus large que le Llama-Turbo a sur le Structurer. Si confirmé, soit on fix le prompt, soit on swap modèle. À surveiller.

**Lien transverse vers comparison** (§6 à venir) : D-CAUSAL.1 (cause-targeting) appliquera probablement aussi à comparison où il faut cibler le **critère précis de comparaison**.

---

## §6 — Type COMPARISON (8 Robust + 40 T2 contradictions, 31% du parfait)

### 6.1 Observations chiffrées

**Subset Robust × gold v5** : 8 questions `primary_type=comparison` (lifecycle_vs_conflict T7), structured_avg moyen 0.312 (CH-48) vs 0.083 (CH-46) → **+0.229pp** ✅

**Bench T2T5 indépendant** : 40 questions T2 contradictions (gold v5 covered), scorer dédié :
| Metric T2 | CH-48 |
|---|---:|
| both_sides_surfaced | 0.203 |
| tension_mentioned | 0.425 |
| both_sources_cited | 0.475 |
| chain_coverage (T5) | 0.284 |

### 6.2 Distribution des patterns (basé sur 3 samples T2 inspectés + 8 Robust)

| Pattern | % | Description |
|---|---:|---|
| **C-α — Routing fail comparison → factual** | ~30% | Question contradictoire routée comme factuelle simple |
| **C-β — Tension mentionnée mais non détaillée** | ~25% | Cite "n'ont pas la même approche" sans expliciter les 2 côtés |
| **C-γ — Items hors-cible (Pattern A transverse)** | ~20% | Confond comparaison de quoi |
| **OK complet** | ~15% | Cite les 2 sources avec valeurs précises |
| **C-δ — Hallucination des deux côtés** | ~10% | Invente une contradiction inexistante |

### 6.3 Exemples emblématiques

**T2 q_0** : "Quelle est l'énergie d'impact spécifiée par CS-25 pour grand item en verre ?"
- Question piégeuse cachant une contradiction Amdt 26 (3.5 J) vs Amdt 28 (21 J)
- CH-48 : `"CS-25 specifies impact energy for 21 J J"` — Pattern C-α (routé `factual_path` au lieu de `comparison_path`)
- Diagnostic : Analyzer ne détecte pas la contradiction implicite → mauvais routing → réponse simpliste

**T2 q_1** : "2021/821 et 428/2009 ont-ils la même approche ?"
- Gold attendu : décrire les 2 approches divergentes
- CH-48 : `"...n'ont pas la même approche [doc=...] et [doc=...]"` — Pattern C-β (tension OK, contenu non détaillé)

**T2 q_10** : "Si Amdt 26 prescrit 3.5 J et Amdt 28 prescrit 21 J, quelle valeur en 2024 ?"
- CH-48 : ✅ parfait — cite les 2 sources, conclut 21 J (Amdt 28 most recent)
- Démontre que **quand bien routé**, le pipeline traite bien les comparaisons.

### 6.4 Causes structurelles racines

#### Cause COMP-α : Analyzer ne détecte pas les contradictions implicites
Pour T2 q_0 ("Quelle est l'énergie..."), la question est syntaxiquement factuelle mais le corpus contient **2 valeurs divergentes** (3.5 J Amdt 26 / 21 J Amdt 28). L'Analyzer n'a pas de mécanisme pour :
1. Détecter que le retrieval contient des facts divergents sur le même sujet
2. Activer un `comparison_path` même si la question semble factuelle

#### Cause COMP-β : Composer évite de détailler les 2 côtés
Quand le pipeline détecte une tension (T2 q_1), le Composer formule "n'ont pas la même approche" mais ne déroule pas les 2 approches divergentes. Manque d'incitation à exhaustivité comparative.

#### Cause COMP-γ : Items hors-cible (couvert par D-TR.5 et D-LIST.1)
Identique au Pattern A list — confusion catégorielle.

### 6.5 Décisions COMPARISON

#### D-COMP.1 — Détection contradictions implicites pré-Composer
**Décision** : ajouter au pipeline une étape `contradiction_detector` qui inspecte les `atomic_facts` extraits par le Structurer :
- Pour chaque cluster de facts sur le même sujet (même entity), comparer les `value` / les claims
- Si 2 facts ≥ contradictoires détectés → flag `contradiction_present=true` + activer `comparison_path` même si Analyzer avait classé `factual`
- Le Composer reçoit alors les 2 facts + l'instruction "expose les deux valeurs et leur résolution (lifecycle/scope/conflict)"

**Impact estimé** : récupère ~30% des fails comparison (Pattern C-α — routing fail).
**Effort** : 2 jours (détecteur sémantique + integration + tests).
**Risque charte** : détection sémantique multi-langue (LLM léger), pas regex sur valeurs.

#### D-COMP.2 — Composer "expose both sides explicitly"
**Décision** : pour les questions `comparison` ou flagged `contradiction`, le Composer prompt explicite :
- "Présente explicitement les 2 valeurs/positions divergentes avec citations distinctes"
- "Indique la résolution attendue (lifecycle, scope, conflict) si applicable"
- Validation post-Composer : si la réponse mentionne moins de 2 sources distinctes alors que `must_surface_both_docs` ≥ 2 → retry avec prompt plus explicite

**Impact estimé** : récupère ~25% des fails comparison (Pattern C-β).
**Effort** : 1 jour (prompt + validation + tests).

#### D-COMP.3 — Lien D-CAUSAL.1 (cause-targeting)
*(D-CAUSAL.1 cible les facts pertinents à la question — applicable aussi aux comparisons pour préciser le critère exact de comparaison demandé.)*

#### D-COMP.4 — Liens transverses
- **D-TR.5** (Q↔A Alignment) : couvre Pattern C-γ items hors-cible
- **D-LIST.1** (Target Disambiguation) : applicable à comparison aussi pour préciser ce qu'on compare

### 6.6 ROI cumulé estimé Fix COMPARISON

| Fix | Pattern | Δ comparison_score | Δ T2_score | Effort |
|---|---|---:|---:|---:|
| D-COMP.1 (contradiction detector) | C-α (30%) | +0.10-0.15 | +0.10-0.15 | 2j |
| D-COMP.2 (Composer both sides) | C-β (25%) | +0.08-0.12 | +0.08-0.12 | 1j |
| **D-TR.5** (Q↔A Alignment) | C-γ (20%) | +0.05 | +0.05 | (transverse) |
| **TOTAL spécifique** | | **+0.18-0.27** | **+0.18-0.27** | **3j** |

**comparison_score cible post-fix** :
- Robust subset (8q) : 0.312 → ~0.50-0.60
- T2 contradictions : both_sides_surfaced 0.20 → 0.40, both_sources_cited 0.48 → 0.65

---

## §7 — Type MULTI_HOP (12 Robust questions, 14% du parfait — STAGNATION)

### 7.1 Observations chiffrées

| Métrique CH-48 | Score moyen | Distance à 1.0 |
|---|---:|---:|
| `structured_avg` | 0.144 | 0.856 manque |
| `judge_score` | 0.55 | 0.45 manque |
| **judge ≥ 0.5** | **8/12 (67%)** | — |

**Insight clé** : `judge` (0.55) >> `structured_avg` (0.144). Le pipeline produit des réponses **substantiellement utiles** mais **omet les identifiers exacts** attendus. Le scoring pénalise mais le contenu est correct.

**Δ vs CH-46 : -0.010** (stagnation totale).

### 7.2 Distribution des patterns (12 questions analysées)

| Pattern | Nb | % | Description |
|---|---:|---:|---|
| **M-α — Cascade tronquée** | 4 | **33%** | 1-2 étapes au lieu de 4-5 attendues |
| **OK substantiel sans identifiers** | 3 | **25%** | judge ≥ 0.6 mais structured_avg = 0 (identifier manqué) |
| **M-γ — Hors-sujet total** | 2 | 17% | Réponse à côté complète |
| **M-δ — Confusion temporal active** | 1 | 8% | Utilise document deprecated au lieu d'actif |
| **M-ε — Hallucination locale** | 1 | 8% | Invente un fait spécifique |
| **M-β — Réponse partielle** | 1 | 8% | 1/3 identifiers seulement |
| **OK complet** | 1 | 8% | Toutes les étapes + identifiers |

### 7.3 Exemples emblématiques

#### M-α — Cascade tronquée (DOMINANT 33%)
**MH_003** : "Pour un export en juin 2024 d'un item nucléaire 0B001, quel est l'enchaînement réglementaire applicable ?"
- Gold : 4 étapes (item Annex I → autorisation Article 3 → Annex I version juin 2024 = délégué 2023/996 → autorité compétente → validité tout territoire douanier)
- CH-48 : 1 sentence sur "réglementation des usines de séparation isotopes" (hors-sujet en plus)

**MH_001** : "France/Japon network access controller, base juridique + autorité ?"
- Gold : 2 éléments (Article 2021/821 + autorité française désignée)
- CH-48 : 1 paragraphe partiellement correct, manque l'autorité française

#### Pattern OK substantiel mais identifiers omis (25%)
**MH_007** : "Avocat défend exportateur 2018, contestable en 2024 ?"
- Gold attend identifiers : `2021/821`
- CH-48 : `"...l'exportation a été faite avant le 9 septembre 2021, dispositions continuent de s'appliquer"`
- judge=**0.8** (substantiellement correct) mais structured_avg=**0.0** (omet "2021/821" explicite)

C'est la révélation principale : **le contenu est juste, les identifiers manquent**. Fix simple via prompt.

### 7.4 Causes structurelles racines

#### Cause MH-α : Cascade tronquée (couvert par D-LIST.3 exhaustivité)
Le Composer s'arrête à 1-2 étapes là où la question demande 4-5. Couvert par D-LIST.3.

#### Cause MH-β : Composer omet les identifiers exacts (NOUVEAU PATTERN)
Le pipeline retrieve les facts qui contiennent les identifiers mais le Composer formule une réponse **sémantiquement correcte sans les inclure verbatim**. Ex : utilise "le règlement actuel" au lieu de "2021/821", "avant juin 2021" au lieu de "avant le 9 septembre 2021".

#### Cause MH-γ : Hors-sujet (couvert par D-TR.5)
#### Cause MH-δ : Confusion document deprecated/actif (couvert par D-TEMP.1)
#### Cause MH-ε : Hallucination locale (couvert par D-UNA.2)

### 7.5 Décisions MULTI_HOP

#### D-MH.1 — Composer "Preserve Identifiers" (NOUVEAU)
**Décision** : pour les questions multi-step où le Composer mobilise plusieurs facts/chunks, le prompt explicite doit forcer l'inclusion verbatim des identifiers principaux des facts utilisés :
- L'EvidenceCollector flag les identifiers principaux extraits (codes règlements, dates, articles, codes Annex)
- Le Composer prompt : "ta réponse doit explicitement mentionner ces identifiers : [...]"
- Validation post-Composer : si > 50% des identifiers attendus omis ET la réponse est substantiellement longue → retry une fois avec prompt "rappelle explicitement les identifiants"

**Impact estimé** : récupère ~25% des fails multi_hop (Pattern OK-substantiel-sans-identifiers).
**Effort** : 1 jour (prompt + validation + tests).
**Note charte** : extraction d'identifiers par sémantique LLM léger, pas regex domain-specific.

#### D-MH.2 à D-MH.5 — Liens transverses (pas de coût additionnel)
- D-LIST.3 (exhaustivité) → couvre M-α (33%)
- D-TR.5 (Q↔A alignment) → couvre M-γ (17%)
- D-TEMP.1 (temporal active version) → couvre M-δ (8%)
- D-UNA.2 (source attribution) → couvre M-ε (8%)

### 7.6 ROI cumulé estimé Fix MULTI_HOP

| Fix | Pattern | Δ multi_hop_score | Effort spécifique |
|---|---|---:|---:|
| **D-LIST.3** (exhaustivité) | M-α (33%) | +0.10-0.15 | (transverse) |
| **D-TR.5** (Q↔A align) | M-γ (17%) | +0.05 | (transverse) |
| **D-MH.1** (preserve identifiers) | OK-sans-id (25%) | +0.10-0.15 | 1j |
| **D-TEMP.1** (active version) | M-δ (8%) | +0.03 | (transverse) |
| **D-UNA.2** (source attribution) | M-ε (8%) | +0.02 | (transverse) |
| **TOTAL** | | **+0.30-0.40** | **1j spécifique** |

**multi_hop_score cible post-fix** : 0.144 → **~0.45-0.55**

### 7.7 Insight critique multi_hop

**Le pipeline V4.1 a un meilleur résultat sémantique qu'il n'apparaît dans les chiffres** :
- 67% des questions ont judge ≥ 0.5 (réponses utiles)
- 75% ont structured_avg = 0 (identifiers omis)

→ **Beaucoup du gain viendra de l'amélioration du scoring/Composer prompt** (D-MH.1) plutôt que du raisonnement profond. C'est encourageant : les fondations multi_hop sont meilleures que ce que les métriques laissent paraître.

→ Confirme aussi que **D-LIST.5 (scorer fuzzy)** + **D-MH.1 (preserve identifiers)** ensemble pourraient révéler ~+10pp de qualité actuelle "cachée".

---

## §7 — Type MULTI_HOP / HYPOTHETICAL (à amender)

*[En attente d'analyse]*

---

## §8 — Décisions transverses

### D-TR.1 — Gold-set v4 → v5 complet (chantier CH-50)
**Décision** : étendre le gold-set de 132 à ~240 questions (couverture totale Robust 170q + T2T5 70q). Construction par Claude (multi-passes sur le corpus) + review humain Fred sur questions critiques. Format unifié : `ground_truth.answer` (texte de référence) + `exact_identifiers` + `list_items_expected` + `supporting_doc_ids` + flags `confidence_high/medium/low`.

**Impact** : permet l'analyse de déviation au gold sur 100% des benchs (au lieu de 37% actuel). Métrique absolue "% du parfait" valide globalement.

### D-TR.2 — Métriques absolues vs idéal (au lieu de delta vs baseline)
**Décision** : reporter dans le dashboard admin/benchmarks :
- Score absolu / 1.000 (% du parfait)
- Delta vs run précédent (info complémentaire)
- Regression detection : alerte si % du parfait baisse > 3pp sur un type

**Justification** : évite le piège Goodhart (s'améliorer en relatif tout en stagnant en absolu).

### D-TR.5 — Question↔Answer Alignment Verifier (NOUVEAU — depuis §3, IMPACT MAJEUR TRANSVERSE) ⭐⭐⭐
**Décision** : insérer un nouveau stage `qa_alignment_verifier` **post-Composer**, **avant** la livraison finale de la réponse. Ce Verifier prend en entrée :
- La question initiale
- La réponse produite par le Composer
- Optionnel : les `atomic_facts` utilisés

Et détermine sémantiquement (LLM léger Mistral-7B ou similaire) :
- La question demande-t-elle **conceptuellement** ce que la réponse fournit ?
- Si oui → laisser passer
- Si non → forcer abstain "no specific answer found in corpus" + flag `qa_misalignment` pour observabilité

**Justification — Cross-cutting impact** :
| Type | Pattern couvert | % du type | Sample illustratif |
|---|---|---:|---|
| list | A (items hors cible) | 40% | SET_009 EU external refs → régimes intl |
| factual | F (extraction brute) | 20% | COND_007 amdt 25/26 au lieu raisonnement temporel |
| unanswerable | O (off-topic) | 40% | UNA_006 Russie → date adoption 2021/821 |
| (autres types) | — | TBD | À mesurer post-fix |

Estimation grossière : ce **fix unique** peut récupérer **15-25% du score global Robust** en couvrant les off-topic transverses.

**Impact estimé global** :
- list_score : 0.160 → 0.25-0.30 (+0.09-0.14)
- factual_score : 0.150 → 0.25-0.30 (+0.10-0.15)
- unanswerable_score : 0.200 → 0.50-0.60 (+0.30-0.40)
- global_score Robust : +0.04-0.07pp

**Effort** : 2 jours (Verifier + prompt + tests + intégration au pipeline V4.1).
**Risque** :
- Latence : +1-2s par question (LLM léger)
- Faux positifs : Verifier trop sévère pourrait rejeter des réponses valides → tuner sur gold-set
- Cascade : un mauvais Verifier dégrade tout le pipeline → tests robustes obligatoires avant prod

**Charte** :
- Verifier sémantique multi-langue (LLM), pas keywords
- Pas de critère corpus-spécifique : le Verifier reçoit Q + réponse, ne sait pas dans quel domaine

**Précédence dans le plan** : c'est probablement le **fix #1 à implémenter** (avant D-LIST.1, D-FACT.2) car son ROI absolu est le plus élevé et il bénéficie à 3 types simultanément.

### D-TR.4 — Multi-tag gold-set v5 (NOUVEAU — depuis §2)
**Décision** : adopter un schema multi-facette dans le gold-set v5 :
```json
{
  "primary_type": "factual",
  "secondary_types": ["conditional", "temporal"],
  "flags": ["negation", "kg_centric", "multi_step"]
}
```
- `primary_type` : type dominant (1 valeur)
- `secondary_types` : autres facettes pertinentes
- `flags` : caractéristiques transverses (négation, KG-centrique, multi-step, etc.)

**Justification** : beaucoup de questions ont des facettes multiples (NEG_007 = list + negation, COND_007 = conditional + temporal). Un single-tag force un compromis qui mène à de mauvais routages et des analyses biaisées.

**Impact** :
- Routage Analyzer plus précis (active reasoning_path si flag `negation` ET `temporal`)
- Métriques par flag (taux d'échec négation toutes catégories confondues)
- Ciblage chirurgical des fixes

**Effort** : à intégrer dans CH-50 gold-set complet (pas un coût additionnel).

### D-TR.3 — Anti-biais auto-juge (déjà actif mais à formaliser)
**Décision** :
- LLM-judge bench reste **distinct** du LLM Composer/Analyzer/Structurer (Llama-3.3-70B juge vs Llama-3.3-70B Turbo générateur — risque accepté car tâches radicalement différentes : compose vs juger)
- Garde-fous additionnels :
  - structured_metrics (non-LLM, immune au biais)
  - sanity check Fred 10q par run majeur
  - Pearson juge × structured > 0.7 sur gold-set
  - log des désaccords judge_overscored top-20 par run

**Justification** : la cohérence bench/prod (même modèle) prime sur l'élimination absolue du biais ; les garde-fous compensent.

---

## §9 — Risques et open questions

### Risques identifiés
1. **Empilement de stages LLM** : D-LIST.1 + D-LIST.2 + D-LIST.3 ajoutent ~3-5s de latence par question list (cumul retry potentiel). Surveiller que latence ne dépasse pas 30s p95 cible Test Armand.
2. **Multilingue D-LIST.2** : les mots-clés `LIFECYCLE_RELATION`, `SUPERSEDES` sont génériques en EN, mais la détection multi-langue (FR `cycle de vie`, DE `Lebenszyklus`) doit être sémantique, pas lexicale, pour respecter la charte.
3. **Risque scorer fuzzy D-LIST.5** : un fuzzy trop permissif peut masquer des fails réels. Validation sur gold v4 obligatoire avant déploiement.

### Open questions
1. Le Pattern A (40%) est-il vraiment résolvable par "Target Disambiguation" ou faut-il aussi améliorer le retrieval (mauvais chunks récupérés) ?
2. D-LIST.3 retry vs `max_tokens` simple : quel est le meilleur trade-off ? À benchmarker.
3. Pour les questions KG-centriques, faut-il un fallback chunks si Cypher renvoie 0 résultats ?
4. Faut-il étendre `ListStructurer` à un `MultiTargetStructurer` qui accepterait plusieurs cibles ontologiques pour les questions multi-aspects ?

### À challenger via LLM tiers
- **ChatGPT-5 / o1** : challenge sur D-LIST.1 (target disambiguation) — meilleur pattern industriel ?
- **Gemini 2.5** : challenge sur D-LIST.2 (KG vs chunks routing)
- **Claude Web (Opus 4.7)** : challenge sur l'architecture globale + risques empilement stages

---

## §A — Synthèse globale post-gold-v5 (2026-05-09)

### A.1 Couverture totale après gold v5

| Bench | Total | Gold v4 | Gold v5 | Couverture |
|---|---:|---:|---:|---:|
| Robust | 170 | 63 | 170 | **100%** ✅ |
| T2T5 | 70 | 0 | 70 | **100%** ✅ |
| RAGAS | 132 | 132 | 132 | 100% (déjà OK) |
| **Total bench** | **372** | **195** | **372** | **100%** |

Gold v5 = 290 entrées (mappage T1+T2+T5+T6+T7), distribués sur 7 primary_types avec multi-tag.

### A.2 Tableau de bord par primary_type (déviation au gold v5, 170q Robust complet)

| primary_type | n | CH-46 | CH-48 | Δ | % parfait | Cible post-fix |
|---|---:|---:|---:|---:|---:|---:|
| **causal** | 22 | 0.045 | 0.386 | +0.341 ⭐ | 39% | ~55% |
| comparison | 8 | 0.083 | 0.312 | +0.229 | 31% | ~55% |
| factual | 45 | 0.115 | 0.237 | +0.122 | 24% | ~50% |
| temporal | 45 | 0.170 | 0.182 | +0.012 | 18% | ~50% |
| **multi_hop** | 12 | 0.154 | 0.144 | -0.010 ⚠️ | 14% | ~50% |
| list | 26 | 0.048 | 0.108 | +0.060 | 11% | ~45% |
| unanswerable | 12 | 0.000 | 0.000 | = (bug scorer) | 0%* | ~70% (post fix) |

\* unanswerable=0 en structured_avg suspect — bug du scorer post-hoc qui ne détecte pas correctement les abstain en français. À corriger avec D-UNA.4.

### A.3 Insights majeurs validés sur 170 questions

1. **CH-47 reasoning_mode est un succès massif** :
   - hypothetical (flag) : **0 → 0.325** (+0.325pp)
   - conditional (flag) : **0.048 → 0.429** (+0.381pp)
   - causal (primary) : **0.045 → 0.386** (+0.341pp)
   → Le pivot V4.1 a clairement fonctionné sur les types reasoning.

2. **Régressions confirmées** :
   - **negation flag** : **0.075 → 0.000** (-0.075pp) — Pattern G dominant, **D-FACT.2 negation_path PRIORITAIRE ABSOLU**
   - **temporal flag** : -0.091pp (questions ayant temporal en secondary)
   - **scope_hierarchy** : -0.074pp

3. **Stagnations et plafonds structurels** :
   - **list** : 11% du parfait (pas amélioré significativement par V4.1)
   - **multi_hop** : stagnation (-0.010), mais judge=0.55 vs structured=0.144 → fix prompt simple (D-MH.1)

4. **Plafond pipeline** : tous les types sont sous 40% du parfait. Ni CH-46 ni CH-48 ne dépassent 39% sur quelque type que ce soit. **Le pipeline V4.1 a un plafond structurel** que les fixes proposés visent à lever.

### A.4 Décisions consolidées (32 au total)

**Décisions transverses (5)** ⭐⭐⭐ :
- **D-TR.5** Q↔A Alignment Verifier (couvre 3 types : list 40% / factual 20% / unanswerable 40% + multi_hop)
- D-TR.4 Multi-tag gold-set v5 ✅ DÉJÀ FAIT
- D-TR.1 Gold-set complet 240q+ ✅ FAIT (gold v5 290q)
- D-TR.2 Métriques absolues vs idéal
- D-TR.3 Anti-biais auto-juge formalisé

**Décisions par type** :
- **D-LIST.1-6** (6) : target disambiguation, kg_query_path, exhaustivité, attributes, scorer fuzzy, abstain/off-target metrics
- **D-FACT.1-4** (4) : conditionnelles detection, **negation_path** ⭐⭐, routage temporel, hallucination guard
- **D-UNA.2-4** (3) : source attribution, scope check, abstain reward (D-UNA.1 promu D-TR.5)
- **D-TEMP.1-5** (5) : **temporal_active_version** ⭐⭐, kg_query (lien LIST), inférence inverse, anti-dégénération, multi-tag (lien TR.4)
- **D-CAUSAL.1-4** (4) : cause-targeting, anti-circularité, multi-step hypothetical, audit Structurer
- **D-COMP.1-4** (4) : contradiction detector, both-sides Composer, lien CAUSAL.1, lien TR.5/LIST.1
- **D-MH.1** (1) : preserve identifiers ⭐ (révèle qualité cachée)

**Total** : **32 décisions** dans l'ADR.

### A.5 ROI cumulé estimé (toutes décisions)

| Métrique | CH-48 actuel | Cible post-fix complet | Δ absolu |
|---|---:|---:|---:|
| Robust global_score | 0.403 | **~0.55-0.60** | +0.15-0.20pp |
| List score | 0.108 | ~0.45 | +0.34pp |
| Factual score | 0.237 | ~0.50 | +0.26pp |
| Multi_hop score | 0.144 | ~0.50 | +0.36pp |
| Unanswerable score | 0.200 (réel) | ~0.70 | +0.50pp |
| Temporal score | 0.426 | ~0.65 | +0.22pp |
| Causal score | 0.751 | ~0.90 | +0.15pp |
| Comparison score | 0.312 | ~0.60 | +0.29pp |

**Effort total estimé** : **~25-30 jours** dev étalés sur 5-6 semaines (parallélisable partiellement).

### A.6 Priorité d'exécution révisée (basée sur impact / effort)

**Priorité 1 — ROI maximal transverse (4-5 jours)** :
1. **D-TR.5** Q↔A Alignment Verifier (2j, transverse 3 types) → +0.04-0.07pp global
2. **D-LIST.5** Scorer fuzzy + **D-LIST.6** observabilité (1.5j) → révèle qualité cachée
3. **D-MH.1** Preserve Identifiers (1j) → +0.10-0.15pp multi_hop

**Priorité 2 — ROI majeur par type (8-10 jours)** :
1. **D-FACT.2** negation_path (2-3j) → +0.15-0.25pp factual + corrige régression
2. **D-LIST.1** Target Disambiguation (2-3j) → +0.10-0.15pp list
3. **D-TEMP.1** temporal_active_version (3j) → +0.10-0.15pp temporal

**Priorité 3 — Compléments par type (8-10 jours)** :
1. D-LIST.2 / D-TEMP.2 KG query path (2-3j)
2. D-LIST.3 Composer exhaustivité (1j)
3. D-COMP.1 contradiction detector (2j)
4. D-COMP.2 both sides Composer (1j)
5. D-CAUSAL.1 cause-targeting (1.5j)

**Priorité 4 — Polish et observabilité (3-4 jours)** :
1. D-CAUSAL.2-4, D-UNA.2-4, D-TEMP.3-4

### A.7 Gates de validation par phase

- **Après Priorité 1** : re-bench Robust → attendu global_score ≥ 0.45
- **Après Priorité 2** : re-bench Robust + T2T5 → attendu global_score ≥ 0.50
- **Après Priorité 3** : re-bench complet → attendu global_score ≥ 0.55
- **Après Priorité 4** : finalisation → attendu global_score ≥ 0.58

À chaque gate :
- Verification structured_avg par type ≥ cible
- Pas de régression sur judge_score / latency
- Sanity check Fred 10q
- Update ADR avec mesures réelles vs estimées

---

## §10 — Plan d'exécution proposé (post-validation)

### Phase 1 — Quick wins (semaine 1)
- D-LIST.5 (scorer fuzzy) : 0.5j → révèle le vrai score actuel
- D-LIST.6 (observabilité abstain/off-target) : 1j → permet de re-prioriser
- D-LIST.4 (List+Attributes) : 0.5j

### Phase 2 — Major fixes list (semaines 2-3)
- D-LIST.1 (Target disambiguation) : 3j
- D-LIST.3 (Composer exhaustivité) : 1j
- D-LIST.2 (KG path) : 3j

### Phase 3 — Autres types (semaines 4+)
*Selon §2-§7 à amender*

### Gates
- Bench Robust+T2T5+RAGAS après chaque phase (+ smoke pour rapidité)
- Acceptation Fred avant promotion en prod

---

## Annexes

### A. Données brutes
- Bench CH-48 Robust : `/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json`
- Bench CH-48 T2T5 : `/data/benchmark/results/t2t5_run_20260509_162259_V4_CH48_LLAMA_TURBO_TOGETHER.json`
- Bench CH-48 RAGAS : (en cours)
- Gold-set v4 : `/app/benchmark/questions/gold_set_v4.json` (132 questions)
- Scripts d'analyse : `/app/scripts/ch48_*.py`

### B. Références internes
- ADR V4 architecture : `2026-05-05_CH-40_ADR_V4_ARCHITECTURE.md` (§10 = CH-47)
- Setup CH-48 Together AI : `2026-05-08_CH-48_TOGETHER_AI_SETUP.md`
- Mémoire `feedback_domain_agnostic_strict`, `feedback_no_corpus_specific_examples_in_prompts`, `feedback_no_benchmark_overfit_focus_production`

### C. Méthodologie d'analyse
- Approche reference-based (vs delta-based) → cf §0.2
- Subset Robust × gold_v4 = 63 questions communes
- Métriques `structured_metrics` déjà présentes : item_recall, exact_match, citation, coverage, structured_avg
- Lecture manuelle 100% des samples list (20/20)

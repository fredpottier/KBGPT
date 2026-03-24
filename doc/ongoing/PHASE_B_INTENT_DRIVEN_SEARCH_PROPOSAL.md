# Phase B — Intent-Driven KG Search Engine

**Date** : 24 mars 2026
**Auteurs** : Claude Opus + Codex (via Octopus)
**Statut** : Proposition a challenger par ChatGPT (mode deep search)

---

## 1. Contexte et probleme

### 1.1 Qu'est-ce qu'OSMOSIS

OSMOSIS est un systeme de Q&A documentaire qui ingere des corpus de documents (PDF, PPTX, MD), extrait des faits atomiques (claims) via un pipeline LLM, les structure dans un Knowledge Graph (Neo4j), et permet une recherche semantique enrichie. Il utilise aussi Qdrant comme base vectorielle pour stocker les passages documentaires bruts (chunks).

OSMOSIS est **agnostique du domaine** — il fonctionne sur tout corpus (SAP, biomedical, reglementaire, juridique).

### 1.2 Le benchmark

Un benchmark comparatif OSMOSIS vs RAG baseline a ete realise (275 questions, valide par 2 juges independants Qwen+Claude avec convergence 0.3%) :

| Metrique | OSMOSIS | RAG | Verdict |
|----------|---------|-----|---------|
| T1 Exactitude factuelle (questions humaines) | 35% | 41% | **RAG meilleur** |
| T1 Exactitude factuelle (questions cross-doc KG) | 42% | 27% | OSMOSIS meilleur |
| T2 Detection contradictions (KG) | 100% | 0% | **OSMOSIS game changer** |
| T2 Detection contradictions (humaines) | 25% | 0% | OSMOSIS meilleur |
| T4 Completude (KG) | 68% | 49% | OSMOSIS meilleur |
| T4 Tracabilite (KG) | 100% | 89% | OSMOSIS meilleur |

### 1.3 Resultats detailles — Metrique par metrique

Le benchmark evalue 3 taches (T1 Provenance, T2 Contradictions, T4 Audit) avec 2 types de questions chacune (KG cross-doc et humaines). Chaque metrique mesure un aspect specifique de la qualite de la reponse. Les scores sont valides par 2 juges independants (Qwen 14B et Claude Sonnet) avec un ecart moyen de 0.3%.

#### T1 — Provenance et Citations (30 questions KG cross-doc + 100 questions humaines)

Cette tache teste la capacite du systeme a retrouver un fait precis dans le corpus et a citer correctement ses sources. Les questions KG sont des questions qui necessitent de croiser plusieurs documents (ex: "Quelles differences de prerequis entre la conversion 2022 et PCE 2025 ?"). Les questions humaines sont des questions factuelles simples redigees en lisant les documents (ex: "Quel client SAP doit etre supprime avant la conversion ?").

| Metrique | Ce qu'elle mesure | OSM KG | RAG KG | OSM Hum | RAG Hum | Analyse |
|----------|-------------------|--------|--------|---------|---------|---------|
| factual_correctness_avg | La reponse contient-elle le fait attendu (meme reformule) ? Score 0-100. | **42.1%** | 27.3% | 35.3% | **40.8%** | OSM meilleur sur cross-doc (+15pp), RAG meilleur sur questions simples (+5pp). **C'est le coeur du probleme : sur les questions simples, le KG ne compense pas.** |
| answers_correctly_rate | La reponse est-elle factuellement correcte ET pertinente ? Metrique binaire la plus exigeante. | **27.6%** | 16.7% | 20.0% | **22.4%** | Meme pattern : OSM meilleur cross-doc, RAG meilleur simple. 20% signifie que 4 reponses sur 5 sont jugees incorrectes ou non pertinentes. |
| answer_relevant_rate | La reponse repond-elle effectivement a la question posee (meme si incorrecte) ? | **58.6%** | 46.7% | 44.2% | **52.0%** | OSM plus pertinent sur cross-doc mais MOINS pertinent sur questions humaines simples. Le KG detourne la reponse du sujet sur les questions simples. |
| citation_present_rate | La reponse cite-t-elle ses sources avec [Source N] ? | 100% | 100% | 100% | 100% | Parfait des deux cotes grace au prompt renforce. Non discriminant. |
| correct_source_rate | Le BON document est-il cite ? Verifie la provenance exacte. | **44.8%** | 23.3% | 30.5% | **35.7%** | OSM meilleur cross-doc (+21pp). Sur questions simples, RAG meilleur (+5pp). Le KG aide a identifier les bons documents quand la question le demande explicitement. |
| false_idk_rate (inverse) | Le systeme refuse-t-il de repondre alors que l'info existe ? Plus bas = mieux. | **13.8%** | 33.3% | 34.7% | **36.7%** | OSM refuse beaucoup moins sur cross-doc (14% vs 33%). Sur questions humaines, les deux refusent ~35% du temps — 1 question sur 3 sans reponse alors que l'info est dans le corpus. **C'est un probleme majeur pour les deux systemes.** |

**Verdict T1** : OSMOSIS est meilleur quand la question exige du cross-doc (+15pp factual). Mais sur les questions simples (60%+ des cas reels), le RAG fait mieux. Le taux de refus injustifie (~35%) est inacceptable pour les deux systemes.

#### T2 — Detection des Contradictions (25 questions KG + 50 questions humaines)

Cette tache teste la capacite du systeme a detecter et exposer les divergences, evolutions ou contradictions entre documents. Les questions KG sont basees sur des tensions REFINES/QUALIFIES verifiees dans le KG (ex: "L'authentification X.509 est-elle decrite de la meme maniere dans les Security Guides 2022 et 2023 ?"). Les questions humaines portent sur des comparaisons entre versions que j'ai identifiees en lisant les documents.

| Metrique | Ce qu'elle mesure | OSM KG | RAG KG | OSM Hum | RAG Hum | Analyse |
|----------|-------------------|--------|--------|---------|---------|---------|
| both_sides_surfaced_rate | Les deux positions d'une divergence sont-elles exposees ? | **100%** | 0% | **100%** | 100% | **Game changer sur KG** : OSM expose systematiquement les deux cotes, RAG ne le fait jamais. Sur humaines, les deux y arrivent (le LLM voit les deux docs dans les chunks). |
| tension_mentioned_rate | La divergence/contradiction est-elle explicitement signalee ? | **100%** | 0% | **25%** | 0% | OSM mentionne les tensions sur KG a 100%. Sur humaines, seulement 25% — le KG aide mais pas assez. RAG ne mentionne jamais les tensions. |
| correct_tension_type_rate | Le type de tension (evolution, nuance, contradiction) est-il correctement identifie ? | **50%** | 0% | **25%** | 0% | OSM identifie le type dans 50% des cas KG. RAG ne le fait jamais. |
| both_sourced_rate | Les deux positions sont-elles accompagnees de leurs sources ? | **75%** | 0% | 0% | 0% | OSM source les deux cotes dans 75% des cas KG. Sur humaines, aucun des deux ne le fait. |
| silent_arbitration_rate (inverse) | Le systeme choisit-il un cote sans le signaler ? Plus bas = mieux. | **0%** | 0% | **0%** | 0% | Les deux systemes n'arbitrent pas silencieusement — bon signe. |

**Verdict T2** : C'est le **differentiel le plus fort** d'OSMOSIS. Sur les questions KG (basees sur des tensions verifiees), OSM atteint 100% sur l'exposition des deux positions alors que RAG est a 0%. C'est la preuve que le KG apporte une valeur unique. Mais cette valeur se dilue sur les questions humaines (25% vs 0% — mieux mais pas assez).

#### T4 — Audit et Completude (20 questions KG + 50 questions humaines)

Cette tache teste la capacite du systeme a produire un resume complet et source d'un sujet a travers plusieurs documents. Les questions KG demandent de couvrir un sujet a travers tous les documents (ex: "Resume toute la documentation sur SAP HANA dans les documents de securite, operations et conversion"). Les questions humaines sont similaires mais formulees naturellement.

| Metrique | Ce qu'elle mesure | OSM KG | RAG KG | OSM Hum | RAG Hum | Analyse |
|----------|-------------------|--------|--------|---------|---------|---------|
| topic_coverage_rate | La reponse couvre-t-elle le sujet principal demande ? | **88.9%** | 57.9% | **82.0%** | 77.6% | OSM couvre mieux le sujet, surtout sur KG (+31pp). Sur humaines l'ecart est modeste (+4pp). |
| completeness_avg | Score global de completude (0-100). La reponse couvre-t-elle les differents aspects du sujet ? | **67.8%** | 48.9% | **66.5%** | 61.6% | OSM plus complet sur KG (+19pp). Sur humaines, ecart modeste (+5pp). |
| comprehensiveness_rate | La reponse est-elle jugee exhaustive par le juge ? Metrique binaire exigeante. | **44.4%** | 15.8% | **50.0%** | 40.8% | OSM plus exhaustif, surtout sur KG (+29pp). Mais meme OSM ne depasse pas 50% — la moitie des reponses sont jugees incompletes. |
| traceability_rate | Chaque affirmation est-elle tracable a un document source ? | **100%** | 89.5% | 94.0% | **95.9%** | OSM parfait sur KG. Sur humaines, quasi-identique. La tracabilite est bonne pour les deux. |
| sources_mentioned_rate | Les documents sources sont-ils mentionnes dans la reponse ? | 100% | 100% | 98.0% | 98.0% | Identique. Non discriminant. |
| contradictions_flagged_rate | Les contradictions existantes sont-elles signalees ? | **16.7%** | 0% | **18.0%** | 12.2% | OSM signale des contradictions que RAG ignore totalement sur KG. Sur humaines, modeste avantage. |

**Verdict T4** : OSMOSIS est meilleur sur toutes les metriques, avec un avantage fort sur KG (completude +19pp, coverage +31pp, exhaustivite +29pp). Sur les questions humaines, l'avantage existe mais est modeste (+5pp completude). La tracabilite est bonne pour les deux (~95%). L'exhaustivite reste un defi (50% max).

### 1.4 Synthese globale des forces et faiblesses

**Forces OSMOSIS (la ou le KG apporte une valeur UNIQUE)** :
- Detection des contradictions cross-doc : 100% vs 0% (T2 KG)
- Mention des tensions : 100% vs 0% (T2 KG)
- Couverture documentaire cross-doc : 89% vs 58% (T4 KG)
- Completude cross-doc : 68% vs 49% (T4 KG)
- Refus injustifie cross-doc : 14% vs 33% (T1 KG)

**Faiblesses OSMOSIS (la ou le KG degrade ou n'apporte rien)** :
- Exactitude factuelle questions simples : 35% vs 41% (T1 humain) — **le KG degrade**
- Pertinence questions simples : 44% vs 52% (T1 humain) — **le KG detourne**
- Refus injustifie questions simples : 35% vs 37% (T1 humain) — **pas d'amelioration**
- Exhaustivite questions simples : 50% vs 41% (T4 humain) — avantage modeste
- Tracabilite : 94% vs 96% (T4 humain) — identique

**Le pattern est clair** : OSMOSIS excelle quand la question EXIGE du cross-doc (comparaison, tensions, couverture multi-documents). Il est mediocre a mauvais quand la question est simple et factuelle. Le KG n'ameliore pas — et parfois degrade — les reponses aux questions simples qui representent la majorite des interactions reelles.

**L'objectif de la Phase B** : faire d'OSMOSIS un game changer sur TOUTES les metriques, pas seulement sur le cross-doc. Pour les questions simples, OSMOSIS doit etre au minimum aussi bon que le RAG (+0pp) et idealement meilleur (+5-10pp). Pour le cross-doc, l'avantage doit passer de "significatif" a "ecrasant".

### 1.5 Le probleme fondamental

Le KG est un **game changer pour les tensions cross-doc et la completude**, mais il **DEGRADE l'exactitude factuelle** sur les questions simples. Le RAG pur (simple vector search Qdrant) fait mieux qu'OSMOSIS sur 35% → 41% de factual correctness.

**Cause racine identifiee** : le KG essaie de REMPLACER ou MODIFIER les chunks Qdrant au lieu de DECIDER COMMENT chercher et ENRICHIR la synthese.

### 1.4 L'autocritique de la proposition initiale

La premiere proposition (Intent Resolver + 4 strategies) a ete challengee en interne. Le verdict : **elle est trop defensive**. Elle protege contre la degradation (invariant A : memes chunks que le RAG) mais ne cree pas de valeur differenciante sur 60% des questions (type A simple factuel).

**Le vrai enjeu** : le KG doit enrichir la SYNTHESE, pas le retrieval. Les chunks Qdrant restent la source de verite pour les passages, mais le KG doit apporter au LLM de synthese des informations que Qdrant ne peut PAS fournir :
- Les **relations entre documents** (REFINES, QUALIFIES, CONTRADICTS)
- Les **entites canoniques** et leurs variantes (SAME_CANON_AS)
- Les **claims structures** (SPO triples via structured_form_json)
- Les **valeurs comparables** (QuestionSignatures avec extracted_value)
- Les **clusters de claims similaires** (ClaimCluster cross-doc)
- Les **tensions explicites** entre versions/documents

---

## 2. Ontologie Neo4j actuelle — Description complete

### 2.1 Types de noeuds

#### Claim (15 861 noeuds)
**Role** : Unite atomique de connaissance — un fait extrait d'un document par le pipeline LLM.
**Proprietes cles** :
- `claim_id` : identifiant unique
- `text` : texte du claim (fait atomique, 1-2 phrases)
- `verbatim_quote` : citation exacte du document source
- `doc_id` : document source
- `page_no` : page dans le document
- `claim_type` : FACTUAL (95%), PRESCRIPTIVE (3.6%), DEFINITIONAL (1.4%)
- `structured_form_json` : triple SPO (sujet, predicat, objet). Ex: `{"subject": "SAP S/4HANA", "predicate": "BASED_ON", "object": "ABAP Platform"}`
- `chunk_ids` : **liste des IDs de chunks Qdrant** associes (pont KG → Qdrant). 100% rempli.
- `embedding` : vecteur 1024d (multilingual-e5-large). **50% rempli** (7936/15861).
- `confidence` : score de confiance de l'extraction
- `quality_status` : PASS (80.5%), BUCKET_LOW_INDEPENDENCE (11.7%), RESOLVE_INDEPENDENCE (7.4%)
- `fingerprint`, `content_fingerprint` : deduplication

**Couverture embedding** : seulement 50% des claims ont un vecteur. Les 7925 autres sont invisibles pour le vector search Neo4j. C'est un bottleneck critique.

#### Entity (7 059 noeuds)
**Role** : Entite nommee mentionnee dans les claims — concept, produit, feature, service, acteur.
**Proprietes** : `name`, `normalized_name`, `entity_type` (concept/product/feature/service/actor), `mention_count`, `aliases[]`
**Types** : concept (5435), product (760), feature (688), service (93), actor (47)

#### CanonicalEntity (267 noeuds)
**Role** : Pivot de deduplication — regroupe les variantes d'une meme entite.
**Proprietes** : `canonical_name`, `entity_type`, `source_entity_ids[]`, `doc_count`, `total_mention_count`
**Usage** : resolution de synonymes (ex: "SAP EWM" et "SAP Extended Warehouse Management" → meme CanonicalEntity)

#### ClaimCluster (2 381 noeuds)
**Role** : Groupement de claims semantiquement similaires — deduplication et regroupement cross-doc.
**Proprietes** : `cluster_id`, `canonical_label`, `claim_ids[]`, `doc_ids[]`, `claim_count`, `doc_count`, `cross_doc` (bool), `avg_confidence`
**Usage potentiel** : identifier les claims redondants entre documents, trouver le "consensus" sur un sujet.

#### QuestionDimension (382 noeuds)
**Role** : Question factuelle canonique — pivot de comparaison cross-doc.
**Proprietes** : `dimension_id`, `dimension_key`, `canonical_question` (en anglais), `value_type`, `allowed_operators`, `value_comparable`, `status` (tous "candidate"), `info_count`, `doc_count`, `embedding` (1024d, 100% rempli)
**Index** : `qd_embedding` (VECTOR, ONLINE)
**Couverture** : 4.8% des claims (755/15861 via QuestionSignatures)
**Exemple** : dimension_key="minimum_required_version", canonical_question="What is the minimum version of SAP NetWeaver required for ADS?"

#### QuestionSignature (755 noeuds)
**Role** : Reponse extraite a une QuestionDimension — valeur factuelle avec provenance.
**Proprietes** : `qs_id`, `claim_id` (lien vers le Claim source), `doc_id`, `question`, `dimension_key`, `dimension_id`, `extracted_value`, `value_normalized`, `operator`, `value_type`, `confidence`, `extraction_method` (pattern_level_a | llm_level_b), `scope_basis`, `scope_status`
**Usage** : reponse structuree "La version minimum est 7.50 selon le document X"

#### Facet (9 noeuds)
**Role** : Domaine thematique transversal (securite, compliance, data_management, etc.)
**Proprietes** : `facet_id`, `facet_name`, `domain`, `keywords[]`, `facet_kind`
**Couverture** : 2659 claims taguees (16.8% du corpus)

#### WikiArticle (69 noeuds)
**Role** : Articles de synthese generes automatiquement sur les concepts/produits importants.
**Proprietes** : `title`, `slug`, `markdown`, `importance_tier`, `importance_score`, `status` ("published"), `source_count`, `total_citations`
**Lien** : WikiArticle -[:ABOUT]-> Entity

#### DocumentContext (22 noeuds)
**Role** : Contexte d'applicabilite d'un document — sujet principal, qualificateurs, frame d'applicabilite.
**Proprietes** : `doc_id`, `primary_subject`, `document_type`, `applicability_frame_json`, `qualifiers_json`

#### ApplicabilityAxis (2 noeuds)
**Role** : Axes de contextualisation (ex: version, region) pour les claims.

#### ComparableSubject (4 noeuds)
**Role** : Sujets comparables identifies pour le challenge cross-doc.

### 2.2 Relations

| Relation | Count | Direction | Signification |
|----------|-------|-----------|---------------|
| ABOUT | 25 634 | Claim → Entity | "Ce claim parle de cette entite" — ancrage semantique principal |
| IN_CLUSTER | 7 728 | Claim → ClaimCluster | "Ce claim appartient a ce groupe semantique" |
| SIMILAR_TO | 4 208 | Claim ↔ Claim | "Ces deux claims sont semantiquement proches" |
| BELONGS_TO_FACET | 2 659 | Claim → Facet | "Ce claim releve de ce domaine thematique" |
| CHAINS_TO | 1 547 | Claim → Claim | "Ce claim est narrativement lie a cet autre (meme sujet, cross-doc)" |
| ANSWERS | 770 | QuestionSignature → QuestionDimension | "Cette QS repond a cette question canonique" |
| HAS_QUESTION_SIG | 755 | Claim → QuestionSignature | "Ce claim a une QS extraite" |
| SAME_CANON_AS | 379 | Entity → CanonicalEntity | "Cette entite est une variante de cette entite canonique" |
| REFINES | 280 | Claim → Claim | "Ce claim PRECISE/AFFINE un autre claim (souvent cross-doc)" |
| QUALIFIES | 249 | Claim → Claim | "Ce claim NUANCE/QUALIFIE un autre claim (souvent cross-doc)" |
| IN_CATEGORY | 69 | WikiArticle → WikiCategory | Categorisation wiki |
| ABOUT_SUBJECT | 52 | Claim → Subject | Ancrage thematique secondaire |
| HAS_AXIS_VALUE | 12 | Claim → ApplicabilityAxis | Valeur d'axe (version, region) |
| CONTRADICTS | 2 | Claim ↔ Claim | Contradiction directe (tres rare, 2 seulement) |

### 2.3 Index vectoriels

- `claim_embedding` : VECTOR sur Claim.embedding (1024d, cosine). 7936 claims indexes sur 15861.
- `qd_embedding` : VECTOR sur QuestionDimension.embedding (1024d, cosine). 382 QD, 100% indexes.
- `claim_text_search` : FULLTEXT sur Claim.text

### 2.4 Lien avec Qdrant

Collection `knowbase_chunks_v2` : ~15 000 chunks avec embeddings 1024d (multilingual-e5-large).
- Chaque chunk a un payload `chunk_id` au format `default:DOC_ID:#/texts/N`
- Chaque Claim Neo4j a un champ `chunk_ids[]` qui contient les IDs des chunks Qdrant associes
- Le mapping est 100% — tous les claims ont des chunk_ids
- Un chunk peut contenir plusieurs claims, un claim pointe vers un chunk

### 2.5 Systeme ClaimKey / QuestionDimension (deux systemes paralleles)

Il existe **deux systemes non connectes** dans le code :

**Systeme A (stratified/ClaimKey)** — MVP V1, Usage B (Challenge de texte)
- 0 noeuds dans Neo4j (jamais peuple)
- 14 patterns regex (SLA, TLS, backup, RTO...)
- `ClaimKey` + `InformationMVP` — modeles dataclass non utilises en production
- Le `TextChallenger` cherche des noeuds qui n'existent pas

**Systeme B (claimfirst/QuestionDimension)** — Architecture actuelle
- 382 QD + 755 QS dans Neo4j
- 50+ patterns Level A + LLM Level B
- Operationnel mais ne couvre que 4.8% des claims
- Le gating est volontairement restrictif : ne retient que les faits comparables (valeurs numeriques, versions, seuils)

---

## 3. Architecture proposee — Intent-Driven KG Search

### 3.1 Principe

```
Question → IntentResolver (< 50ms, sans LLM)
         → SearchRouter (dispatch par type)
         → Qdrant search (TOUJOURS le socle — jamais degrade)
         → KG Enrichissement de la SYNTHESE (pas du retrieval)
         → LLM synthese avec contexte KG augmente
```

### 3.2 IntentResolver — 4 types de questions

| Type | Detection (regex/scoring) | Frequence | KG Role |
|------|--------------------------|-----------|---------|
| A. Simple factuel | WH-question sans comparatif | ~60% | Enrichit la synthese |
| B. Cross-doc comparison | Verbe de comparaison + ref documentaire | ~15% | Scope les documents |
| C. Audit/completude | Quantificateur universel (all, every, complete) | ~15% | Detecte les gaps |
| D. Factuel comparable | Comparatif + metrique (minimum version, threshold) | ~10% | QD match structuree |
| X. Ambigu | Score < seuil | Variable | Traite comme A |

### 3.3 Invariant critique

**Pour le type A** : `chunks(OSMOSIS) == chunks(RAG)`. Le KG ne modifie PAS les chunks. Il enrichit le PROMPT de synthese.

### 3.4 Strategies par type

#### Type A — Simple factuel (60%)
```
Qdrant search → chunks identiques au RAG
KG : lookup des claims lies aux chunk_ids retournes
   → extraire entity_names, tensions, structured_form (SPO)
   → PAS injecte dans les chunks mais dans le CONTEXTE LLM additionnel
Synthese LLM : chunks RAG + bloc "Contexte KG" separe
```

**La difference avec le RAG** : le LLM recoit un bloc additionnel :
```
[Contexte KG]
Entites identifiees : SAP Fiori (18 docs), ABAP Platform (10 docs), RFC (11 docs)
Relations structurees :
- SAP S/4HANA BASED_ON ABAP Platform [Source: Security Guide 2023]
- SAP Fiori REQUIRES SAP Gateway [Source: Installation Guide]
Tensions detectees : aucune
```

Ce contexte aide le LLM a produire une reponse plus precise et mieux sourcee SANS modifier les chunks.

#### Type B — Cross-doc comparison (15%)
```
KG : identifier les documents en tension via Entity → Claims → REFINES/QUALIFIES
Qdrant search FILTRE par chaque document en tension (top_k/2 par doc)
KG : charger les tensions explicites entre ces documents
Synthese LLM : chunks multi-doc + bloc "Tensions cross-doc" explicite
```

#### Type C — Audit/completude (15%)
```
Qdrant search global (identique RAG)
KG : identifier TOUS les documents pertinents (Entity → Claims → doc_ids)
Si documents manquants : Qdrant search supplementaire
KG : charger les ClaimClusters pour identifier le "consensus" cross-doc
Synthese LLM : chunks + bloc "Couverture documentaire" + tensions
```

#### Type D — Factuel comparable (10%)
```
Qdrant search global (identique RAG — base de securite)
KG : QuestionDimension vector search (qd_embedding)
Si QD match : charger les QuestionSignatures → valeurs cross-doc
Synthese LLM : chunks RAG + bloc "Valeurs comparees" structure
```

---

## 4. La vraie valeur ajoutee — KG-Augmented Synthesis

### 4.1 Le probleme actuel

Aujourd'hui, le KG enrichit les CHUNKS (ajoute entity_names, contradiction_texts aux chunks retournes). Mais le LLM de synthese ne voit que `[Entites: SAP Fiori]` dans le contexte — ce qui ne change quasiment rien a la reponse.

### 4.2 Ce que le KG devrait injecter dans le prompt de synthese

Pour CHAQUE type de question, le KG devrait construire un **bloc de contexte structure** distinct des chunks, injecte dans le prompt LLM :

```
=== CONTEXTE KNOWLEDGE GRAPH ===

Entites pertinentes identifiees dans le corpus :
- "SAP Fiori" mentionne dans 18 documents (securite, installation, operations, scope)
- "ABAP Platform" mentionne dans 10 documents

Relations structurees (extraites du KG, pas des chunks) :
- SAP S/4HANA est base sur ABAP Platform et SAP HANA [Claim claim_xyz, doc 028]
- SAP Fiori requiert SAP Gateway pour fonctionner [Claim claim_abc, doc 011]

Tensions entre documents :
- REFINE : "User authentication using X.509 certificates" (Security Guide 2023)
  raffine "User authentication using SSL" (Security Guide 2022)
- QUALIFIE : "Standard SOP for production resources" (Feature Scope on-prem)
  qualifie "Standard SOP for costs" (Feature Scope PCE)

Valeurs comparables (si pertinent) :
- Version minimum ADS : 7.50 (Operations Guide 2021), 7.3 EHP1 SP7 (Conversion Guide 2023)

Couverture documentaire :
- Ce sujet est couvert par 5 documents : [liste]
- 2 documents ont des positions divergentes
===
```

Ce bloc est **separe des chunks**. Les chunks restent les memes que le RAG. Le KG ajoute un "cerveau" au-dessus qui aide le LLM a produire une meilleure reponse.

### 4.3 Pourquoi cela change tout

1. **Pour les questions simples (60%)** : le LLM a les memes chunks que le RAG PLUS le contexte KG. Il ne peut que faire mieux ou aussi bien.
2. **Pour les contradictions** : les tensions sont explicitement nommees dans le contexte. Le LLM ne peut pas les ignorer.
3. **Pour la completude** : la couverture documentaire est explicite. Le LLM sait s'il manque des perspectives.
4. **Pour les valeurs** : les valeurs extraites sont comparees. Le LLM peut les citer directement.

---

## 5. Questions pour ChatGPT (mode deep search)

### Questions architecturales

1. **L'ontologie actuelle est-elle suffisante** pour construire le contexte KG decrit en 4.2, ou faut-il ajouter/modifier des types de noeuds ? Par exemple :
   - Faut-il un noeud `DocumentRelation` qui encode explicitement les relations entre documents (pas entre claims) ?
   - Faut-il un noeud `TopicCluster` qui regroupe les claims par sujet transversal (au-dela des ClaimClusters actuels) ?
   - Le systeme ClaimKey (non peuple) devrait-il etre abandonne au profit d'une extension des QuestionDimensions ?

2. **Le fossé Claims vs Chunks** est le probleme structurel n°1. Les claims sont atomiques (1 phrase), les chunks sont contextuels (500-800 chars). Faut-il :
   - Creer un noeud intermediaire `Passage` qui regroupe les claims d'un meme chunk avec le contexte documentaire ?
   - Ou stocker le texte du chunk directement sur le Claim (champ `passage_text` existe deja mais pas exploite) ?
   - Ou accepter le fossé et ne PAS essayer de retourner des claims comme chunks ?

3. **Les ClaimClusters (2381 noeuds) sont sous-exploites**. Ils regroupent des claims semantiquement similaires cross-doc. Pourraient-ils etre le pivot de la synthese KG (identifier le "consensus" du corpus sur un sujet) ?

4. **Les 252 tensions cross-doc (REFINES + QUALIFIES)** sont la source de la valeur T2. Mais elles ne couvrent que les paires de claims en tension. Pour les questions de comparaison entre documents, faut-il :
   - Un mecanisme de detection de tensions "a la volee" (comparer les claims de 2 documents au runtime) ?
   - Ou enrichir le pipeline d'ingestion pour detecter plus de tensions (le gating actuel est tres conservateur) ?

### Questions sur l'etat de l'art

5. **Existe-t-il des travaux academiques ou industriels** (2024-2025) sur l'injection de contexte KG dans le prompt LLM (et pas dans le retrieval) ? Le concept de "KG-Augmented Synthesis" vs "KG-Augmented Retrieval" est-il documente ?

6. **Microsoft GraphRAG** utilise des "community summaries" comme contexte. OSMOSIS pourrait-il generer des equivalents a partir des ClaimClusters ? Quels sont les retours d'experience ?

7. **HippoRAG 2** (ICML 2025) utilise un "passage node" dans le KG pour lier les faits aux passages. Est-ce une approche qui resoudrait le fossé Claims vs Chunks ?

### Questions sur le ClaimKey / QuestionDimension

8. **L'ADR North Star dit "Sans ClaimKey, Usage A devient un RAG deguise"**. Aujourd'hui c'est exactement ce qu'on observe. Faut-il :
   - Elargir le gating des QuestionDimensions pour couvrir plus de 4.8% des claims ? Avec quel risque de bruit ?
   - Ou accepter que les QD restent un accelerateur specialise et construire la valeur differenciante ailleurs ?

9. **Le challenge (Usage B) est non-fonctionnel** car le systeme ClaimKey stratified n'est pas peuple. Faut-il :
   - Abandonner le systeme A et connecter l'Usage B aux QuestionDimensions ?
   - Ou peupler les ClaimKey a partir des QD existantes ?

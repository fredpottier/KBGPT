# OSMOSIS Phase B — Analyse consolidee et plan d'implementation

**Date** : 24 mars 2026
**Objectif** : Transformer OSMOSIS d'un "RAG ameliore" en un systeme de raisonnement documentaire differenciateur
**Destinataire** : Claude Web pour challenge et validation

---

## 1. Qu'est-ce qu'OSMOSIS

OSMOSIS est un systeme de Q&A documentaire qui :
1. Ingere des corpus de documents (PDF, PPTX, MD) via un pipeline LLM
2. Extrait des faits atomiques ("claims") structures (sujet-predicat-objet)
3. Les stocke dans un Knowledge Graph (Neo4j) avec entites, relations, tensions
4. Stocke en parallele les passages documentaires bruts ("chunks") dans une base vectorielle (Qdrant)
5. Permet une recherche semantique censee etre enrichie par le KG

OSMOSIS est **agnostique du domaine** — il fonctionne sur tout corpus (SAP, biomedical, reglementaire, juridique).

L'ADR North Star du projet dit : *"OSMOSIS est un Knowledge Graph documentaire dont le coeur est un registre de faits documentaires interrogeables par question."* Et surtout : *"Sans ClaimKey, Usage A devient un RAG deguise"* — c'est exactement ce qu'on observe aujourd'hui.

---

## 2. Le benchmark — resultats detailles

Un benchmark comparatif OSMOSIS vs RAG baseline a ete realise :
- **275 questions** reparties en 3 taches (T1 Provenance, T2 Contradictions, T4 Audit) x 2 types (KG cross-doc et humaines)
- **Meme LLM** (Qwen 2.5 14B AWQ) pour les deux systemes
- **Meme prompt** de synthese
- **RAG baseline** : memes embeddings (multilingual-e5-large), meme collection Qdrant, mais SANS KG
- **Valide par 2 juges independants** (Qwen + Claude Sonnet) avec ecart moyen 0.3% — les resultats sont fiables

### 2.1 T1 — Provenance et Citations

Teste la capacite a retrouver un fait precis et citer correctement ses sources.

**Questions KG cross-doc (30q)** — questions qui necessitent de croiser plusieurs documents :

| Metrique | Signification | OSMOSIS | RAG | Analyse |
|----------|---------------|---------|-----|---------|
| factual_correctness_avg | La reponse contient-elle le fait attendu ? | **42%** | 27% | OSM +15pp grace au cross-doc |
| answers_correctly_rate | Reponse correcte ET pertinente ? | **28%** | 17% | Mieux mais reste bas |
| answer_relevant_rate | La reponse est-elle pertinente ? | **59%** | 47% | OSM +12pp |
| citation_present_rate | Citations [Source N] presentes ? | 100% | 100% | Identique |
| correct_source_rate | Le BON document est-il cite ? | **45%** | 23% | OSM +22pp sur provenance |
| false_idk_rate | Refus injustifie (plus bas = mieux) | **14%** | 33% | OSM refuse 2x moins |

**Questions humaines (100q)** — questions factuelles simples redigees en lisant les documents :

| Metrique | Signification | OSMOSIS | RAG | Analyse |
|----------|---------------|---------|-----|---------|
| factual_correctness_avg | La reponse contient-elle le fait attendu ? | 35% | **41%** | **RAG meilleur +6pp** |
| answers_correctly_rate | Reponse correcte ET pertinente ? | 20% | **22%** | RAG legerement mieux |
| answer_relevant_rate | La reponse est-elle pertinente ? | 44% | **52%** | **RAG +8pp — le KG detourne** |
| citation_present_rate | Citations presentes ? | 100% | 100% | Identique |
| correct_source_rate | Le BON document est-il cite ? | 31% | **36%** | RAG legerement mieux |
| false_idk_rate | Refus injustifie | 35% | 37% | Quasi-identique — **35% est catastrophique** |

### 2.2 T2 — Detection des Contradictions

Teste la capacite a detecter et exposer les divergences entre documents.

**Questions KG (25q)** — basees sur des tensions REFINES/QUALIFIES verifiees dans le KG :

| Metrique | Signification | OSMOSIS | RAG | Analyse |
|----------|---------------|---------|-----|---------|
| both_sides_surfaced_rate | Les deux positions exposees ? | **100%** | 0% | **GAME CHANGER** |
| tension_mentioned_rate | Tension explicitement signalee ? | **100%** | 0% | **GAME CHANGER** |
| correct_tension_type_rate | Type de tension identifie ? | **50%** | 0% | OSM identifie le type |
| both_sourced_rate | Deux positions sourcees ? | **75%** | 0% | OSM source les deux cotes |
| silent_arbitration_rate | Arbitrage silencieux ? (bas = mieux) | 0% | 0% | Identique |

**Questions humaines (50q)** — comparaisons formulees naturellement :

| Metrique | Signification | OSMOSIS | RAG | Analyse |
|----------|---------------|---------|-----|---------|
| both_sides_surfaced_rate | Les deux positions exposees ? | 100% | 100% | Identique (le LLM voit les docs) |
| tension_mentioned_rate | Tension explicitement signalee ? | **25%** | 0% | OSM mieux mais seulement 25% |
| correct_tension_type_rate | Type identifie ? | **25%** | 0% | Faible |
| both_sourced_rate | Sourcees ? | 0% | 0% | Aucun ne source les tensions |
| silent_arbitration_rate | Arbitrage silencieux ? | 0% | 0% | Identique |

### 2.3 T4 — Audit et Completude

Teste la capacite a produire un resume complet et source d'un sujet cross-doc.

**Questions KG (20q)** :

| Metrique | Signification | OSMOSIS | RAG | Analyse |
|----------|---------------|---------|-----|---------|
| topic_coverage_rate | Couvre le sujet ? | **89%** | 58% | **OSM +31pp** |
| completeness_avg | Score completude | **68%** | 49% | **OSM +19pp** |
| comprehensiveness_rate | Exhaustif ? | **44%** | 16% | **OSM +28pp** |
| traceability_rate | Tracable ? | **100%** | 90% | OSM parfait |
| sources_mentioned_rate | Sources mentionnees ? | 100% | 100% | Identique |
| contradictions_flagged_rate | Contradictions signalees ? | **17%** | 0% | OSM seul a le faire |

**Questions humaines (50q)** :

| Metrique | Signification | OSMOSIS | RAG | Analyse |
|----------|---------------|---------|-----|---------|
| topic_coverage_rate | Couvre le sujet ? | **82%** | 78% | Modeste +4pp |
| completeness_avg | Score completude | **67%** | 62% | Modeste +5pp |
| comprehensiveness_rate | Exhaustif ? | **50%** | 41% | +9pp |
| traceability_rate | Tracable ? | 94% | 96% | Identique |
| sources_mentioned_rate | Sources mentionnees ? | 98% | 98% | Identique |
| contradictions_flagged_rate | Contradictions signalees ? | **18%** | 12% | Leger avantage |

### 2.4 Synthese — le pattern

**OSMOSIS excelle quand la question EXIGE du cross-doc** (T1 KG +15pp factual, T2 KG 100% vs 0%, T4 KG +19pp completude).

**OSMOSIS est mediocre a mauvais sur les questions simples** (T1 humain -6pp factual, -8pp pertinence) qui representent la majorite des interactions reelles.

**Le taux de refus injustifie (~35%) est catastrophique pour les deux systemes** — 1 question sur 3 sans reponse alors que l'info est dans le corpus.

---

## 3. Ontologie Neo4j — ce qui existe

### 3.1 Noeuds

| Type | Count | Role | Proprietes cles |
|------|-------|------|-----------------|
| **Claim** | 15 861 | Fait atomique extrait d'un document | `text`, `verbatim_quote`, `doc_id`, `page_no`, `claim_type` (95% FACTUAL), `structured_form_json` (triple SPO), `chunk_ids` (pont vers Qdrant, 100% rempli), `embedding` (1024d, **100% rempli** depuis le backfill du 24 mars), `passage_text` (texte du passage source, existe mais sous-exploite), `confidence`, `quality_status` |
| **Entity** | 7 059 | Entite nommee (concept, produit, feature, service) | `name`, `normalized_name`, `entity_type`, `mention_count`, `aliases[]` |
| **CanonicalEntity** | 267 | Pivot de deduplication d'entites | `canonical_name`, `source_entity_ids[]`, `doc_count` |
| **ClaimCluster** | 2 381 | Groupement de claims semantiquement similaires | `canonical_label`, `claim_ids[]`, `doc_ids[]`, `claim_count`, `doc_count`, `cross_doc` (bool), `avg_confidence` |
| **QuestionDimension** | 382 | Question factuelle canonique (pivot comparaison cross-doc) | `dimension_key`, `canonical_question`, `value_type`, `embedding` (1024d, 100%), `info_count`, `doc_count` |
| **QuestionSignature** | 755 | Reponse extraite a une QD (valeur + provenance) | `claim_id`, `doc_id`, `extracted_value`, `value_normalized`, `operator`, `confidence` |
| **Facet** | 9 | Domaine thematique transversal | `facet_name`, `domain`, `keywords[]` |
| **WikiArticle** | 69 | Articles de synthese generes | `title`, `markdown`, `importance_tier` |
| **DocumentContext** | 22 | Contexte d'applicabilite d'un document | `doc_id`, `primary_subject`, `applicability_frame_json` |

### 3.2 Relations

| Relation | Count | Direction | Signification |
|----------|-------|-----------|---------------|
| ABOUT | 25 634 | Claim → Entity | Ancrage semantique principal |
| IN_CLUSTER | 7 728 | Claim → ClaimCluster | Appartenance a un groupe |
| SIMILAR_TO | 4 208 | Claim ↔ Claim | Similarite semantique |
| BELONGS_TO_FACET | 2 659 | Claim → Facet | Domaine thematique |
| CHAINS_TO | 1 547 | Claim → Claim | Chaine narrative cross-doc |
| ANSWERS | 770 | QS → QD | Reponse a une question canonique |
| SAME_CANON_AS | 379 | Entity → CanonicalEntity | Synonymie |
| REFINES | 280 | Claim → Claim | Raffinement (souvent cross-doc) |
| QUALIFIES | 249 | Claim → Claim | Nuance/qualification (souvent cross-doc) |
| CONTRADICTS | 2 | Claim ↔ Claim | Contradiction directe (tres rare) |

**252 tensions cross-doc** (63 REFINES + 189 QUALIFIES entre documents differents) — c'est la source de la valeur T2.

### 3.3 Lien avec Qdrant

Collection `knowbase_chunks_v2` : ~15 000 chunks, embeddings 1024d (multilingual-e5-large).
Chaque Claim a un champ `chunk_ids[]` qui pointe vers les chunks Qdrant (format `default:DOC_ID:#/texts/N`). Le mapping est 100%.

### 3.4 Systeme ClaimKey / QuestionDimension

Deux systemes paralleles non connectes :
- **Systeme A (ClaimKey)** : 0 noeuds dans Neo4j, 14 patterns regex, non fonctionnel en production
- **Systeme B (QuestionDimension)** : 382 QD + 755 QS, operationnel, couvre 4.8% des claims

L'ADR dit que ClaimKey est le pivot du systeme. En realite, QuestionDimension est le successeur de ClaimKey dans le code actuel.

---

## 4. Architecture actuelle du search

Le search (`search_documents()` dans `search.py`, ~2100 lignes) suit ce flow :

```
1. Embedding de la question
2. Claims KG vector search (Neo4j claim_embedding) → enrichment map
3. Qdrant vector search → chunks (le coeur du retrieval)
4. Phase C light : si tensions cross-doc detectees, search Qdrant supplementaire
5. Enrichissement KG : injection entity_names/contradiction_texts sur les chunks
6. KG Traversal CHAINS_TO : contexte markdown cross-doc
7. QS Cross-Doc : comparaisons QuestionSignatures
8. Reranking + LatestSelector boost
9. Synthese LLM avec chunks + graph_context_text
```

**Le probleme identifie** : les etapes 2, 4 et 5 modifient ou completent les chunks Qdrant, ce qui les rend differents de ce que le RAG retournerait. Sur les questions simples, cette modification DEGRADE les resultats.

---

## 5. Analyse de l'etat de l'art (ChatGPT deep search)

### 5.1 GraphRAG (Microsoft)

GraphRAG construit un graphe d'entites puis pre-genere des "community summaries" via LLM. A l'inference, il produit des reponses intermediaires par communaute puis les agrege (map-reduce). Gains substantiels sur les questions "global" (comprehensiveness, diversity).

**Point d'attention pour OSMOSIS** : GraphRAG perd en tracabilite avec la resumisation — on ne sait plus quel passage exact supporte un element du resume. OSMOSIS a un avantage potentiel : tracabilite claim-level vs summarization-level.

### 5.2 HippoRAG 2 (ICML 2025)

Adresse exactement notre probleme : les KG ameliorent le sense-making mais degradent les taches factuelles basiques. HippoRAG 2 combine Personalized PageRank + "deeper passage integration" pour obtenir de bonnes performances "across both simple and complex tasks".

**Lecon pour OSMOSIS** : si le graphe est fonde sur des unites trop atomiques (claims = 1 phrase), il faut re-introduire la notion de passage comme contexte.

### 5.3 Lost in the Middle

Les LLMs ne consomment pas robustement les longs contextes. Si l'info pertinente est "au milieu", les performances chutent. Implication directe : le bloc KG injecte dans le prompt doit etre court, structure, et place strategiquement.

### 5.4 Re2G, FLARE, Rewrite-Retrieve-Read

- **Re2G** : retrieve + rerank + generate — gains via reranking
- **FLARE** : active retrieval iteratif pendant la generation — utile pour les audits longs
- **Rewrite-Retrieve-Read** : adapter la requete avant le search

---

## 6. Analyse critique des pistes et propositions

### 6.1 Piste "Passage node" (HippoRAG 2)

**Proposition** : creer un noeud Passage dans Neo4j, jumeau du chunk Qdrant.

**Notre evaluation** : **fausse bonne idee dans notre contexte**. Nous avons DEJA le lien Claim → Chunk via `chunk_ids` (100% rempli). Le champ `passage_text` existe deja sur les Claims. HippoRAG 2 a besoin du Passage node car ils n'ont PAS de base vectorielle separee — nous, si (Qdrant). Creer un Passage node dupliquerait les donnees sans valeur ajoutee.

**Ce qu'il faut faire a la place** : exploiter le `passage_text` existant sur les Claims pour construire le contexte KG, sans creer de nouveau type de noeud.

### 6.2 Piste "Community summaries" (GraphRAG)

**Proposition** : generer des resumes de clusters a la GraphRAG.

**Notre evaluation** : **prometteuse mais avec un piege**. Pre-generer des resumes LLM est couteux (tokens), fragile (stale quand le corpus change), et perd la tracabilite (limitation reconnue par GraphRAG lui-meme).

**Ce qu'il faut faire** : NE PAS pre-generer des resumes. UTILISER les ClaimClusters (2381, deja existants, avec `canonical_label`, `doc_ids[]`, `cross_doc` flag) pour identifier le consensus et les divergences AU RUNTIME. Injecter dans le prompt un bloc structure : "Ce sujet est couvert par X documents. Les documents A et B sont alignes. Le document C apporte une nuance."

C'est plus leger, plus tracable, et ne necessite pas de pre-generation.

### 6.3 Invariant non-regression Type A (PRIORITE CRITIQUE)

**Proposition** : pour les questions simples (60%+), chunks identiques au RAG + bloc KG court separe.

**Notre evaluation** : **exactement ce qu'il faut, c'est la priorite n1**. Le bloc KG doit etre :
- **Court** (50-100 tokens, pas un pave)
- **Structure** (listes, pas prose)
- **Place AVANT les chunks** (attention LLM au debut > au milieu)
- **Construit a partir des chunks retournes** (pas d'info KG hors-sujet)

Exemple concret :
```
[Contexte Knowledge Graph — 3 entites identifiees]
• SAP Fiori → mentionne dans 18 documents (securite, installation, scope)
• ABAP Platform → base technologique de S/4HANA
• Tension detectee : Security Guide 2022 vs 2023 sur l'authentification X.509

[Sources ci-dessous]
[Source 1: 027_Security_Guide_2023] ...
[Source 2: 028_Security_Guide_2022] ...
```

### 6.4 Amelioration du socle RAG (rerank, query rewriting, FLARE)

**Notre evaluation** : **piege de priorisation**. On a DEJA un reranker. Le query rewriting necessite un appel LLM (latence). FLARE est interessant pour les audits longs mais c'est un chantier majeur.

**Le vrai gain rapide** : corriger le prompt de synthese pour reduire le taux de refus injustifie (35% → <15%). Le LLM est trop conservateur — il dit "je ne sais pas" quand l'info est partiellement presente. C'est un fix de prompt, pas d'architecture.

### 6.5 Detection de tensions enrichie

**Notre evaluation** : le probleme n'est pas le nombre de tensions (252 suffisent) mais leur **accessibilite au runtime**. Les tensions sont invisibles quand le search Qdrant retourne des chunks d'un seul document.

**La solution** : pour les questions Type B (cross-doc), le bloc KG mentionne explicitement les tensions meme si les chunks viennent d'un seul document. Le LLM est informe de la tension AVANT de lire les chunks.

### 6.6 Extension QuestionDimensions

**Notre evaluation** : pas prioritaire. Couverture 4.8%, elargir augmente le bruit. Garder comme accelerateur specialise pour l'Usage B (challenge) et les reponses structurees (tableaux de valeurs).

---

## 7. Plan d'implementation propose

### Etape 1 (2 jours) — Fix prompt + Invariant Type A

**Objectif** : eliminer la degradation sur les questions simples et reduire le taux de refus.

1. **Corriger le prompt de synthese** : remplacer "si l'information n'est pas dans les sources, dis-le" par "reponds avec ce que tu trouves — ne dis 'non disponible' QUE si AUCUNE source n'est pertinente"
2. **Implementer l'invariant Type A** : pour les questions simples, les chunks sont EXACTEMENT ceux du RAG. Le KG ne modifie PAS les chunks.
3. **Construire le bloc KG court** : a partir des chunks retournes, extraire les entites, tensions et structured_form. Injecter comme bloc separe de 50-100 tokens AVANT les chunks.

**Metriques de succes** : false_idk < 20%, factual(human) >= 41%

### Etape 2 (3 jours) — Intent Resolver + Routing

**Objectif** : router chaque question vers la bonne strategie sans appel LLM.

1. **IntentResolver** (regex + scoring, < 5ms) : 4 types A/B/C/D + fallback X→A
2. **Type A (simple, ~60%)** : Qdrant pur + bloc KG court. Invariant enforce.
3. **Type B (cross-doc, ~15%)** : identifier les documents en tension via KG → mentionner dans le bloc KG les tensions explicites, meme si Qdrant ne retourne qu'un seul document
4. **Type C (audit, ~15%)** : Qdrant global + ClaimClusters pour identifier la couverture documentaire → bloc "Couverture" dans le prompt
5. **Type D (comparable, ~10%)** : Qdrant + QD vector search → overlay structure avec valeurs comparees

### Etape 3 (2 jours) — Exploitation des ClaimClusters

**Objectif** : donner au LLM une vue "consensus vs divergences" du corpus.

1. Pour Type C : traverser les ClaimClusters lies au sujet → extraire doc_ids, claim_count par doc, cross_doc flag
2. Construire un bloc "Couverture documentaire" : quels documents, combien de claims, quels gaps, quelles divergences
3. Signaler les tensions via REFINES/QUALIFIES des claims dans les clusters cross-doc
4. Pas de pre-generation de resumes — tout au runtime via requetes Neo4j

### Etape 4 (1 jour) — Benchmark de validation

Relancer le benchmark complet et verifier :
- Invariant : OSMOSIS >= RAG sur TOUTES les metriques
- false_idk < 20% (vs 35% actuellement)
- T2 tensions human >= 40% (vs 25% actuellement)
- T4 completude KG >= 75% (vs 68% actuellement)

### Etape 5 (optionnel, 3-5 jours) — Active retrieval pour audits

Implementer un mecanisme FLARE-like pour Type C uniquement :
- Le LLM genere une premiere reponse → identifie les manques → relance un search cible
- Uniquement pour les questions d'audit (pas pour Type A/B/D)

---

## 8. Ce que nous ne recommandons PAS

1. **Creer un noeud Passage** : on a deja `passage_text` et `chunk_ids` — duplication inutile
2. **Pre-generer des community summaries** : trop couteux, stale, perte de tracabilite
3. **Query rewriting LLM** : ajoute de la latence, gain marginal vs fix de prompt
4. **Elargir le gating QD** : augmente le bruit, gain marginal sur le benchmark
5. **Intent resolver LLM-based** : trop lent (2-15s), les regex suffisent pour 4 types

---

## 9. Invariants non negociables

1. **Agnosticite domaine** : aucun pattern, mot-cle ou regle specifique a un domaine (SAP, biomedical, etc.)
2. **Auditabilite** : chaque reponse doit etre explicable et tracable jusqu'au passage source exact
3. **Non-regression RAG** : OSMOSIS >= RAG sur TOUTES les metriques, par construction
4. **Tracabilite claim-level** : avantage vs GraphRAG qui perd la tracabilite dans les resumes agrees
5. **Latence acceptable** : l'intent resolver < 5ms, le bloc KG < 200ms, le total < +500ms vs RAG

---

## 10. Metriques de succes Phase B

| Metrique | Actuel | Objectif | Levier |
|----------|--------|----------|--------|
| T1 factual human | 35% | **>= 42%** | Invariant A + fix prompt |
| T1 false_idk human | 35% | **< 15%** | Fix prompt agressif |
| T1 factual KG | 42% | **>= 50%** | Bloc KG cross-doc |
| T2 tensions human | 25% | **>= 50%** | Bloc KG avec tensions explicites |
| T4 completude KG | 68% | **>= 80%** | ClaimClusters couverture |
| T4 completude human | 67% | **>= 75%** | ClaimClusters + audit |
| OSMOSIS >= RAG | Oui sauf T1 human | **Toutes metriques** | Invariant A enforce |

---

## 11. Questions pour le challenger

1. L'invariant "chunks identiques au RAG pour Type A" est-il la bonne approche, ou faut-il aller plus loin et faire du KG un vrai selecteur de chunks (au risque de degrader) ?

2. Le bloc KG court (50-100 tokens) est-il suffisant pour changer la qualite des reponses, ou est-ce que "lost in the middle" signifie qu'il sera ignore par le LLM ?

3. Les ClaimClusters (2381 noeuds) sont-ils une bonne base pour le "consensus cross-doc", ou faut-il un mecanisme plus sophistique (community detection, hierarchie) ?

4. Le taux de refus injustifie (35%) est-il vraiment un probleme de prompt ou un probleme plus profond (chunks non pertinents, embeddings mal calibres, questions ambigues) ?

5. Le plan en 8-10 jours est-il realiste, ou faut-il prevoir une refacto plus profonde de search.py (qui fait 2100 lignes et accumule des patches) ?

6. La strategie "KG enrichit la synthese, pas le retrieval" est-elle la bonne direction finale, ou est-ce une etape de transition vers un KG qui pilote vraiment la recherche (comme le dit l'ADR North Star) ?

7. Existe-t-il des approches dans l'etat de l'art 2024-2025 qui combinent tracabilite audit-grade + global sensemaking sans sacrifier la precision factuelle ? C'est le trilemme d'OSMOSIS.

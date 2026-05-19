# Vision Produit OSMOSIS

> **Niveau de fiabilite** : Strategie produit (Mars 2026). Positionnement et vision — pas de verification code (document non-technique).

*Document consolide — Mars 2026*

---

## 1. Positionnement

### De la recherche documentaire a l'intelligence documentaire

OSMOSIS n'est pas un RAG ameliore, pas un moteur de recherche, et surtout pas un "Truth Engine". C'est un **moteur d'analyse documentaire intelligent qui detecte ce que la recherche ne voit pas**.

**Categorie produit retenue** : **Documentation Verification Platform**

Pourquoi cette categorie et pas une autre :

| Option evaluee | Verdict | Raison |
|----------------|---------|--------|
| "Chat with your docs" | Ecartee | Marche sature (Glean, Guru, Notion AI, Copilot) |
| "Truth Engine" / "Truth Layer" | Ecartee | Le mot "verite" est dangereux commercialement — implique un jugement absolu, politiquement explosif en entreprise |
| "Enterprise RAG" | Ecartee | Mort en arrivant — comparaison directe avec Copilot = defaite assuree |
| "Documentation Verification Platform" | **Retenue** | Alignee avec l'existant technique, differenciante, vendable |

**Positionnement en une phrase** :
> "OSMOSIS repond a vos questions, mais surtout il vous dit quand vos documents ne sont pas d'accord entre eux."

**Tagline** : *"De la recherche documentaire a l'intelligence documentaire"*

### Le vrai probleme resolu

Le probleme n'est pas la recherche documentaire. Le probleme est :

> **Les entreprises ne peuvent pas se fier a leur propre documentation.**

Exemples concrets :
- **Produit** : spec produit dit X, doc marketing dit Y, doc support dit Z — contradictions permanentes
- **Securite** : doc architecture vs doc runbook vs doc compliance — incoherences critiques
- **Reglementaire** : version 2022 vs version 2024 — impossible de savoir ce qui est encore valide
- **Post-acquisition** : documentation heritee de 3 entites fusionnees — chaos documentaire

---

## 2. Les 5 capacites fondamentales

Definies le 24 mars 2026. C'est la boussole produit — chaque feature doit servir au moins une de ces capacites.

### Capacite 1 — Reponse directe (baseline)

*"Repondre aux questions que pose un utilisateur"*

Le mecanisme (RAG ou KG) est de la plomberie invisible. L'utilisateur veut la bonne reponse.

- **Invariant** : OSMOSIS ne doit JAMAIS etre pire qu'un RAG sur cette capacite
- **Statut mars 2026** : 35% factual OSMOSIS vs 41% RAG sur questions simples — a corriger. 100% des refus a tort ont un score Qdrant >= 0.75, c'est un probleme de prompt, pas de retrieval.

### Capacite 2 — Synthese multi-document

*"Proposer une reponse qui n'est localisee dans aucun document unique mais fait appel a plusieurs docs sans lien evident"*

Le KG connecte des claims a travers des documents qui ne se citent pas mutuellement. Entity→ABOUT + ClaimClusters + CHAINS_TO permettent de reconstruire une reponse distribuee.

- **Statut mars 2026** : T4 completude OSMOSIS 68% vs RAG 49% (+19pp). 820 ClaimClusters cross-doc exploitables.

### Capacite 3 — Raisonnement differentiel

*"Identifier ce qui est nouveau ou modifie par comparaison entre versions"*

Si aucun document ne dit explicitement "nouveau", OSMOSIS compare les fonctionnalites v2022 vs v2023 et deduit par difference. S'appuie sur les relations MODIFIED/ADDED/REMOVED et l'ApplicabilityFrame.

- **Statut mars 2026** : Partiellement implemente. Pas encore benchmarke specifiquement.

### Capacite 4 — Detection de tensions documentaires

*"Deceler quand deux documents ne disent pas la meme chose sur un meme prisme"*

5 couches de detection : bucketing, exclusivite predicat, ValueFrame, comparateur formel, arbitrage LLM. 6 regimes de verite (NORMATIVE_STRICT, NORMATIVE_BOUNDED, EMPIRICAL_STATISTICAL, DESCRIPTIVE_APPROX, CONDITIONAL_SCOPE, TEXTUAL_SEMANTIC).

- **Statut mars 2026** : Benchmark T2 — OSMOSIS 100% detection vs RAG 0%. **C'est LE game-changer.**

### Capacite 5 — Validation et transparence AI Act

*"Analyser un input et dire ce qui est vrai, faux ou inconnu selon la documentation"*

L'utilisateur soumet un texte, OSMOSIS verifie chaque assertion contre le corpus. Statuts : confirmed / contradicted / incomplete / unknown. Evidence-locking : zero connaissance inventee.

- **Statut mars 2026** : Implemente dans `/verify`. Pas encore benchmarke.

---

## 3. Differenciation vs RAG / Copilot / Gemini

### Matrice comparative

| Capacite | RAG classique | OSMOSIS | Microsoft Copilot | Glean |
|----------|:---:|:---:|:---:|:---:|
| 1. Reponse directe | **oui** | oui (= RAG) | **oui** | **oui** |
| 2. Synthese multi-doc | partiel (top-k) | **oui** (KG cross-doc) | partiel | non |
| 3. Raisonnement differentiel | **non** | **oui** (evolution tracking) | non | non |
| 4. Detection tensions | **non** | **oui** (5 couches) | non | non |
| 5. Validation / AI Act | **non** | **oui** (/verify) | non | non |

**Zone de differenciation absolue** : capacites 3, 4, 5 — aucun concurrent actuel ne les propose.

### Benchmark T2 : la preuve par les chiffres

Sur 25 questions KG de type "contradiction" (benchmark 275 questions, double juge Qwen + Claude, convergence 0.3%) :

| Metrique | OSMOSIS | RAG |
|----------|---------|-----|
| both_sides_surfaced | **100%** | 0% |
| tension_mentioned | **100%** | 0% |
| correct_tension_type | **50%** | 0% |

Le RAG ne mentionne JAMAIS les tensions — il repond sans signaler les divergences. OSMOSIS les detecte systematiquement. C'est une difference categorielle, pas incrementale.

### Difference fondamentale d'architecture

```
RAG classique :   documents → chunks → embeddings → reponse
OSMOSIS :         documents → extraction → claims → graph → reasoning
```

Ce n'est pas la meme categorie d'outil. OSMOSIS possede une representation structuree de la connaissance : 15 861 claims, 7 059 entites, 2 620 clusters (dont 820 cross-doc), 252 tensions cross-doc.

---

## 4. Les 3 usages d'exploitation

Formalises dans l'ADR Exploitation Layer (janvier 2025). Ces usages sont distincts et ne doivent PAS etre fusionnes.

### Usage A — Corpus-Derived Document Composition

**Intention** : Produire un document autonome a partir du corpus existant.

L'utilisateur definit un sujet et un angle (securite, reglementaire, architecture). Le systeme identifie les concepts pertinents, agregue les informations, propose un plan, compose un contenu structure fidele au corpus.

**Invariants** : pas de concept nouveau, pas d'affirmation non supportee, zones non couvertes explicites. Composition, pas creation.

**Valeur** : reduction massive du temps de production documentaire, livrables auditables.

### Usage B — In-Context Writing Companion

**Intention** : Assister pendant la redaction en challengeant ce qui est ecrit.

Le systeme ne redige pas a la place de l'utilisateur. A mesure que des phrases sont ajoutees, il fournit un feedback corpus-based : supporte, partiellement documente, non documente, tension detectee.

**Invariants** : pas de correction automatique, pas de vrai/faux absolu, justification obligatoire.

**Valeur** : reduction du risque d'over-claim, securisation des communications.

### Usage C — Concept-Driven Navigator

**Intention** : Construire progressivement un texte explicatif par navigation conceptuelle.

L'utilisateur explore un sujet par concepts, active ou desactive des branches, et le systeme transforme ce scope en plan narratif puis en sections de texte.

**Invariants** : la navigation contraint l'espace de discours, elle ne produit pas le texte. Transition C vers A explicite, jamais implicite.

**Valeur** : facilite la comprehension de sujets complexes, reduit la charge cognitive.

---

## 5. La metaphore du bibliothecaire

Un bibliothecaire extraordinaire recoit 500 livres sur un sujet :

1. **Lit chaque livre** et surligne chaque affirmation importante — pas les titres, les faits precis
2. **Ecrit chaque affirmation sur une fiche bristol** avec au dos la reference exacte (livre, page, paragraphe)
3. **Classe les fiches** par sujet, produit, theme
4. **Relie les fiches entre elles** — "cette fiche precise celle-la", "attention, ces deux fiches se contredisent"
5. **Range tout dans un systeme** interrogeable avec preuves

Les "fiches bristol" sont les **Claims**. Le systeme de rangement est le **Knowledge Graph**. Le bibliothecaire est un pipeline automatise en 10 etapes :

```
Documents (PDF, PPTX, DOCX, Excel)
     |
     v
1. Arrivee du document (file d'attente Redis)
2. Comprehension du sujet (profil documentaire)
3. Decoupage en passages (ancres de contexte)
4. Extraction des Claims (affirmations atomiques, verifiables)
5. Identification des entites (produits, concepts, standards)
6. Tissage des liens (ABOUT, SUPPORTED_BY)
7. Enrichissement specialise (Domain Packs enfichables)
8. Regroupement des doublons semantiques (ClaimClusters)
9. Detection des relations inter-claims (contradictions, precisions, nuances)
10. Persistance dans le Knowledge Graph (Neo4j + Qdrant)
```

Chiffres sur un corpus reel de 22 documents SAP : 15 861 claims, 7 059 entites, 2 620 clusters, 252 tensions cross-doc.

---

## 6. Marche cible et strategie commerciale

### Score de maturite commerciale (audit mars 2026)

| Dimension | Score | Detail |
|-----------|-------|--------|
| Architecture technique | 9/10 | Pipeline complet, multi-tenant, domain-agnostic, 81 modules Python |
| Documentation produit | 3/10 | Zero doc en anglais, zero guide utilisateur |
| Donnees de demo | 2/10 | Aucune donnee non-SAP dans le KG |
| Securite enterprise | 5/10 | Pas de SSO/SAML, pas de secrets management |
| Frontend Intelligence Report | 6/10 | Pas de dashboard contradictions |
| CI/CD | 0/10 | 3 944 tests mais aucun pipeline automatise |
| Scalabilite | 5/10 | Docker-compose only, single-node |
| **Score commercial global** | **5.5/10** | **R&D avancee, pas encore un produit vendable** |

### Cible principale : editeurs logiciels mid-size (50-500 personnes)

Pourquoi :
- Documentation massive qui evolue a chaque release
- Contradictions frequentes entre doc produit, support, marketing
- Pas les moyens de construire leur propre outil
- Comprennent immediatement "vos docs se contredisent sur ces 3 points"

### Cible secondaire : cabinets de conseil / audit

- Analysent des masses documentaires pour leurs clients
- La detection de contradictions est une prestation a forte valeur
- Credibilite institutionnelle qui peut accelerer l'adoption

### 3 horizons strategiques

| Horizon | Temporalite | Positionnement |
|---------|------------|----------------|
| H1 | Maintenant - 6 mois | Documentation Verification Platform |
| H2 | 6 - 18 mois | Knowledge Verification Platform |
| H3 | 18+ mois | AI Knowledge Governance Layer |

**Decision structurante** : produit d'abord, infrastructure ensuite. L'Horizon 3 est une vision, pas un plan d'action — on y arrive avec des clients et du revenu, pas avec un slide deck.

### Les 3 piliers de valeur

| Pilier | Feature reelle | Question client |
|--------|---------------|-----------------|
| **Coherence** | Contradiction detection 5 couches + truth regimes | "Nos docs se contredisent-elles ?" |
| **Tracabilite** | Evolution tracking + applicability frames | "Qu'est-ce qui a change entre v1 et v2 ?" |
| **Fiabilite** | Quality gates + evidence-locking + confidence scoring | "Peut-on se fier a cette information ?" |

---

## 7. Pistes ecartees

### "Chat with docs" — ecarte

Marche sature par Glean, Guru, Notion AI, Copilot. Se battre sur ce terrain contre des acteurs a milliards de financement est une bataille perdue. OSMOSIS ne cherche pas dans les documents — il les verifie.

### "Truth Engine" — ecarte

Le mot "verite" est dangereux commercialement :
1. Implique un jugement de valeur absolu — or le systeme est nuance (6 regimes de verite)
2. Politiquement explosif en entreprise — "qui a tort, le VP Produit ou le VP Marketing ?"
3. Le bon cadrage est "coherence et tracabilite" — moins sexy mais plus vendable

Le terme peut etre utilise dans un whitepaper technique, pas dans un pitch commercial.

### Focus SAP — ecarte

SAP dispose deja d'un outil similaire (KG + RAG) construit avec son ontologie propre, ses sources officielles, et sa legitimite institutionnelle. Se battre sur le terrain SAP contre SAP est une bataille perdue d'avance. L'architecture OSMOSIS est domain-agnostic — c'est sa force, pas un bug.

### "AI Safety" / positionnement premature

Tentant de se projeter sur "AI Governance Layer" sans client. Risque de paralysie par l'ambition. La regle : pas de mention "AI Governance" dans le messaging externe tant qu'il n'y a pas de clients payants.

---

## 8. Etat produit actuel

### Ce qui fonctionne (valide par benchmark)

- Detection de contradictions : 100% vs 0% RAG — game-changer
- Completude multi-doc : +19pp vs RAG sur questions KG
- Tracabilite : 94-100% des reponses sourcees
- ClaimClusters : 2 620 (dont 820 cross-doc)
- Calibration inter-juges : 0.3% ecart (robuste)
- Pipeline ingestion : PDF, PPTX, DOCX, XLSX, MD, HTML
- Multi-tenant avec isolation complete
- Domain-agnostic (zero regex specifique a un domaine)

### Ce qui ne fonctionne pas encore

| Probleme | Score | Cause identifiee |
|----------|-------|-----------------|
| Factual sur questions simples | 35% vs RAG 41% | KG perturbe les questions simples quand injecte dans le prompt |
| Taux de refus a tort | 33% | 100% probleme de prompt (pas retrieval) |
| Partial hallucination | 30% (vs 10% RAG) | KG fournit contexte adjacent qui encourage le LLM a repondre quand il ne devrait pas |
| Enrichissement hors-sujet | 26% irrelevant (vs 17% RAG) | Enrichissement KG elargit hors-sujet |

### Ce qui manque pour commercialiser

1. **Corpus de demo non-SAP** — aucun prospect ne veut voir une demo avec des donnees SAP
2. **Intelligence Report UI** — sans lui, 81 modules Python restent invisibles
3. **Documentation en anglais** — 80% du marche est anglophone
4. **CI/CD pipeline** — tests automatises = credibilite technique
5. **Securite enterprise** — SSO/SAML, secrets management

---

## 9. References archive

Tous les documents sources sont archives dans `doc/archive/pre-rationalization-2026-03/` :

| Source | Emplacement archive |
|--------|-------------------|
| Vision produit (24 mars 2026) | `ongoing/OSMOSIS_VISION_PRODUIT_2026-03.md` |
| Strategie repositionnement | `ongoing/STRATEGY_REPOSITIONNEMENT_OSMOSIS_2026-03.md` |
| 10 usages quotidiens | `ongoing/OSMOSE_USAGES_QUOTIDIENS.md` |
| ADR Exploitation Layer | `ongoing/ADR_EXPLOITATION_LAYER.md` |
| Ambition produit & roadmap | `phases/OSMOSE_AMBITION_PRODUIT_ROADMAP.md` |
| Pipeline explainer | `ongoing/OSMOSE_PIPELINE_EXPLAINER.md` |
| Sprint 0 rapport exhaustif | `ongoing/SPRINT0_RAPPORT_EXHAUSTIF.md` |

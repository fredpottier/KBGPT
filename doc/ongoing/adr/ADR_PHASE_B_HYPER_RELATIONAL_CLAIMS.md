# ADR Phase B — Extraction hyper-relationnelle des Claims

> Date : 2026-05-25
> Statut : DRAFT — en attente validation Fred
> Référence : `doc/ongoing/PLAN_PHASE_B_AUGMENTEE.md` Phase 1, `doc/ongoing/ETAT_ART_KG_RAG_2026_DIAGNOSTIC_OSMOSE.md` (P11 hyper-relational, P13 StepChain)
> Branche : `feat/phase-b-augmentee`

---

## 1. Motivation

Diagnostic mesuré au judge corrigé (anti-overfit abstention, 25/05/2026) :

| Type | C1 réel | Problème |
|---|---|---|
| multi_hop | **0.100** | claims atomiques isolés, pas de chaînes pré-extraites |
| lifecycle | **0.167** | pas de qualifiers temporels structurés sur les claims |
| comparison | 0.400 | claims versionnés sans axe de comparaison explicite |
| factual | 0.433 | OK (fix c.text), mais ~44% des questions ont des claims manquants/incomplets (recall audit) |

Le recall audit a montré que **44% des échecs factual+multi_hop sont des claims absents ou trop atomiques** pour répondre à des questions multi-saut ou conditionnelles. L'extraction actuelle produit des assertions `(subject, predicate, object)` mono-ligne sans :
- **Qualifiers** (quand, où, sous quelle condition, pour quelle version)
- **Chaînes procédurales** (étape 1 → 2 → 3, prérequis)

## 2. État de l'existant (audit 25/05/2026)

### Modèle Claim actuel (`src/knowbase/claimfirst/models/claim.py`)
- `ClaimScope` existe (`version, region, edition, conditions`) mais **sous-exploité** : quasi toujours `null` en pratique
- `claim_type` inclut déjà `PROCEDURAL` mais sans structuration des étapes
- ❌ Pas de champ `qualifiers` structurés
- ❌ Pas de `procedure_role` / lien `STEP_OF`

### Infra Procedure DÉJÀ existante mais orpheline
- `src/knowbase/claimfirst/v6/procedure_extractor.py` + `procedure_persister.py` créent des nodes `:Procedure` + `:ProcedureStep` via DeepSeek-V3.1
- **MAIS non reliés aux Claims** (architecture v6 séparée, additive, jamais branchée au runtime)
- → **Opportunité** : connecter cette infra existante plutôt que la recréer

### Relations claim-claim existantes (`models/result.py`)
- `CONTRADICTS`, `REFINES`, `QUALIFIES`, `CHAINS_TO`
- `CHAINS_TO` créé par ChainDetector (A.object == B.subject) — proxy faible de chaîne procédurale

## 3. Décision — Schéma enrichi cible

### 3.1 Qualifiers structurés sur Claim

Nouvelle classe `ClaimQualifier` (domain-agnostic) :
```python
class ClaimQualifier(BaseModel):
    qualifier_type: Literal[
        "temporal",        # "depuis 2024", "jusqu'à v2.5", "à partir de SPS03"
        "spatial",         # "EU only", "China region"
        "version",         # "S/4HANA 2023", "edition Private Cloud"
        "condition",       # "si MFA activé", "pour clients RISE"
        "scope_limit",     # "hors production", "développement uniquement"
    ]
    value: str
    confidence: float
```
Champ ajouté sur `Claim` : `qualifiers: List[ClaimQualifier] = []`

**Pourquoi pas réutiliser ClaimScope ?** ClaimScope est un objet plat (4 champs fixes). Les qualifiers sont une liste typée extensible qui capture des conditions multiples et hétérogènes. ClaimScope reste pour le filtrage bitemporal ; qualifiers enrichissent le contenu sémantique pour le retrieval et la réponse.

**Domain-agnostic** : les 5 types sont universels (médical : "chez l'adulte", "posologie >65 ans" = condition/scope_limit ; légal : "depuis l'amendement 2021" = temporal ; aerospace : "au-dessus de FL250" = condition).

### 3.2 Node :Procedure relié aux Claims

Réutiliser l'infra `claimfirst/v6/procedure_extractor.py` en la **branchant au pipeline ClaimFirst** :
- Node `(:Procedure {procedure_id, name, goal, domain_neutral_label, doc_id})`
- Relations :
  - `(:Claim)-[:STEP_OF {order:int}]->(:Procedure)` — un claim procédural = une étape
  - `(:Claim)-[:PREREQUISITE_OF]->(:Claim)` — dépendance entre étapes
  - `(:Procedure)-[:HAS_OUTCOME]->(:Claim)` — résultat de la procédure

### 3.3 Nouvelles relations (`models/result.py`)
```python
class RelationType(str, Enum):
    # existants : CONTRADICTS, REFINES, QUALIFIES, CHAINS_TO
    STEP_OF = "STEP_OF"
    PREREQUISITE_OF = "PREREQUISITE_OF"
    HAS_OUTCOME = "HAS_OUTCOME"
```

## 4. Modifications pipeline

| Étape | Fichier | Modif |
|---|---|---|
| Prompt extraction | `extractors/claim_extractor.py` (L94-183) | ajouter section `qualifiers[]` au JSON demandé |
| Modèle | `models/claim.py` (L200-260) | `ClaimQualifier` + champ `qualifiers` + `to_neo4j_properties()` |
| Phase 1.9 (NEW) | `orchestrator.py` (après L484) | QualifierExtractor optionnel si prompt principal n'a pas rempli |
| Phase 6.7 (NEW) | `orchestrator.py` (après L746) | brancher procedure_extractor v6 sur claims PROCEDURAL → Procedure + STEP_OF/PREREQUISITE_OF |
| Persistence | `persistence/claim_persister.py` (L307+) | `qualifiers_json` + `_persist_procedures()` |
| Relations | `models/result.py` (L30) | 3 nouveaux RelationType |
| Runtime tool (Phase 3) | `runtime_a3/execute.py` | `procedure_chain` exploite STEP_OF (hors P1.1) |

## 5. Domain-agnostic check (charte AX-11)

- **Prompt qualifiers** : few-shot avec 3 exemples corpus actuel + 1 médical (posologie conditionnelle) + 1 juridique (amendement temporel). Aucune instruction SAP-spécifique.
- **Types qualifiers** : universels (temporal/spatial/version/condition/scope_limit).
- **Procedures** : notion universelle (recette médicale, procédure légale, séquence aerospace, migration logicielle).
- **Tests** : chaque module testé sur ≥1 cas non-SAP.

## 6. Migration / ré-ingestion

- Claims existants : `qualifiers = []`, pas de Procedure (rétrocompat OK)
- **Ré-ingestion complète requise** pour peupler qualifiers + procedures sur le corpus de test (38 docs)
- ⚠ **Contrainte Fred** : la ré-ingestion utilise l'**EC2 Burst** (Qwen2.5-14B AWQ) car crédit DeepInfra/Together insuffisant. Allumer EC2 Burst AVANT P1.4.
- Snapshot Neo4j avant ré-ingestion (rollback 5 min si problème)
- Marquage `extraction_version` sur les claims pour distinguer v1 (avant) / v2 (enrichi) et mesurer le drift

## 7. Gates Phase 1

| Gate | Critère |
|---|---|
| P1.1 | ADR validé + Pydantic + Cypher constraints + tests unitaires passent |
| P1.2 | sur 5 docs test (2 SAP + 1 médical + 1 juridique + 1 procédural) : ≥30% claims avec qualifiers, ≥10% procedure_role sur docs procéduraux |
| P1.2-validation | prompt testé avec DeepSeek-V3.1 + Qwen2.5-14B (EC2) : ≥80% qualité sur 1 des 2 |
| P1.3 | ≥5 :Procedure créés, ≥20 STEP_OF, ≥5 PREREQUISITE_OF sur corpus test |
| P1.5 | bench 50q judge corrigé : C1 multi_hop ≥ 0.25 (vs 0.10) ET C1 global ≥ 0.45 (vs 0.39) |

**STOP rule** : si P1.2 montre que DeepSeek/Qwen ne produisent pas de qualifiers fiables (<20%), revoir le prompt avant ré-ingestion (ne pas brûler l'EC2 Burst sur une extraction défaillante).

## 8. Risques

| Risque | Mitigation |
|---|---|
| Ré-ingestion casse des claims qui marchent | Snapshot Neo4j + extraction_version + bench mixte v1/v2 |
| Qualifiers bruités (LLM hallucine conditions) | Confidence + validation verbatim_quote (qualifier doit dériver du texte source) |
| Coût/temps EC2 Burst ré-ingestion 38 docs | Tester sur 5-10 docs d'abord (P1.2-P1.3), full seulement si gate P1.3 OK |
| Procedure extractor v6 non testé en prod | Smoke sur 2-3 docs procéduraux avant intégration pipeline |
| multi_hop ne remonte pas malgré chaînes | Phase 3 tool `procedure_chain` requis pour exploiter STEP_OF (chantier séparé) |

## 9. Séquencement P1

1. **P1.1** (ce doc) — design + Pydantic + Cypher constraints + tests — 2j
2. **P1.2** — prompt qualifiers + tests 5 docs multi-corpus — 3-4j
3. **P1.3** — brancher procedure_extractor v6 + détecteur PREREQUISITE_OF — 3j
4. **P1.4** — ré-ingestion (EC2 Burst) : 5-10 docs test puis full 38 — 2-3j
5. **P1.5** — bench 50q judge corrigé — 1j

Total : 11-13j + ré-ingestion. (Réduit vs estimation initiale 13-18j grâce à la réutilisation de l'infra Procedure v6 existante.)

## 10. Note importante — dépendance Phase 3

Les qualifiers (lifecycle, conditions) bénéficient au retrieval + Synthesize **immédiatement** (P1.5).
Mais les chaînes procédurales (STEP_OF) ne donneront leur plein effet multi_hop qu'avec le **tool runtime `procedure_chain`** (Phase 3). Sans ce tool, les Procedures sont créées mais peu exploitées au runtime.

→ **Recommandation** : après P1.5, enchaîner Phase 3 `procedure_chain` pour récolter le gain multi_hop. Ou intégrer un mini-tool dans P1.5.

## 11. Mise en œuvre (25/05/2026) — décisions d'implémentation

Statut : P1.1, P1.2, P1.3, P1.5-tool **livrés et testés** (branche `feat/phase-b-augmentee`). P1.4 (ré-ingestion) + P1.2-Qwen + P1.5-bench en attente EC2 Burst.

### 11.1 P1.3 — pont claim-centric (raffinement vs §3.2)
Le matching exact étape↔claim entre deux extractions LLM indépendantes est fragile. Décision retenue (robuste) :
- **Séquence ordonnée autoritative** = nodes `:ProcedureStep` (réutilise ProcedurePersister v6 tel quel, aucun matching requis pour l'ordre).
- **Points d'entrée retrievables** = claims PROCEDURAL existants reliés à la `:Procedure` par recouvrement lexical (token Jaccard, seuil lenient 0.18) → set `procedure_id`/`procedure_role`/`step_index` + relation `STEP_OF`.
- `PREREQUISITE_OF` : chaîne entre claims-étapes consécutifs (par step_index).
- `HAS_OUTCOME` : claim décrivant le goal (best-effort).
Module : `claimfirst/v6/procedure_linker.py`. Orchestrator Phase 6.7 (toggle `V6_PROCEDURE_EXTRACTION`, off défaut) + Phase 7.6 (persistance).
Smoke DeepSeek-V3.1 (3 sections multi-corpus) : 3 procédures, 11 STEP_OF, 8 PREREQUISITE_OF, 1 HAS_OUTCOME.

### 11.2 P1.5-tool — procedure_chain en side-effect (pas un tool Plan)
Plutôt qu'un nouveau tool nécessitant un routing Plan, le `procedure_chain` est un **side-effect post-retrieval** (pattern `_attach_conflict_pendings`) : pour tout claim retrouvé avec `procedure_id`, charge la `:Procedure` + séquence ordonnée + prérequis et l'expose à Synthesize. Activation automatique, zéro changement de routing. Toggle `V6_PROCEDURE_CHAIN` (off défaut). Fichiers : `runtime_a3/execute.py` (`CYPHER_PROCEDURE_CHAIN`, `_attach_procedure_chains`), `schemas.py` (`ProcedureChainSummary`), `synthesize.py` (payload + guidance prompt).

### 11.3 Point ouvert — LLM d'extraction procédures vs EC2
`ProcedureExtractor` appelle DeepInfra/Together en direct (pas le router burst). Pour la ré-ingestion EC2, le volume procédures (~1 appel/section procédurale) est marginal vs l'extraction de claims. **Option 1 recommandée** : laisser les procédures sur DeepInfra. Voir `doc/ongoing/P1_4_REINGESTION_RUNBOOK.md` §3.

---

*ADR produit le 2026-05-25. Audit pipeline via agent Explore. Validé par Fred. §11 ajouté post-implémentation P1.1-P1.5-tool.*

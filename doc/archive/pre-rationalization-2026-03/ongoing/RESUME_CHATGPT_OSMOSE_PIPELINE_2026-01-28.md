# OSMOSE Pipeline V2 - Situation Complète pour Collaboration

**Date:** 2026-01-28
**Projet:** OSMOSE (Organic Semantic Memory Organization & Smart Extraction)
**Objectif:** Pipeline d'extraction de connaissances structurées depuis des documents SAP

---

## 1. Architecture du Pipeline

### Vue d'Ensemble

Le Pipeline V2 "Stratified" extrait des connaissances structurées de documents techniques SAP en 3 passes :

```
Document PDF/PPTX
    ↓
Pass 0: Persistence (cache v5)
    ↓ DocItems (sections, texte, images)
Pass 1: Extraction Stratifiée
    ├── 1.1 Document Analysis (sujet, thèmes, langue)
    ├── 1.2 Concept Identification (concepts avec lexical_triggers par thème)
    ├── 1.3 Assertion Extraction (Pointer-Based, anti-reformulation)
    └── 1.4 Semantic Linking (LLM + rerank "Specificity Wins")
    ↓
Pass 2: Enrichissement (promotion assertions → Information)
    ↓
Neo4j Graph (Theme → Concept → Information)
```

### Modèle de Données Neo4j

```
(:Theme) -[:HAS_CONCEPT]→ (:Concept {role, lexical_triggers[]})
(:Concept) -[:HAS_INFORMATION]→ (:Information {text})
(:AssertionLog) - Log de toutes les assertions extraites
(:InformationMVP) - Assertions promues en Information
```

---

## 2. Infrastructure LLM

### Mode Normal
- **Modèle :** gpt-4o-mini (OpenAI)
- **Temperature :** 0.2
- **max_tokens :** 4000

### Mode Burst (EC2 Spot)
- **Modèle :** Qwen2.5-14B-Instruct-AWQ (quantifié AWQ)
- **Runtime :** vLLM v0.6.6.post1 sur GPU L4 24GB
- **CloudFormation :** burst-spot.yaml, instances g6.2xlarge/g6.xlarge
- **max_model_len :** 8192 tokens (TOTAL input + output)
- **Activation :** Via Redis key `osmose:burst:state` + routing automatique dans `llm_router.py`

### Routing (llm_router.py)

```python
# Contexte vLLM (lignes 1140-1143)
VLLM_MAX_CONTEXT = 8192   # max_model_len du modèle
SAFETY_MARGIN = 0.20       # 20% marge car estimation tokens imprécise
max_input_tokens = int((VLLM_MAX_CONTEXT - max_tokens) * (1 - SAFETY_MARGIN))
max_input_tokens = max(1000, min(max_input_tokens, 4000))  # Cap à 4000
```

Le router detecte le burst via Redis, puis redirige tous les appels `knowledge_extraction` vers vLLM au lieu d'OpenAI.

---

## 3. Prompts Utilisés (Pass 1)

### 3.1 Document Analysis (Pass 1.1)

```
System: You are a document analysis expert for OSMOSE.
Analyze the document and determine:
1. Its main SUBJECT (1 concise sentence)
2. Its dependency STRUCTURE: CENTRAL | TRANSVERSAL | CONTEXTUAL
3. Its major THEMES (5-8 maximum)
4. The document LANGUAGE (fr, en, de)

CRITICAL RULES:
- Be FRUGAL: maximum 8 themes
- LANGUAGE DETECTION: Analyze content to determine language
- THEMES MUST BE IN THE DOCUMENT'S LANGUAGE

User: Analyze this document:
TITLE: {doc_title}
TABLE OF CONTENTS: {toc}
CONTENT (first {char_limit} characters): {content_preview}

→ Output JSON: {subject_name, subject, structure, themes[], language}
```

### 3.2 Concept Identification by Theme (Pass 1.2)

```
System: Expert concept extraction for OSMOSE knowledge system.
You are extracting concepts for ONE SPECIFIC THEME only.

CONCEPT NAMING RULES:
- Use 2-5 descriptive words
- Use the DOCUMENT'S LANGUAGE
- Be SPECIFIC, not generic

CRITICAL RULE - LEXICAL TRIGGERS (C1):
Each concept MUST have exactly 3 "lexical_triggers" that:
1. ACTUALLY APPEAR VERBATIM in the document content (SAME LANGUAGE!)
2. Are NOT in the FORBIDDEN_TRIGGERS list
3. Are COPIED from the document text (NO translation, NO paraphrasing)
4. Include at least ONE discriminant trigger:
   - Technical acronym (TLS, MFA, KMS, BYOK, HSM, SLA, RTO, RPO)
   - Product name (SAProuter, Fiori, S/4HANA, BTP)
   - Specific term (whitelisting, failover, provisioning)
   - OR a composite trigger in snake_case ("sap_cloud_erp_private")

COMPOSITE TRIGGERS: multi-word proper nouns → snake_case token
Example: "SAP Cloud ERP Private" → trigger "sap_cloud_erp_private"

FORBIDDEN: Do NOT use theme words alone as triggers.

ROLES:
- CENTRAL: Core mechanism/product of this theme (1-2 per theme)
- STANDARD: Important related concepts (majority)
- CONTEXTUAL: Supporting technical context

User: Extract concepts for theme "{theme_name}" from this document.
DOCUMENT SUBJECT: {subject}
LANGUAGE: {language}
MAX CONCEPTS: {max_concepts_per_theme}
FORBIDDEN TRIGGERS: {forbidden_triggers}
CONTENT RELEVANT TO THIS THEME: {theme_content}

→ Output JSON: {concepts: [{name, role, lexical_triggers}], refused_terms}
```

**Budget Adaptatif :**
```python
CONCEPT_BUDGET_MIN = 20
CONCEPT_BUDGET_MAX = 60
budget = clamp(20, 60, 15 + sqrt(sections) * 3)
```

### 3.3 Assertion Extraction (Pass 1.3)

```
System: You are an assertion extraction expert for OSMOSE.
An ASSERTION is a sentence or text segment that carries KNOWLEDGE.

ASSERTION TYPES:
- definitional, prescriptive, factual, permissive,
  conditional, causal, procedural, comparative

User: Extract assertions from this text.
CHUNK_ID: {chunk_id}
EXPECTED LANGUAGE: {language_hint}
TEXT: {text}

→ Output JSON: {assertions: [{text, type, start_char, end_char, confidence, language}]}
```

### 3.4 Pointer-Based Extraction (Pass 1.3 - Anti-Reformulation)

Le texte est divisé en unités numérotées (U1, U2...) et le LLM **pointe** vers l'unité au lieu de copier le texte. Cela empêche le LLM de reformuler les assertions.

```
System: POINTER-BASED METHOD
Text is split into numbered units (U1, U2, U3...).
You must POINT to the unit containing the concept, NOT copy the text.

CRITICAL RULES:
1. Return ONLY the unit number, NEVER the text
2. The LABEL must contain AT LEAST 2 WORDS present in the unit text
3. DO NOT invent abstract labels like "security requirement"
4. USE exact words from the text

User: Extract concepts from text with numbered units.
DOCITEM_ID: {docitem_id}
LANGUAGE: {language}
TEXT WITH UNITS: {units_text}

→ Output JSON: {concepts: [{label, type, unit_id, confidence}]}
```

### 3.5 Semantic Linking (Pass 1.4)

```
System: You are a semantic reasoning expert for OSMOSE.
Determine which ASSERTIONS provide knowledge about which CONCEPTS.

IMPORTANT: An assertion can relate to MULTIPLE concepts (1-5)!

This is NOT lexical matching:
- An assertion can relate to a concept WITHOUT mentioning it explicitly
- A French concept can be linked to an English assertion
- The link must be SEMANTIC (based on meaning)

LINK TYPES: defines, describes, constrains, enables, conditions, causes

RULE C3 - Avoid "spray & pray":
- Maximum 5 concepts per assertion
- Only link if confidence >= 0.70
- Justify each link precisely

User: Establish semantic links between these assertions and concepts.
ASSERTIONS: {assertions}
CONCEPTS: {concepts}

→ Output JSON: {links: [{assertion_id, concept_links: [{concept_id, link_type, justification, confidence}]}]}
```

---

## 4. Système de Rerank "Specificity Wins"

### Problème Résolu : "Concept Aspirateur"

Les concepts génériques (ex: "Infrastructure Security") capturaient toutes les informations, laissant les concepts spécifiques vides.

**Avant fix (avec gpt-4o-mini) :**
| Concept | Infos |
|---------|-------|
| Infrastructure Security | 68 |
| Access Controls | 34 |
| Business Continuity Management | 0 |
| Patch Management | 0 |
| Monitoring & Alerting | 0 |

### Algorithme de Rerank

Après le linking LLM, un post-traitement ajuste les scores de confiance :

```
Score_final = conf_llm × bonus_lexical × bonus_central × penalty_saturante
```

**Fichier :** `src/knowbase/stratified/pass1/assertion_extractor.py`

#### Module A - Snapshot Gelé (anti ordre-dépendance)

Les counts de chaque concept sont gelés au début du Pass 1.4, avant tous les batches :

```python
self._concept_info_snapshot = {c.concept_id: 0 for c in concepts}
self._total_assertions_count = total_assertions
```

#### Module B - Bonus Lexical

```python
def _compute_lexical_bonus(assertion_text, concept) -> float:
    # Priorité 1: Match sur lexical_triggers du concept
    for trigger in concept.lexical_triggers:
        if re.search(rf'\b{re.escape(trigger)}\b', assertion_text, re.I):
            return 1.25  # Match trigger = bonus fort

    # Priorité 2: Tokens du nom du concept (>= 4 chars)
    overlap = concept_tokens & assertion_tokens
    if overlap:
        return 1.20 if has_long_token else 1.10

    return 1.0  # Pas de match
```

#### Module B - Pénalité Saturante

```python
def _saturating_penalty(info_count, concept, lexical_bonus) -> float:
    N = total_assertions  # Gelé
    start = max(10, int(0.20 * N))  # Seuil début pénalité
    end = max(start + 10, int(0.50 * N))  # Seuil pénalité max

    if info_count <= start:
        return 1.0           # Pas de pénalité
    elif info_count <= end:
        return 1.0 - 0.2 * ratio  # Linéaire → 0.8
    else:
        return 0.8           # Plafonné

    # Micro-ajustement: -5% si CONTEXTUAL + pas de match lexical
```

#### Module B - Top-K Dynamique + Double Seuil

```python
# Constantes actuelles
CONF_THRESHOLD_ORIGINAL = 0.45  # Min conf LLM pour être éligible
CONF_THRESHOLD_FINAL = 0.35     # Min conf après rerank
MARGIN_AMBIGUOUS = 0.05         # Détection ambiguïté
TOP_K_DEFAULT = 2               # Max concepts par assertion
TOP_K_STRONG_MATCH = 1          # Winner-takes-all si match trigger fort
```

---

## 5. Résultats Actuels (Neo4j - Run avec Qwen)

### Test sur le document "RISE with SAP Cloud ERP Private - Security"

#### Statistiques Globales

| Métrique | Valeur |
|----------|--------|
| Themes | 6 |
| Concepts | 38 (tous CONTEXTUAL) |
| Information (liées) | 12 |
| InformationMVP | 183 |
| AssertionLog | 392 |
| Relations concept→info | 34 |

#### Distribution par Thème

| Thème | Concepts | Informations |
|-------|----------|--------------|
| Security Operations | ~8 | 5 |
| Deployment Models | ~8 | 4 |
| Tenancy Model Shared Security Responsibility | ~6 | 3 |
| Patch Management | ~5 | 0 |
| End Point Protection | ~5 | 0 |
| Capacity Management | ~6 | 0 |

**3 thèmes sur 6 (50%) sont entièrement vides !**

#### Top Concepts avec Informations

| Concept | Infos |
|---------|-------|
| TLS 1.2 Encryption | 4 |
| SAP ECS Unified Approach | 2 |
| Customer Subnet Isolation | 1 |
| Admin Access CGS VPN | 1 |
| Security Patch Management SPM | 1 |
| AWS Direct Connect SAP | 1 |
| HANA Volume Encryption | 1 |
| Customer Traffic Validation | 1 |

#### Exemples d'Informations Extraites (12 sur 392 assertions)

```
1. "All internet accesses must be encrypted in transit (via TLS)"
   → TLS 1.2 Encryption (conf: 0.57)

2. "SAP has unified the approach for all cloud solutions with DPA"
   → SAP ECS Unified Approach (conf: 0.57)

3. "Each customer is isolated from the SAP Corporate Network"
   → Customer Subnet Isolation (conf: 0.57)

4. "Admin access from CGS is via redundant IPsec VPN to Admin VPCs in AWS"
   → Admin Access CGS VPN (conf: 0.57)

5. "The purpose of Security Patch Management (SPM) is the mitigation..."
   → Security Patch Management SPM (conf: 0.57)
```

### Comparaison Qwen vs gpt-4o-mini

| Métrique | gpt-4o-mini (run précédent) | Qwen2.5-14B (run actuel) |
|----------|----------------------------|--------------------------|
| Concepts | 37 | 38 |
| Informations liées | 32 | 12 |
| Rôles concept | CENTRAL + STANDARD + CONTEXTUAL | 100% CONTEXTUAL |
| Confidences LLM | 0.70 - 0.95 (granulaire) | ~0.60 uniforme |
| Triggers langue | FR (bug corrigé) | EN (correct) |

---

## 6. Problèmes Identifiés

### Problème 1 : Qwen produit des confidences uniformes (~0.60)

**Symptôme :** Toutes les confidences de linking retournées par Qwen sont ~0.60, sans granularité.

**Impact :** Le rerank ne peut pas différencier les bons liens des mauvais. Tous les liens passent le seuil (ou aucun si seuil trop haut).

**Logs typiques :**
```
[OSMOSE:Rerank] assert_abc → concept_tls: conf 0.60 → 0.57 (lex=1.00, central=1.00, penalty=0.95)
[OSMOSE:Rerank] assert_abc → concept_infra: conf 0.60 → 0.57 (lex=1.00, central=1.00, penalty=0.95)
```

**Observation :** Le bonus lexical est toujours 1.00 (pas de match trigger). Cela signifie que les triggers des concepts ne se retrouvent pas dans le texte des assertions.

### Problème 2 : Aucun concept CENTRAL ou STANDARD

Qwen attribue le rôle CONTEXTUAL à tous les concepts. Cela désactive le bonus_central du rerank (+10% pour CENTRAL).

### Problème 3 : 12 informations au lieu de 32

Le pipeline perd ~60% des informations par rapport à gpt-4o-mini. Causes probables :
- Confidences uniformes à 0.60 → beaucoup de liens éliminés
- Pas de match lexical (triggers mal formés ou non verbatim)
- Pas de rôles CENTRAL/STANDARD

### Problème 4 : Triggers potentiellement non-verbatim

Les triggers devraient être des tokens copiés du document. Si Qwen invente des triggers au lieu de les copier, le bonus lexical ne pourra jamais s'activer.

### Problème 5 : Context overflow (RÉSOLU)

`VLLM_MAX_CONTEXT` était 16384 dans le code mais le modèle a `max_model_len=8192`. Corrigé à 8192.

### Problème 6 : Seuils de confiance (RÉSOLU)

`CONF_THRESHOLD_ORIGINAL` était 0.65, trop haut pour Qwen qui retourne ~0.60. Abaissé à 0.45.

---

## 7. Historique des Fixes Appliqués (28 janvier 2026)

### Fix 1 : Context overflow vLLM
- **Fichier :** `src/knowbase/common/llm_router.py` (sync + async)
- **Changement :** `VLLM_MAX_CONTEXT: 16384 → 8192`, `SAFETY_MARGIN: 0.30 → 0.20`, cap `8000 → 4000`
- **Impact :** Qwen ne retourne plus des réponses de 13 tokens

### Fix 2 : max_tokens concept identification
- **Fichier :** `src/knowbase/stratified/pass1/concept_identifier.py`
- **Changement :** `max_tokens: 8000 → 4000`
- **Impact :** Laisse assez de place pour l'input dans le contexte 8192

### Fix 3 : Seuils de confiance pour Qwen
- **Fichier :** `src/knowbase/stratified/pass1/assertion_extractor.py`
- **Changement :** `CONF_THRESHOLD_ORIGINAL: 0.65 → 0.45`, `CONF_THRESHOLD_FINAL: 0.45 → 0.35`
- **Impact :** 216 liens bruts → 12 informations (au lieu de 3 avec anciens seuils)

### Fix 4 : Triggers en anglais (session précédente)
- **Fichier :** `src/knowbase/stratified/prompts/pass1_prompts.yaml`
- **Changement :** Instructions explicites pour triggers dans la langue du document
- **Impact :** Triggers maintenant en anglais pour documents anglais

---

## 8. Prochaines Étapes à Explorer

### Sprint 2 prévu : Enrichir le prompt LLM avec buckets de couverture

L'idée est d'ajouter un indicateur visuel dans le prompt de linking pour guider le LLM :

```python
def _format_concepts_for_prompt(concepts):
    for c in concepts:
        bucket = coverage_bucket(info_count)  # "EMPTY", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"
        lines.append(f"- {c.concept_id}: {c.name} ({c.role}) [{bucket}]")
```

Avec instruction dans le prompt :
```
SPECIFICITY PREFERENCE:
- When multiple concepts match, prefer the MOST SPECIFIC one
- Concepts marked [EMPTY] or [LOW] need content - prioritize them if relevant
- Avoid over-linking to [VERY_HIGH] concepts
```

### Questions Ouvertes

1. **Comment forcer Qwen à produire des confidences plus granulaires ?** (ex: calibration prompt, temperature, exemples few-shot)
2. **Comment améliorer le match des triggers ?** (triggers mal formés, pas verbatim)
3. **Faut-il un prompt différent pour Qwen vs gpt-4o-mini ?** (modèles open-source vs propriétaires)
4. **Approche hybride ?** Qwen pour extraction (volume), gpt-4o-mini pour linking (qualité)
5. **Comment forcer les rôles CENTRAL/STANDARD ?** Qwen met tout en CONTEXTUAL

---

## 9. Code Source Clé

### Fichiers principaux

| Fichier | Rôle |
|---------|------|
| `src/knowbase/stratified/pass1/concept_identifier.py` | Pass 1.2 - Identification concepts |
| `src/knowbase/stratified/pass1/assertion_extractor.py` | Pass 1.3 + 1.4 - Extraction + Linking + Rerank |
| `src/knowbase/stratified/prompts/pass1_prompts.yaml` | Tous les prompts LLM du Pass 1 |
| `src/knowbase/common/llm_router.py` | Routing LLM (OpenAI/Anthropic/vLLM burst) |
| `src/knowbase/stratified/governance/theme_lint.py` | Post-import: détection thèmes vides |
| `src/knowbase/ingestion/burst/cloudformation/burst-spot.yaml` | CloudFormation EC2 Spot vLLM |
| `config/llm_models.yaml` | Configuration modèles par tâche |
| `config/feature_flags.yaml` | Feature flags pipeline |

### Classes principales

```python
# concept_identifier.py
class ConceptIdentifierV2:
    def identify_concepts_by_theme(themes, content, language) -> List[Concept]
    # Budget adaptatif: clamp(20, 60, 15 + sqrt(sections) * 3)

# assertion_extractor.py
class AssertionExtractorV2:
    def extract_assertions(chunks, doc_language) -> List[RawAssertion]
    def link_to_concepts(assertions, concepts) -> List[ConceptLink]
    # Rerank "Specificity Wins":
    def _freeze_concept_counts(concepts, total_assertions)
    def _rerank_links_specificity(links, concepts, assertions) -> (links, bonuses)
    def _apply_margin_and_topk(links, bonuses) -> links
    def _compute_lexical_bonus(text, concept) -> float  # 1.0, 1.10, 1.20, 1.25
    def _saturating_penalty(count, concept, bonus) -> float  # [0.8, 1.0]
```

---

## 10. Politique de Promotion des Assertions

Les assertions extraites sont filtrées avant d'être promues en Information :

| Type d'Assertion | Politique | Condition |
|-----------------|-----------|-----------|
| DEFINITIONAL | ALWAYS | Toujours promouvoir si lié |
| PRESCRIPTIVE | ALWAYS | Toujours promouvoir si lié |
| CAUSAL | ALWAYS | Toujours promouvoir si lié |
| FACTUAL | CONDITIONAL | Si confiance >= 0.7 |
| CONDITIONAL | CONDITIONAL | Si confiance >= 0.7 |
| PERMISSIVE | CONDITIONAL | Si confiance >= 0.7 |
| COMPARATIVE | RARELY | Si confiance >= 0.9 |
| PROCEDURAL | NEVER | Jamais promouvoir |

**Feature flag :** `strict_promotion: false` → Les CONDITIONAL sont aussi promus si conf >= 0.7.

---

## 11. Validation Verbatim (Volet A)

Le pipeline inclut un système anti-reformulation :

```python
def extract_and_validate_assertions(chunks, doc_language):
    # 1. Extraction LLM
    all_assertions = extract_assertions(chunks, doc_language)
    # 2. Validation: chaque assertion DOIT être un substring du texte source
    valid, abstained, stats = validate_raw_assertions(all_assertions, chunks)
    # 3. Log si taux de reformulation > 10%
```

Ce système détecte quand le LLM reformule au lieu de copier le texte exact. Les assertions reformulées sont rejetées (ABSTAIN).

---

*Document généré le 2026-01-28 pour collaboration ChatGPT*

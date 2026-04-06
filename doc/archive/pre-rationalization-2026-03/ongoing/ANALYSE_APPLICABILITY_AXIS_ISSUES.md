# Analyse : Problèmes d'identification de version dans ApplicabilityAxis

## Contexte

Le pipeline OSMOSE ClaimFirst extrait des claims (assertions factuelles) à partir de documents SAP techniques. Chaque document passe par un **ApplicabilityFrame** qui identifie à quelle version/release du produit le document s'applique. Ces informations sont persistées dans Neo4j sous forme de nœuds `ApplicabilityAxis` reliés aux `DocumentContext` par des relations `HAS_AXIS_VALUE`.

**Objectif** : pour un corpus de documents SAP S/4HANA couvrant les releases 1809, 2021, 2022, 2023 et 2025, obtenir un axe `release_id` propre avec des valeurs normalisées (`"1809"`, `"2021"`, `"2022"`, `"2023"`, `"2025"`) permettant ensuite de filtrer et comparer les claims par version.

## Architecture complète du pipeline (phases séquentielles)

Le traitement d'un document suit ces phases :

```
Phase 0.5 — ContextExtractor (1er appel LLM)
  → Envoie titre + TOC + échantillon du contenu au LLM (DocumentAnalyzerV2)
  → Extrait : sujet principal, thèmes, type de document
  → Résultat : DocumentContext (ex: subject="Operations Guide for SAP S/4HANA 2021")
  → ⚠️ La version est présente dans le sujet textuel mais N'EST PAS extraite
    comme donnée structurée à ce stade

Phase 0.55 — SubjectResolverV2 (2ème appel LLM)
  → Envoie titre + headers + contexte au LLM
  → Le LLM doit classifier les éléments en : COMPARABLE_SUBJECT, AXIS_VALUE, DOC_TYPE, NOISE
  → Pour les AXIS_VALUE : attribue un discriminating_role (temporal, revision, status, etc.)
  → Résultat : axis_values (ex: [("1809", "revision")]) transmises comme "priors" à la phase suivante
  → ⚠️ Pas de json_schema enforced → le LLM peut renvoyer un format incorrect
  → ⚠️ Rate la détection dans 33% des cas (docs 003, 005, 025)

Phase 0.6 — ApplicabilityFrame Pipeline (Layers A→B→C→D)

  Layer A: EvidenceUnit Segmenter
    → Découpe le document en unités d'evidence numérotées (EU:0:0, EU:1:0, ...)

  Layer B: CandidateProfile Miner (regex uniquement, pas de LLM)
    → Scanne TOUTES les unités avec des regex pour détecter des candidats :
      - named_version: "Version X", "Release X", "Edition X", "FPS X", "SP X"
      - version: patterns numériques (v1.0, 2.1.3)
      - numeric_identifier: années isolées (2023, 2021)
      - date: dates ISO
    → Produit un CandidateProfile avec des ValueCandidate (type, raw_value, fréquence, positions)
    → ⚠️ Capture les named_version AVEC le préfixe : raw_value = "Edition 2025", pas "2025"

  Layer C: FrameBuilder (3ème appel LLM)
    → Reçoit le CandidateProfile + les priors du SubjectResolver
    → Envoie un prompt LLM demandant de sélectionner les bons candidats et leur rôle sémantique
    → Le LLM doit retourner un JSON structuré :
      {"fields": [{"field_name": "release_id", "value_normalized": "<raw_value d'un candidat>", ...}]}
    → Contrainte forte : value_normalized DOIT être la raw_value EXACTE d'un candidat existant
    → Si parsing LLM échoue → fallback déterministe
    → Validation par AuthorityContract (cross-check avec les priors du SubjectResolver)
    → ⚠️ Pas de json_schema enforced → le LLM peut renvoyer un format incorrect (33% d'échec)
    → ⚠️ La validation rejette les valeurs normalisées par le LLM ("1809") si la raw_value
      du candidat est "Release 1809"

  Layer D: Frame Adapter
    → Convertit le Frame en ApplicabilityAxis (modèle Pydantic) et persiste dans Neo4j
    → La valeur persistée dans Neo4j (scalar_value) = value_normalized du FrameField
    → ⚠️ Aucune normalisation n'est appliquée à ce stade
```

### Point clé : 3 appels LLM, aucun avec contrat JSON enforced

| Phase | Appel LLM | Ce qu'il détecte | json_schema enforced ? |
|-------|-----------|-----------------|----------------------|
| 0.5 — ContextExtractor | DocumentAnalyzerV2 | Sujet principal, thèmes, type | **NON** |
| 0.55 — SubjectResolverV2 | Classification candidates | axis_values (version, revision) | **NON** |
| 0.6 — FrameBuilder | Sélection + rôle sémantique | release_id, publication_year | **NON** |

**Or, le mécanisme de structured output existe dans le code et est prêt à l'emploi.**

Le `llm_router.py` supporte déjà nativement les structured outputs via le paramètre `json_schema` :

```python
# Dans llm_router.py (lignes 1198-1211) — mécanisme EXISTANT mais INUTILISÉ
json_schema = kwargs.get('json_schema') or kwargs.get('guided_json')
if json_schema and any(x in self._burst_model.lower() for x in ['qwen', 'mistral']):
    api_kwargs['response_format'] = {
        "type": "json_schema",
        "json_schema": {
            "name": task_type.value,
            "strict": True,
            "schema": json_schema
        }
    }
```

vLLM v0.9.2 avec Qwen3-14B-AWQ supporte `response_format: {"type": "json_schema", "strict": true}` qui **garantit** que la sortie est un JSON valide conforme au schéma spécifié. C'est un constraint-based decoding — le modèle ne peut physiquement pas produire de tokens qui violeraient le schéma.

**Aucun des 3 appels LLM du pipeline ApplicabilityFrame ne passe `json_schema=...` dans ses kwargs.** C'est la cause racine directe du Problème 2 (JSON malformé dans 33% des cas).

## État actuel observé (import de 12 documents SAP)

### Inventaire des axes dans Neo4j

| Axe | axis_key | known_values | is_orderable |
|-----|----------|-------------|-------------|
| named_version | `release_id` | `["release S4CORE", "Release 1809", "Edition 2025", "Edition 2023", "1809"]` | **FALSE** |
| Year | `publication_year` | `["2023", "2022", "2021", "2014", "2013", "1918", "2018", "2017", "2019", "2016"]` | TRUE |
| status | `lifecycle_status` | `["2023-10-11"]` | FALSE |

### Mapping document → axis values

| Doc ID | Titre (simplifié) | Version attendue | release_id détecté | publication_year | lifecycle_status |
|--------|-------------------|-----------------|-------------------|-----------------|-----------------|
| 003 | Upgrade Guide **2023** | 2023 | ❌ aucun | — | — |
| 004 | Highlights Innovations **(2023 FPS03)** | 2023 | "Edition 2023" | — | — |
| 005 | Conversion Guide **2022** | 2022 | ❌ aucun | — | — |
| 006 | Conversion Guide **2023** | 2023 | "Edition 2023" | — | — |
| 007 | Access to Customer Systems | aucune | ❌ aucun | — | — |
| 008 | Upgrade Guide PCE **2025** | 2025 | "Edition 2025" | — | — |
| 010 | Conversion Guide PCE **2025** | 2025 | "Edition 2025" | — | — |
| 014 | Operations Guide **2021** | 2021 | ⚠️ "release S4CORE" | — | — |
| 018 | Business Scope **1809** | 1809 | "1809" | ⚠️ "2022" | — |
| 020 | RISE with SAP Cloud ERP | aucune | — | ⚠️ "1918" | ⚠️ "2023-10-11" |
| 023 | Business Scope PCE **2025** | 2025 | "Edition 2025" | — | — |
| 025 | Feature Scope **2023** | 2023 | ❌ aucun | — | — |

**Bilan** : sur 10 documents avec une version identifiable, **4 n'ont aucun release_id** (40%), **1 a une valeur incorrecte** ("release S4CORE" au lieu de "2021"), et **5 ont une valeur correcte mais non normalisée** ("Edition 2025" au lieu de "2025").

## Problèmes identifiés

### Problème 1 : Pas de normalisation des valeurs `release_id`

**Symptôme** : Les valeurs stockées sont `"Edition 2025"`, `"Edition 2023"`, `"Release 1809"`, `"release S4CORE"` au lieu de simplement `"2025"`, `"2023"`, `"1809"`, `"2021"`.

**Cause racine** : Le `CandidateProfile Miner` (Layer B) capture les `named_version` avec le préfixe inclus : `NAMED_VERSION_PATTERN = r"\b((?:Version|Release|Edition|Phase|FPS|SP)\s+(?=\S*\d)\S+)"`. Le `raw_value` est donc `"Edition 2025"`, pas `"2025"`. Ensuite, le FrameBuilder exige que le LLM retourne une `value_normalized` identique au `raw_value` d'un candidat. Et le Frame Adapter persiste `value_normalized` tel quel dans Neo4j.

**Impact** : L'axe `release_id` a `is_orderable: FALSE` car les valeurs ne sont pas comparables. Impossible de trier les documents par release ou de détecter "la version la plus récente". Les valeurs sont un mélange de formats (`"Edition 2025"` vs `"1809"`) rendant toute comparaison impossible.

**Où le fix devrait intervenir** : Soit dans le CandidateMiner (extraire juste le numéro), soit dans le FrameAdapter (normaliser avant persistence), soit dans le modèle ApplicabilityAxis (normalisation au `add_value()`). Le plus propre serait probablement dans le FrameAdapter (Layer D) car c'est la couche de traduction vers le modèle persisté.

### Problème 2 : Le LLM renvoie un JSON malformé → fallback déterministe défaillant

**Symptôme** : Pour les docs 014 (Operations Guide 2021) et 025 (Feature Scope 2023), le LLM renvoie :
```json
{
  "field_name": "release_id",
  "reasoning": "The numeric identifier '2021' appears with the marker..."
}
```
au lieu du format attendu :
```json
{
  "fields": [
    {"field_name": "release_id", "value_normalized": "...", ...}
  ]
}
```

**Cause racine** : Le LLM (Qwen3-14B-AWQ) ne respecte pas toujours le schéma JSON demandé. Il renvoie un objet plat au lieu d'un objet avec un tableau `fields`. Le parser cherche `data.get("fields", [])` et ne trouve rien → frame vide → fallback déterministe.

**Observation importante** : Le LLM *comprend* le problème (il identifie correctement "2021" comme release_id dans son reasoning) mais il *formate mal* sa réponse. C'est un problème de format, pas de compréhension.

**Solution disponible mais non utilisée** : Le `llm_router.py` supporte déjà `json_schema` pour le structured output via vLLM. Ce mécanisme utilise le constraint-based decoding de vLLM qui **garantit** un JSON conforme au schéma. Il suffirait de passer `json_schema={...}` dans l'appel LLM du FrameBuilder pour éliminer 100% des erreurs de format.

**Conséquence du fallback** : Le fallback déterministe pour le doc 014 produit `"release S4CORE"` (probablement le premier `named_version` trouvé dans le texte, qui n'est pas la release du document). Pour les docs 003, 005 et 025, le fallback ne trouve rien du tout → aucun axis.

**Impact** : 4 documents sur 12 (33%) n'ont pas de `release_id` ou ont une valeur incorrecte.

### Problème 3 : Le FrameBuilder rejette des valeurs valides ("invented value not in candidates")

**Symptôme** : Pour le doc 018 (Business Scope 1809), le SubjectResolver détecte correctement `('1809', 'revision')` et l'envoie comme prior confirmé. Mais le FrameBuilder log : `LLM invented value '1809' not in candidates — skipping`.

**Cause racine** : Le LLM retourne `value_normalized: "1809"` mais la vérification `value.lower() not in valid_raw_values` échoue parce que dans le CandidateProfile, la `raw_value` du candidat est `"Release 1809"` (capturée par `NAMED_VERSION_PATTERN`), pas `"1809"`. Le LLM normalise intelligemment en `"1809"` mais le validator rejette car cette forme exacte n'est pas dans les candidats.

**Impact** : Le LLM a la bonne réponse mais le pipeline la refuse. C'est une friction directe entre le Problème 1 (raw_value avec préfixe) et la validation stricte. Le LLM fait le bon travail de normalisation mais le pipeline l'empêche.

### Problème 4 : Axes parasites (`publication_year`, `lifecycle_status`)

**Symptômes** :
- Doc 020 (RISE with SAP Cloud ERP) : `publication_year: "1918"` — c'est probablement un numéro de note SAP (ex: "SAP Note 1918xxx") détecté comme année
- Doc 020 : `lifecycle_status: "2023-10-11"` — une date ISO traitée comme statut de lifecycle
- Doc 018 : `publication_year: "2022"` — le document est sur la release 1809, pas 2022. La date 2022 est probablement la date de publication du PDF

**Cause racine** : Le CandidateMiner capture trop largement les années et dates dans le corps du document. Le LLM assigne ensuite des rôles sémantiques incorrects à ces faux candidats. Il n'y a pas de filtre de bon sens (une année < 1990 ne peut pas être une publication_year pour un document SAP).

**Impact** : Axes bruités avec des valeurs parasites. L'axe `publication_year` contient 10 valeurs dont au moins une aberrante (`1918`), diluant la qualité.

### Problème 5 : 4 documents sans aucun axis (33% du corpus)

**Documents concernés** : 003 (Upgrade Guide 2023), 005 (Conversion Guide 2022), 007 (Access to Customer Systems), 025 (Feature Scope 2023).

Pour les docs 003, 005 et 025, la release est clairement dans le titre (`SAP S/4HANA 2023`, `SAP S/4HANA 2022`). Le fait qu'aucun axis ne soit détecté signifie :
1. Le SubjectResolverV2 (Phase 0.55) n'a pas détecté l'axis_value dans le titre → pas de prior envoyé
2. Le FrameBuilder (Phase 0.6) a échoué côté LLM (confirmé pour le 025 : JSON malformé)
3. Le fallback déterministe a aussi échoué (pas de candidat suffisamment fiable)

Le doc 007 n'a peut-être pas de version applicable — c'est potentiellement normal.

### Problème 6 (transversal) : Aucun appel LLM n'utilise le structured output disponible

**Symptôme** : Les 3 appels LLM du pipeline (ContextExtractor, SubjectResolverV2, FrameBuilder) font tous un appel "libre" sans contrainte de format. Le LLM peut retourner n'importe quel JSON (ou même du texte libre).

**Cause racine** : Le `llm_router.py` supporte nativement `json_schema` et `guided_json` comme paramètres pour activer le structured output de vLLM (constraint-based decoding). Mais aucun des appelants ne passe ces paramètres.

**Code existant dans llm_router.py (prêt à l'emploi)** :
```python
# Lignes 1198-1211 — mécanisme EXISTANT
json_schema = kwargs.get('json_schema') or kwargs.get('guided_json')
if json_schema:
    api_kwargs['response_format'] = {
        "type": "json_schema",
        "json_schema": {
            "name": task_type.value,
            "strict": True,
            "schema": json_schema
        }
    }
```

**Appels LLM dans le pipeline (aucun n'utilise json_schema)** :
```python
# FrameBuilder (frame_builder.py, ligne ~380)
response = router.complete(
    task_type=TaskType.METADATA_EXTRACTION,
    messages=messages,
    temperature=0.0,
    max_tokens=2000,
    # ← PAS de json_schema=...
)

# SubjectResolverV2 (subject_resolver_v2.py, ligne ~396)
response = router.complete(
    task_type=TaskType.KNOWLEDGE_EXTRACTION,
    messages=messages,
    temperature=0.1,
    max_tokens=2000,
    # ← PAS de json_schema=...
)
```

**Impact** : Le structured output garantirait que le LLM retourne toujours un JSON conforme au schéma attendu, éliminant 100% des erreurs de parsing (Problème 2). C'est la solution la plus directe et la plus fiable.

**Note** : vLLM + Qwen3 supporte le structured output. Le plan de migration Qwen3 avait identifié une incompatibilité entre thinking mode + JSON schema, mais le thinking est OFF par défaut — donc le structured output est utilisable sans risque pour les appels standard.

## Synthèse : chaîne de fragilités

Le pipeline souffre d'une **cascade de fragilités** où chaque couche amplifie les erreurs :

```
Phase 0.55 — SubjectResolver rate la version dans le titre (33% d'échec)
  → Pas de prior envoyé au FrameBuilder
    → FrameBuilder dépend entièrement du LLM

Phase 0.6 Layer B — CandidateMiner capture "Edition 2025" (pas "2025")
  → LLM reçoit "Edition 2025" comme candidat
    → LLM renvoie "2025" (normalisé) OU format JSON incorrect
      → Si "2025" : rejeté car "not in candidates" (raw_value = "Edition 2025")
      → Si JSON incorrect : fallback déterministe prend la raw_value brute
        → Neo4j stocke "Edition 2025" ou "release S4CORE"
          → Axe non orderable, valeurs incohérentes

Aucune couche n'utilise le structured output disponible
  → 33% des réponses LLM ont un format incorrect
    → Fallback déterministe produit des résultats incorrects ou vides
```

**Résultat net** : sur 10 documents avec une version clairement identifiable dans le titre, **seuls 5 ont un release_id utilisable** (50%), et même ceux-ci ne sont pas normalisés.

## Données techniques de référence

### Regex de capture (CandidateMiner)

```python
# Named versions — capture "Version X", "Release X", etc. AVEC le préfixe
NAMED_VERSION_PATTERN = re.compile(
    r"\b((?:Version|Release|Edition|Phase|FPS|SP)\s+(?=\S*\d)\S+)",
    re.IGNORECASE,
)

# Numeric versions — v1.0, 2.1.3
NUMERIC_VERSION_PATTERN = re.compile(...)

# Years — 4 chiffres isolés entre 1990 et 2039
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
```

### Format JSON attendu du LLM (FrameBuilder prompt)

```json
{
  "fields": [
    {
      "field_name": "<domain-specific role: release_id, publication_year, etc.>",
      "value_normalized": "<exact raw_value from a candidate>",
      "display_label": "<version|release|edition|generation|phase|etc.>",
      "evidence_unit_ids": ["EU:0:1", "EU:3:0"],
      "candidate_ids": ["VC:named_version:abc123"]
    }
  ]
}
```

### Validation dans _parse_llm_response (FrameBuilder)

```python
# Le LLM DOIT choisir une raw_value existante (matching exact, case-insensitive)
valid_raw_values = {vc.raw_value.lower() for vc in profile.value_candidates}
if value.lower() not in valid_raw_values:
    logger.debug(f"LLM invented value '{value}' not in candidates — skipping")
    continue
```

### Persistance dans Neo4j (FrameAdapter)

```python
doc_context.axis_values[field.field_name] = {
    "value_type": "scalar",
    "scalar_value": field.value_normalized,  # ← valeur brute, jamais normalisée
    ...
}
```

### Structured output (llm_router.py — existant, non utilisé)

```python
# Le mécanisme est implémenté et prêt :
response = router.complete(
    task_type=TaskType.METADATA_EXTRACTION,
    messages=messages,
    temperature=0.0,
    max_tokens=2000,
    json_schema={                              # ← Il suffit d'ajouter ce paramètre
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_name": {"type": "string"},
                        "value_normalized": {"type": "string"},
                        ...
                    },
                    "required": ["field_name", "value_normalized"]
                }
            }
        },
        "required": ["fields"]
    }
)
# → vLLM garantit un JSON conforme via constraint-based decoding
```

## Questions pour discussion

1. **Structured output** : Activer `json_schema` sur les 3 appels LLM du pipeline semble être le fix le plus impactant — ça élimine le Problème 2 (33% de JSON malformé). Faut-il le déployer sur les 3 appels ou seulement sur le FrameBuilder qui est le plus critique ?

2. **Normalisation** : Où extraire le numéro pur de "Edition 2025" → "2025" ? Options :
   - (a) CandidateMiner : stocker `raw_value="Edition 2025"` + `normalized_value="2025"` séparément
   - (b) FrameAdapter : normaliser `value_normalized` avant persistence (regex pour extraire le numérique)
   - (c) ApplicabilityAxis.add_value() : normaliser à l'ajout

3. **Validation candidats** : Le check strict `value not in raw_values` bloque les normalisations légitimes du LLM (Problème 3). Options :
   - (a) Match partiel (le numérique de la value est contenu dans un candidat)
   - (b) Ajouter automatiquement les formes normalisées aux `valid_raw_values`
   - (c) Laisser le structured output régler le problème si les candidats sont normalisés en amont

4. **SubjectResolver rate 33% des versions** : Pourquoi "SAP S/4HANA 2023 Upgrade Guide" ne produit-il pas `axis_value: ("2023", "revision")` ? Est-ce un problème de prompt ou de modèle ? Le structured output résoudrait-il aussi ce problème ?

5. **Axes parasites** : `"1918"` comme publication_year, `"2023-10-11"` comme lifecycle_status — quel filtrage ajouter ? Options :
   - (a) Filtre dans le CandidateMiner (exclure années < 1990)
   - (b) Filtre dans le FrameAdapter (validation de cohérence avant persistence)
   - (c) Laisser le structured output + un prompt amélioré résoudre via le LLM

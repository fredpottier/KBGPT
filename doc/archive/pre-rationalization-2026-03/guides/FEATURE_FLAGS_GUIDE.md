# Guide Feature Flags - OSMOSE

## Pourquoi des Feature Flags ?

Les feature flags permettent de **contrôler l'activation des fonctionnalités sans modifier le code**. Cela offre :

1. **Déploiement progressif** - Activer une feature, valider, puis passer à la suivante
2. **Rollback instantané** - Désactiver une feature problématique sans redéployer
3. **Tests A/B** - Comparer les métriques avant/après activation
4. **Configuration par client** - Chaque instance client a sa propre configuration

---

## Fichier de Configuration

**Emplacement :** `config/feature_flags.yaml`

### Structure

```yaml
phase_1_8:
  # Master switch - désactive TOUT Phase 1.8 si false
  enabled: true

  # Feature individuelle
  enable_hybrid_extraction: true

  # Feature avec paramètres
  enable_ontology_prefetch: true
  ontology_prefetch:
    ttl_seconds: 3600
    max_entries_per_domain: 500
```

---

## Comment Utiliser dans le Code

### 1. Importer le module

```python
from knowbase.config.feature_flags import is_feature_enabled, get_feature_config
```

### 2. Vérifier si une feature est active

```python
# Simple check booléen
if is_feature_enabled("enable_hybrid_extraction"):
    # Utiliser la nouvelle extraction hybride
    result = await hybrid_extraction(segment)
else:
    # Fallback sur l'ancienne méthode
    result = await legacy_extraction(segment)
```

### 3. Récupérer la configuration d'une feature

```python
# Récupérer les paramètres
prefetch_config = get_feature_config("ontology_prefetch")
ttl = prefetch_config.get("ttl_seconds", 3600)
max_entries = prefetch_config.get("max_entries_per_domain", 500)
```

---

## Architecture de Déploiement

**OSMOSE utilise une architecture "1 instance = 1 client"** :

```
Client Pharma     → Instance dédiée (Neo4j + Qdrant + App)
Client SAP        → Instance dédiée (Neo4j + Qdrant + App)
Client Finance    → Instance dédiée (Neo4j + Qdrant + App)
```

### Pourquoi ce choix ?

| Multi-tenant logique | 1 instance / client |
|---------------------|---------------------|
| Données sur même infra | Isolation totale |
| Filtrage par tenant_id | Séparation physique |
| Difficile à auditer | Audit simple |
| Risque de fuite | Aucun risque |

**Conséquences :**
- Le `tenant_id` reste "default" (ou nom client pour logs)
- Pas de sections `tenants:` dans la config
- Chaque client a son propre `feature_flags.yaml`

---

## Features Phase 1.8

| Flag | Description | Impact |
|------|-------------|--------|
| `enable_hybrid_extraction` | Route segments LOW_QUALITY_NER vers LLM | Rappel +15% |
| `enable_document_context` | Génère résumé document pour désambiguïsation | Precision +15-20% |
| `enable_llm_judge_validation` | Validation LLM des clusters (KGGen-inspired) | Faux positifs -47% |
| `enable_entity_ruler` | Dictionnaires métier NER (SAP, Pharma, etc.) | Precision NER +20-30% |
| `enable_ontology_prefetch` | Cache Redis ontologie par type document | Cache hit +20%, LLM calls -20% |
| `enable_llm_relation_enrichment` | LLM enrichit relations zone grise (0.4-0.6) | Precision relations +20% |
| `enable_business_rules_engine` | Règles métier YAML par tenant | Différenciateur marché |

---

## Quand Désactiver une Feature ?

### Raisons valides

1. **Coûts LLM trop élevés** - `enable_llm_relation_enrichment` ajoute ~$0.05/doc
2. **Latence inacceptable** - Une feature ralentit trop le pipeline
3. **Bug en production** - Rollback rapide le temps de corriger
4. **Client spécifique** - Un client ne veut pas une feature → modifier SA config

### Comment désactiver

```yaml
# Dans config/feature_flags.yaml de l'instance client
phase_1_8:
  enable_llm_relation_enrichment: false
```

C'est tout. Chaque instance client a sa propre configuration.

---

## Bonnes Pratiques

### 1. Toujours prévoir un fallback

```python
# Mauvais - crash si feature désactivée
result = await hybrid_extraction(segment)

# Bon - fallback gracieux
if is_feature_enabled("enable_hybrid_extraction"):
    result = await hybrid_extraction(segment)
else:
    result = await legacy_extraction(segment)
```

### 2. Logger l'état des flags au démarrage

```python
logger.info(f"[OSMOSE] Feature flags: hybrid={is_feature_enabled('enable_hybrid_extraction')}, "
            f"prefetch={is_feature_enabled('enable_ontology_prefetch')}")
```

### 3. Ne pas imbriquer les checks

```python
# Mauvais - difficile à suivre
if is_feature_enabled("A"):
    if is_feature_enabled("B"):
        if is_feature_enabled("C"):
            ...

# Bon - explicite
use_full_pipeline = (
    is_feature_enabled("A") and
    is_feature_enabled("B") and
    is_feature_enabled("C")
)
if use_full_pipeline:
    ...
```

### 4. Documenter les dépendances

```yaml
# Si enable_llm_relation_enrichment nécessite enable_hybrid_extraction
enable_llm_relation_enrichment: true  # Requiert: enable_hybrid_extraction
```

---

## État Actuel (Phase 1.8)

**Toutes les features Phase 1.8 sont activées par défaut.**

### Déploiement Client

Pour chaque nouveau client :

1. **Cloner la configuration de base**
   ```bash
   cp -r config/ /path/to/client_instance/config/
   ```

2. **Personnaliser pour le client**
   - `feature_flags.yaml` - Activer/désactiver features
   - `rules/*.yaml` - Règles métier spécifiques
   - `ontologies/*.json` - Dictionnaires métier

3. **Déployer l'instance**
   - Docker Compose avec config spécifique
   - Bases de données dédiées (Neo4j, Qdrant, Redis)

---

*Dernière mise à jour : 2025-12-18*

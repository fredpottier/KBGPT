# IDEA 001 - OpenAI Structured Outputs pour Extraction Robuste

**Date** : 2025-10-12
**Statut** : Proposition / À évaluer
**Impact estimé** : 🔥 Élevé - Réduction drastique des erreurs de parsing
**Priorité** : Moyenne-Haute

---

## 📊 Contexte

Actuellement, le projet utilise `response_format={"type": "json_object"}` pour les extractions LLM (entités, facts, métadonnées). Cette approche ne garantit **pas** que le JSON retourné respecte exactement le schéma attendu, ce qui nécessite du code de "réparation" et de transformation.

**Problèmes rencontrés** :
- ✗ Le LLM peut retourner des champs manquants ou mal typés
- ✗ Nécessité de créer `transform_fact_for_neo4j()` pour réparer les incohérences (pdf_pipeline.py:424-529)
- ✗ Parsing manual avec regex pour les facts
- ✗ Erreurs Pydantic validation possibles

---

## 🎯 Qu'est-ce que Structured Outputs ?

**Structured Outputs** est une fonctionnalité d'OpenAI qui garantit que le LLM retourne **toujours** un JSON qui correspond **exactement** à un schéma JSON Schema fourni.

### Différence avec JSON Mode Standard

| Aspect | JSON Mode Standard | Structured Outputs |
|--------|-------------------|-------------------|
| **Conformité schéma** | Non garantie | ✅ 100% garantie |
| **Parsing errors** | Possibles | ❌ Impossibles |
| **Validation Pydantic** | Peut échouer | ✅ Toujours réussit |
| **Champs requis** | Peuvent manquer | ✅ Toujours présents |
| **Types stricts** | Non respectés | ✅ Strictement respectés |

---

## ✨ Avantages pour le Projet SAP_KB

### 1. **Extraction d'Entités PDF** (pdf_pipeline.py)

**Situation actuelle** :
- Utilise `response_format={"type": "json_object"}` (ligne ~400)
- Le LLM génère parfois des facts avec format incompatible FactCreate
- Nécessité de `transform_fact_for_neo4j()` pour mapper les types

**Avec Structured Outputs** :
```python
class FactCreate(BaseModel):
    subject: str
    predicate: str
    object: str
    value: float
    unit: str
    fact_type: FactType  # Enum strict

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "fact_extraction",
            "strict": True,
            "schema": FactCreate.model_json_schema()
        }
    }
)

# ✅ Parsing ne peut PAS échouer, plus besoin de transform_fact_for_neo4j()
result = FactCreate.model_validate_json(response.choices[0].message.content)
```

**Impact** :
- ✅ Suppression de transform_fact_for_neo4j() (100+ lignes de code)
- ✅ Élimination des erreurs Pydantic ValidationError
- ✅ Code plus simple et maintenable

### 2. **Extraction Facts** (pdf_pipeline.py)

**Problème actuel** :
- Parsing manuel avec regex car le format n'est pas garanti
- Mapping free-text → enum `fact_type`
- Parsing de valeurs numériques + unités

**Avec Structured Outputs** :
- Le LLM est **forcé** de retourner un enum valide
- Les valeurs numériques sont déjà typées correctement
- Pas besoin de parsing manuel

### 3. **Metadata Extraction** (pptx_pipeline.py)

**Avec Structured Outputs** :
- Garantie que les champs requis sont présents
- Types strictement respectés
- Moins de code défensif

### 4. **Ontology Generation** (ontology_worker.py)

**Avec Structured Outputs** :
- Structure d'ontologie strictement garantie
- Pas de validation manuelle nécessaire
- Réduction des erreurs de format

---

## 💻 Comment l'Implémenter ?

### Exemple Simple

```python
from pydantic import BaseModel
from openai import OpenAI

# Schéma Pydantic (déjà existant dans le projet)
class EntityExtraction(BaseModel):
    entities: list[Entity]
    facts: list[Fact]

# Appel avec Structured Outputs
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "entity_extraction",
            "strict": True,  # ← Clé importante !
            "schema": EntityExtraction.model_json_schema()
        }
    }
)

# Le parsing ne peut PAS échouer !
result = EntityExtraction.model_validate_json(response.choices[0].message.content)
```

### Intégration dans llm_router.py

Modifier `src/knowbase/common/llm_router.py` pour supporter un paramètre `strict_schema` :

```python
def call_llm(
    prompt: str,
    model_preference: str = "openai",
    response_format: Optional[dict] = None,
    strict_schema: Optional[BaseModel] = None,  # ← Nouveau
    **kwargs
) -> str:
    if strict_schema and model_preference == "openai":
        response = client.chat.completions.create(
            model=model_config["name"],
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": strict_schema.__name__,
                    "strict": True,
                    "schema": strict_schema.model_json_schema()
                }
            },
            **kwargs
        )
    else:
        # Mode standard actuel
        ...
```

---

## 🎯 Cas d'Usage Prioritaires

### 🥇 **Priorité 1 : pdf_pipeline.py - Extraction Facts**

**Raison** : Impact le plus élevé, beaucoup de code de transformation à supprimer

**Fichiers à modifier** :
- `src/knowbase/ingestion/pipelines/pdf_pipeline.py` (lignes 400-650)
- Suppression de `transform_fact_for_neo4j()` (lignes 424-529)

**Gain estimé** :
- -150 lignes de code de transformation
- -100% erreurs Pydantic ValidationError sur facts
- Temps dev économisé : ~2-3h par bug de format évité

### 🥈 **Priorité 2 : ontology_worker.py - Génération Ontologie**

**Raison** : Structure critique, garantie de qualité importante

**Fichiers à modifier** :
- `src/knowbase/api/workers/ontology_worker.py`

**Gain estimé** :
- Validation automatique 100% fiable
- Moins de debugging

### 🥉 **Priorité 3 : pptx_pipeline.py - Métadonnées**

**Raison** : Moins critique mais amélioration de robustesse

**Fichiers à modifier** :
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py`

---

## ⚖️ Trade-offs

### ✅ Avantages

| Avantage | Impact |
|----------|--------|
| Élimine erreurs parsing/validation | 🔥 Élevé |
| Code plus simple (-150 lignes) | 🔥 Élevé |
| Moins de code défensif | 🟡 Moyen |
| Meilleure robustesse | 🔥 Élevé |
| Maintenance facilitée | 🟡 Moyen |

### ⚠️ Inconvénients

| Inconvénient | Impact |
|--------------|--------|
| Migration nécessite tests | 🟡 Moyen |
| Légèrement plus lent (~5-10%) | 🟢 Faible |
| Nécessite OpenAI SDK >= 1.0 | 🟢 Faible |
| Seulement OpenAI (pas Claude) | 🟡 Moyen |

---

## 🛠️ Plan de Migration Suggéré

### Phase 1 : Préparation (1h)
1. Vérifier version OpenAI SDK actuelle
2. Upgrade si nécessaire : `pip install openai>=1.0`
3. Tester sur environnement de dev

### Phase 2 : Implémentation PDF Pipeline (3-4h)
1. Modifier `llm_router.py` pour supporter `strict_schema`
2. Adapter `pdf_pipeline.py` pour utiliser Structured Outputs
3. Supprimer `transform_fact_for_neo4j()`
4. Tests unitaires

### Phase 3 : Validation (2h)
1. Tester sur documents réels
2. Comparer résultats avant/après
3. Monitorer logs d'erreurs

### Phase 4 : Rollout autres pipelines (2h)
1. Ontology worker
2. PPTX pipeline
3. Tests d'intégration

**Temps total estimé** : 8-9 heures

---

## 📊 Métriques de Succès

### Avant Migration
- ❌ ~5-10% erreurs Pydantic ValidationError sur facts
- ❌ 150 lignes de code de transformation
- ❌ Temps debug moyen : 30min par erreur de format

### Après Migration
- ✅ 0% erreurs Pydantic ValidationError attendu
- ✅ -150 lignes de code
- ✅ Temps debug : 0 (pas d'erreurs de format)

---

## 🔍 Limitations Techniques

### Modèles Supportés
- ✅ GPT-4o
- ✅ GPT-4o-mini
- ❌ GPT-3.5-turbo (pas supporté)
- ❌ Claude (OpenAI uniquement)

**Impact pour le projet** : ✅ Pas de problème, on utilise gpt-4o-mini

### Contraintes JSON Schema

Structured Outputs supporte :
- ✅ Types simples (string, number, boolean)
- ✅ Objects et nested objects
- ✅ Arrays
- ✅ Enums
- ✅ Required fields
- ❌ `additionalProperties: true` (pas supporté en mode strict)

---

## 💡 Recommandation Finale

**Verdict** : ✅ **Très recommandé**

**Raisons** :
1. Le projet a déjà rencontré des bugs liés aux formats JSON incohérents
2. Beaucoup de code de "réparation" pourrait être éliminé
3. Utilise déjà gpt-4o-mini (compatible)
4. ROI élevé : 8-9h migration vs ~3-4h économisées par mois en debug

**Action recommandée** :
- Démarrer par une **proof of concept** sur pdf_pipeline.py (2-3h)
- Si succès → Migration progressive des autres pipelines
- Si échec → Pas de régression, code actuel conservé

---

## 📚 Références

- Documentation OpenAI : https://platform.openai.com/docs/guides/structured-outputs
- Migration Guide : https://platform.openai.com/docs/guides/structured-outputs/migrating
- JSON Schema Spec : https://json-schema.org/

---

## 📝 Notes Additionnelles

**Compatibilité avec config actuelle** :
- `config/llm_models.yaml` : Pas de modification nécessaire
- `config/prompts.yaml` : Pas de modification nécessaire
- Multi-provider : Rester compatible avec Claude (fallback sur JSON mode standard)

**Risques identifiés** :
- 🟢 Faible : Migration technique simple
- 🟢 Faible : Rollback possible immédiatement
- 🟡 Moyen : Nécessite tests approfondis pour valider équivalence

---

**Créé par** : Claude Code
**Dernière mise à jour** : 2025-10-12

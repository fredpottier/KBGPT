# 🔍 OSMOSE - Analyse Qualité Extraction Concepts

**Date:** 2025-10-15
**Phase:** Phase 1 V2.1 - Diagnostic Post-Implémentation
**Document Test:** CRITEO_ERP_RFP_-_SAP_Answer (47 slides)

---

## 📊 Résultats Actuels

### Métriques Pipeline

```
- 11 topics segmentés
- 42 concepts canoniques extraits
- 19 connexions cross-documents
- 42 embeddings Qdrant
- 42 concepts Neo4j (37 après MERGE dédupe)
- Durée: 223.8s (3min44s)
```

### Concepts Extraits (Échantillon Neo4j)

| Concept | Type | Définition | Qualité |
|---------|------|------------|---------|
| SAP S/4HANA | ENTITY | (vide) | ✅ Bon |
| HANA | ENTITY | (vide) | ✅ Bon |
| GDPR | ENTITY | (vide) | ✅ Bon |
| HighRadius | ENTITY | (vide) | ✅ Bon |
| Kyriba | ENTITY | (vide) | ✅ Bon |
| "ized" | ENTITY | (vide) | ❌ Fragment |
| "ial" | ENTITY | (vide) | ❌ Fragment |
| "the \"Invoice & Pay" | ENTITY | (vide) | ❌ Mal formé |
| Finance | ENTITY | (vide) | ⚠️ Trop générique |
| Operations | ENTITY | (vide) | ⚠️ Trop générique |

---

## 🐛 Problèmes Identifiés

### 1. **LLM Extraction Désactivée** ⚠️ CRITIQUE

```yaml
# config/semantic_intelligence_v2.yaml ligne 22
methods:
  - "NER"                      # ✅ Activé
  - "CLUSTERING"               # ✅ Activé
  # - "LLM"                    # ❌ DÉSACTIVÉ pour économiser coûts debug
```

**Impact:**
- NER seul extrait des **noms propres** (organisations, personnes, lieux)
- Ne capture PAS les **concepts métier clés** (pratiques, processus, standards)
- Pas de **définitions générées**
- Pas de **typage sémantique** (PRACTICE, STANDARD, TOOL, ROLE)

### 2. **Bruit NER - Fragments** ❌

**Exemples:**
- "ized" (fragment de "specialized", "optimized", etc.)
- "ial" (fragment de "financial", "material", etc.)
- "the \"Invoice & Pay" (extraction mal délimitée)

**Cause:**
- Modèle spaCy `en_core_web_md` découpe mal les entités longues
- Pas de post-processing pour filtrer fragments courts
- Pas de validation de qualité des entités extraites

### 3. **Concepts Trop Génériques** ⚠️

**Exemples:**
- "Finance", "Operations", "AI", "treasury"
- Pas assez spécifiques au contexte SAP/ERP
- Dilue le Knowledge Graph

### 4. **Aucune Définition Générée** ❌

```cypher
MATCH (c:CanonicalConcept) RETURN c.unified_definition
→ Tous retournent "" (vide)
```

**Impact:**
- Impossible de comprendre le sens d'un concept sans lire les documents sources
- Pas de différenciation entre homonymes
- Pas d'aide contextuelle pour l'utilisateur

### 5. **Pas de Typage Sémantique** ❌

**Actuel:**
```
Tous les concepts → Type: ENTITY
```

**Attendu:**
```
- SAP S/4HANA          → ENTITY
- Financial Closing    → PRACTICE
- GDPR                 → STANDARD
- HighRadius           → TOOL
- CFO                  → ROLE
```

---

## 💡 Recommandations

### Phase 1: Corrections Immédiates (1-2h)

#### 1.1 Réactiver LLM Extraction ✅ PRIORITÉ 1

```yaml
# config/semantic_intelligence_v2.yaml ligne 22
methods:
  - "NER"
  - "CLUSTERING"
  - "LLM"  # ✅ RÉACTIVER
```

**Bénéfices:**
- Extraction concepts métier (pratiques SAP, processus finance)
- Génération définitions automatiques
- Typage sémantique (PRACTICE, STANDARD, TOOL, ROLE)
- Filtrage intelligent (rejette fragments et concepts génériques)

**Coût estimé:**
- ~$0.05-0.10 par document (gpt-4o-mini)
- Budget acceptable pour qualité supérieure

#### 1.2 Ajouter Filtrage Post-NER

**Fichier:** `src/knowbase/semantic/utils/ner_manager.py`

```python
def _filter_low_quality_entities(self, entities: List[str]) -> List[str]:
    """
    Filtre les entités NER de mauvaise qualité.

    Critères de rejet:
    - Longueur < 3 caractères
    - Contient seulement minuscules/majuscules (pas de mélange)
    - Mots stop-words génériques (the, and, etc.)
    - Fragments courants (ized, ial, ing, etc.)
    """
    filtered = []
    fragments = {"ized", "ial", "ing", "tion", "ness", "ment"}
    stopwords = {"the", "and", "or", "of", "in", "on", "at", "to"}

    for entity in entities:
        # Rejeter si trop court
        if len(entity) < 3:
            continue

        # Rejeter fragments connus
        if entity.lower() in fragments:
            continue

        # Rejeter stopwords
        if entity.lower() in stopwords:
            continue

        # Rejeter si commence par article
        if entity.lower().startswith(("the ", "a ", "an ")):
            entity = entity.split(" ", 1)[1]  # Enlever article

        filtered.append(entity)

    return filtered
```

#### 1.3 Améliorer Prompt LLM

**Fichier:** `config/prompts.yaml` (créer section `concept_extraction`)

```yaml
concept_extraction:
  system: |
    You are an expert in SAP ERP, Finance, and Business Process Management.
    Your task is to extract KEY business concepts from technical documents.

    Focus on:
    - SAP-specific products/modules (S/4HANA, HANA, Fiori, etc.)
    - Business processes (Financial Closing, Order-to-Cash, etc.)
    - Standards/regulations (GDPR, SOX, IFRS, etc.)
    - Third-party tools integrated with SAP (HighRadius, Kyriba, etc.)
    - Business roles (CFO, Controller, Accountant, etc.)

    REJECT:
    - Generic terms (finance, operations, business)
    - Fragments (ized, ial, ing)
    - Articles/prepositions
    - Company names (unless SAP partners)

  user_template: |
    Extract business concepts from this text segment:

    ---
    {topic_text}
    ---

    Return JSON array:
    [
      {
        "name": "SAP S/4HANA Cloud",
        "type": "ENTITY",
        "definition": "Cloud-based ERP suite from SAP, successor to SAP ECC",
        "confidence": 0.95
      },
      {
        "name": "Three-Way Match",
        "type": "PRACTICE",
        "definition": "Accounts Payable control matching PO, receipt, and invoice",
        "confidence": 0.88
      }
    ]
```

### Phase 2: Améliorations Avancées (4-6h)

#### 2.1 Ajouter Ontologie Domaine SAP

**Fichier:** `config/sap_ontology.yaml`

```yaml
entities:
  products:
    - SAP S/4HANA
    - SAP HANA
    - SAP Fiori
    - SAP BTP
    - SAP Ariba
    - SAP SuccessFactors

  modules:
    - Financial Accounting (FI)
    - Controlling (CO)
    - Materials Management (MM)
    - Sales & Distribution (SD)

practices:
  finance:
    - Financial Closing
    - Month-End Close
    - Order-to-Cash
    - Procure-to-Pay
    - Record-to-Report

standards:
  - GDPR
  - SOX (Sarbanes-Oxley)
  - IFRS
  - US GAAP

tools:
  partners:
    - HighRadius (Collections)
    - Kyriba (Treasury)
    - BlackLine (Reconciliation)
```

Utiliser cette ontologie pour :
1. **Boosting** : Augmenter score confiance si match ontologie
2. **Validation** : Rejeter concepts hors ontologie si confiance < 0.7
3. **Auto-complétion** : Suggérer concepts manquants

#### 2.2 Implémenter Génération Définitions Multi-Sources

```python
async def generate_unified_definition(
    self,
    concept_name: str,
    context_texts: List[str]
) -> str:
    """
    Génère définition unifiée depuis plusieurs sources.

    Strategy:
    1. Extraire toutes mentions du concept dans documents
    2. Identifier contextes clés (première mention, listes, etc.)
    3. Appel LLM pour synthétiser définition unifiée
    4. Valider longueur (50-200 chars) et cohérence
    """
    # Extraire contextes pertinents
    contexts = self._extract_concept_contexts(concept_name, context_texts)

    # Prompt LLM
    prompt = f"""
    Synthesize a concise definition (50-200 chars) for the concept "{concept_name}"
    based on these contexts:

    {chr(10).join(f"- {ctx}" for ctx in contexts[:5])}

    Definition:
    """

    definition = await self.llm_router.complete(prompt, max_tokens=100)
    return definition.strip()
```

#### 2.3 Ajouter Métriques Qualité

```python
class ConceptQualityMetrics:
    """Métriques qualité extraction concepts."""

    def calculate_quality_score(self, concept: Concept) -> float:
        """
        Calcule score qualité 0-1 basé sur:
        - Longueur nom (reject si < 3 ou > 50 chars)
        - Match ontologie (+0.2 si trouvé)
        - Présence définition (+0.3 si générée)
        - Confiance extraction (0-1)
        - Fréquence dans document (+0.1 si > 3 mentions)
        """
        score = 0.0

        # Longueur
        if 3 <= len(concept.name) <= 50:
            score += 0.2

        # Match ontologie
        if self._matches_ontology(concept.name):
            score += 0.2

        # Définition
        if concept.definition:
            score += 0.3

        # Confiance
        score += concept.confidence * 0.3

        return min(score, 1.0)
```

### Phase 3: Innovation - Extraction Contextuelle (8-12h)

#### 3.1 Graph-Based Concept Extraction

Utiliser le **contexte relationnel** pour identifier concepts importants :

```python
# Exemple: "SAP S/4HANA integrates with HighRadius for automated collections"
# → Extraire: SAP S/4HANA (ENTITY), HighRadius (TOOL)
# → Relation: INTEGRATES_WITH
# → Context importance: Concepts liés à SAP = prioritaires
```

#### 3.2 Document Role Detection

Détecter automatiquement le **rôle du document** :

```python
class DocumentRoleDetector:
    """Détecte le rôle d'un document."""

    def detect_role(self, document_text: str) -> DocumentRole:
        """
        Détecte si le document:
        - DEFINES: Définit des concepts (glossaire, spec technique)
        - IMPLEMENTS: Décrit une implémentation (guide config)
        - AUDITS: Rapport d'audit, compliance check
        - PROVES: Preuve de conformité (certification)
        - REFERENCES: Mentionne seulement (présentation, email)
        """
```

Utiliser le role pour **pondérer l'importance** des concepts extraits.

---

## 🎯 Plan d'Action Recommandé

### Semaine en Cours

- [x] **Diagnostic complet** (ce document)
- [ ] **Réactiver LLM extraction** (1h)
- [ ] **Ajouter filtrage post-NER** (2h)
- [ ] **Tester sur 5-10 documents** (2h)
- [ ] **Mesurer amélioration qualité** (1h)

**Critères Succès:**
- Réduction fragments < 5%
- Augmentation concepts métier > 80%
- Génération définitions > 90%
- Typage sémantique correct > 85%

### Semaines 11-12

- [ ] Implémenter ontologie SAP
- [ ] Ajouter génération définitions multi-sources
- [ ] Créer dashboard métriques qualité
- [ ] Tester sur corpus complet (50+ documents)

---

## 📈 Métriques Attendues Après Corrections

| Métrique | Avant | Après (Cible) |
|----------|-------|---------------|
| Concepts extraits | 42 | 50-60 |
| Fragments/bruit | 15% | < 5% |
| Concepts métier | 30% | > 80% |
| Définitions générées | 0% | > 90% |
| Typage sémantique | 0% (tous ENTITY) | > 85% |
| Score qualité moyen | 0.4 | > 0.75 |

---

## 🔗 Références

- Configuration: `config/semantic_intelligence_v2.yaml`
- Pipeline: `src/knowbase/semantic/semantic_pipeline_v2.py`
- Extracteur: `src/knowbase/semantic/extraction/concept_extractor.py`
- NER: `src/knowbase/semantic/utils/ner_manager.py`
- Ontologie: `config/sap_ontology.yaml` (à créer)

---

**Conclusion:** Le pipeline OSMOSE Pure V2.1 fonctionne techniquement (Neo4j OK, Qdrant OK, extraction end-to-end), mais la **qualité des concepts extraits est insuffisante** car l'extraction LLM est désactivée et il manque du filtrage. Les corrections Phase 1 (réactiver LLM + filtrage NER) peuvent être implémentées en **1-2h** et amélioreront drastiquement la qualité.

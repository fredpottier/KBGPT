# 📋 Description des Tâches LLM - Pour Validation Modèles

**Projet** : OSMOSE (Organic Semantic Memory Organization & Smart Extraction)
**Objectif** : Valider l'équivalence des modèles Gemini vs OpenAI pour chaque tâche

---

## 1. 📝 Concept Extraction (knowledge_extraction)

### Configuration actuelle
- **Modèle OpenAI** : `gpt-4o-mini`
- **Modèle Gemini proposé** : `gemini-1.5-flash-8b`
- **Température** : 0.2
- **Max tokens** : ~2048

### Description de la tâche

**Objectif** : Extraire des concepts métier structurés à partir de texte enrichi provenant de présentations PowerPoint (slides SAP, documentation technique, présentations business).

**Input** :
- Texte extrait d'une slide PowerPoint (300-800 mots typiquement)
- Contexte du document (résumé global du deck)
- Notes du présentateur (si disponibles)
- Prompt système définissant le format de sortie attendu

**Traitement attendu** :
1. Identifier les concepts clés mentionnés dans le texte (produits SAP, fonctionnalités, processus métier, architecture)
2. Extraire pour chaque concept :
   - Nom du concept (ex: "SAP S/4HANA Cloud Private Edition")
   - Type (ex: "produit", "fonctionnalité", "processus")
   - Définition complète (2-3 phrases expliquant le concept)
   - Niveau de confiance (0.0-1.0)
   - Métadonnées contextuelles (slide source, catégorie, tags)

**Output** :
- Format JSON structuré
- Liste de 3-8 concepts par slide
- Chaque concept contient : `name`, `type`, `definition`, `confidence`, `metadata`

**Exemple concret** :

*Input text* :
```
SAP S/4HANA Cloud Private Edition offers a fully managed cloud ERP solution with
dedicated infrastructure. It provides quarterly innovation updates while maintaining
full customization capabilities through BTP extensions.
```

*Output attendu* :
```json
[
  {
    "name": "SAP S/4HANA Cloud Private Edition",
    "type": "product",
    "definition": "Fully managed cloud ERP solution with dedicated infrastructure, offering quarterly innovation updates and full customization via BTP extensions.",
    "confidence": 0.95,
    "metadata": {"category": "Cloud ERP", "deployment": "private"}
  },
  {
    "name": "BTP Extensions",
    "type": "capability",
    "definition": "SAP Business Technology Platform extensions enabling custom development and integration for S/4HANA Cloud.",
    "confidence": 0.88,
    "metadata": {"category": "Platform", "purpose": "customization"}
  }
]
```

**Exigences qualitatives** :
- ✅ **Précision** : Concepts correctement identifiés (pas de hallucinations)
- ✅ **Complétude** : Ne pas manquer les concepts principaux
- ✅ **Cohérence** : Définitions factuelles et exactes
- ✅ **Format** : JSON valide, respect strict du schéma
- ✅ **Concision** : Définitions claires mais pas verboses

**Volume** :
- ~1,000 appels par document de 230 slides
- Tokens moyens : 622 IN / 344 OUT
- Durée cible : <2s par appel

**Criticité** : **HAUTE** - C'est le cœur du système d'extraction sémantique

---

## 2. 🎨 Vision Summary (OSMOSE Pure Mode)

### Configuration actuelle
- **Modèle OpenAI** : `gpt-4o` (Vision)
- **Modèle Gemini proposé** : `gemini-1.5-flash`
- **Température** : 0.5
- **Max tokens** : 4000

### Description de la tâche

**Objectif** : Générer un résumé riche et détaillé d'une slide PowerPoint en analysant SIMULTANÉMENT le contenu visuel (diagrammes, graphiques, images) ET le texte pour créer une description narrative fluide.

**Input** :
- Image PNG de la slide (encodée base64)
- Texte extrait par OCR/python-pptx
- Notes du présentateur
- Index de la slide et contexte du document

**Traitement attendu** :
1. **Analyser la structure visuelle** : Identifier les diagrammes, flowcharts, graphiques, schémas d'architecture, tableaux
2. **Interpréter les éléments visuels** : Comprendre les relations spatiales (flèches, connexions, groupements, hiérarchies)
3. **Décrire l'organisation** : Expliquer comment l'information est présentée visuellement
4. **Intégrer le texte** : Fusionner le contenu textuel avec les insights visuels
5. **Capturer l'emphase** : Identifier les éléments mis en avant (couleurs, tailles, callouts)
6. **Synthétiser** : Produire une narration fluide et cohérente (2-4 paragraphes)

**Output** :
- Texte en prose naturelle (PAS de JSON, PAS de bullet points)
- 1,000-2,000 mots par slide
- Description comme si on expliquait la slide à quelqu'un qui ne peut pas la voir

**Exemple concret** :

*Input* : Slide montrant un schéma d'architecture SAP avec boîtes et flèches

*Output attendu* :
```
This slide presents a comprehensive architecture diagram for SAP S/4HANA Cloud
integration. At the center, a large blue box labeled "SAP S/4HANA Cloud" serves
as the core system. Three green boxes positioned above it represent integration
layers: "SAP Integration Suite" on the left, "SAP Business Technology Platform"
in the center, and "API Management" on the right. Bidirectional arrows connect
each integration layer to the core S/4HANA system, indicating two-way data flow.

Below the central S/4HANA box, four smaller boxes arranged horizontally show
connected systems: "Salesforce" (orange), "Workday" (yellow), "Legacy ERP" (gray),
and "Custom Apps" (purple). Each is connected via dashed lines suggesting API-based
integration. A callout box in the top-right corner, highlighted in red, emphasizes
"Real-time synchronization" with a lightning bolt icon, indicating the architecture's
focus on instantaneous data exchange. The visual hierarchy clearly positions S/4HANA
as the central hub with integration capabilities extending both upward to platform
services and downward to external systems.
```

**Exigences qualitatives** :
- ✅ **Vision forte** : Doit réellement "voir" et interpréter les visuels (pas juste le texte)
- ✅ **Richesse descriptive** : Descriptions détaillées et nuancées
- ✅ **Narration fluide** : Prose naturelle, pas de structure rigide
- ✅ **Précision spatiale** : Relations visuelles correctement décrites
- ✅ **Complétude** : Tous les éléments visuels importants mentionnés

**Volume** :
- 230 appels par document (1 par slide)
- Tokens estimés : ~2,300 IN / ~1,500 OUT
- Durée cible : 3-5s par appel

**Criticité** : **TRÈS HAUTE** - C'est l'USP unique d'OSMOSE (différenciation vs Copilot)

---

## 3. 🔍 Vision Analysis (Legacy Mode)

### Configuration actuelle
- **Modèle OpenAI** : `gpt-4o` (Vision)
- **Modèle Gemini proposé** : `gemini-1.5-flash`
- **Température** : 0.2
- **Max tokens** : 8000

### Description de la tâche

**Objectif** : Extraire des données structurées (concepts, facts, entities, relations) d'une slide PowerPoint en analysant à la fois le contenu visuel et textuel, et retourner un JSON avec 4 sections distinctes.

**Input** :
- Image PNG de la slide (encodée base64)
- Texte extrait
- Notes du présentateur
- Prompt définissant le schéma JSON de sortie

**Traitement attendu** :
1. **Analyser visuellement** : Diagrammes, graphiques, images
2. **Extraire 4 types d'information** :
   - **Concepts** : Idées principales, produits, fonctionnalités (avec définition complète)
   - **Facts** : Faits vérifiables, chiffres, dates, affirmations factuelles
   - **Entities** : Entités nommées (entreprises, produits, personnes, lieux)
   - **Relations** : Relations sémantiques entre entités (X "integrates with" Y)

**Output** :
- Format JSON structuré avec 4 sections
```json
{
  "concepts": [
    {"full_explanation": "...", "meta": {...}}
  ],
  "facts": [
    {"statement": "...", "confidence": 0.95}
  ],
  "entities": [
    {"name": "...", "type": "...", "context": "..."}
  ],
  "relations": [
    {"subject": "...", "predicate": "...", "object": "..."}
  ]
}
```

**Exemple concret** :

*Input* : Slide "SAP S/4HANA integrates with Salesforce for real-time CRM sync" (avec diagramme)

*Output attendu* :
```json
{
  "concepts": [
    {
      "full_explanation": "Real-time CRM integration between SAP S/4HANA and Salesforce enables bidirectional synchronization of customer data, orders, and account information.",
      "meta": {"type": "integration_pattern", "complexity": "medium"}
    }
  ],
  "facts": [
    {
      "statement": "SAP S/4HANA supports real-time integration with Salesforce CRM",
      "confidence": 0.98
    }
  ],
  "entities": [
    {"name": "SAP S/4HANA", "type": "product", "context": "ERP system"},
    {"name": "Salesforce", "type": "product", "context": "CRM system"}
  ],
  "relations": [
    {
      "subject": "SAP S/4HANA",
      "predicate": "integrates_with",
      "object": "Salesforce"
    }
  ]
}
```

**Exigences qualitatives** :
- ✅ **Vision + parsing** : Doit analyser visuels ET produire JSON valide
- ✅ **Complétude** : 4 sections remplies quand pertinent
- ✅ **Précision** : Données factuelles correctes
- ✅ **Relations correctes** : Triplets sémantiques valides
- ✅ **Format strict** : JSON conforme au schéma

**Volume** :
- 230 appels par document (mode legacy)
- Tokens estimés : ~2,500 IN / ~3,500 OUT
- Durée cible : 4-6s par appel

**Criticité** : **HAUTE** - Mode legacy mais toujours utilisé pour certains workflows

---

## 4. 🧮 Embeddings Generation

### Configuration actuelle
- **Modèle OpenAI** : `text-embedding-3-large`
- **Alternative Gemini** : Vertex AI Text Embeddings (pas Gemini direct)
- **Dimensions** : 1024D (forcées pour compatibilité Qdrant)

### Description de la tâche

**Objectif** : Générer des vecteurs d'embeddings de haute qualité (1024 dimensions) pour des chunks de texte afin de permettre la recherche sémantique dans Qdrant.

**Input** :
- Batch de textes (typiquement 1000-2000 chunks à la fois)
- Chaque chunk : 200-600 mots (extraits de concepts, résumés de slides)
- Exemple : "SAP S/4HANA Cloud Private Edition is a fully managed cloud ERP solution..."

**Traitement attendu** :
1. **Encoder sémantiquement** : Capturer le sens profond du texte
2. **Normalisation** : Vecteurs normalisés (norme L2)
3. **Cohérence** : Textes similaires → vecteurs proches (distance cosine)
4. **Dimensions fixes** : Exactement 1024D (contrainte Qdrant)

**Output** :
- Array numpy de shape (N, 1024)
- dtype: float32
- Valeurs normalisées

**Exemple concret** :
```python
texts = [
    "SAP S/4HANA Cloud offers real-time analytics",
    "SAP Analytics Cloud provides business intelligence"
]
embeddings = embedder.encode(texts)
# Shape: (2, 1024)
# embeddings[0] et embeddings[1] doivent être proches (similarité thématique)
```

**Exigences qualitatives** :
- ✅ **Qualité sémantique** : Recherche pertinente (pas de "topic drift")
- ✅ **Cohérence cross-lingual** : Support multilingue si besoin
- ✅ **Stabilité** : Mêmes textes → mêmes vecteurs (reproductibilité)
- ✅ **Performance** : Batch processing rapide (1000+ chunks/min)

**Volume** :
- ~13,763 chunks par document (gros documents)
- Tokens estimés : ~5.5M tokens par document
- Durée cible : <60s pour tout le batch

**Criticité** : **MOYENNE-HAUTE** - Impact direct sur qualité de recherche

**Note** : Gemini n'a pas d'API embeddings. Alternatives :
1. Garder OpenAI text-embedding-3-large ($0.13/1M)
2. Migrer vers Vertex AI Text Embeddings ($0.025/1M, -80%)

---

## 📊 Résumé Comparatif

| Tâche | Modèle OpenAI | Modèle Gemini | Criticité | Économie |
|-------|---------------|---------------|-----------|----------|
| Concept Extraction | gpt-4o-mini | gemini-1.5-flash-8b | HAUTE | -75% |
| Vision Summary | gpt-4o | gemini-1.5-flash | TRÈS HAUTE | -75% |
| Vision Analysis | gpt-4o | gemini-1.5-flash | HAUTE | -75% |
| Embeddings | text-emb-3-large | Vertex AI / OpenAI | MOYENNE | 0% à -80% |

---

## 🎯 Questions pour Validation OpenAI

### Pour chaque tâche :

1. **Le modèle Gemini proposé a-t-il des capacités équivalentes pour cette tâche ?**
   - Précision sémantique comparable ?
   - Qualité de parsing JSON ?
   - Capacités vision (pour tâches 2 et 3) ?

2. **Y a-t-il des limitations connues de Gemini pour ce cas d'usage ?**
   - Context window insuffisant ?
   - Problèmes de format de sortie ?
   - Drift qualité sur gros volumes ?

3. **Recommanderiez-vous un modèle OpenAI différent si coût n'était pas un facteur ?**
   - gpt-4o au lieu de gpt-4o-mini pour extraction ?
   - gpt-4-turbo pour vision ?

4. **Stratégies d'optimisation OpenAI pour réduire les coûts ?**
   - Batch API (50% réduction) ?
   - Prompt engineering pour réduire tokens ?
   - Modèles plus petits pour certaines sous-tâches ?

---

## 📞 Contact

Pour toute question sur ces cas d'usage, merci de contacter l'équipe OSMOSE.

**Prochaines étapes** :
1. Validation par OpenAI de l'équivalence Gemini
2. POC A/B testing sur 100 documents
3. Benchmark qualité OpenAI vs Gemini
4. Migration progressive si validation OK

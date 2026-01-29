# Document d'Implémentation : POC Lecture Stratifiée v1.2

**Statut**: PRÊT À EXÉCUTER (validé ChatGPT)
**Date**: 2025-01-23
**Objectif**: Valider la faisabilité technique de l'ADR_STRATIFIED_READING_MODEL.md
**LLM**: Qwen 14B (EC2)
**Stockage**: Qdrant + Neo4j existants (purge préalable autorisée)

---

## 1. Objectif du POC

### Ce qu'on veut VRAIMENT prouver

> **Risque réel de l'ADR** : *"Est-ce qu'un LLM peut résister à la tentation de sur-structurer et sur-conceptualiser ?"*

| Question | Critère de succès |
|----------|-------------------|
| Le LLM respecte-t-il la frugalité ? | **Coupe-circuit dur** : >60 concepts = FAIL immédiat |
| Le LLM comprend-il les structures de dépendance ? | Justification + rejection des alternatives |
| L'Information est-elle utilisable ? | Micro-usage simulé fonctionnel |
| Le modèle résiste-t-il à un document hostile ? | Refus de sur-structurer = succès |
| L'overlay Information fonctionne-t-il ? | Anchors → texte à 95%+ |

### Ce qu'on NE teste PAS

- Cross-document (NIVEAU 3 - ConceptCanonique)
- UI/UX
- Performance à grande échelle
- Coût LLM optimisé

---

## 2. Périmètre du POC

### Documents de test : 4 documents CONFIRMÉS

| # | Structure | Fichier | Caractéristiques |
|---|-----------|---------|------------------|
| 1 | **CENTRAL** | `IndustryGuide-SAP-Addressing-GDPR-Requirements.pdf` | Ultra-central : tout gravite autour de SAP. Hiérarchie : problème RGPD → besoin métier → réponse SAP. |
| 2 | **TRANSVERSAL** | `gdpr_guide-for-processors_en.pdf` | Framework normatif générique (CNIL). Concepts abstraits : obligations, rôles, responsabilités. Pas de "héros". |
| 3 | **CONTEXTUAL** | `euro-ncap-assessment-protocol-sa-safe-driving-v104.pdf` | Rule-heavy mais concept-bearing. Concepts : assist systems, driver monitoring, scoring logic. |
| 4 | **HOSTILE** | `euro-ncap-assessment-protocol-vru-v114.pdf` | **Max hostile**. Hyper procédural : tests, paramètres physiques, seuils. Concepts faibles et locaux. |

**Localisation** : `C:\Users\fredp\Downloads\POC\`

> **Test hostile (VRU)** : Document bien formaté mais conceptuellement pauvre.
> - Succès = <10 concepts ou refus explicite de sur-structurer
> - Échec = sur-extraction de faux concepts (>30)

### Infrastructure

```
STOCKAGE (bases existantes, purgées)
├── Qdrant: Collection "poc_stratified" (chunks + embeddings)
└── Neo4j: Nodes POC uniquement (tenant_id = "poc_v2")

CODE (isolé)
poc/
├── poc_stratified_reader.py    # Orchestrateur principal
├── extractors/
│   ├── document_analyzer.py    # Phase 1.1 : Analyse globale
│   ├── concept_identifier.py   # Phase 1.2 : Concepts frugaux
│   └── information_extractor.py # Phase 1.3 : Information
├── validators/
│   ├── frugality_guard.py      # Coupe-circuit dur
│   ├── anchor_validator.py     # Validation anchors
│   └── redundancy_checker.py   # Détection doublons
├── models/
│   └── schemas.py              # Pydantic models
├── prompts/
│   └── poc_prompts.yaml        # Prompts Qwen 14B
├── mini_usage/
│   └── usage_simulator.py      # Micro-usage test
└── output/
    └── poc_report.md           # Rapport final
```

### Briques Réutilisables du Pipeline Existant

**⚠️ PRINCIPE** : Réutiliser les briques d'infrastructure, PAS la logique d'extraction.

| Composant | Réutiliser ? | Justification |
|-----------|--------------|---------------|
| `LLMRouter` | ✅ OUI | Appels LLM, gestion providers |
| `QdrantClient` | ✅ OUI | Stockage chunks + embeddings |
| `Neo4jClient` | ✅ OUI | Stockage structure (tenant `poc_v2`) |
| `EmbeddingService` | ✅ OUI | Calcul embeddings |
| `pdf_pipeline` (extraction texte) | ❌ **NON** | Logique chunk-by-chunk incompatible avec lecture top-down |
| `concept_extractor` | ❌ **NON** | Extraction myope, exactement ce qu'on veut changer |
| `relation_validator` | ❌ **NON** | Validation LLM stricte, obsolète |

### Nouvelle Approche Extraction Texte (POC)

L'extraction texte du POC doit être **top-down** :

```
ANCIENNE APPROCHE (à ne pas reprendre)
Document → Chunks → Extraction par chunk → Consolidation (échoue)

NOUVELLE APPROCHE (POC)
Document → Lecture globale (Subject, Themes) → Concepts avec contexte global → Information chunk par chunk MAIS avec contexte
```

**Implémentation POC** :
1. **Phase 0** : Extraire texte brut du PDF (PyMuPDF ou vision si nécessaire)
2. **Phase 1.1** : Passer le document ENTIER (ou résumé dense) au LLM pour analyse globale
3. **Phase 1.2-1.3** : Extraction avec le contexte global en mémoire

> **Si vision nécessaire** (scans, images) : utiliser `gpt-4o-vision`, pas vLLM.

---

## 3. Modèles de Données (Pydantic)

```python
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
from enum import Enum

class DependencyStructure(str, Enum):
    CENTRAL = "CENTRAL"
    TRANSVERSAL = "TRANSVERSAL"
    CONTEXTUAL = "CONTEXTUAL"

class ConceptRole(str, Enum):
    CENTRAL = "CENTRAL"
    CONTEXTUAL = "CONTEXTUAL"
    STANDARD = "STANDARD"

class InfoType(str, Enum):
    DEFINITION = "DEFINITION"
    FACT = "FACT"
    CAPABILITY = "CAPABILITY"
    CONSTRAINT = "CONSTRAINT"
    OPTION = "OPTION"
    LIMITATION = "LIMITATION"
    CONDITION = "CONDITION"
    CONSEQUENCE = "CONSEQUENCE"

class Anchor(BaseModel):
    """Pointeur vers le texte source"""
    chunk_id: str
    start_char: int
    end_char: int

class Theme(BaseModel):
    """Nœud thématique récursif"""
    id: str
    name: str
    parent_id: Optional[str] = None
    children: List["Theme"] = []

# ========== NOUVEAU : Justification des structures ==========

class StructureJustification(BaseModel):
    """Justification de la structure choisie + rejet des alternatives"""
    chosen: DependencyStructure
    justification: str
    rejected: Dict[str, str]  # {"TRANSVERSAL": "why not", "CONTEXTUAL": "why not"}

class Information(BaseModel):
    """N0 - Pointeur typé (PAS de texte stocké)"""
    id: str
    info_type: InfoType
    anchor: Anchor
    concept_refs: List[str] = []
    theme_ref: str
    # text: PAS DE CHAMP TEXT - récupéré via anchor

class MeaningSignature(BaseModel):
    """Signature sémantique multi-composantes"""
    embedding: List[float]
    co_terms: List[str]
    verbs: List[str]
    objects: List[str]

class ConceptSitue(BaseModel):
    """N1 - Concept frugal"""
    id: str
    name: str
    role: ConceptRole
    theme_ref: str
    meaning_signature: Optional[MeaningSignature] = None
    information_ids: List[str] = []

# ========== NOUVEAU : Métriques de qualité ==========

class QualityMetrics(BaseModel):
    """Métriques de qualité du POC"""
    concept_count: int
    information_count: int
    info_per_concept_avg: float
    redundancy_rate: float  # % d'Info sémantiquement proches
    anchor_success_rate: float  # % d'anchors valides
    refusal_count: int  # Nb de concepts refusés par le LLM

class DocumentStructure(BaseModel):
    """Structure complète extraite"""
    doc_id: str
    doc_title: str

    # Structure de dépendance AVEC justification
    structure_decision: StructureJustification

    # Hiérarchie
    subject: str
    themes: List[Theme]

    # Données
    concepts: List[ConceptSitue]
    informations: List[Information]

    # Métriques
    metrics: QualityMetrics

    @validator('concepts')
    def check_frugality(cls, v):
        """COUPE-CIRCUIT DUR : >60 concepts = FAIL"""
        if len(v) > 60:
            raise ValueError(f"FRUGALITY VIOLATION: {len(v)} concepts (max 60)")
        return v
```

---

## 4. Garde-fous et Coupe-circuits

### 4.1 Coupe-circuit Frugalité (CRITIQUE)

```python
# frugality_guard.py

class FrugalityGuard:
    MAX_CONCEPTS = 60  # Dur, non négociable
    MIN_CONCEPTS = 5   # Trop peu = doc hostile ou erreur

    def validate(self, concepts: List[ConceptSitue], doc_type: str) -> tuple[bool, str]:
        count = len(concepts)

        if count > self.MAX_CONCEPTS:
            return False, f"FAIL: {count} concepts > {self.MAX_CONCEPTS} (sur-structuration)"

        if count < self.MIN_CONCEPTS and doc_type != "HOSTILE":
            return False, f"WARN: {count} concepts < {self.MIN_CONCEPTS} (sous-extraction?)"

        if count < self.MIN_CONCEPTS and doc_type == "HOSTILE":
            return True, f"SUCCESS: Document hostile correctement refusé ({count} concepts)"

        return True, f"OK: {count} concepts dans la plage acceptable"
```

> **Règle absolue** : Si concept_count > 60 → **FAIL immédiat du POC**. Pas de post-filtrage.

### 4.1.1 Détection de Dérive Progressive (non bloquant)

Même si tous les documents passent le seuil, une **tendance** peut être mauvaise :

```python
# Exemple de dérive inquiétante (tout "OK" mais tendance mauvaise) :
# Doc 1 : 28 concepts
# Doc 2 : 34 concepts
# Doc 3 : 48 concepts
# Doc 4 : 57 concepts (hostile!)

def compute_concept_density(concept_count: int, doc_length_chars: int) -> float:
    """Concepts par 1000 caractères - signal de dérive"""
    return concept_count / (doc_length_chars / 1000)
```

> **Usage** : Non bloquant, mais à reporter. Si density augmente sur les 4 docs → signal d'alerte.

### 4.2 Validation des Anchors

```python
# anchor_validator.py

class AnchorValidator:
    def validate_all(self, informations: List[Information], chunks: Dict[str, str]) -> float:
        valid = 0
        for info in informations:
            try:
                chunk_text = chunks[info.anchor.chunk_id]
                extracted = chunk_text[info.anchor.start_char:info.anchor.end_char]
                if len(extracted) > 10:  # Au moins 10 chars
                    valid += 1
            except:
                pass
        return valid / len(informations) if informations else 0
```

### 4.3 Détection de Redondance

```python
# redundancy_checker.py

class RedundancyChecker:
    def __init__(self, embedding_model):
        self.model = embedding_model
        self.SIMILARITY_THRESHOLD = 0.92  # Très proche = redondant

    def check_redundancy(self, informations: List[Information], chunks: Dict) -> float:
        """Retourne le % d'Information redondantes"""
        texts = [self._get_text(info, chunks) for info in informations]
        embeddings = self.model.encode(texts)

        redundant_count = 0
        for i, emb_i in enumerate(embeddings):
            for j, emb_j in enumerate(embeddings[i+1:], i+1):
                similarity = cosine_similarity(emb_i, emb_j)
                if similarity > self.SIMILARITY_THRESHOLD:
                    redundant_count += 1
                    break  # Compter chaque info une seule fois

        return redundant_count / len(informations)
```

---

## 5. Phases d'Extraction

### Phase 1.1 : Analyse Globale + Justification Structure

**Output requis** (avec justification négative) :

```json
{
  "subject": "Architecture de sécurité de RISE with SAP",
  "dependency_structure": {
    "chosen": "CENTRAL",
    "justification": "Toutes les assertions sur FWaaS, IPSec, Pacemaker n'ont de sens que dans le contexte de RISE. Sans RISE, ces informations sont inapplicables.",
    "rejected": {
      "TRANSVERSAL": "Les concepts décrits (FWaaS, Pacemaker) sont spécifiques à RISE, pas des pratiques génériques applicables ailleurs.",
      "CONTEXTUAL": "Le document ne présente pas principalement des conditions/options mais décrit un système complet."
    }
  },
  "themes": [...]
}
```

**Prompt Qwen 14B** (extrait) :
```
Tu dois OBLIGATOIREMENT fournir :
1. La structure choisie (CENTRAL, TRANSVERSAL, ou CONTEXTUAL)
2. Une justification de ce choix (2-3 phrases)
3. Pour CHAQUE structure NON choisie, expliquer POURQUOI elle ne convient pas

Si tu ne peux pas justifier le rejet des alternatives, réponds "UNDECIDED".
```

### Phase 1.2 : Concepts Frugaux + Signal de Refus

> **⚠️ RÈGLE CRITIQUE POUR LES PROMPTS** : Ne JAMAIS mentionner la cible "20-50 concepts" dans les prompts.
> Qwen 14B a tendance à "remplir les quotas" si on donne des chiffres.
> → Rappeler uniquement les **critères qualitatifs** (récurrence, types variés, centralité).
> → Le LLM doit **découvrir** qu'il y a ~30 concepts, pas "viser" 30.

**Output requis** :

```json
{
  "concepts": [...],
  "refused_terms": [
    {"term": "cloud", "reason": "Trop générique, pas d'information spécifique attachée"},
    {"term": "security", "reason": "Terme parapluie, couvert par les themes"}
  ],
  "concept_count": 32
}
```

> **Signal de maturité** : Le LLM doit expliciter ce qu'il **refuse** de promouvoir en concept.

### Phase 1.3 : Information + Anchors

Inchangé, mais avec validation anchor systématique.

---

## 6. Micro-Usage Simulé (NOUVEAU)

### Objectif

Valider que la structure produite est **utilisable**, pas juste "belle".

### Test 1 : Composition simple

```python
# usage_simulator.py

def test_compose_paragraph(structure: DocumentStructure, concept_names: List[str]) -> str:
    """
    Demande au LLM de composer un paragraphe à partir de 3 concepts.
    Vérifie que le résultat utilise UNIQUEMENT les Information liées.
    """
    # Récupérer les Information des concepts demandés
    relevant_infos = get_infos_for_concepts(structure, concept_names)

    # Demander au LLM de composer
    prompt = f"""
    À partir des informations suivantes UNIQUEMENT, compose un paragraphe explicatif.

    Informations disponibles :
    {format_infos(relevant_infos)}

    RÈGLE : Tu ne peux utiliser QUE ces informations. Aucune invention.
    """

    result = llm.generate(prompt)

    # Vérifier que le résultat est traçable
    return validate_traceability(result, relevant_infos)
```

### Test 2 : Question factuelle

```python
def test_factual_question(structure: DocumentStructure, question: str) -> dict:
    """
    Pose une question factuelle et vérifie que la réponse est ancrée.
    """
    # Ex: "Quelles sont les options de haute disponibilité ?"

    # Trouver les Information pertinentes
    relevant = search_by_theme_and_type(structure, "High Availability", ["OPTION", "CAPABILITY"])

    if not relevant:
        return {"answer": "NON DOCUMENTÉ", "status": "correct_refusal"}

    # Générer réponse
    answer = compose_from_infos(relevant)

    return {"answer": answer, "sources": [i.id for i in relevant], "status": "answered"}
```

### Critères de succès micro-usage

| Test | Succès | Échec |
|------|--------|-------|
| Composition 3 concepts | Paragraphe cohérent, 100% traçable | Invention ou incohérence |
| Question factuelle | Réponse ancrée OU refus explicite | Hallucination |

---

## 7. Métriques de Succès (Révisées)

### Métriques quantitatives

| Métrique | Cible | Acceptable | FAIL immédiat |
|----------|-------|------------|---------------|
| Concepts par document | 20-50 | 10-60 | **>60** |
| Information par document | 200-500 | 100-800 | <50 |
| Info moyenne par concept | 5-15 | 3-20 | <2 |
| Anchors fonctionnels | ≥95% | ≥85% | <80% |
| **Redondance Information** | <10% | <20% | >30% |
| **Refusals documentés** | ≥5 par doc | ≥2 | 0 (suspect) |
| **Concept density** | - | - | Tendance croissante = alerte |

### Métriques micro-usage (à reporter explicitement)

| Métrique | Description |
|----------|-------------|
| Taux de refus correct | Nb de "NON DOCUMENTÉ" légitimes / total questions |
| Taux de réponse | Nb de réponses ancrées / total questions |

> **Le taux de refus n'est PAS un échec** — c'est une **mesure de maturité**. Un système qui refuse correctement est plus fiable qu'un système qui répond toujours.

### Métriques qualitatives

| Critère | Validation |
|---------|------------|
| Structure justifiée avec rejets | Oui obligatoire |
| Document hostile correctement traité | Refus ou <10 concepts |
| Micro-usage fonctionnel | 2/2 tests passent |

---

## 8. Plan d'Exécution (Révisé)

### Étape 0 : Préparation (J0)

- [ ] Purger Qdrant collection existante
- [ ] Purger Neo4j (ou créer tenant_id "poc_v2")
- [ ] Sélectionner 4 documents (dont 1 hostile)
- [ ] Configurer accès Qwen 14B (EC2)

### Étape 1 : Setup Code (J1)

- [ ] Créer structure `poc/`
- [ ] Implémenter modèles Pydantic avec validateurs
- [ ] Implémenter garde-fous (frugality, anchors, redundancy)
- [ ] Configurer prompts Qwen 14B

### Étape 2 : Phase 1.1 - Analyse Globale (J2)

- [ ] Implémenter `document_analyzer.py`
- [ ] Tester sur 4 documents
- [ ] **Vérifier** : Justifications + rejets présents

### Étape 3 : Phase 1.2 - Concepts (J3)

- [ ] Implémenter `concept_identifier.py`
- [ ] Tester sur 4 documents
- [ ] **Vérifier** : Coupe-circuit frugalité fonctionne
- [ ] **Vérifier** : Document hostile = <10 concepts ou refus

### Étape 4 : Phase 1.3 - Information (J4)

- [ ] Implémenter `information_extractor.py`
- [ ] Stocker chunks dans Qdrant
- [ ] **Vérifier** : Anchors valides ≥95%
- [ ] **Vérifier** : Redondance <20%

### Étape 5 : Micro-Usage (J5)

- [ ] Implémenter `usage_simulator.py`
- [ ] Test composition 3 concepts
- [ ] Test question factuelle
- [ ] **Vérifier** : Traçabilité 100%

### Étape 6 : Validation Finale (J6)

- [ ] Calculer toutes métriques
- [ ] Rédiger rapport `poc_report.md`
- [ ] Décision GO/NO-GO/PIVOT

---

## 9. Critères GO/NO-GO (Révisés)

### GO (continuer vers intégration)

- [ ] 4 documents traités sans FAIL
- [ ] Document hostile correctement géré (refus ou <10 concepts)
- [ ] Métriques quantitatives dans zone acceptable
- [ ] Justifications structure présentes et cohérentes
- [ ] Micro-usage : 2/2 tests passent
- [ ] Redondance <20%

### NO-GO (retour à l'ADR)

- Coupe-circuit frugalité déclenché (>60 concepts)
- Document hostile sur-structuré (>30 concepts)
- Anchors <80%
- Micro-usage échoue (hallucinations)
- Aucun refusal documenté (LLM ne filtre pas)

### PIVOT (ajustements)

- Ajuster prompts Qwen 14B si frugalité limite
- Ajuster chunking si anchors imprécis
- Revoir seuils si edge cases

---

## 10. Risques et Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Qwen 14B moins performant que GPT-4 | Qualité extraction | Prompts très explicites, few-shot examples |
| Sur-structuration malgré prompts | FAIL POC | Coupe-circuit dur + doc hostile |
| Anchors imprécis | Info non retrouvable | Validation systématique + ajustement chunking |
| Redondance élevée | Bruit inutilisable | Détection + déduplication |
| Faux positif "ça marche" | Mauvaise décision | Micro-usage obligatoire |

---

## Historique

| Date | Modification |
|------|--------------|
| 2025-01-23 | Création v1.0 |
| 2025-01-23 | v1.1 - Intégration feedback ChatGPT : 4 docs, coupe-circuits, justifications, micro-usage |
| 2025-01-23 | v1.2 - Ajustements finaux : concept_density, règle prompts sans chiffres, critères doc hostile, taux de refus |
| 2025-01-23 | v1.3 - Documents confirmés (SAP GDPR, CNIL GDPR, Euro NCAP SA, Euro NCAP VRU) + briques réutilisables clarifiées |


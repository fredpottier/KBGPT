# OSMOSE - Modèle de Maturité Cognitive

*Document de réflexion stratégique - À revisiter après validation PR1-4*
*Date: Janvier 2026*

---

## Vision

> **"OSMOSE : le cortex documentaire qui sait ce qu'il sait… et sait quand se taire."**

Cette phrase capture l'essence de ce qui différencie OSMOSE des systèmes RAG classiques : la **méta-cognition documentaire** - la capacité non seulement de répondre, mais de savoir QUAND et COMMENT répondre en fonction de la qualité de sa connaissance.

---

## 1. Modèle de Maturité Cognitive (5 Niveaux)

### Niveau 1 - Retrieval (RAG Basique)
- **Caractéristiques**: Recherche vectorielle simple, top-k documents
- **Comportement**: Répond toujours, même avec peu de pertinence
- **Limites**: Hallucinations fréquentes, pas de conscience de couverture

### Niveau 2 - Structured Retrieval (KG-Augmented)
- **Caractéristiques**: Knowledge Graph + vecteurs, relations typées
- **Comportement**: Meilleure précision factuelle
- **Limites**: Pas de conscience des conflits ou de l'évolution temporelle

### Niveau 3 - Contextual Intelligence ⬅️ **OSMOSE Actuel**
- **Caractéristiques**:
  - DocContextFrame (scope document, markers version)
  - AnchorContext (assertions qualifiées par document)
  - Consolidation ProtoConcept → CanonicalConcept
  - Memory Layer (sessions conversationnelles PostgreSQL)
- **Comportement**: Sait d'où vient l'information, peut qualifier sa confiance
- **En cours (PR1-4)**: Stockage assertions Neo4j, MarkerStore

### Niveau 4 - Cognitive Awareness (Cible Court Terme)
- **Caractéristiques**:
  - Cognitive Behavior Layer (décision HOW to respond)
  - Détection explicite des conflits inter-documents
  - Stratégies de réponse adaptatives
  - Auditabilité complète du raisonnement
- **Comportement**: Sait quand se taire, expose les conflits, demande clarification
- **Infrastructure existante**: Partiellement en place

### Niveau 5 - Cortex (Vision Long Terme)
- **Caractéristiques**:
  - Raisonnement multi-hop autonome
  - Génération d'hypothèses et validation
  - Apprentissage continu du corpus
  - Anticipation des besoins utilisateur
- **Comportement**: Vrai partenaire cognitif, pas seulement réactif

---

## 2. Cognitive Behavior Layer (Niveau 4)

### Concept

Le **Cognitive Behavior Layer** est un moteur de décision qui détermine non pas QUOI répondre, mais COMMENT répondre. Il analyse les signaux du système pour choisir une stratégie de réponse appropriée.

### Signaux d'Entrée

| Signal | Source | Description |
|--------|--------|-------------|
| `coverage_ratio` | Qdrant + Neo4j | % de la question couverte par les sources |
| `confidence_score` | AnchorContext | Confiance agrégée des assertions |
| `conflict_detected` | ConflictDetector | Présence de contradictions inter-documents |
| `temporal_gap` | MarkerStore | Écart entre versions documentaires |
| `assertion_count` | AssertionStore | Nombre d'assertions supportant la réponse |

### Stratégies de Réponse

```python
class ResponseStrategy(Enum):
    ADMIT_IGNORANCE = "admit_ignorance"      # Couverture < 30%
    EXPOSE_CONFLICT = "expose_conflict"       # Conflits détectés
    CLARIFY_FIRST = "clarify_first"          # Ambiguïté détectée
    CAUTIOUS_ANSWER = "cautious_answer"      # Confiance 50-80%
    CONFIDENT_ANSWER = "confident_answer"    # Confiance > 80%
```

### Pseudo-code du Moteur de Décision

```python
def determine_response_strategy(signals: CognitiveSignals) -> ResponseStrategy:
    # Priorité 1: Conflits explicites
    if signals.conflict_detected:
        return ResponseStrategy.EXPOSE_CONFLICT

    # Priorité 2: Couverture insuffisante
    if signals.coverage_ratio < 0.3:
        return ResponseStrategy.ADMIT_IGNORANCE

    # Priorité 3: Besoin de clarification
    if signals.ambiguity_score > 0.5:
        return ResponseStrategy.CLARIFY_FIRST

    # Priorité 4: Réponse nuancée selon confiance
    if signals.confidence_score > 0.8 and signals.assertion_count >= 3:
        return ResponseStrategy.CONFIDENT_ANSWER
    else:
        return ResponseStrategy.CAUTIOUS_ANSWER
```

### Templates de Réponse par Stratégie

| Stratégie | Préfixe Type |
|-----------|--------------|
| ADMIT_IGNORANCE | "Je n'ai pas trouvé d'information fiable sur ce sujet dans ma base documentaire..." |
| EXPOSE_CONFLICT | "Attention : j'ai identifié des informations contradictoires entre [Doc A] et [Doc B]..." |
| CLARIFY_FIRST | "Pour vous répondre précisément, pourriez-vous préciser si vous parlez de [version X] ou [version Y]..." |
| CAUTIOUS_ANSWER | "D'après mes sources (confiance modérée), voici ce que j'ai trouvé..." |
| CONFIDENT_ANSWER | "Voici la réponse consolidée à partir de [N] sources concordantes..." |

---

## 3. Capacités OSMOSE Existantes (Analyse)

### Ce qui existe déjà

| Capacité | Implémentation | Fichiers |
|----------|----------------|----------|
| **Memory Layer** | Sessions PostgreSQL, historique conversations | `sessions.py`, `memory_layer/` |
| **Auditabilité** | Panel sources, thumbnails, raisonnement dans synthèse | `SearchResultDisplay.tsx`, `SourcesSection.tsx` |
| **Consolidation** | ProtoConcept → CanonicalConcept, Entity Resolution | `consolidation/`, `entity_resolution/` |
| **Conflits (base)** | CONTRADICTS, OVERRIDES, OUTDATED sur Facts | `facts.py`, `conflict_detector.py` |
| **Context Documentaire** | DocContextFrame, AnchorContext (PR1-4) | `context/models.py`, `anchor_context.py` |

### Ce qui manque pour Niveau 4

| Capacité | Status | Priorité |
|----------|--------|----------|
| Cognitive Behavior Layer | Non implémenté | Haute |
| Coverage Ratio Calculation | Partiel (scores Qdrant) | Moyenne |
| Conflict Detection Cross-Doc | Infrastructure en place, pas de surface | Haute |
| Response Strategy Engine | Non implémenté | Haute |
| Clarification Triggers | Non implémenté | Moyenne |

---

## 4. Différenciation vs Concurrents

### Microsoft Copilot / Google Gemini

| Aspect | Copilot/Gemini | OSMOSE |
|--------|----------------|--------|
| Approche | RAG généraliste, confiance aveugle | Méta-cognition, conscience des limites |
| Conflits | Ignorés ou moyennés | Exposés explicitement |
| Versions | Non gérées | Markers, timeline, scope |
| Auditabilité | Limitée | Sources, thumbnails, raisonnement |
| Spécialisation | Généraliste | Domain-agnostic mais corpus-aware |

### USP OSMOSE

> "Le premier système RAG qui sait quand il ne sait pas"

- **Transparence cognitive**: Expose ses incertitudes
- **Gestion des versions**: Comprend l'évolution documentaire
- **Consolidation intelligente**: Ne mélange pas les sources contradictoires
- **Auditabilité native**: Chaque réponse traçable jusqu'aux sources

---

## 5. Roadmap Cognitive (Post PR1-4)

### Phase 2.15 - Cognitive Behavior Layer (Proposé)

1. **CoverageCalculator**
   - Analyser la couverture question/réponse
   - Intégrer scores Qdrant + count Neo4j

2. **ConflictSurfacer**
   - Exposer les conflits dans l'API search
   - Ajouter `conflicts[]` dans SearchResponse

3. **ResponseStrategyEngine**
   - Implémenter le moteur de décision
   - Templates de réponse par stratégie

4. **ClarificationDetector**
   - Détecter les questions ambiguës (multi-version, multi-scope)
   - Générer des questions de clarification

### Phase 2.16 - Intelligence Avancée (Future)

- Raisonnement multi-hop avec traces
- Hypothèses et validation automatique
- Learning continu du corpus

---

## 6. Discussion Claude × ChatGPT (Résumé)

### Proposition ChatGPT - Fonctions Cognitives

ChatGPT a proposé 8 fonctions cognitives pour un "cortex documentaire":

1. **Coverage Awareness** - Savoir si le corpus couvre la question
2. **Confidence Calibration** - Niveau de certitude de la réponse
3. **Conflict Detection** - Identifier contradictions
4. **Temporal Intelligence** - Comprendre évolution versions
5. **Clarification Engine** - Demander précisions si ambiguïté
6. **Reasoning Trace** - Expliquer le raisonnement
7. **Knowledge Gaps** - Identifier ce qui manque
8. **Contextual Memory** - Se souvenir des conversations

### Analyse Claude

- **Fonctions 6-8**: Déjà implémentées (Memory Layer, Auditabilité)
- **Fonctions 1-5**: Infrastructure partiellement en place avec PR1-4
- **Gap principal**: Le Cognitive Behavior Layer qui orchestre tout

### Consensus

OSMOSE est solidement au **Niveau 3** avec l'infrastructure pour atteindre le **Niveau 4**. La pièce manquante est le **moteur de décision comportemental** qui transforme les signaux en stratégies de réponse.

---

## 7. Métriques de Succès (Niveau 4)

| Métrique | Cible | Mesure |
|----------|-------|--------|
| Taux d'aveu d'ignorance | > 10% quand approprié | Réponses ADMIT_IGNORANCE |
| Conflits exposés | 100% détectés | Conflits surfacés vs existants |
| Satisfaction clarification | > 80% | Feedback utilisateur |
| Confiance calibrée | Corrélation > 0.8 | Confidence vs exactitude |

---

## 8. Prochaines Étapes

1. **Immédiat**: Valider PR1-4 (DocContext, AnchorContext, MarkerStore, AssertionStore)
2. **Court terme**: Spécifier ADR pour Cognitive Behavior Layer
3. **Moyen terme**: Implémenter Phase 2.15
4. **Long terme**: Évoluer vers Niveau 5 (Cortex)

---

*Ce document sera mis à jour après validation PR1-4 et servira de base pour la spécification du Cognitive Behavior Layer.*

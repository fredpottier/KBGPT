# Phase 1.5 - Architecture Agentique V1.1

**Status**: 🟢 IMPLÉMENTÉ (Sem 11 Jour 1-2)
**Date**: 2025-10-15
**Version**: 1.1.0
**Objectif**: Maîtrise coûts LLM + scalabilité production via 6 agents spécialisés

---

## 🎯 Objectifs Phase 1.5

### Problèmes Phase 1 V2.1
- ❌ **Coûts LLM non maîtrisés**: LLM appelé systématiquement sans routing
- ❌ **Qualité concepts insuffisante**: Definitions vides, typage ENTITY uniquement
- ❌ **Pas de rate limiting**: Risque dépassement quotas OpenAI
- ❌ **Pas de retry logic**: Échecs LLM = perte définitive
- ❌ **Pas de multi-tenant**: Isolation budgets/tenant absente

### Solutions Phase 1.5
- ✅ **Routing intelligent**: NO_LLM/SMALL/BIG selon densité entities
- ✅ **Quality gates**: GatekeeperDelegate avec 3 profils (STRICT/BALANCED/PERMISSIVE)
- ✅ **Rate limiting**: 500/100/50 RPM (SMALL/BIG/VISION)
- ✅ **Retry policy**: 1 retry max avec BIG model si Gate < 30% promoted
- ✅ **Multi-tenant budgets**: Caps document + quotas jour/tenant

---

## 📖 Comprendre l'Architecture Agentique - Vue d'Ensemble

### Qu'est-ce qu'une architecture agentique ?

Imaginez une entreprise où chaque employé a un rôle spécialisé : un directeur orchestre le travail, un comptable gère le budget, un contrôleur qualité vérifie les résultats, etc. C'est exactement le principe de notre architecture agentique !

Au lieu d'avoir un seul programme qui fait tout (ce qui rend difficile la gestion des coûts et de la qualité), nous avons créé **6 agents spécialisés** qui travaillent ensemble comme une équipe coordonnée.

### Pourquoi cette approche ?

**Analogie simple** : C'est comme préparer un repas gastronomique :
- Avant (Phase 1) : Un seul cuisinier fait tout → coûteux, lent, qualité variable
- Maintenant (Phase 1.5) : Une brigade avec chef, sous-chef, pâtissier, etc. → efficace, rapide, qualité contrôlée

**Bénéfices concrets** :
1. **Contrôle des coûts** : Chaque agent surveille ce qu'il dépense (comme un budget départemental)
2. **Qualité garantie** : Un agent dédié vérifie la qualité (comme un contrôle qualité en usine)
3. **Résilience** : Si une étape échoue, on peut réessayer intelligemment (comme un plan B)
4. **Scalabilité** : Chaque agent peut être optimisé indépendamment (comme améliorer un poste de travail)

---

## 🏗️ Architecture: 6 Agents Spécialisés

### Architecture FSM (Finite State Machine)

```
┌─────────────────────────────────────────────────────────────┐
│                    SUPERVISOR AGENT (FSM Master)             │
│  INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS    │
│         → GATE_CHECK → PROMOTE → FINALIZE → DONE            │
└──────┬─────────────┬────────────┬───────────┬───────────────┘
       │             │            │           │
       ▼             ▼            ▼           ▼
  ┌─────────┐  ┌─────────────┐ ┌──────────┐ ┌──────────────┐
  │ BUDGET  │  │  EXTRACTOR  │ │  MINER   │ │  GATEKEEPER  │
  │ MANAGER │  │ORCHESTRATOR │ │          │ │   DELEGATE   │
  └─────────┘  └─────────────┘ └──────────┘ └──────────────┘
       │             │                             │
       └─────────────┼─────────────────────────────┘
                     ▼
              ┌─────────────┐
              │     LLM     │
              │  DISPATCHER │
              └─────────────┘
```

### 🎭 Le Parcours d'un Document - En Termes Simples

Imaginez qu'un document arrive dans notre système. Voici son voyage à travers les 6 agents :

**1. SupervisorAgent (Le Chef d'Orchestre)** 🎼
- Rôle : Coordonne toute l'équipe
- Analogie : Le chef de projet qui dit "Maintenant, on fait ça, puis ça"
- Décisions : Vérifie que chaque étape se passe bien, gère les erreurs

**2. BudgetManager (Le Comptable)** 💰
- Rôle : Surveille les dépenses
- Analogie : Le contrôleur de gestion qui dit "Attention, il nous reste 50€ sur 100€"
- Décisions : Autorise ou refuse les appels coûteux selon le budget restant

**3. ExtractorOrchestrator (L'Analyste Intelligent)** 🧠
- Rôle : Décide comment extraire les concepts
- Analogie : Le médecin qui choisit entre une radio, un scanner ou une IRM selon les symptômes
- Décisions : "Ce paragraphe est simple → pas besoin d'IA puissante" ou "C'est complexe → utilisons le meilleur modèle"

**4. PatternMiner (Le Détective)** 🔍
- Rôle : Trouve les répétitions et les liens entre concepts
- Analogie : Le détective qui remarque "Tiens, ce nom revient 5 fois dans le dossier, c'est important !"
- Décisions : Enrichit les concepts avec des informations de contexte

**5. GatekeeperDelegate (Le Contrôleur Qualité)** ✅
- Rôle : Filtre les résultats de mauvaise qualité
- Analogie : L'inspecteur qualité qui dit "Ça, c'est bon, ça, c'est à jeter"
- Décisions : N'accepte que les concepts bien formés et pertinents

**6. LLMDispatcher (Le Régulateur de Traffic)** 🚦
- Rôle : Évite la surcharge des appels IA
- Analogie : Le contrôleur aérien qui espace les décollages pour éviter les embouteillages
- Décisions : "Attends ton tour, il y a trop d'appels en cours"

---

## 🤖 Les 6 Agents Expliqués en Détail

### 1. SupervisorAgent (FSM Master)

**Fichier**: `src/knowbase/agents/supervisor/supervisor.py`
**Config**: `config/agents/supervisor.yaml`

#### 📋 Vue Technique

**Responsabilités**:
- Orchestration FSM stricte (10 états: INIT → DONE)
- Timeout enforcement (adaptatif : 60s/segment, max 30min)
- Max steps enforcement (50 steps/doc)
- Error handling avec état ERROR
- Retry logic (1 retry max avec BIG si Gate < 30%)

**FSM States**:
```python
class FSMState(str, Enum):
    INIT = "init"
    BUDGET_CHECK = "budget_check"
    SEGMENT = "segment"
    EXTRACT = "extract"
    MINE_PATTERNS = "mine_patterns"
    GATE_CHECK = "gate_check"
    PROMOTE = "promote"
    FINALIZE = "finalize"
    ERROR = "error"
    DONE = "done"
```

**FSM Transitions**:
- `INIT → BUDGET_CHECK`
- `BUDGET_CHECK → SEGMENT | ERROR`
- `SEGMENT → EXTRACT | ERROR`
- `EXTRACT → MINE_PATTERNS | ERROR`
- `MINE_PATTERNS → GATE_CHECK | ERROR`
- `GATE_CHECK → PROMOTE | EXTRACT (retry) | ERROR`
- `PROMOTE → FINALIZE | ERROR`
- `FINALIZE → DONE | ERROR`
- `ERROR → DONE` (terminal)

**Metrics**:
- `steps_count`: Nombre d'étapes FSM
- `cost_incurred`: Coût total accumulé ($)
- `llm_calls_count`: Compteur par tier (SMALL/BIG/VISION)

#### 🌟 Explication Simple

**Le SupervisorAgent est comme un chef de projet qui suit un plan très précis.**

**Analogie** : Imaginez la préparation d'un mariage :
1. **INIT** : "Bon, on commence l'organisation"
2. **BUDGET_CHECK** : "Vérifions qu'on a assez d'argent"
3. **SEGMENT** : "Divisons les tâches : déco, traiteur, musique"
4. **EXTRACT** : "Pour chaque tâche, trouvons les bons prestataires"
5. **MINE_PATTERNS** : "Oh, ce traiteur et ce fleuriste travaillent souvent ensemble, notons ça"
6. **GATE_CHECK** : "Éliminons les prestataires pas sérieux"
7. **PROMOTE** : "Validons les prestataires retenus"
8. **FINALIZE** : "Calculons le coût final"
9. **DONE** : "C'est prêt !"

**Si quelque chose se passe mal** (par exemple, pas assez de budget), le Supervisor peut :
- Passer en état **ERROR** : "Stop, il y a un problème"
- Ou faire un **RETRY** : "Essayons avec une approche plus économique"

**Protection contre les boucles infinies** :
- **Timeout adaptatif** : Si le document a 10 sections, on donne 13 minutes (780s). Si 50 sections, on donne 30 minutes max.
- **Max 50 étapes** : Si on dépasse, c'est qu'il y a un bug, on arrête.

**Exemple concret** :
```
Document : PowerPoint de 10 slides
- Timeout calculé : 780 secondes (13 minutes)
- Étapes réelles : 8 étapes (INIT → DONE)
- Temps réel : 305 secondes (5 minutes)
- Résultat : ✅ Succès, avec 8 minutes de marge
```

---

### 2. ExtractorOrchestrator (Routing Agent)

**Fichier**: `src/knowbase/agents/extractor/orchestrator.py`
**Config**: `config/agents/routing_policies.yaml`

#### 📋 Vue Technique

**Responsabilités**:
- Analyse segments avec **PrepassAnalyzer** (NER spaCy)
- Route vers NO_LLM/SMALL/BIG selon densité entities
- Extraction concepts avec budget awareness
- Fallback graceful (BIG → SMALL → NO_LLM)

**Routing Logic**:
```python
if entity_count < 3:
    route = NO_LLM  # NER + Clustering uniquement
elif entity_count <= 8:
    route = SMALL   # gpt-4o-mini
else:
    route = BIG     # gpt-4o
```

**Fallback Chain**:
1. Si `budget_remaining["BIG"] == 0` → fallback SMALL
2. Si `budget_remaining["SMALL"] == 0` → fallback NO_LLM
3. NO_LLM toujours disponible (pas de coût)

**Tools**:
- `prepass_analyzer`: NER spaCy pour routing
- `extract_concepts`: Extraction avec route choisie

#### 🌟 Explication Simple

**L'ExtractorOrchestrator est comme un médecin qui choisit le bon examen médical.**

**Analogie médecale** :
- **Patient avec mal de tête léger** → Examen basique (pas d'IRM) = **NO_LLM**
- **Patient avec symptômes moyens** → Scanner standard = **SMALL** (gpt-4o-mini, économique)
- **Patient avec symptômes complexes** → IRM haute résolution = **BIG** (gpt-4o, précis mais cher)

**Le processus en détail** :

**Étape 1 - Pré-analyse rapide** (gratuite, instantanée) :
```
Texte : "SAP ERP est un logiciel de gestion intégré."
Pré-analyse détecte : 3 entités (SAP, ERP, logiciel de gestion)
→ Décision : "C'est simple, pas besoin d'IA puissante"
```

**Étape 2 - Routage intelligent** :
- **Scénario A** : 2 entités trouvées → **NO_LLM** (extraction basique, gratuit, 0.5s)
- **Scénario B** : 5 entités trouvées → **SMALL** (extraction économique, $0.002, 1.5s)
- **Scénario C** : 15 entités trouvées → **BIG** (extraction premium, $0.015, 2s)

**Étape 3 - Plan B si budget épuisé** :
```
Budget restant BIG : 0 calls
→ "Pas de budget pour BIG, je bascule sur SMALL"
→ Si SMALL aussi épuisé : "Je bascule sur NO_LLM (gratuit)"
```

**Exemple concret** :
```
Document : 10 sections de complexité variable

Section 1 : "Introduction" (2 entités)
→ Route : NO_LLM, coût : $0, temps : 0.5s

Section 2 : "Architecture technique" (12 entités)
→ Route : BIG, coût : $0.015, temps : 2s

Section 3 : "Conclusion" (3 entités)
→ Route : SMALL, coût : $0.002, temps : 1.5s

Total : $0.017 au lieu de $0.150 si on avait utilisé BIG partout
Économie : 88% !
```

---

### 3. PatternMiner (Cross-Segment Reasoning)

**Fichier**: `src/knowbase/agents/miner/miner.py`

#### 📋 Vue Technique

**Responsabilités**:
- Détection patterns récurrents (frequency ≥ 2)
- Co-occurrence analysis (concepts même segment)
- Hierarchy inference (parent-child relations)
- Named Entity disambiguation

**Algorithmes**:
1. **Frequency analysis**: Count occurrences cross-segments
2. **Pattern scoring**: `pattern_score = freq / total_segments`
3. **Co-occurrence**: Lie concepts dans même segment
4. **Hierarchy inference**: Détecte relations parent-child

**Output**:
- Enrichit `state.candidates` avec:
  - `pattern_score`: float (0-1)
  - `frequency`: int
  - `related_concepts`: List[str]

**Tools**:
- `detect_patterns`: Détecte patterns récurrents
- `link_concepts`: Créer relations CO_OCCURRENCE

#### 🌟 Explication Simple

**Le PatternMiner est comme un détective qui relie les indices.**

**Analogie policière** :
Imaginez une enquête avec 10 témoignages différents. Le PatternMiner remarque :
- "Tiens, ce suspect est mentionné dans 7 témoignages sur 10 → important !"
- "Ce suspect et cette voiture apparaissent toujours ensemble → ils sont liés"
- "Le patron de l'entreprise est toujours cité avec l'entreprise → relation hiérarchique"

**Ce qu'il fait concrètement** :

**1. Détection de fréquence** :
```
Document découpé en 10 sections
Concept "SAP S/4HANA" apparaît dans 8 sections
→ pattern_score = 8/10 = 0.8
→ Conclusion : "C'est un concept central du document"
```

**2. Co-occurrence (qui apparaît avec qui ?)** :
```
Section 1 : SAP, ERP, Gestion financière
Section 2 : SAP, ERP, Comptabilité
Section 3 : SAP, CRM, Ventes
→ Liens détectés :
  - SAP ↔ ERP (apparaissent ensemble 2 fois)
  - SAP ↔ Gestion financière
  - SAP ↔ CRM
```

**3. Hiérarchie (qui dépend de qui ?)** :
```
"SAP" apparaît dans 10 sections
"SAP S/4HANA" apparaît dans 5 sections (toujours quand "SAP" est là)
→ Inférence : S/4HANA est une sous-catégorie de SAP
→ Relation : SAP (parent) → S/4HANA (enfant)
```

**Exemple concret** :
```
Document : Guide SAP de 50 pages

Avant PatternMiner :
- 150 concepts extraits
- Aucun lien entre eux
- Tous au même niveau

Après PatternMiner :
- 150 concepts enrichis
- 87 relations de co-occurrence
- 23 relations hiérarchiques
- Scores de pertinence (0-1)

Résultat : Le Knowledge Graph est maintenant structuré et navigable !
```

---

### 4. GatekeeperDelegate (Quality Control)

**Fichier**: `src/knowbase/agents/gatekeeper/gatekeeper.py`
**Config**: `config/agents/gate_profiles.yaml`

#### 📋 Vue Technique

**Responsabilités**:
- Score candidates selon Gate Profile (STRICT/BALANCED/PERMISSIVE)
- Promeut concepts ≥ seuil vers Neo4j Published
- Rejette fragments, stopwords, PII
- Recommande retry si promotion_rate < 30%

**Gate Profiles**:

| Profil       | min_confidence | required_fields        | min_promotion_rate |
|--------------|----------------|------------------------|-------------------|
| STRICT       | 0.85           | name, type, definition | 50%               |
| BALANCED     | 0.70           | name, type             | 30%               |
| PERMISSIVE   | 0.60           | name                   | 20%               |

**Hard Rejections**:
- Nom < 3 chars ou > 100 chars
- Stopwords (the, and, or, le, de, etc.)
- Fragments (ized, ial, ing, tion)
- PII patterns (email, phone, SSN, credit card)

**Tools**:
- `gate_check`: Score et filtre candidates
- `promote_concepts`: Promotion Neo4j Proto→Published

#### 🌟 Explication Simple

**Le GatekeeperDelegate est comme un inspecteur qualité à l'usine.**

**Analogie industrielle** :
Imaginez une usine de production de pièces. À la fin de la chaîne, un inspecteur vérifie chaque pièce :
- ✅ **Conforme** : Va dans le stock "produits finis"
- ❌ **Défectueuse** : Va au rebut
- 🔄 **Limite** : Selon le profil qualité, accepté ou refusé

**Les 3 profils qualité** :

**1. STRICT (Haute Exigence)** :
```
Utilisé pour : Documents officiels, documentation technique
Critères :
- Confiance ≥ 85%
- Doit avoir : nom, type, définition complète
- Accepte seulement si ≥ 50% des candidats sont bons

Exemple :
Concept : "SAP S/4HANA"
- Nom : ✅ "SAP S/4HANA"
- Type : ✅ "Produit logiciel"
- Définition : ✅ "Système ERP de nouvelle génération..."
- Confiance : ✅ 0.92
→ ACCEPTÉ

Concept : "système"
- Nom : ✅ "système"
- Type : ❌ manquant
- Définition : ❌ manquant
- Confiance : ❓ 0.65
→ REJETÉ (pas assez complet)
```

**2. BALANCED (Standard)** :
```
Utilisé pour : Documents d'entreprise standard
Critères :
- Confiance ≥ 70%
- Doit avoir : nom, type (définition optionnelle)
- Accepte si ≥ 30% des candidats sont bons

Exemple :
Concept : "ERP"
- Nom : ✅ "ERP"
- Type : ✅ "Type de logiciel"
- Définition : ❌ manquant (mais pas obligatoire)
- Confiance : ✅ 0.75
→ ACCEPTÉ
```

**3. PERMISSIVE (Exploratoire)** :
```
Utilisé pour : Première exploration, documents brouillons
Critères :
- Confiance ≥ 60%
- Doit avoir : nom uniquement
- Accepte si ≥ 20% des candidats sont bons

Exemple :
Concept : "gestion"
- Nom : ✅ "gestion"
- Type : ❌ manquant
- Définition : ❌ manquant
- Confiance : ✅ 0.62
→ ACCEPTÉ (on explore)
```

**Hard Rejections (toujours rejetés)** :
```
❌ Trop court : "le", "un", "de" (< 3 caractères)
❌ Stopwords : "and", "or", "the", "mais", "donc"
❌ Fragments : "ized", "tion", "ment" (morceaux de mots)
❌ Données personnelles : "john.doe@email.com", "06 12 34 56 78"
```

**Système de retry intelligent** :
```
Situation : Extraction d'un document de 10 sections

Tentative 1 (avec SMALL) :
- 50 candidats extraits
- GateKeeper (BALANCED) accepte 12 concepts (24%)
- 24% < 30% minimum → qualité insuffisante

Décision du Supervisor :
→ "Qualité trop basse, on réessaie avec BIG model"

Tentative 2 (avec BIG) :
- 45 candidats extraits
- GateKeeper accepte 18 concepts (40%)
- 40% > 30% minimum → ✅ OK !
```

**Exemple concret** :
```
Document : Présentation SAP (27 candidats)

GateKeeper avec profil BALANCED :

Acceptés (23 concepts) :
✅ "SAP ERP" (0.89) - nom, type, définition
✅ "Finance" (0.76) - nom, type
✅ "Comptabilité générale" (0.82) - nom, type, définition
... (20 autres)

Rejetés (4 concepts) :
❌ "le" (stopword)
❌ "sys" (trop court, fragment)
❌ "gestion de la" (pas de type, confiance 0.45)
❌ "info@sap.com" (PII - donnée personnelle)

Résultat : 85% de promotion → ✅ Excellente qualité
```

---

### 5. BudgetManager (Caps & Quotas)

**Fichier**: `src/knowbase/agents/budget/budget.py`
**Config**: `config/agents/budget_limits.yaml`

#### 📋 Vue Technique

**Responsabilités**:
- Enforce caps durs par document
- Enforce quotas tenant/jour (Redis)
- Tracking temps-réel consommation
- Refund logic si retry échoue

**Caps Document**:
```yaml
SMALL: 120 calls/doc
BIG: 8 calls/doc
VISION: 2 calls/doc
```

**Quotas Tenant/Jour**:
```yaml
SMALL: 10,000 calls/jour/tenant
BIG: 500 calls/jour/tenant
VISION: 100 calls/jour/tenant
```

**Redis Keys**:
```
budget:tenant:{tenant_id}:SMALL:{date} → count calls
budget:tenant:{tenant_id}:BIG:{date} → count calls
budget:tenant:{tenant_id}:VISION:{date} → count calls
```

**TTL**: 24h (rolling window)

**Tools**:
- `check_budget`: Vérifie quotas disponibles
- `consume_budget`: Consomme après appel LLM
- `refund_budget`: Rembourse si retry échoue

#### 🌟 Explication Simple

**Le BudgetManager est comme un banquier qui surveille vos dépenses.**

**Analogie bancaire** :
Vous avez 2 types de limites :
1. **Limite par achat** : Vous ne pouvez pas dépenser plus de 100€ par achat
2. **Limite journalière** : Vous ne pouvez pas dépenser plus de 1000€ par jour

Le BudgetManager fait la même chose avec les appels IA :
1. **Limite par document** : Maximum 8 appels "BIG" par document
2. **Limite journalière par client** : Maximum 500 appels "BIG" par jour

**Double protection** :

**Niveau 1 - Par Document** :
```
Document en cours de traitement
Budget initial :
- SMALL : 120 appels autorisés
- BIG : 8 appels autorisés
- VISION : 2 appels autorisés

Section 1 : Utilise BIG → Reste 7 BIG
Section 2 : Utilise SMALL → Reste 119 SMALL
...
Section 8 : Utilise BIG → Reste 0 BIG

Section 9 : Veut utiliser BIG
→ ❌ Refusé : "Plus de budget BIG pour ce document"
→ ✅ Fallback : Utilise SMALL à la place
```

**Niveau 2 - Par Client/Jour** (stocké dans Redis) :
```
Client "Entreprise XYZ" - 15 octobre 2025
Quota journalier BIG : 500 appels

9h00 : 50 appels BIG utilisés → Reste 450
12h00 : 200 appels BIG utilisés → Reste 250
16h00 : 400 appels BIG utilisés → Reste 50
18h00 : Tentative d'utiliser 100 appels BIG
→ ❌ Refusé : "Quota journalier presque épuisé (reste 50)"

Le lendemain (16 octobre) :
→ ✅ Compteur remis à zéro : 500 appels disponibles
```

**Système de remboursement** :
```
Situation : Retry qui échoue

Tentative 1 :
- Utilise 1 appel BIG (coût : $0.015)
- Budget consommé : BIG = 1

Tentative échoue (erreur réseau)

Décision du système :
→ "Échec technique, ce n'est pas la faute de l'utilisateur"
→ Remboursement : Budget BIG = 0 (remboursé)
→ Coût remboursé : -$0.015
```

**Protection multi-tenant** :
```
Scénario : 3 clients utilisent le système

Client A (tenant_id: "client-a") :
- Quota BIG : 500 appels/jour
- Utilisé : 300 appels
- Reste : 200

Client B (tenant_id: "client-b") :
- Quota BIG : 500 appels/jour
- Utilisé : 450 appels
- Reste : 50

Client C (tenant_id: "client-c") :
- Quota BIG : 500 appels/jour
- Utilisé : 50 appels
- Reste : 450

→ Les budgets sont ISOLÉS : Client B ne peut pas "voler" le budget de Client C
```

**Exemple concret** :
```
Traitement d'un document PowerPoint de 10 slides

Avant traitement :
- Budget doc BIG : 8 appels
- Budget jour BIG : 450 appels (client XYZ)

Slide 1 (simple) : NO_LLM → Budget inchangé
Slide 2 (complexe) : BIG → Doc: 7, Jour: 449
Slide 3 (simple) : SMALL → Budget inchangé
Slide 4 (complexe) : BIG → Doc: 6, Jour: 448
...
Slide 10 (complexe) : BIG → Doc: 2, Jour: 444

Après traitement :
- Budget doc BIG : 2 appels restants
- Budget jour BIG : 444 appels restants
- Coût total : $0.090 (6 × $0.015)
```

---

### 6. LLMDispatcher (Rate Limiting)

**Fichier**: `src/knowbase/agents/dispatcher/dispatcher.py`

#### 📋 Vue Technique

**Responsabilités**:
- Rate limiting strict (500/100/50 RPM)
- Priority queue (P0 retry > P1 first pass > P2 batch)
- Concurrency control (10 calls max simultanées)
- Circuit breaker (suspend si error_rate > 30%)

**Rate Limits**:
```yaml
SMALL (gpt-4o-mini): 500 RPM
BIG (gpt-4o): 100 RPM
VISION (gpt-4o-vision): 50 RPM
```

**Priority Queue**:
- **P0 (RETRY)**: Retry après échec → priorité absolue
- **P1 (FIRST_PASS)**: Premier passage → priorité normale
- **P2 (BATCH)**: Traitement batch → basse priorité

**Circuit Breaker**:
- **CLOSED**: Normal operation
- **OPEN**: Error rate > 30%, suspend 60s
- **HALF_OPEN**: Test recovery après 60s

**Métriques**:
- Queue size par priorité
- Active calls count
- Total calls
- Error rate (sliding window 100 calls)

**Tools**:
- `dispatch_llm`: Enqueue et execute appel LLM
- `get_queue_stats`: Métriques temps-réel

#### 🌟 Explication Simple

**Le LLMDispatcher est comme un contrôleur de trafic aérien.**

**Analogie aéroportuaire** :
Imaginez un aéroport avec :
- **Limite d'atterrissages** : Maximum 100 avions par heure
- **File d'attente prioritaire** : Urgences médicales en premier
- **Limitation de piste** : Maximum 10 avions en approche simultanée
- **Suspension temporaire** : Si trop d'incidents, on ferme 1 heure

Le LLMDispatcher fait exactement ça avec les appels IA.

**Les 3 limites de protection** :

**1. Rate Limiting (appels par minute)** :
```
Limite OpenAI pour gpt-4o : 100 appels/minute

Sans LLMDispatcher :
→ On envoie 150 appels en 30 secondes
→ ❌ OpenAI bloque : "429 Too Many Requests"
→ ❌ Perte de 50 appels

Avec LLMDispatcher :
→ Il régule : "Stop, on a fait 100 appels en 1 minute"
→ Les 50 appels restants attendent 30 secondes
→ ✅ Tous les appels passent, aucune erreur
```

**2. Priority Queue (file d'attente intelligente)** :
```
3 types de requêtes avec priorités différentes :

P0 - RETRY (Priorité maximale) :
→ Un appel a échoué, on réessaie
→ Passe AVANT tout le monde
Exemple : Erreur réseau sur extraction slide 5
→ Réessai immédiat, pas d'attente

P1 - FIRST_PASS (Priorité normale) :
→ Traitement normal d'un nouveau document
→ Passe dans l'ordre d'arrivée
Exemple : Nouveau PowerPoint à traiter
→ Attend son tour

P2 - BATCH (Priorité basse) :
→ Traitement en masse de 100 documents
→ Passe quand il n'y a pas d'urgence
Exemple : Import nocturne de 50 PDF
→ S'exécute quand la charge est faible
```

**3. Concurrency Control (limite simultanée)** :
```
Maximum 10 appels IA en même temps

Situation : 15 appels arrivent simultanément
→ 10 premiers : ✅ Traitent immédiatement
→ 5 suivants : ⏳ Attendent qu'un slot se libère

Avantage :
- Évite de surcharger le serveur
- Garantit un temps de réponse stable
- Évite les timeouts
```

**Circuit Breaker (disjoncteur automatique)** :

Comme un disjoncteur électrique qui coupe le courant si trop de problèmes.

**État CLOSED (Normal)** :
```
100 derniers appels : 5 erreurs
Taux d'erreur : 5% < 30%
→ ✅ Tout va bien, on continue
```

**État OPEN (Problème détecté)** :
```
100 derniers appels : 35 erreurs
Taux d'erreur : 35% > 30%
→ ⚠️ Alerte : OpenAI a probablement un problème
→ 🚫 Suspension : On arrête d'envoyer des appels pendant 60s
→ Économie : On évite de gaspiller des appels qui vont échouer
```

**État HALF_OPEN (Test de récupération)** :
```
Après 60 secondes de pause :
→ 🔄 On envoie 1 appel test
→ Si succès : Circuit CLOSED, on reprend normalement
→ Si échec : Circuit OPEN, on attend encore 60s
```

**Exemple concret** :
```
Traitement de 50 documents en parallèle (batch nocturne)

Sans LLMDispatcher :
→ 500 appels BIG envoyés en 5 minutes
→ Limite OpenAI : 100/minute
→ ❌ 400 appels bloqués avec erreur 429
→ ❌ Documents en échec
→ Temps perdu : 30 minutes de retry

Avec LLMDispatcher :
→ 100 appels BIG/minute (respecte la limite)
→ Queue intelligente : P0 (retry) > P1 (normal) > P2 (batch)
→ Max 10 appels simultanés (évite surcharge)
→ ✅ Tous les appels passent
→ Temps total : 5 minutes (optimal)

Économie :
- 0 appel raté
- 0 retry gaspillé
- $0 de surcoût
```

**Dashboard temps-réel** :
```
LLMDispatcher Status - 15/10/2025 14:30

Queue Sizes :
- P0 (RETRY) : 2 appels
- P1 (FIRST_PASS) : 15 appels
- P2 (BATCH) : 45 appels

Active Calls : 10/10 (pleine charge)
Total Calls Today : 3,247
Error Rate : 2.3% (sliding window 100 calls)
Circuit Breaker : CLOSED ✅

Rate Limits :
- SMALL : 387/500 RPM (77%)
- BIG : 89/100 RPM (89%)
- VISION : 12/50 RPM (24%)
```

---

## 🔄 Scénario Complet : Traitement d'un Document

### Le Parcours d'un Document PowerPoint de 10 Slides

**Contexte** :
- Document : "SAP_Solution_Overview.pptx"
- Client : "Entreprise XYZ" (tenant_id: xyz)
- Heure : 15/10/2025 à 14h30
- Budget jour restant : BIG = 450 appels, SMALL = 8,500 appels

**Étape 0 : Initialisation (SupervisorAgent)** ⏱️ 0s
```
SupervisorAgent : "Nouveau document reçu"
État initial créé :
- document_id : SAP_Solution_Overview
- tenant_id : xyz
- budget_remaining : { SMALL: 120, BIG: 8, VISION: 2 }
- segments : []
- candidates : []
- promoted : []
- cost_incurred : $0
- started_at : 14:30:00

FSM : INIT → BUDGET_CHECK
```

**Étape 1 : Vérification Budget (BudgetManager)** ⏱️ 0.2s
```
BudgetManager : "Vérifie les quotas"

Check quotas tenant (Redis) :
- SMALL : 8,500/10,000 ✅
- BIG : 450/500 ✅
- VISION : 98/100 ✅

Check caps document :
- SMALL : 120/120 ✅
- BIG : 8/8 ✅
- VISION : 2/2 ✅

Résultat : ✅ Tous les budgets OK
FSM : BUDGET_CHECK → SEGMENT
```

**Étape 2 : Segmentation** ⏱️ 2s
```
TopicSegmenter : "Découpe le document"

Analyse :
- 10 slides détectées
- Regroupement thématique :
  * Slides 1-2 : Introduction (1 segment)
  * Slides 3-5 : Architecture technique (1 segment)
  * Slides 6-8 : Modules fonctionnels (1 segment)
  * Slides 9-10 : Conclusion (1 segment)

Résultat : 4 segments créés
Timeout adaptatif calculé : 120 + (60×4) + 60 = 420s (7 minutes)

FSM : SEGMENT → EXTRACT
```

**Étape 3 : Extraction (ExtractorOrchestrator)** ⏱️ 15s
```
ExtractorOrchestrator : "Analyse chaque segment"

Segment 1 - Introduction (2 entités détectées)
→ PrepassAnalyzer : "Simple, 2 entités"
→ Route : NO_LLM
→ Extraction : 3 concepts
→ Coût : $0
→ Temps : 1s

Segment 2 - Architecture (15 entités détectées)
→ PrepassAnalyzer : "Complexe, 15 entités"
→ Route : BIG (budget OK : 8 appels restants)
→ Extraction : 12 concepts
→ Coût : $0.015
→ Temps : 2s
→ Budget doc BIG : 7 restants

Segment 3 - Modules (6 entités détectées)
→ PrepassAnalyzer : "Moyen, 6 entités"
→ Route : SMALL (budget OK : 120 appels restants)
→ Extraction : 8 concepts
→ Coût : $0.002
→ Temps : 1.5s
→ Budget doc SMALL : 119 restants

Segment 4 - Conclusion (4 entités détectées)
→ PrepassAnalyzer : "Moyen, 4 entités"
→ Route : SMALL
→ Extraction : 4 concepts
→ Coût : $0.002
→ Temps : 1.5s
→ Budget doc SMALL : 118 restants

Total extraction :
- Candidats : 27 concepts
- Coût : $0.019
- Temps : 6s
- Budget consommé : BIG=1, SMALL=2

FSM : EXTRACT → MINE_PATTERNS
```

**Étape 4 : Pattern Mining (PatternMiner)** ⏱️ 1s
```
PatternMiner : "Détecte les patterns et relations"

Frequency analysis :
- "SAP" : 4/4 segments (pattern_score: 1.0)
- "ERP" : 3/4 segments (pattern_score: 0.75)
- "Module Finance" : 2/4 segments (pattern_score: 0.5)

Co-occurrence detection :
- SAP ↔ ERP : 3 occurrences ensemble
- SAP ↔ S/4HANA : 2 occurrences ensemble
- ERP ↔ Finance : 2 occurrences ensemble

Hierarchy inference :
- SAP (parent) → S/4HANA (enfant)
- ERP (parent) → Module Finance (enfant)

Résultat :
- Patterns détectés : 8
- Relations créées : 15
- Candidats enrichis : 27

FSM : MINE_PATTERNS → GATE_CHECK
```

**Étape 5 : Quality Gate (GatekeeperDelegate)** ⏱️ 3s
```
GatekeeperDelegate : "Filtre la qualité (profil BALANCED)"

Contextual scoring (GraphCentralityScorer) :
- 27 candidats analysés
- Centralité calculée
- Temps : 1s

Contextual scoring (EmbeddingsContextualScorer) :
- 27 candidats analysés
- 23 marqués PRIMARY (pertinents)
- 0 marqués COMPETITOR (hors sujet)
- Temps : 2s

Hard rejections :
❌ "de" (stopword)
❌ "sys" (fragment, trop court)
❌ "le système" (confiance 0.45 < 0.70)

Gate check (profil BALANCED : min_confidence=0.70) :
✅ "SAP ERP" (0.92) → PROMU
✅ "S/4HANA" (0.87) → PROMU
✅ "Module Finance" (0.78) → PROMU
... (20 autres concepts promus)

Résultat :
- Promus : 23 concepts
- Rejetés : 4 concepts
- Promotion rate : 85% (> 30% minimum) ✅

FSM : GATE_CHECK → PROMOTE
```

**Étape 6 : Promotion (GatekeeperDelegate)** ⏱️ 0.5s
```
GatekeeperDelegate : "Promeut les concepts vers Neo4j"

Promotion Proto → Published :
- 23 concepts promus
- Statut changé : Proto → Published
- Relations Neo4j créées

FSM : PROMOTE → FINALIZE
```

**Étape 7 : Finalisation (SupervisorAgent)** ⏱️ 0.1s
```
SupervisorAgent : "Calcul des métriques finales"

Métriques finales :
- Steps FSM : 8 étapes
- Coût total : $0.019
- LLM calls : { SMALL: 2, BIG: 1, VISION: 0 }
- Budget restant : { SMALL: 118, BIG: 7, VISION: 2 }
- Concepts promus : 23
- Promotion rate : 85%
- Temps total : 21.8s

FSM : FINALIZE → DONE ✅
```

**Résumé Final** :
```
Document traité avec succès ✅

Coût :
- Coût document : $0.019
- Coût moyen par slide : $0.002
- Économie vs tout BIG : $0.131 (87% économie !)

Performance :
- Temps traitement : 21.8s (< 30s cible) ✅
- Timeout alloué : 420s (marge : 398s)
- Promotion rate : 85% (> 30% cible) ✅

Budget tenant XYZ (après traitement) :
- SMALL : 8,498/10,000 restants
- BIG : 449/500 restants
- VISION : 98/100 restants

Qualité :
- Concepts promus : 23
- Relations créées : 15
- Patterns détectés : 8
- Knowledge Graph enrichi ✅
```

---

## 📊 État Partagé (AgentState)

**Fichier**: `src/knowbase/agents/base.py`

```python
class AgentState(BaseModel):
    """État partagé entre agents (passé via FSM)."""
    document_id: str
    tenant_id: str = "default"

    # Budget tracking
    budget_remaining: Dict[str, int] = {
        "SMALL": 120,
        "BIG": 8,
        "VISION": 2
    }

    # Extraction state
    segments: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    promoted: List[Dict[str, Any]] = []

    # Metrics
    cost_incurred: float = 0.0
    llm_calls_count: Dict[str, int] = {
        "SMALL": 0,
        "BIG": 0,
        "VISION": 0
    }

    # FSM tracking
    current_step: str = "init"
    steps_count: int = 0
    max_steps: int = 50
    started_at: float = Field(default_factory=time.time)
    timeout_seconds: int = 600  # Adaptatif (60s/segment)

    # Errors
    errors: List[str] = []
```

---

## 🛠️ Tools (JSON I/O Strict)

### Base Classes

```python
class ToolInput(BaseModel):
    """Schema de base pour input de tool (JSON strict)."""
    pass

class ToolOutput(BaseModel):
    """Schema de base pour output de tool (JSON strict)."""
    success: bool
    message: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
```

### Liste des Tools Implémentés

| Agent                | Tool Name          | Input                                      | Output                              |
|----------------------|--------------------|--------------------------------------------|-------------------------------------|
| ExtractorOrchestrator| prepass_analyzer   | segment_text, language                     | entity_count, recommended_route     |
| ExtractorOrchestrator| extract_concepts   | segment, route, use_llm                    | concepts, cost, llm_calls           |
| PatternMiner         | detect_patterns    | candidates, min_frequency                  | patterns, enriched_candidates       |
| PatternMiner         | link_concepts      | candidates                                 | relations (CO_OCCURRENCE)           |
| GatekeeperDelegate   | gate_check         | candidates, profile_name                   | promoted, rejected, retry_recommended|
| GatekeeperDelegate   | promote_concepts   | concepts                                   | promoted_count                      |
| BudgetManager        | check_budget       | tenant_id, model_tier, requested_calls     | budget_ok, remaining, reason        |
| BudgetManager        | consume_budget     | tenant_id, model_tier, calls, cost         | consumed, new_remaining             |
| BudgetManager        | refund_budget      | tenant_id, model_tier, calls, cost         | refunded, new_remaining             |
| LLMDispatcher        | dispatch_llm       | model_tier, prompt, priority, max_tokens   | response, cost, latency_ms          |
| LLMDispatcher        | get_queue_stats    | -                                          | queue_sizes, active_calls, error_rate|

---

## 📈 KPIs et Métriques

### Métriques Temps-Réel (par document)

| Métrique              | Cible                | Mesure                          |
|-----------------------|----------------------|---------------------------------|
| Cost per doc          | $0.25 (Scénario A)   | `state.cost_incurred`           |
| Processing time       | < 30s/doc            | `time.time() - state.started_at`|
| Promotion rate        | ≥ 30%                | `len(promoted) / len(candidates)`|
| LLM calls SMALL       | ≤ 120/doc            | `state.llm_calls_count["SMALL"]`|
| LLM calls BIG         | ≤ 8/doc              | `state.llm_calls_count["BIG"]`  |
| FSM steps             | ≤ 50/doc             | `state.steps_count`             |

### Métriques Agrégées (tenant/jour)

| Métrique              | Cible                | Mesure                          |
|-----------------------|----------------------|---------------------------------|
| Daily cost            | < $50/tenant/jour    | Redis ZSUM costs:{tenant}:{date}|
| Daily calls SMALL     | ≤ 10k/tenant/jour    | Redis GET budget:tenant:SMALL   |
| Daily calls BIG       | ≤ 500/tenant/jour    | Redis GET budget:tenant:BIG     |
| Error rate            | < 5%                 | Sliding window 100 calls        |
| Circuit breaker trips | 0/jour               | Count OPEN transitions          |

---

## 🚀 Intégration Pipeline

### Avant (Phase 1 V2.1)

```python
# ingestion/osmose_integration.py
async def run_osmose_pipeline(doc_path: str):
    # Segmentation
    segments = await topic_segmenter.segment(doc)

    # Extraction (LLM systématique!)
    concepts = await concept_extractor.extract(segments)

    # Indexation
    indexed = await semantic_indexer.index(concepts)

    # Storage Neo4j
    await store_to_neo4j(indexed)
```

### Après (Phase 1.5 Agentique)

```python
# ingestion/osmose_integration.py
async def run_osmose_pipeline_agentique(doc_path: str):
    # Initialiser état
    state = AgentState(
        document_id=doc_id,
        tenant_id=tenant_id
    )

    # Lancer Supervisor FSM
    supervisor = SupervisorAgent(config)
    final_state = await supervisor.execute(state)

    # Retourner résultats
    return {
        "promoted": final_state.promoted,
        "cost": final_state.cost_incurred,
        "llm_calls": final_state.llm_calls_count,
        "steps": final_state.steps_count
    }
```

---

## ✅ Validation Phase 1.5

### Critères de Succès (GO/NO-GO)

| Critère                      | Cible              | Mesure                    | Status |
|------------------------------|--------------------|--------------------------| ------ |
| Cost Scénario A              | ≤ $1.00/1000p      | Mesure pilote 50 PDF     | 🟡 TODO|
| Cost Scénario B              | ≤ $3.08/1000p      | Mesure pilote 30 PDF     | 🟡 TODO|
| Cost Scénario C              | ≤ $7.88/1000p      | Mesure pilote 20 PPTX    | 🟡 TODO|
| Processing time              | < 30s/doc          | P95 latency              | 🟡 TODO|
| Quality promotion rate       | ≥ 30%              | Gate BALANCED            | 🟡 TODO|
| Rate limit violations        | 0                  | Count 429 errors         | 🟡 TODO|
| Circuit breaker trips        | 0                  | Count OPEN transitions   | 🟡 TODO|
| Multi-tenant isolation       | 100%               | Budget leaks             | 🟡 TODO|

### Tests Pilote (Semaine 11-12)

**Semaine 11 (Jours 3-5)**:
- 50 PDF textuels (Scénario A)
- Objectif: $0.25/doc, < 30s/doc

**Semaine 12**:
- 30 PDF complexes (Scénario B): $0.77/doc
- 20 PPTX (Scénario C): $1.57/doc

---

## 📝 Fichiers Créés

### Code Python

```
src/knowbase/agents/
├── __init__.py                      # Package init
├── base.py                          # BaseAgent, AgentState, ToolInput/Output
├── supervisor/
│   ├── __init__.py
│   └── supervisor.py                # SupervisorAgent (FSM Master)
├── extractor/
│   ├── __init__.py
│   └── orchestrator.py              # ExtractorOrchestrator
├── miner/
│   ├── __init__.py
│   └── miner.py                     # PatternMiner
├── gatekeeper/
│   ├── __init__.py
│   ├── gatekeeper.py                # GatekeeperDelegate
│   ├── graph_centrality_scorer.py   # Scoring par centralité
│   └── embeddings_contextual_scorer.py  # Scoring contextuel
├── budget/
│   ├── __init__.py
│   └── budget.py                    # BudgetManager
└── dispatcher/
    ├── __init__.py
    └── dispatcher.py                # LLMDispatcher
```

### Configuration YAML

```
config/agents/
├── supervisor.yaml                  # FSM config, retry policy
├── routing_policies.yaml            # Routing thresholds, model configs
├── gate_profiles.yaml               # STRICT/BALANCED/PERMISSIVE
└── budget_limits.yaml               # Caps, quotas, cost targets
```

### Documentation

```
doc/phase1_osmose/
└── PHASE1.5_ARCHITECTURE_AGENTIQUE.md  # Ce fichier
```

---

## 🔮 Prochaines Étapes

### Semaine 11 (Jours 3-5)
- [ ] Tests unitaires pour chaque agent
- [ ] Intégration avec `osmose_integration.py`
- [ ] Setup Redis (quotas tracking)
- [ ] Pilote Scénario A (50 PDF textuels)
- [ ] Dashboard Grafana (10 KPIs)

### Semaine 12
- [ ] Pilote Scénarios B & C
- [ ] Optimisation budgets (ajustement seuils)
- [ ] Tests multi-tenant isolation
- [ ] Rapport technique 20 pages

### Semaine 13
- [ ] Analyse résultats pilote
- [ ] Décision GO/NO-GO Phase 2
- [ ] Validation critères de succès
- [ ] Présentation stakeholders

---

## 💡 Glossaire pour Non-Techniques

**Agent** : Programme informatique spécialisé dans une tâche (comme un employé spécialisé)

**FSM (Finite State Machine)** : Plan d'action avec des étapes précises (comme une recette de cuisine)

**LLM (Large Language Model)** : Intelligence artificielle comme GPT-4 (comme ChatGPT)

**Rate Limiting** : Limitation du nombre d'appels par minute (comme un péage autoroutier)

**Circuit Breaker** : Disjoncteur automatique qui coupe si trop d'erreurs (comme un fusible électrique)

**NER (Named Entity Recognition)** : Extraction automatique de noms, lieux, organisations (comme surligner dans un texte)

**Tenant** : Client/Organisation utilisant le système (comme locataire d'un immeuble)

**Budget** : Nombre d'appels IA autorisés (comme crédit téléphonique)

**Promotion Rate** : Pourcentage de concepts gardés après contrôle qualité (comme taux d'acceptation)

**Fallback** : Plan B si le premier choix échoue (comme roue de secours)

---

**Fin Phase 1.5 - Architecture Agentique V1.1**

*Date création: 2025-10-15*
*Date dernière mise à jour: 2025-10-16*
*Auteur: Claude Code + User*
*Version: 1.1.1 (enrichi avec explications vulgarisées)*

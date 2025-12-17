# Phase 3.5 : Frontend "Explainable Graph-RAG"

**Version:** 2.0
**Date:** 2025-12-17
**Status:** 🟡 PLANIFICATION
**Durée estimée:** 6-7 semaines (Semaines 29-35)
**Prérequis:** Phase 2 complète + Phase 2.5 (Memory Layer) + Phase 3 (Multi-Source simplifiée)

---

## Table des Matières

1. [Vision et Objectifs](#1-vision-et-objectifs)
2. [Killer Features](#2-killer-features)
3. [Expérience Utilisateur Cible](#3-expérience-utilisateur-cible)
4. [Architecture Technique](#4-architecture-technique)
5. [Maquettes Détaillées](#5-maquettes-détaillées)
6. [Composants Frontend](#6-composants-frontend)
7. [APIs Backend Requises](#7-apis-backend-requises)
8. [Intégration Memory Layer](#8-intégration-memory-layer)
9. [Planning Détaillé](#9-planning-détaillé)
10. [KPIs de Succès](#10-kpis-de-succès)
11. [Risques et Mitigation](#11-risques-et-mitigation)

---

## 1. Vision et Objectifs

### 1.1 Vision

> **"Chaque réponse de KnowWhere est une fenêtre transparente sur le raisonnement du Knowledge Graph."**

L'utilisateur ne reçoit pas simplement une réponse textuelle : il **voit** comment cette réponse a été construite, quels concepts ont été mobilisés, quelles relations ont été traversées, et quels documents ont servi de sources.

### 1.2 Objectifs Stratégiques

| Objectif | Description | Métrique |
|----------|-------------|----------|
| **Transparence** | Montrer le raisonnement derrière chaque réponse | 100% réponses avec graphe |
| **Traçabilité** | Lier chaque affirmation à ses sources documentaires | Sources cliquables |
| **Exploration** | Permettre d'approfondir via les concepts connexes | Suggestions pertinentes |
| **Confiance** | Afficher les scores de confiance | Confidence visible |
| **Différenciation** | USP visuel vs Copilot/Gemini/ChatGPT | "Aucun concurrent ne fait ça" |

### 1.3 Proposition de Valeur pour le Partenaire

```
┌─────────────────────────────────────────────────────────────────┐
│                    PARCOURS UTILISATEUR                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PARTENAIRE                         KNOWWHERE                   │
│  (AI-Readiness Assessment)          (Explainable Graph-RAG)     │
│                                                                  │
│  "Ces 500 docs sont AI-ready"  ──►  Import automatique          │
│         (Score: 85%)                        │                   │
│                                             ▼                   │
│                                     Extraction concepts          │
│                                     Relations typées             │
│                                     Knowledge Graph              │
│                                             │                   │
│                                             ▼                   │
│  ◄───────────────────────────────  CHAT EXPLAINABLE             │
│                                     • Réponse + Graphe visible  │
│                                     • Sources traçables          │
│                                     • Exploration guidée         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Killer Features

Cette section décrit les fonctionnalités différenciantes qui transforment KnowWhere en un outil véritablement unique sur le marché.

### 2.1 Living Graph (Graphe Vivant)

> **Le graphe de la session grandit à chaque question, créant une carte mentale de l'exploration**

**Concept :**
Le graphe ne se réinitialise pas à chaque question. Au contraire, il **accumule** les concepts explorés au fil de la conversation, avec un code couleur temporel :
- Concepts **récents** : couleurs vives
- Concepts **anciens** : couleurs atténuées
- Nouveaux concepts ajoutés : animation "apparition"

**Avantages :**
- L'utilisateur visualise son **parcours d'exploration**
- Identification visuelle des **zones non explorées**
- Possibilité de **revenir** sur un concept précédemment vu
- Création d'une **carte mentale personnalisée** de la session

**Interactions :**
| Action | Résultat |
|--------|----------|
| Nouvelle question | Nouveaux concepts s'ajoutent avec animation |
| Hover concept ancien | Rappel de la question qui l'a introduit |
| Click "Reset Graph" | Réinitialisation optionnelle |
| Click "Export Graph" | Export PNG/SVG de la carte mentale |

```
Session: Question 1 → Question 2 → Question 3
         │             │             │
         ▼             ▼             ▼
      [C1][C2]      [C3][C4]      [C5][C6]
         │             │             │
         └─────────────┴─────────────┘
                      │
             LIVING GRAPH UNIFIÉ
```

### 2.2 Smart Hover (Survol Intelligent)

> **Toutes les informations essentielles sans aucun click**

**Concept :**
Un tooltip enrichi apparaît au survol de n'importe quel élément, avec des informations contextuelles complètes :

**Sur un concept :**
```
┌─────────────────────────────────────────┐
│ 🟢 RBAC                                  │
│ Role-Based Access Control                │
│                                          │
│ Type: PRACTICE    Confidence: 94%        │
│ Mentions: 127     Documents: 12          │
│                                          │
│ "Modèle de contrôle d'accès où les      │
│  permissions sont attribuées à des       │
│  rôles plutôt qu'aux individus..."       │
│                                          │
│ 🔗 8 relations • 📚 12 sources           │
│                                          │
│ [Click pour voir la carte complète →]    │
└─────────────────────────────────────────┘
```

**Sur une relation :**
```
┌─────────────────────────────────────────┐
│ ─── INTEGRATES_WITH ───                  │
│                                          │
│ RBAC ←→ Identity Authentication Service  │
│                                          │
│ Confidence: 91%                          │
│ Evidence: 8 documents                    │
│                                          │
│ "IAS provides the identity layer for    │
│  RBAC enforcement in S/4HANA Cloud..."   │
└─────────────────────────────────────────┘
```

**Sur une source :**
```
┌─────────────────────────────────────────┐
│ 📄 SAP S/4HANA Security Guide           │
│                                          │
│ Type: PDF    Pages: 156                  │
│ Importé: 2024-11-15                      │
│                                          │
│ Concepts utilisés de ce doc: 5          │
│ [RBAC] [IAS] [Cloud Connector] ...       │
│                                          │
│ [Click pour aperçu complet →]            │
└─────────────────────────────────────────┘
```

### 2.3 Citations Inline (Style Académique)

> **Chaque affirmation est traçable, comme dans une publication scientifique**

**Concept :**
La réponse textuelle inclut des citations numérotées type académique ¹²³ qui renvoient aux sources exactes :

**Exemple :**
```
La migration vers SAP S/4HANA Cloud implique plusieurs aspects de
sécurité critiques¹:

1. **Identity Authentication Service (IAS)**¹² - Le service d'authentification
   centralisé doit être configuré pour gérer les identités utilisateurs...

2. **RBAC (Role-Based Access Control)**¹³ - Le modèle de contrôle d'accès
   basé sur les rôles nécessite une révision complète lors de la migration.

───────────────────────────────────────────────────────────────────────
¹ SAP S/4HANA Security Guide, p.12-15 (Confidence: 95%)
² BTP Architecture Overview, slides 22-28 (Confidence: 92%)
³ Cloud Connector Setup Guide, ch.3 (Confidence: 88%)
```

**Interactions :**
| Action | Résultat |
|--------|----------|
| Hover sur ¹ | Tooltip avec titre doc + extrait |
| Click sur ¹ | Scroll vers source dans panel |
| Click "Copier avec citations" | Export texte avec références |

### 2.4 Predictive Questions (Questions Prédictives)

> **Le système suggère intelligemment les prochaines questions pertinentes**

**Sources de suggestions :**
1. **Concepts bleus** (à explorer) → Questions basées sur ces concepts
2. **Relations non explorées** → "Vous n'avez pas encore exploré la relation X→Y"
3. **Pattern utilisateur** → Basé sur les questions similaires d'autres utilisateurs
4. **Gaps de couverture** → "Votre exploration couvre 60% du sujet, considérez..."
5. **Context Memory Layer** → Questions basées sur l'historique utilisateur

**Affichage :**
```
┌─ 💡 Questions suggérées ──────────────────────────────────────────┐
│                                                                    │
│ Basées sur votre exploration:                                      │
│ ┌──────────────────────────────────────────────────────────┐      │
│ │ 🔵 "Comment configurer SAML avec IAS ?"                  │ [→]  │
│ └──────────────────────────────────────────────────────────┘      │
│ ┌──────────────────────────────────────────────────────────┐      │
│ │ 🔵 "Sécuriser les applications Fiori"                    │ [→]  │
│ └──────────────────────────────────────────────────────────┘      │
│                                                                    │
│ Vous n'avez pas encore exploré:                                    │
│ ┌──────────────────────────────────────────────────────────┐      │
│ │ ⚪ "Impact du Cloud Connector sur la latence réseau"     │ [→]  │
│ └──────────────────────────────────────────────────────────┘      │
│                                                                    │
│ Populaires sur ce sujet:                                           │
│ ┌──────────────────────────────────────────────────────────┐      │
│ │ 📊 "Comparaison sécurité On-Premise vs Cloud"            │ [→]  │
│ └──────────────────────────────────────────────────────────┘      │
└────────────────────────────────────────────────────────────────────┘
```

### 2.5 Session Summary (Résumé Exportable)

> **Transformer une session de recherche en briefing métier exploitable**

**Concept :**
À tout moment, l'utilisateur peut générer un **résumé intelligent** de sa session. Ce n'est PAS une transcription mais un **compte-rendu métier structuré** généré par LLM.

**Format du résumé :**
```
═══════════════════════════════════════════════════════════════════
          SYNTHÈSE DE SESSION - KnowWhere
═══════════════════════════════════════════════════════════════════

📅 Date: 17 décembre 2025
👤 Utilisateur: Jean Dupont
🕐 Durée: 45 minutes (14 questions)
📊 Couverture: 23 concepts explorés

───────────────────────────────────────────────────────────────────
                        CONTEXTE
───────────────────────────────────────────────────────────────────

Objectif de recherche identifié:
  → Migration sécurisée vers SAP S/4HANA Cloud

Périmètre couvert:
  • Authentification et identité (IAS, SAML)
  • Contrôle d'accès (RBAC, Authorization Objects)
  • Connectivité hybride (Cloud Connector)

───────────────────────────────────────────────────────────────────
                    POINTS CLÉS RETENUS
───────────────────────────────────────────────────────────────────

1. ARCHITECTURE SÉCURITÉ
   IAS est le point central de gestion des identités pour le Cloud.
   Configuration SAML requise pour SSO avec IdP corporate.
   → Sources: Security Guide p.12-15, BTP Overview slides 22-28

2. MODÈLE D'AUTORISATION
   RBAC via Business Catalogs et Business Roles (différent On-Prem).
   Migration des rôles existants nécessite mapping explicite.
   → Sources: Authorization Best Practices, Fiori Security Config

3. CONNECTIVITÉ HYBRIDE
   Cloud Connector obligatoire pour accès ressources On-Premise.
   RFC over HTTP tunneling pour appels BAPI.
   → Sources: Cloud Connector Setup Guide ch.3

───────────────────────────────────────────────────────────────────
                    ACTIONS IDENTIFIÉES
───────────────────────────────────────────────────────────────────

☐ Inventorier les rôles SAP GUI existants pour mapping Cloud
☐ Configurer l'intégration IAS avec l'Active Directory corporate
☐ Installer Cloud Connector sur serveur dédié DMZ
☐ Définir la matrice RBAC pour les utilisateurs Fiori

───────────────────────────────────────────────────────────────────
                    ZONES NON EXPLORÉES
───────────────────────────────────────────────────────────────────

⚠️ Sujets non abordés qui pourraient être pertinents:
  • Audit et logging des accès (SAP Audit Log)
  • Chiffrement des données au repos et en transit
  • Gestion des clés API et certificats

───────────────────────────────────────────────────────────────────
                        SOURCES
───────────────────────────────────────────────────────────────────

[1] SAP S/4HANA Security Guide (2024) - 15 citations
[2] BTP Architecture Overview - 8 citations
[3] Cloud Connector Setup Guide - 6 citations
[4] Fiori Security Configuration - 4 citations
[5] Authorization Best Practices - 3 citations

═══════════════════════════════════════════════════════════════════
           Généré par KnowWhere - Le Cortex Documentaire
═══════════════════════════════════════════════════════════════════
```

**Export PDF :**
- Layout professionnel avec logo KnowWhere
- Table des matières cliquable
- Graphe de session inclus (image)
- Annexe avec tous les extraits sources cités

### 2.6 Expert Mode (Mode Expert)

> **Pour les power users : contrôle avancé sur le comportement du système**

**Toggle accessible via icône ⚙️ :**

**Contrôles Expert Mode :**
```
┌─ ⚙️ MODE EXPERT ──────────────────────────────────────────────────┐
│                                                                    │
│ 📊 PARAMÈTRES DE RECHERCHE                                         │
│ ┌────────────────────────────────────────────────────────────────┐│
│ │ Profondeur expansion graphe:  [1] [2] [●3] [4] [5]             ││
│ │ Seuil confiance minimum:      [====●=====] 70%                 ││
│ │ Sources max par réponse:      [====●=====] 10                  ││
│ │ Types de relations:           [✓] All [✓] PART_OF [✓] USES ... ││
│ └────────────────────────────────────────────────────────────────┘│
│                                                                    │
│ 🔍 FILTRES DOCUMENTS                                               │
│ ┌────────────────────────────────────────────────────────────────┐│
│ │ Types:    [✓] PDF [✓] PPTX [✓] DOCX [ ] Excel                  ││
│ │ Date:     [Après: 2022-01-01] [Avant: ____]                    ││
│ │ Tags:     [Security] [Migration] [+]                           ││
│ └────────────────────────────────────────────────────────────────┘│
│                                                                    │
│ 🎨 AFFICHAGE GRAPHE                                                │
│ ┌────────────────────────────────────────────────────────────────┐│
│ │ Layout:   [●] Force [○] Hierarchical [○] Radial                ││
│ │ Nœuds:    [===●====] Taille par mentions                       ││
│ │ Labels:   [✓] Toujours visibles [ ] Au hover seulement         ││
│ │ Cluster:  [ ] Auto-cluster si > 50 nœuds                       ││
│ └────────────────────────────────────────────────────────────────┘│
│                                                                    │
│ [Réinitialiser par défaut]                    [Sauver préférences]│
└────────────────────────────────────────────────────────────────────┘
```

### 2.7 Concept Comparator (Comparateur de Concepts)

> **Comparer côte à côte deux ou plusieurs concepts**

**Activation :** Sélectionner 2+ concepts (Ctrl+Click ou bouton "Comparer")

**Vue comparative :**
```
┌─────────────────────────────────────────────────────────────────────┐
│                    COMPARAISON CONCEPTS                              │
├────────────────────────────┬────────────────────────────────────────┤
│         IAS                │           RBAC                          │
│  Identity Authentication   │    Role-Based Access Control            │
│         SERVICE            │          PRACTICE                       │
├────────────────────────────┼────────────────────────────────────────┤
│ 📊 MÉTRIQUES               │ 📊 MÉTRIQUES                            │
│ Mentions: 89               │ Mentions: 127                           │
│ Documents: 8               │ Documents: 12                           │
│ Confidence: 94%            │ Confidence: 92%                         │
├────────────────────────────┼────────────────────────────────────────┤
│ 🔗 RELATIONS COMMUNES      │ 🔗 RELATIONS COMMUNES                   │
│ ←→ S/4HANA Cloud           │ ←→ S/4HANA Cloud                        │
│ ←→ Security Framework      │ ←→ Security Framework                   │
├────────────────────────────┼────────────────────────────────────────┤
│ 🔗 RELATIONS UNIQUES       │ 🔗 RELATIONS UNIQUES                    │
│ → SAML (auth protocol)     │ → Authorization Objects                 │
│ → User Provisioning        │ → Business Catalogs                     │
│ → SSO                      │ → Fiori Launchpad                       │
├────────────────────────────┼────────────────────────────────────────┤
│ 📚 SOURCES COMMUNES        │                                         │
│ • SAP S/4HANA Security Guide (both mentioned)                        │
│ • BTP Architecture Overview (both mentioned)                         │
├────────────────────────────┴────────────────────────────────────────┤
│ 💡 INSIGHT                                                           │
│ "IAS et RBAC sont complémentaires: IAS gère QUI accède (identity),  │
│  RBAC gère À QUOI ils accèdent (authorization). Dans une migration   │
│  S/4HANA Cloud, les deux doivent être configurés conjointement."     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.8 Quick Actions (Actions Rapides)

> **Menu contextuel sur chaque concept pour actions en un click**

**Au click-droit ou bouton "..." sur un concept :**
```
┌────────────────────────────────────────┐
│ 🟢 RBAC                                │
├────────────────────────────────────────┤
│ 📖 Voir carte d'identité               │
│ 🔍 "Qu'est-ce que RBAC ?"              │
│ 📊 "Comparaison RBAC Cloud vs On-Prem" │
│ 📈 "Évolution RBAC 2020-2024"          │
│ 🔗 Voir toutes les relations           │
│ ───────────────────────────            │
│ ➕ Ajouter au comparateur               │
│ 📌 Épingler dans le graphe             │
│ 🚫 Masquer du graphe                   │
│ ───────────────────────────            │
│ 📋 Copier définition                   │
│ 🔗 Copier lien vers concept            │
└────────────────────────────────────────┘
```

### 2.9 Adaptive Layout (Layout Adaptatif 70/30)

> **L'interface s'adapte intelligemment au contenu**

**Principe :** Layout flexible 70/30 avec priorité au contenu le plus pertinent.

**État par défaut (réponse simple) :**
```
┌─────────────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────┬───────────────────────────────┐ │
│ │         CHAT (70%)              │       GRAPHE (30%)             │ │
│ │                                 │                                │ │
│ │  [Messages]                     │   [Knowledge Graph]            │ │
│ │                                 │                                │ │
│ │  Réponse détaillée...           │         ●──●                  │ │
│ │                                 │        / \   \                │ │
│ │                                 │       ●   ●   ●               │ │
│ │                                 │                                │ │
│ └─────────────────────────────────┴───────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**État exploration graphe (click sur concept) :**
```
┌─────────────────────────────────────────────────────────────────────┐
│ ┌───────────────────┬───────────────────┬─────────────────────────┐ │
│ │   CHAT (40%)      │   GRAPHE (30%)    │   CARTE CONCEPT (30%)   │ │
│ │                   │                   │                         │ │
│ │  [Messages]       │ [Knowledge Graph] │  [Slide-in Panel]       │ │
│ │                   │                   │                         │ │
│ │  Réponse...       │       ●──●       │   📖 RBAC               │ │
│ │                   │      / \   \      │   Definition...          │ │
│ │                   │     ●   ●   ●     │   Relations...           │ │
│ │                   │         ↑         │   Sources...             │ │
│ │                   │     [selected]    │                         │ │
│ └───────────────────┴───────────────────┴─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**État focus graphe (fullscreen graphe) :**
```
┌─────────────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │                      GRAPHE FULLSCREEN (100%)                    │ │
│ │                                                                  │ │
│ │              ●───────●───────●                                  │ │
│ │             / \     / \     / \                                 │ │
│ │            ●   ●   ●   ●   ●   ●                               │ │
│ │           / \ / \ / \ / \ / \ / \                               │ │
│ │          ●   ●   ●   ●   ●   ●   ●                             │ │
│ │                                                                  │ │
│ │  [🔙 Retour au chat]                  [Living Graph: 45 nodes]  │ │
│ └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Transitions :** Framer Motion smooth animations entre états.

---

## 3. Expérience Utilisateur Cible

### 3.1 Parcours Principal : Question → Réponse Expliquée

```
ÉTAPE 1: L'utilisateur pose une question
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Quelles sont les implications de sécurité pour migrer vers SAP S/4HANA Cloud ?"

ÉTAPE 2: Le système analyse la question
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Détection des concepts clés : "sécurité", "migration", "SAP S/4HANA Cloud"
• Expansion graphe : concepts liés (IAS, RBAC, Cloud Connector...)
• Récupération chunks pertinents

ÉTAPE 3: Affichage de la réponse enrichie
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┌─────────────────┬─────────────────┬─────────────────┐
│   RÉPONSE       │   GRAPHE        │   SOURCES       │
│   (Texte LLM)   │   (Visualisation)│   (Documents)   │
└─────────────────┴─────────────────┴─────────────────┘

ÉTAPE 4: L'utilisateur explore
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Click sur concept → Carte d'identité (slide-in)
• Click sur concept bleu → Nouvelle question suggérée
• Click sur source → Aperçu document avec extrait
```

### 3.2 Système de Couleurs

| Couleur | Code Hex | Signification | Quand l'utiliser |
|---------|----------|---------------|------------------|
| 🟡 **Jaune/Or** | `#F6AD55` | Concept de la **question** | Concepts détectés dans la query |
| 🟢 **Vert** | `#48BB78` | Concepts **utilisés** pour la réponse | Concepts ayant contribué au raisonnement |
| 🔵 **Bleu** | `#4299E1` | Concepts **proches/chapeau** | Axes d'exploration suggérés |
| ⚪ **Gris** | `#A0AEC0` | Concepts du **contexte** | Voisinage non directement utilisé |
| 🔴 **Rouge** | `#F56565` | **Conflits/alertes** | Contradictions détectées |

**Relations :**
| Style | Signification |
|-------|---------------|
| Trait plein épais (3px) | Relation traversée dans le raisonnement |
| Trait plein fin (1px) | Relation disponible, non utilisée |
| Trait pointillé | Relation inférée (non explicite dans les docs) |

### 3.3 Interactions Clés

| Action | Résultat | Animation |
|--------|----------|-----------|
| **Hover** sur concept | Tooltip avec nom + type + confidence | Fade-in 200ms |
| **Click** sur concept | Panel carte d'identité (slide-in droite) | Slide 300ms |
| **Click** sur relation | Tooltip avec type + evidence | Fade-in 200ms |
| **Click** sur source | Modal aperçu document | Scale-up 250ms |
| **Click** sur concept 🔵 | Pré-remplit une question suggérée | Highlight + scroll |
| **Zoom** graphe | Zoom in/out avec molette | Smooth 150ms |
| **Pan** graphe | Drag pour naviguer | Inertie naturelle |

---

## 4. Architecture Technique

### 4.1 Stack Technologique

| Couche | Technologie | Justification |
|--------|-------------|---------------|
| **Framework** | Next.js 14 (App Router) | Existant, SSR, performance |
| **UI Library** | Chakra UI | Existant, accessible, theming |
| **Graphe** | D3.js v7 | Flexibilité maximale, customisation |
| **State Management** | React Query + Zustand | Existant + state local graphe |
| **Animations** | Framer Motion | Transitions fluides |
| **Types** | TypeScript strict | Sécurité types |

### 4.2 Choix D3.js : Justification

**Pourquoi D3.js plutôt que Cytoscape/React Flow :**

| Critère | D3.js | Cytoscape | React Flow |
|---------|-------|-----------|------------|
| **Customisation** | ✅ Illimitée | ⚠️ Limitée | ⚠️ Modérée |
| **Performance** | ✅ SVG natif | ✅ Canvas | ⚠️ DOM heavy |
| **Animations** | ✅ Natives | ⚠️ Via plugins | ✅ Bonnes |
| **Communauté** | ✅ Énorme | ✅ Bonne | ⚠️ Récente |
| **Apprentissage** | ❌ Courbe | ✅ Facile | ✅ Facile |
| **Future-proof** | ✅ Standard | ⚠️ Niche | ⚠️ Niche |

**Décision : D3.js** pour garantir qu'aucune limitation ne bloque les évolutions futures.

### 4.3 Architecture Composants

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ChatPage                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      ChatContainer                             │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                   ChatHeader                             │  │  │
│  │  │  [Logo] [Titre] [Settings] [User]                        │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │                                                                │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                  MessagesArea                            │  │  │
│  │  │  ┌─────────────────────────────────────────────────┐    │  │  │
│  │  │  │              MessageBubble                       │    │  │  │
│  │  │  │  ┌───────────┬───────────┬───────────┐          │    │  │  │
│  │  │  │  │ Response  │ GraphPanel│ SourcesPanel         │    │  │  │
│  │  │  │  │ TextArea  │           │           │          │    │  │  │
│  │  │  │  │           │ ┌───────┐ │ ┌───────┐ │          │    │  │  │
│  │  │  │  │           │ │D3Graph│ │ │DocList│ │          │    │  │  │
│  │  │  │  │           │ └───────┘ │ └───────┘ │          │    │  │  │
│  │  │  │  └───────────┴───────────┴───────────┘          │    │  │  │
│  │  │  │                                                  │    │  │  │
│  │  │  │  ┌─────────────────────────────────────────┐    │    │  │  │
│  │  │  │  │         QueryExplainer                   │    │    │  │  │
│  │  │  │  │  "J'ai compris: [concept1] [concept2]"   │    │    │  │  │
│  │  │  │  └─────────────────────────────────────────┘    │    │  │  │
│  │  │  └─────────────────────────────────────────────────┘    │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  │                                                                │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                   ChatInput                              │  │  │
│  │  │  [TextArea                                    ] [Send]   │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 ConceptCardPanel (Slide-in)                    │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │ [X]  RBAC (Role-Based Access Control)                   │  │  │
│  │  ├─────────────────────────────────────────────────────────┤  │  │
│  │  │ ConceptDefinition                                        │  │  │
│  │  │ ConceptRelations                                         │  │  │
│  │  │ ConceptSources                                           │  │  │
│  │  │ ConceptTimeline                                          │  │  │
│  │  │ ConceptSuggestions                                       │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.4 Flow de Données

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   User      │     │  Frontend   │     │   Backend   │
│   Action    │     │   State     │     │   APIs      │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │ 1. Submit query   │                   │
       │──────────────────►│                   │
       │                   │ 2. POST /chat/    │
       │                   │    graph-guided   │
       │                   │──────────────────►│
       │                   │                   │
       │                   │ 3. Response +     │
       │                   │    graph_data +   │
       │                   │    sources        │
       │                   │◄──────────────────│
       │                   │                   │
       │ 4. Render         │                   │
       │◄──────────────────│                   │
       │                   │                   │
       │ 5. Click concept  │                   │
       │──────────────────►│                   │
       │                   │ 6. GET /concepts/ │
       │                   │    {id}/card      │
       │                   │──────────────────►│
       │                   │                   │
       │                   │ 7. Concept card   │
       │                   │◄──────────────────│
       │                   │                   │
       │ 8. Show panel     │                   │
       │◄──────────────────│                   │
       │                   │                   │
```

---

## 5. Maquettes Détaillées

### 5.1 Vue Chat Principal (Layout Adaptatif 70/30)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  🌊 KnowWhere                                         [🔍] [⚙️] [👤 User]      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │ 👤 Question                                                      10:32 AM  │ │
│  │                                                                             │ │
│  │ Quelles sont les implications de sécurité pour migrer vers                 │ │
│  │ SAP S/4HANA Cloud ?                                                        │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │ 🤖 KnowWhere                                                     10:32 AM  │ │
│  │                                                                             │ │
│  │ ┌─ 💡 Comment j'ai compris votre question ─────────────────────────────┐   │ │
│  │ │                                                                       │   │ │
│  │ │  Concepts détectés : [🟡 S/4HANA Cloud] [🟡 Sécurité] [🟡 Migration] │   │ │
│  │ │  Expansion graphe  : +12 concepts liés                               │   │ │
│  │ │  Documents scannés : 23 documents                                    │   │ │
│  │ │                                                                       │   │ │
│  │ └───────────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                             │ │
│  │ La migration vers SAP S/4HANA Cloud implique plusieurs aspects de          │ │
│  │ sécurité critiques :                                                       │ │
│  │                                                                             │ │
│  │ 1. **Identity Authentication Service (IAS)** - Le service d'authentification│ │
│  │    centralisé doit être configuré pour gérer les identités utilisateurs... │ │
│  │                                                                             │ │
│  │ 2. **RBAC (Role-Based Access Control)** - Le modèle de contrôle d'accès    │ │
│  │    basé sur les rôles nécessite une révision complète lors de la migration.│ │
│  │                                                                             │ │
│  │ 3. **Cloud Connector** - Ce composant sécurise les communications entre    │ │
│  │    votre infrastructure on-premise et SAP BTP...                           │ │
│  │                                                                             │ │
│  │ ┌─────────────────────────────────┬────────────────────────────────────┐   │ │
│  │ │   📊 GRAPHE DE RAISONNEMENT     │   📚 SOURCES (8 documents)         │   │ │
│  │ │                                  │                                    │   │ │
│  │ │         [S/4HANA Cloud]         │   📄 SAP S/4HANA Security Guide    │   │ │
│  │ │        🟡 (query concept)        │      Pages 12-15, 45-48            │   │ │
│  │ │              │                   │      Confidence: 95%               │   │ │
│  │ │    ┌────────┼────────┐          │                                    │   │ │
│  │ │    │        │        │          │   📄 BTP Architecture Overview     │   │ │
│  │ │    ▼        ▼        ▼          │      Slides 22-28                  │   │ │
│  │ │  [IAS]   [RBAC]    [CC]         │      Confidence: 92%               │   │ │
│  │ │   🟢       🟢       🟢          │                                    │   │ │
│  │ │    │        │        │          │   📄 Cloud Connector Setup Guide   │   │ │
│  │ │    ▼        ▼        ▼          │      Chapter 3                     │   │ │
│  │ │ [SAML]  [Fiori]   [RFC]         │      Confidence: 88%               │   │ │
│  │ │   🔵       🔵       🔵          │                                    │   │ │
│  │ │                                  │   [Voir les 5 autres sources →]   │   │ │
│  │ │  ─────────────────────          │                                    │   │ │
│  │ │  🟡 Question  🟢 Utilisé        │                                    │   │ │
│  │ │  🔵 À explorer  ⚪ Contexte     │                                    │   │ │
│  │ │                                  │                                    │   │ │
│  │ └─────────────────────────────────┴────────────────────────────────────┘   │ │
│  │                                                                             │ │
│  │ ┌─ 💡 Pour approfondir ────────────────────────────────────────────────┐   │ │
│  │ │                                                                       │   │ │
│  │ │  Cliquez sur les concepts 🔵 pour explorer :                         │   │ │
│  │ │  • [SAML] → "Comment configurer SAML avec IAS ?"                     │   │ │
│  │ │  • [Fiori] → "Sécuriser les applications Fiori"                      │   │ │
│  │ │  • [RFC] → "Sécurisation des connexions RFC"                         │   │ │
│  │ │                                                                       │   │ │
│  │ └───────────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                             │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │ 💬 Posez votre question...                                       [Envoyer]│ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Panel Carte d'Identité Concept (Slide-in Droite)

```
┌──────────────────────────────────────────────────────────────────┐
│                                                          [✕]    │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                  │
│  🟢 RBAC                                                        │
│  Role-Based Access Control                                       │
│                                                                  │
│  Type: PRACTICE          Confidence: 94%                        │
│  Mentions: 127           Documents: 12                          │
│                                                                  │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                  │
│  📖 DÉFINITION                                                   │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  Modèle de contrôle d'accès où les permissions sont attribuées  │
│  à des rôles plutôt qu'à des utilisateurs individuels. Dans le  │
│  contexte SAP, RBAC est implémenté via les authorization        │
│  objects et les rôles Fiori.                                    │
│                                                                  │
│  Cette définition a été construite à partir de 12 sources       │
│  documentaires avec un consensus de 94%.                        │
│                                                                  │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                  │
│  🔗 RELATIONS (8)                                                │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  ┌─────────────────┬─────────────────────────────────────────┐  │
│  │ PART_OF         │ SAP S/4HANA Security Framework          │  │
│  ├─────────────────┼─────────────────────────────────────────┤  │
│  │ INTEGRATES_WITH │ Identity Authentication Service (IAS)   │  │
│  ├─────────────────┼─────────────────────────────────────────┤  │
│  │ REQUIRES        │ Authorization Objects                    │  │
│  │                 │ User Management                          │  │
│  ├─────────────────┼─────────────────────────────────────────┤  │
│  │ USED_BY         │ Fiori Launchpad                          │  │
│  │                 │ SAP GUI                                   │  │
│  │                 │ API Access                                │  │
│  └─────────────────┴─────────────────────────────────────────┘  │
│                                                                  │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                  │
│  📚 SOURCES (12 documents)                                       │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  📄 SAP S/4HANA Security Guide                                  │
│     15 mentions • Confidence 95%                                │
│     ┌─────────────────────────────────────────────────────┐    │
│     │ "RBAC provides a structured approach to managing    │    │
│     │  user permissions based on their organizational     │    │
│     │  role rather than individual identity..."           │    │
│     └─────────────────────────────────────────────────────┘    │
│     [Voir le document →]                                        │
│                                                                  │
│  📄 BTP Authorization Best Practices                            │
│     8 mentions • Confidence 90%                                 │
│     [Voir l'extrait →]                                          │
│                                                                  │
│  📄 Fiori Security Configuration                                │
│     6 mentions • Confidence 88%                                 │
│     [Voir l'extrait →]                                          │
│                                                                  │
│  [+ 9 autres documents...]                                      │
│                                                                  │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                  │
│  📅 ÉVOLUTION TEMPORELLE                                         │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│     2020          2022          2024                            │
│       │             │             │                              │
│  ─────●─────────────●─────────────●─────────────►               │
│       │             │             │                              │
│   "Basic RBAC"  "Enhanced    "AI-assisted                       │
│                  Fiori"      role mining"                       │
│                                                                  │
│  [Voir l'analyse d'évolution complète →]                        │
│                                                                  │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                  │
│  💡 QUESTIONS SUGGÉRÉES                                          │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ "Comment configurer RBAC avec Identity Authentication ?"│    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ "Quelles sont les bonnes pratiques RBAC pour Fiori ?"  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ "Différences RBAC entre On-Premise et Cloud ?"         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 5.3 Modal Aperçu Document Source

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                       [✕]  │
│  📄 SAP S/4HANA Security Guide                                             │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  Type: PDF          Pages: 156          Importé: 2024-11-15                │
│  Langue: Anglais    Concepts extraits: 89                                  │
│                                                                             │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  📍 EXTRAIT PERTINENT (Page 45)                                            │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  "Role-Based Access Control (RBAC) provides a structured approach   │   │
│  │   to managing user permissions based on their organizational role   │   │
│  │   rather than individual identity. In SAP S/4HANA Cloud, RBAC is   │   │
│  │   implemented through a combination of:                             │   │
│  │                                                                      │   │
│  │   • Business Catalogs - grouping of related apps and services      │   │
│  │   • Business Roles - assignment of catalogs to functional roles    │   │
│  │   • Authorization Objects - fine-grained permission controls       │   │
│  │                                                                      │   │
│  │   This approach ensures that users have access only to the          │   │
│  │   functionalities required for their job responsibilities..."       │   │
│  │                                                                      │   │
│  │                                               [🟢 RBAC mentionné ici] │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  🏷️ CONCEPTS DANS CE DOCUMENT                                              │
│                                                                             │
│  [RBAC] [Authorization Objects] [Business Catalogs] [Business Roles]       │
│  [S/4HANA Cloud] [Fiori] [User Management] [+82 autres...]                 │
│                                                                             │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  [📥 Télécharger le document]          [📖 Ouvrir dans nouvel onglet]      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Composants Frontend

### 6.1 Arborescence des Composants

```
frontend/src/
├── components/
│   │
│   ├── chat/                              # Composants Chat refondus
│   │   ├── ChatContainer.tsx              # Container principal
│   │   ├── ChatHeader.tsx                 # Header avec actions
│   │   ├── ChatMessages.tsx               # Zone messages scrollable
│   │   ├── ChatInput.tsx                  # Input avec suggestions
│   │   ├── MessageBubble.tsx              # Bulle message (user/assistant)
│   │   ├── AssistantMessage.tsx           # Message assistant enrichi
│   │   ├── QueryExplainer.tsx             # "Comment j'ai compris"
│   │   ├── GraphPanel.tsx                 # Panel graphe dans message
│   │   ├── SourcesPanel.tsx               # Panel sources dans message
│   │   └── SuggestedQuestions.tsx         # Questions suggérées
│   │
│   ├── graph/                             # Composants Graphe D3
│   │   ├── KnowledgeGraph.tsx             # Wrapper D3 principal
│   │   ├── GraphCanvas.tsx                # Canvas SVG D3
│   │   ├── GraphNode.tsx                  # Nœud concept (cercle coloré)
│   │   ├── GraphEdge.tsx                  # Arête relation (ligne)
│   │   ├── GraphTooltip.tsx               # Tooltip hover
│   │   ├── GraphLegend.tsx                # Légende couleurs
│   │   ├── GraphControls.tsx              # Zoom/Reset controls
│   │   └── useGraphSimulation.ts          # Hook force simulation D3
│   │
│   ├── concept/                           # Composants Carte Concept
│   │   ├── ConceptCardPanel.tsx           # Panel slide-in container
│   │   ├── ConceptHeader.tsx              # Header avec nom + badges
│   │   ├── ConceptDefinition.tsx          # Section définition
│   │   ├── ConceptRelations.tsx           # Section relations (tableau)
│   │   ├── ConceptSources.tsx             # Section sources (liste)
│   │   ├── ConceptTimeline.tsx            # Section évolution temporelle
│   │   ├── ConceptSuggestions.tsx         # Questions suggérées
│   │   └── ConceptMiniGraph.tsx           # Mini graphe relations
│   │
│   ├── document/                          # Composants Document
│   │   ├── DocumentPreviewModal.tsx       # Modal aperçu document
│   │   ├── DocumentExcerpt.tsx            # Extrait texte surligné
│   │   ├── DocumentMetadata.tsx           # Métadonnées document
│   │   └── DocumentConceptTags.tsx        # Tags concepts du doc
│   │
│   └── ui/                                # Composants UI génériques
│       ├── SlidePanel.tsx                 # Panel glissant générique
│       ├── ConfidenceBadge.tsx            # Badge score confiance
│       ├── ConceptTag.tsx                 # Tag concept cliquable
│       ├── RelationTypeBadge.tsx          # Badge type relation
│       ├── LoadingGraph.tsx               # Skeleton graphe
│       └── EmptyState.tsx                 # État vide
│
├── app/
│   └── chat/
│       └── page.tsx                       # Page chat (refonte complète)
│
├── hooks/
│   ├── useChat.ts                         # Hook état chat
│   ├── useGraphData.ts                    # Hook données graphe
│   ├── useConceptCard.ts                  # Hook carte concept
│   └── useGraphInteractions.ts            # Hook interactions D3
│
├── lib/
│   ├── api/
│   │   ├── chatApi.ts                     # API chat graph-guided
│   │   ├── graphApi.ts                    # API données graphe
│   │   ├── conceptApi.ts                  # API concepts
│   │   └── documentApi.ts                 # API documents
│   │
│   └── graph/
│       ├── graphLayout.ts                 # Algorithmes layout D3
│       ├── graphColors.ts                 # Palette couleurs
│       └── graphUtils.ts                  # Utilitaires graphe
│
├── stores/
│   └── graphStore.ts                      # Zustand store graphe
│
└── types/
    ├── chat.ts                            # Types messages/réponses
    ├── graph.ts                           # Types nodes/edges
    ├── concept.ts                         # Types concepts
    └── document.ts                        # Types documents
```

### 6.2 Composants Clés - Spécifications

#### 6.2.1 `KnowledgeGraph.tsx`

```typescript
interface KnowledgeGraphProps {
  // Données
  nodes: GraphNode[];
  edges: GraphEdge[];

  // Highlighting
  queryConceptIds: string[];      // Concepts de la question (jaune)
  usedConceptIds: string[];       // Concepts utilisés (vert)
  suggestedConceptIds: string[];  // Concepts à explorer (bleu)

  // Interactions
  onNodeClick: (node: GraphNode) => void;
  onNodeHover: (node: GraphNode | null) => void;
  onEdgeClick: (edge: GraphEdge) => void;

  // Configuration
  width: number;
  height: number;
  showLegend?: boolean;
  enableZoom?: boolean;
  enablePan?: boolean;
}

interface GraphNode {
  id: string;
  name: string;
  type: ConceptType;
  confidence: number;
  mentionCount: number;
  // Position (calculée par D3)
  x?: number;
  y?: number;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationType: RelationType;
  confidence: number;
  isUsed: boolean;        // Utilisé dans le raisonnement
  isInferred: boolean;    // Relation inférée vs explicite
}
```

#### 6.2.2 `ConceptCardPanel.tsx`

```typescript
interface ConceptCardPanelProps {
  conceptId: string | null;
  isOpen: boolean;
  onClose: () => void;
  onConceptClick: (conceptId: string) => void;
  onQuestionClick: (question: string) => void;
}

interface ConceptCard {
  // Identité
  id: string;
  canonicalName: string;
  aliases: string[];
  type: ConceptType;

  // Qualité
  confidence: number;
  mentionCount: number;
  documentCount: number;

  // Définition
  definition: string;
  definitionSources: SourceReference[];

  // Relations
  relations: ConceptRelation[];

  // Sources
  sources: DocumentSource[];

  // Évolution
  timeline: TimelineEvent[];

  // Suggestions
  suggestedQuestions: string[];
}
```

#### 6.2.3 `AssistantMessage.tsx`

```typescript
interface AssistantMessageProps {
  // Contenu
  content: string;

  // Explication query
  queryAnalysis: {
    detectedConcepts: ConceptReference[];
    expansionCount: number;
    documentsScanned: number;
  };

  // Graphe
  graphData: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    queryConceptIds: string[];
    usedConceptIds: string[];
    suggestedConceptIds: string[];
  };

  // Sources
  sources: DocumentSource[];

  // Suggestions
  suggestedQuestions: string[];

  // Interactions
  onConceptClick: (conceptId: string) => void;
  onSourceClick: (sourceId: string) => void;
  onQuestionClick: (question: string) => void;
}
```

---

## 7. APIs Backend Requises

### 7.1 Nouveaux Endpoints

| Endpoint | Méthode | Description | Priorité |
|----------|---------|-------------|----------|
| `/api/chat/graph-guided` | POST | Chat avec retour graphe | P0 |
| `/api/concepts/{id}/card` | GET | Carte d'identité concept | P0 |
| `/api/graph/subgraph` | POST | Sous-graphe autour de concepts | P0 |
| `/api/concepts/{id}/suggestions` | GET | Questions suggérées | P1 |
| `/api/documents/{id}/preview` | GET | Aperçu document + extraits | P1 |

### 7.2 Spécifications API

#### 7.2.1 `POST /api/chat/graph-guided`

**Request:**
```json
{
  "query": "Quelles sont les implications de sécurité pour migrer vers SAP S/4HANA Cloud ?",
  "tenant_id": "default",
  "options": {
    "expansion_depth": 2,
    "max_sources": 10,
    "include_suggestions": true
  }
}
```

**Response:**
```json
{
  "response": {
    "content": "La migration vers SAP S/4HANA Cloud implique plusieurs aspects...",
    "confidence": 0.92
  },

  "query_analysis": {
    "detected_concepts": [
      {"id": "c1", "name": "SAP S/4HANA Cloud", "confidence": 0.98},
      {"id": "c2", "name": "Security", "confidence": 0.95},
      {"id": "c3", "name": "Migration", "confidence": 0.90}
    ],
    "expansion_count": 12,
    "documents_scanned": 23
  },

  "graph_data": {
    "nodes": [
      {"id": "c1", "name": "SAP S/4HANA Cloud", "type": "PRODUCT", "confidence": 0.98, "mention_count": 234},
      {"id": "c4", "name": "IAS", "type": "SERVICE", "confidence": 0.94, "mention_count": 89},
      {"id": "c5", "name": "RBAC", "type": "PRACTICE", "confidence": 0.92, "mention_count": 127}
    ],
    "edges": [
      {"source": "c1", "target": "c4", "type": "INTEGRATES_WITH", "confidence": 0.91, "is_used": true},
      {"source": "c1", "target": "c5", "type": "USES", "confidence": 0.89, "is_used": true}
    ],
    "query_concept_ids": ["c1", "c2", "c3"],
    "used_concept_ids": ["c1", "c4", "c5", "c6"],
    "suggested_concept_ids": ["c7", "c8", "c9"]
  },

  "sources": [
    {
      "document_id": "doc1",
      "document_name": "SAP S/4HANA Security Guide",
      "document_type": "PDF",
      "pages": "12-15, 45-48",
      "confidence": 0.95,
      "excerpt": "Role-Based Access Control (RBAC) provides a structured approach..."
    }
  ],

  "suggested_questions": [
    "Comment configurer IAS pour S/4HANA Cloud ?",
    "Quelles sont les bonnes pratiques RBAC ?",
    "Migration des autorisations existantes vers le Cloud"
  ]
}
```

#### 7.2.2 `GET /api/concepts/{id}/card`

**Response:**
```json
{
  "id": "c5",
  "canonical_name": "RBAC",
  "full_name": "Role-Based Access Control",
  "aliases": ["Role-Based Access Control", "Contrôle d'accès basé sur les rôles"],
  "type": "PRACTICE",
  "confidence": 0.94,
  "mention_count": 127,
  "document_count": 12,

  "definition": {
    "text": "Modèle de contrôle d'accès où les permissions sont attribuées à des rôles...",
    "source_count": 8,
    "consensus_score": 0.92
  },

  "relations": [
    {"type": "PART_OF", "target_id": "c10", "target_name": "SAP S/4HANA Security Framework", "confidence": 0.91},
    {"type": "INTEGRATES_WITH", "target_id": "c4", "target_name": "Identity Authentication Service", "confidence": 0.88},
    {"type": "REQUIRES", "target_id": "c11", "target_name": "Authorization Objects", "confidence": 0.85}
  ],

  "sources": [
    {
      "document_id": "doc1",
      "document_name": "SAP S/4HANA Security Guide",
      "mention_count": 15,
      "confidence": 0.95,
      "excerpt": "RBAC provides a structured approach to managing user permissions...",
      "pages": "45-48"
    }
  ],

  "timeline": [
    {"date": "2020-Q1", "event": "Basic RBAC", "document": "Security Guide v1"},
    {"date": "2022-Q2", "event": "Enhanced with Fiori tiles", "document": "Security Guide v2"},
    {"date": "2024-Q1", "event": "AI-assisted role mining", "document": "Security Guide v3"}
  ],

  "suggested_questions": [
    "Comment configurer RBAC avec Identity Authentication ?",
    "Quelles sont les bonnes pratiques RBAC pour Fiori ?",
    "Différences RBAC entre On-Premise et Cloud ?"
  ]
}
```

### 7.3 Modifications Endpoints Existants

| Endpoint | Modification | Raison |
|----------|-------------|--------|
| `POST /api/search` | Ajouter `include_graph` param | Retourner graphe si demandé |
| `GET /api/concepts/{id}/explain` | Enrichir avec timeline | Exploiter TemporalDiffEngine |

---

## 8. Intégration Memory Layer (Phase 2.5)

> **Le Frontend exploite la Memory Layer pour une expérience conversationnelle continue**

### 8.1 Dépendance Phase 2.5

Cette phase **dépend** de la Phase 2.5 (Memory Layer) qui doit être implémentée au préalable. La Memory Layer fournit :

| Composant Memory Layer | Utilisation Frontend |
|------------------------|---------------------|
| **Session Manager** | Persistance du Living Graph entre rafraîchissements |
| **Context Resolver** | Résolution de questions implicites ("Et pour X ?") |
| **User Profile** | Personnalisation des suggestions, préférences Expert Mode |
| **Intelligent Summarizer** | Génération du Session Summary PDF |
| **Conversation History** | Affichage historique, reprise de sessions précédentes |

### 8.2 Composants Frontend Memory-Aware

```
frontend/src/
├── components/
│   ├── memory/                              # Composants Memory Layer
│   │   ├── SessionSelector.tsx              # Sélecteur de session (nouvelle/existante)
│   │   ├── SessionHistory.tsx               # Liste sessions passées
│   │   ├── SessionResume.tsx                # Bouton "Reprendre où j'en étais"
│   │   ├── ContextIndicator.tsx             # Indicateur contexte actif
│   │   └── SummaryExporter.tsx              # Export PDF session summary
│   │
│   └── chat/
│       ├── ChatContainer.tsx                # ← Enrichi avec session context
│       └── ChatMessages.tsx                 # ← Charge historique session
│
├── hooks/
│   ├── useSession.ts                        # Hook gestion session courante
│   ├── useSessionHistory.ts                 # Hook historique sessions
│   └── useContextResolver.ts                # Hook résolution contexte implicite
│
└── lib/api/
    └── memoryApi.ts                         # API Memory Layer
```

### 8.3 APIs Memory Layer Requises

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/memory/sessions` | GET | Liste sessions utilisateur |
| `/api/memory/sessions/{id}` | GET | Détail session (messages, graph state) |
| `/api/memory/sessions` | POST | Créer nouvelle session |
| `/api/memory/sessions/{id}/context` | GET | Contexte actuel (pour résolution implicite) |
| `/api/memory/sessions/{id}/summary` | POST | Générer résumé intelligent |
| `/api/memory/sessions/{id}/export` | GET | Export PDF session summary |
| `/api/memory/user/profile` | GET/PUT | Profil utilisateur (préférences) |

### 8.4 UX Memory-Aware

#### 8.4.1 Démarrage Session

```
┌─────────────────────────────────────────────────────────────────┐
│  🌊 KnowWhere                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Bonjour Jean ! Comment puis-je vous aider ?                    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 📝 Nouvelle recherche                                       ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Ou reprendre une session récente :                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 📁 Migration S/4HANA Security (hier, 14 questions)         ││
│  │    Dernière question: "Configuration RBAC Fiori"            ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ 📁 Analyse Cloud Connector (3 déc, 8 questions)            ││
│  │    Dernière question: "Ports réseau requis"                 ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  [Voir toutes les sessions →]                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 8.4.2 Indicateur de Contexte Actif

Lors d'une session en cours, un badge discret indique le contexte actif :

```
┌─────────────────────────────────────────────────────────────────┐
│  🌊 KnowWhere          [📌 Contexte: Migration S/4HANA Security]│
├─────────────────────────────────────────────────────────────────┤
```

#### 8.4.3 Questions Implicites

La Memory Layer permet de comprendre des questions sans contexte explicite :

```
👤 "Et pour la rétention des logs ?"
       │
       ▼
[Context Resolver détecte le contexte actif: "S/4HANA Security"]
       │
       ▼
🤖 "Dans le contexte de la sécurité S/4HANA Cloud, la rétention
    des logs d'audit est configurée via..."
```

#### 8.4.4 Session Summary avec Actions

```
┌─────────────────────────────────────────────────────────────────┐
│  📊 RÉSUMÉ DE SESSION                              [📥 PDF]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Cette session a couvert 23 concepts en 14 questions.           │
│                                                                  │
│  Actions identifiées pour "Client X":                           │
│  ☐ Configurer IAS avec AD corporate                             │
│  ☐ Mapper rôles SAP GUI vers Business Roles Cloud               │
│  ☐ Installer Cloud Connector en DMZ                             │
│                                                                  │
│  [📥 Exporter en PDF]  [📧 Envoyer par email]                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.5 Stockage Living Graph

Le Living Graph est persisté via la Memory Layer :

```json
{
  "session_id": "sess_abc123",
  "living_graph": {
    "nodes": [...],
    "edges": [...],
    "node_metadata": {
      "c1": {"introduced_at_question": 1, "last_accessed": 5},
      "c2": {"introduced_at_question": 1, "last_accessed": 3},
      "c3": {"introduced_at_question": 3, "last_accessed": 5}
    }
  },
  "updated_at": "2025-12-17T10:32:00Z"
}
```

Cela permet :
- De **reprendre** exactement où l'utilisateur en était
- D'afficher le graphe avec les bonnes **opacités temporelles**
- De générer des **suggestions basées sur l'historique** d'exploration

---

## 9. Planning Détaillé

### 9.1 Vue d'Ensemble

```
Semaine 29 │████████████████████│ Chat Layout + D3 Setup
Semaine 30 │████████████████████│ Graphe Interactif + Highlighting
Semaine 31 │████████████████████│ Carte Concept + Slide Panel
Semaine 32 │████████████████████│ Sources + Document Preview
Semaine 33 │████████████████████│ Query Explainer + Suggestions
Semaine 34 │████████████████████│ Polish + Démo Prep
```

### 9.2 Semaine 29 : Fondations Chat & D3 (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J1 | Setup D3.js + types TypeScript | `lib/graph/*`, `types/graph.ts` | 4h |
| J1 | Refonte structure `ChatContainer` | Layout 3 colonnes responsive | 4h |
| J2 | `KnowledgeGraph.tsx` base | Canvas SVG + force simulation | 6h |
| J2 | `GraphNode.tsx` + `GraphEdge.tsx` | Rendu nœuds/arêtes basique | 2h |
| J3 | Système couleurs + légende | `GraphLegend.tsx`, `graphColors.ts` | 4h |
| J3 | `GraphControls.tsx` | Zoom, reset, fullscreen | 4h |
| J4 | API `POST /chat/graph-guided` | Backend endpoint | 6h |
| J4 | Hook `useGraphData.ts` | Fetch + transform data | 2h |
| J5 | Intégration chat → graphe | Graphe s'affiche avec réponse | 6h |
| J5 | Tests + debug | Validation fonctionnelle | 2h |

**Checkpoint Sem 29 :**
- ✅ Chat affiche un graphe D3 interactif
- ✅ Nœuds colorés selon rôle (query/used/suggested)
- ✅ Zoom/pan fonctionnels

### 9.3 Semaine 30 : Graphe Interactif (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J6 | `GraphTooltip.tsx` | Tooltip hover avec infos | 4h |
| J6 | Animations hover | Scale + glow effects | 4h |
| J7 | Highlighting dynamique | Concepts liés highlight on hover | 6h |
| J7 | Edges styling | Trait plein/pointillé, épaisseur | 2h |
| J8 | Click → event propagation | onNodeClick déclenche action | 4h |
| J8 | `useGraphInteractions.ts` | Hook centralisant interactions | 4h |
| J9 | `GraphPanel.tsx` dans message | Intégration dans `AssistantMessage` | 6h |
| J9 | Responsive design graphe | Adaptation taille conteneur | 2h |
| J10 | Performance optimization | Throttle, memoization | 4h |
| J10 | Tests interactions | Validation tous les clicks/hovers | 4h |

**Checkpoint Sem 30 :**
- ✅ Graphe entièrement interactif
- ✅ Tooltips informatifs
- ✅ Highlighting intelligent
- ✅ Performance fluide (60fps)

### 9.4 Semaine 31 : Carte Concept (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J11 | `SlidePanel.tsx` générique | Panel slide-in réutilisable | 4h |
| J11 | `ConceptCardPanel.tsx` container | Structure sections | 4h |
| J12 | API `GET /concepts/{id}/card` | Backend endpoint complet | 6h |
| J12 | `ConceptHeader.tsx` | Nom, badges, stats | 2h |
| J13 | `ConceptDefinition.tsx` | Définition + source count | 4h |
| J13 | `ConceptRelations.tsx` | Tableau relations typées | 4h |
| J14 | `ConceptSources.tsx` | Liste sources avec extraits | 6h |
| J14 | Click source → modal | Transition vers preview | 2h |
| J15 | `ConceptTimeline.tsx` | Timeline évolution (si data) | 6h |
| J15 | Animation slide-in | Framer Motion smooth | 2h |

**Checkpoint Sem 31 :**
- ✅ Click sur concept → panel slide-in
- ✅ Carte complète avec toutes sections
- ✅ Navigation fluide

### 9.5 Semaine 32 : Sources & Documents (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J16 | `SourcesPanel.tsx` | Panel sources dans message | 4h |
| J16 | `DocumentPreviewModal.tsx` | Modal aperçu document | 4h |
| J17 | API `GET /documents/{id}/preview` | Backend endpoint | 4h |
| J17 | `DocumentExcerpt.tsx` | Extrait avec highlighting | 4h |
| J18 | `DocumentMetadata.tsx` | Métadonnées document | 3h |
| J18 | `DocumentConceptTags.tsx` | Tags concepts du doc | 3h |
| J18 | Click concept tag → carte | Navigation croisée | 2h |
| J19 | Pagination sources | "Voir plus" avec lazy load | 4h |
| J19 | Download/Open document | Actions document | 4h |
| J20 | Tests sources flow | Validation complète | 4h |
| J20 | Mobile responsive (desktop-first ok) | Adaptation tablette | 4h |

**Checkpoint Sem 32 :**
- ✅ Sources affichées avec extraits
- ✅ Modal preview document
- ✅ Navigation document → concept fluide

### 9.6 Semaine 33 : Query Explainer & Suggestions (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J21 | `QueryExplainer.tsx` | "Comment j'ai compris" | 4h |
| J21 | Concepts détectés cliquables | Tags concepts dans query | 4h |
| J22 | Expansion graphe visualisée | Afficher +N concepts trouvés | 4h |
| J22 | API `GET /concepts/{id}/suggestions` | Backend suggestions | 4h |
| J23 | `ConceptSuggestions.tsx` | Questions suggérées | 4h |
| J23 | `SuggestedQuestions.tsx` message | Section bas de message | 4h |
| J24 | Click suggestion → input | Pré-remplir chat input | 3h |
| J24 | Concepts bleus → suggestion | Click bleu = question pré-faite | 3h |
| J24 | Historique questions | LocalStorage recent questions | 2h |
| J25 | Tests flow complet | Question → réponse → exploration | 4h |
| J25 | Edge cases | Pas de résultat, erreurs, loading | 4h |

**Checkpoint Sem 33 :**
- ✅ Query analysis visible
- ✅ Suggestions pertinentes
- ✅ Flow exploration fluide

### 9.7 Semaine 34 : Polish & Démo (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J26 | Animations Framer Motion | Transitions fluides partout | 6h |
| J26 | Loading states | Skeletons élégants | 2h |
| J27 | Dark mode (optionnel) | Thème sombre | 4h |
| J27 | Empty states | États vides informatifs | 4h |
| J28 | Performance audit | Lighthouse, bundle size | 4h |
| J28 | Bug fixes | Issues identifiées | 4h |
| J29 | Scénario démo 1 | "SAP S/4HANA Security Migration" | 3h |
| J29 | Scénario démo 2 | "CRR Evolution 2020-2024" | 3h |
| J29 | Scénario démo 3 | "Exploration concept RBAC" | 2h |
| J30 | Documentation utilisateur | Guide rapide | 3h |
| J30 | Dry run démo | Répétition avec données réelles | 3h |
| J30 | Backup plan | Fallbacks si problèmes | 2h |

**Checkpoint Sem 34 :**
- ✅ UI polished, animations fluides
- ✅ 3 scénarios démo prêts
- ✅ Documentation prête
- ✅ Démo testée end-to-end

### 9.8 Semaine 35 : Intégration Memory Layer + Killer Features (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J31 | Living Graph persistence | State Neo4j + reload | 4h |
| J31 | Session selector UI | `SessionSelector.tsx` | 4h |
| J32 | Context indicator | `ContextIndicator.tsx` | 3h |
| J32 | Citations inline | Markdown parser + tooltips | 5h |
| J33 | Smart Hover enrichi | Tooltips avec définitions | 4h |
| J33 | Quick Actions menu | Menu contextuel concepts | 4h |
| J34 | Session Summary generation | LLM summarizer integration | 6h |
| J34 | PDF export | Template PDF + génération | 2h |
| J35 | Expert Mode panel | `ExpertModePanel.tsx` | 4h |
| J35 | Concept Comparator | `ConceptComparator.tsx` | 4h |

**Checkpoint Sem 35 (FINAL) :**
- ✅ Memory Layer intégrée (Living Graph persistent)
- ✅ Citations inline avec tooltips
- ✅ Session Summary exportable PDF
- ✅ Expert Mode fonctionnel
- ✅ Concept Comparator fonctionnel
- ✅ Toutes killer features livrées

---

## 10. KPIs de Succès

### 10.1 KPIs Techniques

| KPI | Target | Mesure |
|-----|--------|--------|
| **Temps chargement graphe** | < 500ms | P95 latency |
| **FPS animations** | ≥ 60fps | Chrome DevTools |
| **Bundle size** | < 500KB (chat page) | Webpack analyzer |
| **Lighthouse Performance** | > 90 | Lighthouse audit |
| **Couverture tests** | > 70% | Jest coverage |
| **Erreurs runtime** | 0 (démo) | Sentry monitoring |

### 10.2 KPIs UX

| KPI | Target | Mesure |
|-----|--------|--------|
| **Clicks pour explorer concept** | ≤ 2 | User testing |
| **Temps compréhension graphe** | < 10s | User testing |
| **Satisfaction "explainability"** | > 4/5 | Feedback démo |
| **Facilité navigation** | > 4/5 | Feedback démo |

### 10.3 KPIs Démo Partenaire

| KPI | Target | Validation |
|-----|--------|------------|
| **"Wow effect" visuel** | Oui | Réaction partenaire |
| **Différenciation claire vs concurrents** | Oui | Comparaison verbalisée |
| **Questions de suivi positives** | ≥ 3 | Intérêt manifesté |
| **Demande de test avec leurs données** | Oui | Engagement |

---

### 10.4 KPIs Killer Features

| KPI | Target | Mesure |
|-----|--------|--------|
| **Living Graph utilisé** | > 50% sessions | Analytics |
| **Session Summary exports** | > 20% sessions | Download count |
| **Smart Hover engagement** | > 80% users | Hover analytics |
| **Expert Mode adoption** | > 10% users | Toggle analytics |
| **Citations cliquées** | > 30% | Click analytics |

---

## 11. Risques et Mitigation

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **D3.js courbe d'apprentissage** | Medium | Medium | Commencer tôt, exemples existants |
| **Performance graphe (>100 nœuds)** | Medium | High | Lazy loading, clustering, WebGL fallback |
| **APIs backend pas prêtes** | Low | High | Mock data pour frontend, paralléliser dev |
| **Complexité Panel carte** | Medium | Medium | Itérer, MVP d'abord puis enrichir |
| **Responsive difficile** | Low | Low | Desktop-first, tablette acceptable |
| **Données démo insuffisantes** | Medium | High | Préparer corpus dédié en avance |

---

## 12. Dépendances

### 12.1 Dépendances Phase 2

| Composant Phase 2 | Impact Frontend | Criticité |
|-------------------|-----------------|-----------|
| **RelationExtractionEngine** | Relations typées dans graphe | CRITIQUE |
| **TaxonomyBuilder** | Hiérarchies visibles | HIGH |
| **TemporalDiffEngine** | Timeline dans carte concept | HIGH |
| **RelationInferenceEngine** | Relations inférées (pointillés) | MEDIUM |
| **CrossDocRelationMerger** | Consolidation sources | MEDIUM |

### 12.2 Dépendances Phase 2.5 (Memory Layer)

| Composant Phase 2.5 | Impact Frontend | Criticité |
|---------------------|-----------------|-----------|
| **SessionManager** | Persistance Living Graph, reprise session | CRITIQUE |
| **ContextResolver** | Questions implicites, suggestions personnalisées | CRITIQUE |
| **UserProfile** | Préférences Expert Mode, historique | HIGH |
| **IntelligentSummarizer** | Session Summary PDF | HIGH |
| **ConversationHistory** | Affichage historique, reprise | MEDIUM |

### 12.3 Dépendances Techniques

| Dépendance | Version | Usage |
|------------|---------|-------|
| `d3` | ^7.8.0 | Graphe visualisation |
| `framer-motion` | ^10.0.0 | Animations |
| `@chakra-ui/react` | Existant | UI components |
| `zustand` | ^4.0.0 | State graphe |
| `react-query` | Existant | Data fetching |

---

## 13. Prochaines Étapes

1. **Phase 2.5 (Memory Layer)** : Développer la Memory Layer en prérequis
2. **Validation de ce document** avec itérations si nécessaire
3. **Setup technique** : Installer D3.js, créer structure composants
4. **API Backend** : Développer endpoints en parallèle du frontend
5. **Corpus démo** : Préparer données représentatives

---

**Version:** 2.0
**Auteur:** Claude Code
**Date mise à jour:** 2025-12-17
**Statut:** 🟡 En attente validation

---

> **"L'explainability n'est pas une feature, c'est la proposition de valeur."**
>
> **"Une mémoire conversationnelle qui ne repart jamais de zéro."**

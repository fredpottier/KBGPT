# Architecture KG Agnostique - KnowWhere/OSMOSE

*Document de référence pour l'architecture Knowledge Graph domain-agnostic*

**Version**: 2.0
**Date**: 2025-12-26
**Statut**: Validé

---

## North Star

> **Le graphe stocke et relie.
> Le domaine décide de ce qu'il montre et de ce qu'il croit.**

Ce principe fondamental garantit que :
- Le KG reste **agnostique** vis-à-vis du domaine d'application
- La **topologie** n'est jamais contrainte par des considérations métier
- La **responsabilité de l'exposition** est déléguée à une couche externe

---

## Modèle 5 Couches

L'architecture sépare strictement les responsabilités en 5 couches :

```
┌─────────────────────────────────────────────────────────────────┐
│  COUCHE 5 : DÉCISION                                           │
│  Question : Puis-je m'y fier ?                                 │
│  Responsabilité : Humain / Métier                              │
│  Exemple : Un médecin valide avant prescription                │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│  COUCHE 4 : UI / API                                           │
│  Question : Comment présenter la relation ?                    │
│  Responsabilité : Produit                                      │
│  Exemple : Badge "non vérifié", tooltip de confiance           │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│  COUCHE 3 : PROFIL DE VISIBILITÉ                               │
│  Question : Cette relation est-elle montrable ?                │
│  Responsabilité : Admin du Tenant                              │
│  Exemple : Profil "Vérifié" = uniquement multi-source          │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│  COUCHE 2 : TOPOLOGIE                                          │
│  Question : La relation est-elle navigable/calculable ?        │
│  Responsabilité : Knowledge Graph                              │
│  Exemple : Arête directe entre CanonicalConcepts               │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│  COUCHE 1 : STOCKAGE                                           │
│  Question : La relation existe-t-elle ?                        │
│  Responsabilité : Knowledge Graph                              │
│  Exemple : CanonicalRelation node avec métadonnées             │
└─────────────────────────────────────────────────────────────────┘
```

### Invariants par couche

| Couche | Invariant | Le KG ne doit JAMAIS... |
|--------|-----------|-------------------------|
| 1 - Stockage | Toute relation plausible est stockée | ...supprimer une relation car elle est "peu fiable" |
| 2 - Topologie | Toute relation stockée est navigable | ...bloquer la création d'arête selon la maturité |
| 3 - Profil | Les règles sont des profils comportementaux | ...hardcoder des règles par domaine métier |
| 4 - UI/API | La présentation reflète la confiance | ...afficher sans distinction de maturité |
| 5 - Décision | L'humain a le dernier mot | ...remplacer le jugement humain |

---

## 4 Profils de Visibilité (Couche 3)

### Pourquoi des profils et pas des politiques par domaine ?

❌ **Approche rejetée** : Définir des politiques par domaine (healthcare, legal, finance...)
- Impossible de prévoir tous les domaines d'utilisation
- Non maintenable à long terme
- Présuppose une connaissance du contexte métier

✅ **Approche adoptée** : 4 profils comportementaux universels
- Décrivent le **comportement voulu**, pas le domaine
- L'admin choisit le profil adapté à son usage
- Peut changer de profil si nécessaire

### Les 4 Profils

```
┌─────────────────────────────────────────────────────────────────┐
│  🔒 VÉRIFIÉ (verified)                                         │
│                                                                 │
│  "Uniquement les faits confirmés par plusieurs sources"        │
│                                                                 │
│  Paramètres techniques:                                         │
│  • min_maturity: VALIDATED                                     │
│  • min_confidence: 0.90                                         │
│  • min_source_count: 2                                          │
│                                                                 │
│  Quand l'utiliser:                                              │
│  • Décisions importantes                                        │
│  • Besoin de fiabilité maximale                                 │
│  • Moins d'infos mais plus sûres                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  ⚖️ ÉQUILIBRÉ (balanced) ← DÉFAUT                              │
│                                                                 │
│  "Faits vérifiés + informations fiables avec indication"       │
│                                                                 │
│  Paramètres techniques:                                         │
│  • min_maturity: CANDIDATE                                     │
│  • min_confidence: 0.70                                         │
│  • min_source_count: 1                                          │
│                                                                 │
│  Quand l'utiliser:                                              │
│  • Usage quotidien                                              │
│  • Bon équilibre quantité/qualité                               │
│  • À l'aise avec les indicateurs de fiabilité                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  🔍 EXPLORATOIRE (exploratory)                                 │
│                                                                 │
│  "Maximum de connexions pour découvrir des liens"              │
│                                                                 │
│  Paramètres techniques:                                         │
│  • min_maturity: CANDIDATE                                     │
│  • min_confidence: 0.40                                         │
│  • show_conflicts: true                                         │
│  • show_ambiguous: true                                         │
│                                                                 │
│  Quand l'utiliser:                                              │
│  • Exploration d'un nouveau sujet                              │
│  • Recherche de patterns                                        │
│  • Brainstorming                                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  🔓 COMPLET (full_access)                                      │
│                                                                 │
│  "Accès à toutes les données sans filtre"                      │
│                                                                 │
│  Paramètres techniques:                                         │
│  • min_confidence: 0.0                                          │
│  • Toutes les maturités visibles                               │
│  • Métadonnées techniques exposées                             │
│                                                                 │
│  Quand l'utiliser:                                              │
│  • Administration système                                       │
│  • Audit de qualité                                             │
│  • Debug technique                                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Contrat KG ↔ Visibility Service

### Ce que le KG garantit (Couches 1-2)

```yaml
kg_contract:
  storage:
    - Toute RawAssertion extraite est persistée
    - Toute CanonicalRelation consolidée est persistée
    - Les métadonnées sont complètes (maturity, confidence, sources)

  topology:
    - Arête typée créée pour TOUTE CanonicalRelation
    - Indépendamment de la maturité (CANDIDATE, VALIDATED, etc.)
    - Métadonnées embarquées sur l'arête

  queryability:
    - Toutes les relations sont requêtables sans filtre
    - Algorithmes de graphe applicables (PageRank, centralité, etc.)
    - Export complet possible pour audit
```

### Ce que le Visibility Service garantit (Couche 3)

```yaml
visibility_contract:
  filtering:
    - Applique le profil sélectionné au moment de la requête
    - Ne modifie JAMAIS les données sous-jacentes
    - Filtrage transparent et auditable

  profiles:
    - 4 profils comportementaux prédéfinis
    - Sélection par tenant (v2.0)
    - Sélection par rôle (future v3.0)

  user_experience:
    - Explications claires pour non-techniciens
    - Changement de profil à tout moment
    - Indicateur du nombre de relations filtrées (optionnel)
```

---

## Structure des Métadonnées sur Arêtes

Chaque arête typée entre CanonicalConcepts porte :

```cypher
(concept1)-[:REQUIRES {
  // Identifiant de traçabilité
  canonical_relation_id: "abc123def456",

  // Maturité (pour filtrage par profil)
  maturity: "CANDIDATE",  // CANDIDATE | VALIDATED | CONTEXT_DEPENDENT | AMBIGUOUS_TYPE | CONFLICTING

  // Confiance (pour filtrage et UI)
  confidence: 0.87,       // 0.0 - 1.0

  // Provenance
  source_count: 1,        // Nombre de documents sources
  predicate_norm: "requires",  // Prédicat normalisé
  first_seen: datetime(),
  last_seen: datetime(),
  last_updated: datetime()
}]->(concept2)
```

---

## Évolution Prévue

### Version Actuelle (v2.0) : Granularité par Tenant

```
┌─────────────┐     choisit      ┌─────────────┐
│   Tenant    │ ───────────────> │   Profil    │
│  (company)  │                  │ (balanced)  │
└─────────────┘                  └─────────────┘
       │
       │ s'applique à
       ▼
┌─────────────┐
│ Tous les    │
│ utilisateurs│
└─────────────┘
```

- L'admin du tenant choisit UN profil pour tout le tenant
- Tous les utilisateurs du tenant voient les mêmes données
- Simple et suffisant pour la plupart des cas

### Version Future (v3.0) : Granularité par Rôle

```
┌─────────────┐
│   Tenant    │
└─────────────┘
       │
       ├─── user ──────────> [verified, balanced]
       │                      défaut: balanced
       │
       ├─── advanced ──────> [verified, balanced, exploratory]
       │                      défaut: balanced
       │
       └─── admin ─────────> [verified, balanced, exploratory, full_access]
                              défaut: balanced
```

**Fonctionnalités v3.0 :**
- Chaque rôle a une liste de profils autorisés
- L'utilisateur peut changer de profil dans sa liste
- L'admin peut restreindre l'accès à certains profils
- `full_access` réservé aux admins

---

## Interface Admin

### Sélection du Profil

```
┌─────────────────────────────────────────────────────────────────┐
│  Profil de visibilité des relations                            │
│                                                                 │
│  Choisissez comment les informations sont affichées à vos      │
│  utilisateurs. Vous pouvez changer ce paramètre à tout moment. │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ ○ 🔒 Vérifié                                              │ │
│  │   Uniquement les faits confirmés par plusieurs sources    │ │
│  │   [Voir détails]                                          │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ ● ⚖️ Équilibré (recommandé)                               │ │
│  │   Faits vérifiés + informations fiables avec indication   │ │
│  │   [Voir détails]                                          │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ ○ 🔍 Exploratoire                                         │ │
│  │   Maximum de connexions pour découvrir des liens          │ │
│  │   [Voir détails]                                          │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ ○ 🔓 Complet                                              │ │
│  │   Accès à toutes les données sans filtre                  │ │
│  │   [Voir détails]                                          │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ℹ️ Ce profil s'applique à tous les utilisateurs.             │
│                                                                 │
│                                     [Annuler]  [Enregistrer]   │
└─────────────────────────────────────────────────────────────────┘
```

### Détail d'un Profil (exemple: Équilibré)

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚖️ Profil Équilibré                                           │
│                                                                 │
│  Ce profil affiche les informations confirmées ainsi que       │
│  celles qui semblent fiables même si elles proviennent d'une   │
│  seule source. Un indicateur visuel distingue les deux.        │
│                                                                 │
│  Quand l'utiliser ?                                            │
│  • Usage quotidien de la base de connaissances                 │
│  • Vous voulez un bon équilibre entre quantité et qualité      │
│  • Vous êtes à l'aise pour interpréter les indicateurs         │
│                                                                 │
│  Ce que vous verrez :                                          │
│  ✓ Relations confirmées par plusieurs sources (sans badge)    │
│  ✓ Relations fiables d'une seule source (avec badge)          │
│  ✓ Niveau de confiance affiché                                 │
│                                                                 │
│  Ce que vous ne verrez pas :                                   │
│  ✗ Relations avec une confiance faible (< 70%)                │
│  ✗ Informations ambiguës ou contradictoires                   │
│                                                                 │
│                                                    [Fermer]    │
└─────────────────────────────────────────────────────────────────┘
```

---

## FAQ

### Q: Pourquoi pas de politique "healthcare" ou "legal" ?

**R**: OSMOSE est agnostique. Nous ne pouvons pas prévoir tous les domaines d'utilisation. Les profils décrivent des **comportements** (restrictif, permissif) que l'admin associe à son contexte.

Un hôpital choisira probablement "Vérifié", mais c'est SA décision, pas la nôtre.

### Q: Peut-on créer des profils personnalisés ?

**R**: Non dans la v2.0. Les 4 profils couvrent 95% des besoins. Si un besoin spécifique émerge, nous pouvons :
1. Ajouter un 5ème profil standard
2. Ouvrir la personnalisation en v3.0

### Q: Que se passe-t-il si on change de profil ?

**R**: Le changement est immédiat. Les prochaines requêtes utiliseront le nouveau profil. Les données ne sont pas modifiées.

### Q: Comment un utilisateur sait-il quel profil est actif ?

**R**: À définir dans l'UI. Options :
- Indicateur permanent dans le header
- Info dans les résultats de recherche
- Page "Mon compte" avec profil actuel

### Q: Le profil affecte-t-il le RAG/Chat ?

**R**: Oui, le même profil s'applique à :
- Exploration du graphe
- Recherche sémantique
- Réponses du chat (context fourni au LLM)

---

## Fichiers de Référence

| Fichier | Description |
|---------|-------------|
| `config/visibility_policies.yaml` | Définition des 4 profils |
| `src/knowbase/api/services/visibility_service.py` | Service de filtrage |
| `src/knowbase/relations/canonical_relation_writer.py` | Création des arêtes typées |

---

## Historique du Document

| Date | Version | Changement |
|------|---------|------------|
| 2025-12-26 | 1.0 | Création après débat architectural |
| 2025-12-26 | 2.0 | Simplification: 4 profils comportementaux au lieu de politiques par domaine |

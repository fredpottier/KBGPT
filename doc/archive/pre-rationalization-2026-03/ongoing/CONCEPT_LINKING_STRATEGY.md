# Stratégie de liens inter-concepts — Atlas OSMOSE

**Statut** : Architecture validée, à implémenter
**Priorité** : Haute — navigabilité de l'Atlas

## Principe fondamental

**Les articles sont générés indépendamment du linking.**
**Le linking est une passe batch distincte, exécutée après constitution ou mise à jour du corpus d'articles.**

Deux responsabilités séparées :

| Responsabilité | Objectif | Contraintes |
|----------------|----------|-------------|
| **Génération** | Produire un article fidèle au corpus, structuré, indépendant | Qualité rédactionnelle, citations, couverture |
| **Linking** | Transformer les articles en graphe navigable | Résolution d'ambiguïtés, cohérence globale, pas de faux positifs |

## Pourquoi cette séparation

1. **Pas de dépendance d'ordre** — tous les articles traités à armes égales (pas de "1er article sans liens")
2. **Vision globale** — la passe de linking voit tous les articles, concepts, slugs disponibles
3. **Rejouable** — après import de nouveaux docs : regénérer les articles impactés, rejouer le linking
4. **Gouvernable** — qualité des articles et qualité du linking mesurables séparément

## Pipeline cible

### Phase A — Génération des articles

Pour chaque concept : EvidencePack → SectionPlanner → ConstrainedGenerator → persistence.
Output : `WikiArticle` avec `markdown` brut (sans liens inter-concepts).

### Phase B — Concept Registry

Registre global construit depuis les WikiArticle + Entity :
- concept_id, canonical_title, slug
- aliases (depuis Entity aliases dans le KG)
- article_exists, article_version

### Phase C — Passe de linking batch

Pour chaque article :
1. Détecter les mentions de concepts dans le texte
2. Résoudre chaque mention vers le registry (mot → mention → concept → slug)
3. Injecter les liens markdown `[Mention](/wiki/slug)`
4. Stocker le résultat

Output par article :
- `linked_markdown` (version avec liens)
- `outgoing_links[]` (concepts référencés)
- `unresolved_mentions[]` (mentions détectées mais sans article)
- `ambiguous_mentions[]` (mentions nécessitant résolution manuelle)

### Phase D — Rebuild incrémental

Quand de nouveaux documents arrivent :
- **Relinking global** : fréquent, peu coûteux (pas de LLM, juste résolution)
- **Regénération d'articles** : ciblée sur les concepts impactés, plus rare

## Implémentation par versions

### V1 — MVP (Phase 4 actuelle)

- Génération des articles sans liens (déjà fait)
- Passe de linking batch LLM sur tout le corpus
  - Le LLM reçoit : texte de l'article + liste complète des concepts avec slugs et aliases
  - Il retourne : le markdown avec liens injectés contextuellement
  - Stocké dans un champ `linked_markdown` (le `markdown` original est préservé)
- Frontend affiche `linked_markdown` si disponible, sinon `markdown`
- Script/endpoint admin pour relancer le linking sur tout le corpus

### V2 — Linking incrémental intelligent

- Relinking automatique après génération d'un nouvel article
- Scope : article généré + articles existants qui mentionnent le nouveau concept
- Détection basée sur le concept registry

### V3 — Resolver sémantique (si l'Atlas grossit)

- Mention detection par embeddings + KG
- Exploitation des Entity aliases dans Neo4j
- Plus besoin de LLM pour le linking (résolution déterministe)

## Options écartées

- **Regex frontend seule** : ne comprend pas le contexte, faux positifs inévitables
- **LLM linking à la génération (option A)** : dépendance d'ordre, pas de vision globale
- **NER backend** : overkill pour le volume actuel
- **Annotation manuelle** : incompatible avec un atlas auto-généré
- **Hybride LLM+frontend (ancienne option D)** : le frontend porte une logique sémantique fragile

## Point d'attention

Le linking batch via LLM a un coût. Pour ~200 articles, c'est raisonnable.
Pour 2000+, il faudra passer en V3 (resolver déterministe) ou optimiser le prompt.

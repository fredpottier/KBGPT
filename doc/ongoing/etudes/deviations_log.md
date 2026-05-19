# Log des déviations détectées — Vision Guardian

> Ce log est tenu par l'agent `vision-guardian` (slash command `/vision-guardian`).
>
> Chaque entrée correspond à une activité observée (commit, chantier, bench, fichier) qui **ne se rattache pas directement** à un principe de `doc/VISION.md` ou une phase de `doc/EXECUTION_ROADMAP.md`.
>
> **Une déviation N'EST PAS un échec.** C'est une **hypothèse de travail à examiner**. Elle peut être :
> - une bonne idée qui mérite d'enrichir le plan (→ ouvrir un ADR)
> - une distraction tactique sans valeur structurante (→ `dropped`)
> - un apprentissage qui doit faire évoluer la VISION (→ amendement ADR)
> - une priorité prématurée (→ `deferred` à une phase ultérieure)
>
> **L'agent trace, l'utilisateur décide.**

---

## Légende des statuts

| Statut | Signification |
|---|---|
| `new` | Détecté par l'agent, pas encore revu par l'utilisateur |
| `reviewed` | Lu par l'utilisateur, en attente d'arbitrage |
| `integrated` | Validé → intégré à VISION/ROADMAP ou phase courante (préciser comment) |
| `deferred` | Bonne idée mais pas maintenant → différé à phase X (préciser laquelle) |
| `dropped` | Abandonné après revue → tactique, sans valeur structurante, ou anti-pattern confirmé |

---

## Légende des types

| Type | Description |
|---|---|
| **tweak** | Petit ajustement (config, param, prompt tweak) qui vise un score sans changer l'archi |
| **chantier nouveau** | Nouveau chantier (CH-XX) qui n'est pas dans le backlog ADR de la roadmap |
| **bench / mesure** | Nouveau benchmark ou mesure ad-hoc qui ne sert pas une cible C1-C5 explicite |
| **refactor** | Refactoring (non lié à un objectif de phase) |
| **exploration** | POC / spike non rattaché à une phase |
| **violation axiome** | Code/config qui contredit un axiome AX-1 à AX-16 |

---

## Index chronologique

(Le plus récent en haut)

<!-- L'agent ajoute ici les nouvelles entrées au-dessus -->

### 2026-05-19 — 11 tâches héritées non rattachées à la roadmap A→D

- **Type** : chantier nouveau (gouvernance backlog)
- **Signal** : 11 tâches `pending` ou `in_progress` dans le tracker au moment de la première invocation de `vision-guardian` :
  - `#70` Fix facet linkage 27% biomédical (embedding similarity)
  - `#246` CH-52.9 S8 Threat Model + Domain-Agnostic + Red-team + Domain Packs
  - `#247` CH-52.10 S9 Frontend chat V5 + workspace drill-down
  - `#248` CH-52.11 S10/S11 Deployment Strategy + Tests + Réingestion + Blind A/B
  - `#305` V6-P2.2 Batch extraction 3 docs complets SAP
  - `#308` Voie B — V6 évolution ClaimFirst pipeline + purge KG + réingestion
  - `#309` Voie A.2 — Valider multiform seul sur bench 50q complet
  - `#312` V6-J2 Reference typée (in_progress)
  - `#313` V6-J3 ConceptCard auto-générée
  - `#314` V6-J0 Purge KG + réingestion complète corpus 38 docs
- **Description** : Ces tâches ont été créées avant la refondation Vision (18/05/2026). Aucune ne se rattache explicitement à une phase A→D ni à un ADR au backlog (§4 EXECUTION_ROADMAP). Plusieurs sont des héritages directs de la dérive 08-18/05 (V6-J2, V6-J3, V6-J0, Voie A.2, Voie B = continuation de l'approche "tweaks bench V5.1 sans plafond") qui est précisément ce que VISION §8.4 identifie comme anti-pattern à arrêter.
- **Pourquoi c'est une déviation** : VISION §11.3 dit explicitement *"Si un nouveau chantier est proposé sans pouvoir être rattaché à un principe de ce document, il doit être tracé dans le log des déviations pour arbitrage explicite"*. Ces 11 tâches n'ont jamais été arbitrées vs la roadmap A→D. Les garder telles quelles risque de re-déclencher la boucle de tweaks (anti-pattern §8.4) au premier moment de baisse d'attention.
- **Bénéfice potentiel** :
  - `#246, #247, #248` (CH-52.9/10/11) : peuvent contenir des éléments d'infrastructure réutilisables pour runtime_v6 (cf audit code 18/05 — 65% réutilisable) → à arbitrer en lien avec Phase A
  - `#314` V6-J0 (purge KG + réingestion) : peut s'aligner avec Phase A2 (relations claim-vs-claim qui nécessitent ré-extraction)
  - Les autres (`#312, #313, #305, #308, #309`) : majoritairement continuation du paradigme V5.1+outils dormants, peu d'alignement avec KG-first runtime
- **Coût d'opportunité** : si on garde tout telles quelles → risque de re-démarrer ces tâches en mode "tweak" alors que Phase A1 (bitemporel) devrait être la priorité. Coût direct : ~0.5j d'arbitrage maintenant ; coût d'inaction : potentiellement 1-2 sem de re-dérive plus tard.
- **Recommandation agent** :
  - [x] **Différer à phase ultérieure** : `#246` CH-52.9 (Domain-Agnostic + Domain Packs) → Phase D1 (Domain Pack mécanisme) ; `#247` CH-52.10 (Frontend chat V5) → Phase C ; `#248` CH-52.11 (Deployment + réingestion) → Phase D2-D4
  - [x] **Différer à phase ultérieure** : `#314` V6-J0 (purge + réingestion) → Phase A2 (sera nécessaire post-bitemporel pour ré-extraire les claims avec les 4 timestamps)
  - [x] **Différer + ré-examiner** : `#70` facet linkage biomédical → après Phase B (validation cross-domain), c'est un fix V5 sur un domaine qui pourrait être impacté par le pivot
  - [x] **Ignorer / dropped** : `#312` V6-J2, `#313` V6-J3, `#305` V6-P2.2, `#309` Voie A.2 → continuation V5.1+outils dormants, hors paradigme KG-first runtime. À marquer `dropped` ou `deferred` selon décision utilisateur.
  - [x] **Ignorer / dropped** : `#308` Voie B (V6 évolution ClaimFirst + purge + réingestion) → est en partie absorbé dans Phase A2 du nouveau plan, doublonne avec V6-J0 (#314)
- **Statut** : `integrated` (arbitré 2026-05-19 par l'utilisateur)

**Décisions appliquées dans le tracker (2026-05-19)** :
- `#314` V6-J0 → **integrated** Phase A2 (subject mis à jour : "PHASE A2 — V6-J0 Purge KG + réingestion 38 docs")
- `#70` facet linkage biomédical → **deferred** post-Phase B (subject prefix "DEFERRED post-Phase B")
- `#246` CH-52.9 → **deferred** Phase D1 (subject prefix "DEFERRED Phase D1")
- `#247` CH-52.10 → **deferred** Phase C (subject prefix "DEFERRED Phase C")
- `#248` CH-52.11 → **deferred** Phase D2-D4 (subject prefix "DEFERRED Phase D2-D4")
- `#305` V6-P2.2 → **dropped** (status: deleted dans tracker)
- `#308` Voie B → **dropped** (status: deleted, absorbé par Phase A2 via #314)
- `#309` Voie A.2 → **dropped** (status: deleted, multiform contredit Probability Isolation)
- `#312` V6-J2 → **dropped** (status: deleted, outil dormant confirmé ; infra Neo4j Reference conservée pour usage futur si runtime_v6 le sollicite)
- `#313` V6-J3 → **dropped** (status: deleted, idem paradigme outil dormant)

---

## Statistiques (à mettre à jour à chaque revue)

| Période | Déviations détectées | Statut majoritaire | Note |
|---|---|---|---|
| 19/05/2026 (init) | 0 | — | Premier état |

---

## Comment l'utilisateur traite ce log

Workflow recommandé :

1. **Lecture en début de session** : `cat doc/ongoing/etudes/deviations_log.md` pour voir les déviations `new` depuis la dernière session
2. **Arbitrage** : pour chaque entrée `new`, l'utilisateur :
   - Lit la description + bénéfice/coût/recommandation
   - Décide : `integrated` / `deferred` / `dropped` / continue à `reviewed` si ambigu
   - **Modifie le statut** dans le log (et la section "Statuts" de l'entrée si besoin)
   - Si `integrated` : crée la tâche correspondante ou met à jour VISION/ROADMAP (avec ADR si rupture d'axiome)
   - Si `deferred` : note la phase cible
3. **Revue périodique** des `deferred` : en début de Phase B, C, D, relire les `deferred` pour les promouvoir si pertinent.

---

## Anti-patterns à ne PAS faire

- ❌ **Supprimer une entrée `new`** : préférer `dropped` avec une raison (préserve la mémoire d'apprentissage)
- ❌ **Tout marquer `integrated`** : si tout devient prioritaire, plus rien ne l'est. Discipline = direr "non" ou "plus tard" 80% du temps
- ❌ **Ignorer le log pendant 1 mois** : il devient illisible. Mieux vaut une revue de 5 min/jour qu'une revue de 1h/mois

---

*Log initialisé le 19/05/2026 par REFONDATION P4 (création agent vision-guardian).*

# Design — Gestion de versions a l'import documentaire

**Date** : 2026-03-22
**Statut** : Discovery terminee, en attente de validation
**Methode** : Analyse multi-AI (Claude + Codex/GPT-5.4)

---

## 1. Contexte

### Probleme actuel

OSMOSIS detecte automatiquement les versions/releases des documents via le framework ApplicabilityFrame (4 couches evidence-locked). Le taux de succes est d'environ 49% — plus de la moitie des documents n'obtiennent pas de version detectee.

Consequences :
- Les claims de ces documents ne sont pas filtrables par version dans la recherche
- La detection de contradictions cross-version est partielle
- L'evolution temporelle (tracking d'un sujet a travers les versions) est incomplete

### Proposition initiale

Ajouter une etape intermediaire entre la generation du cache d'extraction et le pipeline ClaimFirst, permettant a l'utilisateur de specifier/confirmer la version du document.

---

## 2. Flow actuel

```
Upload fichier
     |
     v
Docling extraction (cache .v4cache.json)
     |
     v
Pipeline ClaimFirst (17 phases)
  ├── Phase 0.5 : DocumentContext (sujet principal, topics)
  ├── Phase 0.55 : ComparableSubject (classification du sujet)
  ├── Phase 0.6 : ApplicabilityFrame (detection version)
  │     ├── Layer A : segmentation en EvidenceUnits
  │     ├── Layer B : scan deterministe (markers + value candidates)
  │     ├── Layer C : LLM evidence-locked (ne voit que des IDs)
  │     └── Layer D : validation deterministe
  ├── Phase 1-8 : extraction claims, entites, facettes, clustering...
  └── Persistance Neo4j + Qdrant
```

### Ce que contient le cache

Le fichier `.v4cache.json` contient :
- `doc_title` : titre extrait du document (ou None)
- `full_text` : texte complet
- `doc_items` : structure du document (paragraphes, tableaux, figures)
- `sections` : hierarchie des sections
- `chunks` : chunks avec text, kind, page_no

### Ce que contient l'ApplicabilityFrame

```json
{
  "doc_id": "...",
  "fields": [
    {
      "field_name": "release_id",
      "value_normalized": "2023",
      "display_label": "release",
      "evidence_unit_ids": ["EU:0:1"],
      "candidate_ids": ["VC:named_version:xyz"],
      "confidence": "high",
      "reasoning": "found in title + version marker nearby"
    }
  ],
  "unknowns": ["region", "standard_version"],
  "method": "llm_evidence_locked"
}
```

---

## 3. Analyse de pertinence

### Est-ce pertinent ?

**Oui, mais pas comme etape systematique.** L'intervention humaine est justifiee uniquement quand la detection automatique echoue.

### Consensus Claude + Codex

| Aspect | Verdict |
|---|---|
| Etape systematique a chaque upload | NON — friction excessive |
| Mecanisme de recuperation selectif | OUI — quand la detection echoue |
| Batch imports (100+ docs) | Mode bulk obligatoire, pas d'ecran par doc |
| Creation libre de versions | NON en v1 — risque de pollution |
| Feature flag par tenant | OUI — desactivable |

### Risques identifies

1. **Friction a l'import** : si chaque document demande une confirmation, les utilisateurs abandonneront
2. **Fatigue utilisateur** : pour un import de 50 documents, 50 confirmations = insoutenable
3. **Mauvaises assignations** : un utilisateur non-expert peut assigner la mauvaise version
4. **Pollution du KG** : des versions creees librement sans coherence avec le referentiel
5. **Fausse securite** : une version "user_assigned" donne une confiance non meritee

---

## 4. Architecture recommandee

### Principe : "Automation first, human recovery second"

```
Document uploade
     |
     v
Cache Docling (extraction)
     |
     v
Detection automatique de version (Phase 0.6)
     |
     v
+----------------------------+
| Confiance haute (>= 0.8) ? |
| OUI -> Auto-assign         |
| NON -> Queue de review      |
+----------------------------+
     | (si NON)
     v
+-----------------------------------+
| UI de review (optionnelle)        |
| - Candidats pre-detectes         |
| - Selection version existante     |
| - "Laisser non assigne"          |
| - Pas de creation libre (v1)     |
+-----------------------------------+
```

### Les 5 regles du design

1. **Automation first** : la version est detectee automatiquement dans 100% des cas. L'humain n'intervient que quand la machine echoue.

2. **Provenance explicite** : chaque version porte son `source` :
   - `document_evidence` : detectee par le pipeline
   - `user_assigned` : assignee manuellement
   - `batch_inferred` : deduite du batch d'import
   Le KG sait toujours d'ou vient l'information.

3. **Pas de creation libre** : l'utilisateur choisit parmi les versions existantes ou les candidats detectes. Pas de champ texte libre en v1.

4. **Batch-compatible** : pour 100+ documents, mode bulk avec :
   - Auto-assign au-dessus du seuil de confiance
   - Groupement des documents par version predite
   - Confirmation en bulk (pas doc par doc)
   - Exception queue pour les cas incertains

5. **Feature flag** : activable par tenant via DomainContextProfile. Desactive = comportement actuel inchange.

---

## 5. Alternatives sans intervention humaine

Avant d'ajouter une etape interactive, explorer ces ameliorations automatiques :

1. **Extraction depuis le nom de fichier** : "SAP_S4HANA_2023_Security_Guide.pdf" -> version 2023
2. **Extraction depuis le chemin/dossier** : "/docs/2023/security/" -> version 2023
3. **Regles de nommage par tenant** : conventions configurables (regex sur filename)
4. **Coherence du batch** : si 10 docs sont importes ensemble et 8 ont "2023", inferer pour les 2 restants
5. **Registre de versions** : table de reference des versions connues, matching automatique
6. **Second-pass recovery** : pipeline de recuperation pour les documents sans version, sans bloquer l'import

---

## 6. Impact estime sur la qualite du KG

| Metrique | Avant | Apres (estime) |
|---|---|---|
| Documents avec version detectee | ~49% | ~85-90% |
| Contradictions cross-version detectees | Partiel | Significativement ameliore |
| Friction a l'import | Aucune | Minimale (seulement les cas incertains) |

---

## 7. MVP — Implementation minimale

### Composants

| Composant | Effort |
|---|---|
| Feature flag tenant (DomainContextProfile) | 1h |
| Amelioration detection depuis filename/metadata | 2h |
| Endpoint `/api/admin/version-review` (queue des docs sans version) | 3h |
| Page admin "Version Review" (liste des docs non resolus) | 4h |
| Modification FrameBuilder pour accepter un `user_prior` | 2h |
| Mode batch (auto-assign + exception queue) | 3h |
| **Total MVP** | **~2 jours** |

### Ce qu'on NE fait PAS en v1

- Ecran de confirmation a chaque upload
- Creation libre de nouvelles versions (seulement selection parmi existantes)
- Assignation automatique basee sur le contenu LLM (on garde l'evidence-locked)
- Modification du pipeline existant (on ajoute, on ne modifie pas)

---

## 8. Questions ouvertes pour discussion

1. **Granularite** : version = release_id ? Ou faut-il aussi gerer edition, region, language ?
2. **Referentiel** : d'ou vient la liste des versions connues ? Config admin ? Auto-decouverte ?
3. **Retroactivite** : quand une version est assignee apres import, faut-il re-traiter les claims ?
4. **Multi-version** : un document peut-il couvrir plusieurs versions (ex: "What's New 2022-2023") ?
5. **Heritage** : si un document est une mise a jour d'un autre, le systeme le detecte-t-il ?

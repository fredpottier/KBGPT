# OSMOSE Assertion-Centric Implementation Plan

**Date** : 2026-01-07
**Status** : Spec validee, pret pour implementation
**Auteurs** : ChatGPT (conception UX/Data), Claude Code (implementation)
**Objectif** : Transformer l'affichage de confiance en "reponse instrumentee"

---

## 1. Vision et Paradigme

### 1.1 Le Probleme Actuel

L'affichage actuel sous la reponse :
- Score de confiance (pourcentage brut) → incomprehensible
- KnowledgeProofPanel → metriques techniques (concepts, relations)
- ReasoningTracePanel → triplets RDF illisibles
- CoverageMapPanel → desactive car non pertinent

**Resultat** : L'utilisateur ne comprend pas pourquoi il devrait faire confiance.

### 1.2 Le Nouveau Paradigme

> **OSMOSE ne "montre pas la preuve" → OSMOSE rend la reponse lisible selon son degre de verite**

Principes :
1. **La preuve est dans la forme**, pas dans un panneau externe
2. **4 statuts visuels** : FACT, INFERRED, FRAGILE, CONFLICT
3. **Contrat de verite** au lieu d'un score
4. **Proof Tickets** comme recus de preuve
5. **Le KG devient un outil expert**, pas un argument marketing

---

## 2. Modele de Donnees : Assertion-Centric

### 2.1 Unite Fondamentale : Assertion

```
Avant : Reponse = texte monolithique + metriques globales
Apres : Reponse = Liste ordonnee d'assertions, chacune avec son statut de verite
```

Une assertion = **un claim logique verifiable** (pas une phrase grammaticale).

### 2.2 Les 4 Statuts (fermes, non negociables)

| Statut | Definition | Rendu Visuel |
|--------|------------|--------------|
| `FACT` | Explicitement present dans >= 1 source | ● vert en marge |
| `INFERRED` | Deduit logiquement de FACTs | Texte italique |
| `FRAGILE` | Faiblement soutenu (1 source, ancien, ambigu) | Souligne pointille |
| `CONFLICT` | Sources incompatibles | Fond rouge pale |

### 2.3 Granularite

- 1 assertion = 1 claim logique (pas 1 phrase)
- Un paragraphe peut produire 1-3 assertions max
- Une liste : chaque bullet = 1 assertion si claim autonome
- Objectif : **6-14 assertions** pour une reponse de 3-8 paragraphes

### 2.4 Markdown

- `text_md` contient du Markdown (gras, italique, liens, listes simples)
- **Interdit** : headings, code blocks, tables
- Le frontend applique le style de statut sur le wrapper, pas a l'interieur

---

## 3. Regles de Classification Backend

### 3.1 Signaux Disponibles

Pour chaque assertion `A` :
- `evidence_used` (source_ids proposes par le LLM)
- Pour chaque SourceRef :
  - `document_date`
  - `authority` (official/internal/partner/external)
  - `excerpt`
- Similarite semantique assertion ↔ excerpt (cross-encoder)
- Detection de contradiction (NLI)

### 3.2 Seuils

```python
# Support score (cross-encoder similarity)
SUPPORT_FORT = 0.78      # >= seuil
SUPPORT_MOYEN = 0.65     # >= seuil, < SUPPORT_FORT
SUPPORT_FAIBLE = 0.65    # < seuil → ne compte pas

# Fraicheur
FRESH_MONTHS = 36        # doc_date >= now - 36 mois
STALE_MONTHS = 60        # doc_date < now - 60 mois

# Autorite (poids)
AUTHORITY_WEIGHTS = {
    "official": 1.0,
    "internal": 0.8,
    "partner": 0.7,
    "external": 0.6
}

# Contradiction
CONTRADICTION_THRESHOLD = 0.75
```

### 3.3 Algorithme de Classification

```
Etape 1 : Verifier si FACT possible
----------------------------------
supporting_sources = sources avec sim >= 0.65
weighted_support = sum(weight(authority) * sim)

FACT_CANDIDATE si :
  - au moins 1 source avec sim >= 0.78
  - OU au moins 2 sources avec sim >= 0.65 de documents differents

Sinon → pas FACT → aller vers INFERRED/FRAGILE

Etape 2 : Detecter CONFLICT
---------------------------
CONFLICT si :
  - >= 1 source supportante (sim >= 0.65)
  - ET >= 1 source contradictoire (contradiction_score >= 0.75)
  - provenant de documents differents

Si CONFLICT :
  - status = CONFLICT
  - sources = supportantes
  - contradictions = contradictoires

Etape 3 : Evaluer FRAGILE
-------------------------
FRAGILE si au moins un de :
  - FACT mais supporting_sources_count == 1 ET doc stale (> 60 mois)
  - FACT mais weighted_support < 0.9
  - FACT mais source "external" uniquement sans corroboration
  - INFERRED mais derived_from contient une assertion FRAGILE

Sinon → FACT "plein"

Etape 4 : Evaluer INFERRED
--------------------------
INFERRED si :
  - pas FACT (Etape 1 echoue)
  - ET le LLM fournit derived_from
  - ET tous les derived_from sont status FACT (pas FRAGILE/CONFLICT)
  - ET coherence logique validee (NLI entails >= 0.75)

Sinon → FRAGILE (inference non garantie)
```

---

## 4. Spec API `/search`

### 4.1 Schema de Reponse

```json
{
  "request_id": "uuid",
  "query": "string",
  "instrumented_answer": {
    "answer_id": "uuid",
    "generated_at": "ISO-8601",
    "truth_contract": {
      "facts_count": 0,
      "inferred_count": 0,
      "fragile_count": 0,
      "conflict_count": 0,
      "sources_count": 0,
      "sources_date_range": { "from": "YYYY", "to": "YYYY" }
    },
    "assertions": [...],
    "proof_tickets": [...],
    "sources": [...],
    "open_points": [...]
  },
  "retrieval": {
    "candidates_considered": 42,
    "top_k_used": 12,
    "kg_nodes_touched": 18,
    "kg_edges_touched": 27
  }
}
```

### 4.2 Assertion

```json
{
  "id": "A1",
  "text_md": "SAP S/4HANA repose exclusivement sur **SAP HANA**.",
  "status": "FACT|INFERRED|FRAGILE|CONFLICT",
  "scope": "paragraph|list_item",
  "sources": ["S1", "S2"],
  "contradictions": ["S7"],
  "derived_from": ["A1", "A2"],
  "inference_note": "string|null",
  "meta": {
    "support": {
      "supporting_sources_count": 2,
      "weighted_support": 1.63,
      "freshness": "fresh|mixed|stale",
      "has_official": true
    }
  }
}
```

### 4.3 SourceRef

```json
{
  "id": "S1",
  "document": {
    "id": "DOC1",
    "title": "SAP S/4HANA – Overview",
    "type": "PDF|PPTX|DOCX",
    "date": "2025-02",
    "authority": "official|internal|partner|external",
    "uri": "static/presentations/s4hana_overview.pptx"
  },
  "locator": {
    "page_or_slide": 8,
    "bbox": [0.11, 0.32, 0.89, 0.46]
  },
  "excerpt": "SAP S/4HANA is built exclusively on SAP HANA.",
  "thumbnail_url": "static/thumbnails/...",
  "evidence_url": "static/evidence/DOC1/slide/8#bbox=..."
}
```

### 4.4 ProofTicket

```json
{
  "ticket_id": "T1",
  "assertion_id": "A1",
  "title": "S/4HANA repose exclusivement sur SAP HANA",
  "status": "FACT",
  "summary": "Explicitement ecrit dans 2 sources officielles recentes.",
  "primary_sources": ["S1", "S2"],
  "cta": {
    "label": "Voir citation",
    "target": { "type": "source", "id": "S1" }
  }
}
```

### 4.5 TruthContract

```json
{
  "facts_count": 5,
  "inferred_count": 2,
  "fragile_count": 1,
  "conflict_count": 0,
  "sources_count": 3,
  "sources_date_range": { "from": "2023", "to": "2025" }
}
```

Rendu UI :
```
🛡️ Contrat de verite
5 faits sources · 2 inferences · 1 fragile · 0 conflit · Sources 2023–2025
```

---

## 5. Prompt LLM (Assertion-Based Synthesis)

### 5.1 Input au LLM

```json
{
  "question": "...",
  "evidence": [
    {
      "source_id": "S1",
      "document_title": "S/4HANA Technical Whitepaper",
      "document_date": "2024-05",
      "authority": "official",
      "page_or_slide": 12,
      "excerpt": "SAP S/4HANA is built exclusively on SAP HANA."
    }
  ]
}
```

### 5.2 Prompt (pseudo)

```
System: Tu es OSMOSE. Tu produis des reponses sous forme d'assertions.
Chaque assertion doit etre soit explicitement supportee par les sources,
soit marquee comme inference. Tu n'inventes jamais de citation.

User: Generate an instrumented answer as JSON.

Goal: 3-8 paragraphs, structured as 6-14 ordered assertions.

Output JSON with:
- "assertions": ordered list with fields:
  - "id": "A1", "A2", ...
  - "text_md": markdown text (no headings/tables/code blocks)
  - "kind": "FACT" or "INFERRED"
  - "evidence_used": array of source_id (required for FACT)
  - "derived_from": array of assertion ids (required for INFERRED)
  - "notes": 1 sentence explanation for INFERRED only
- "open_points": array when evidence is insufficient

Rules:
1) FACT: claim explicitly supported by at least one excerpt
2) INFERRED: not explicitly stated, derived only from FACT assertions
3) Keep assertions count between 6 and 14
4) Prefer recent and authoritative sources
5) If evidence conflicts, mark in open_points

Return only valid JSON.
```

---

## 6. Types TypeScript

```typescript
// Voir fichier complet dans frontend/src/types/instrumented.ts

export type AssertionStatus = "FACT" | "INFERRED" | "FRAGILE" | "CONFLICT";
export type AssertionScope = "paragraph" | "list_item";
export type Authority = "official" | "internal" | "partner" | "external";

export interface Assertion {
  id: string;
  text_md: string;
  status: AssertionStatus;
  scope: AssertionScope;
  sources: string[];
  contradictions: string[];
  derived_from: string[];
  inference_note: string | null;
  meta?: AssertionMeta;
}

export interface TruthContract {
  facts_count: number;
  inferred_count: number;
  fragile_count: number;
  conflict_count: number;
  sources_count: number;
  sources_date_range: { from: string; to: string };
}

export interface InstrumentedAnswer {
  answer_id: string;
  generated_at: string;
  truth_contract: TruthContract;
  assertions: Assertion[];
  proof_tickets: ProofTicket[];
  sources: SourceRef[];
  open_points: OpenPoint[];
}
```

---

## 7. Schemas Pydantic

```python
# Voir fichier complet dans src/knowbase/api/schemas/instrumented.py

from typing import List, Literal, Optional
from pydantic import BaseModel

AssertionStatus = Literal["FACT", "INFERRED", "FRAGILE", "CONFLICT"]
AssertionScope = Literal["paragraph", "list_item"]
Authority = Literal["official", "internal", "partner", "external"]

class Assertion(BaseModel):
    id: str
    text_md: str
    status: AssertionStatus
    scope: AssertionScope
    sources: List[str] = []
    contradictions: List[str] = []
    derived_from: List[str] = []
    inference_note: Optional[str] = None
    meta: Optional[AssertionMeta] = None

class TruthContract(BaseModel):
    facts_count: int
    inferred_count: int
    fragile_count: int
    conflict_count: int
    sources_count: int
    sources_date_range: SourcesDateRange

class InstrumentedAnswer(BaseModel):
    answer_id: str
    generated_at: str
    truth_contract: TruthContract
    assertions: List[Assertion]
    proof_tickets: List[ProofTicket] = []
    sources: List[SourceRef] = []
    open_points: List[OpenPoint] = []
```

---

## 8. Plan d'Implementation

### Phase 1 : Schemas et Types (2h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 1.1 | Creer `src/knowbase/api/schemas/instrumented.py` avec tous les Pydantic models | 1h |
| 1.2 | Creer `frontend/src/types/instrumented.ts` avec tous les types TS | 30min |
| 1.3 | Ajouter exports dans `__init__.py` et `index.ts` | 15min |
| 1.4 | Tests unitaires schemas (validation JSON exemple) | 15min |

### Phase 2 : Prompt LLM Assertion-Based (3h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 2.1 | Ajouter prompt `assertion_synthesis` dans `config/prompts.yaml` | 30min |
| 2.2 | Creer `src/knowbase/api/services/assertion_generator.py` | 1.5h |
| 2.3 | Parser la reponse LLM JSON → List[AssertionCandidate] | 30min |
| 2.4 | Tests unitaires avec mock LLM | 30min |

### Phase 3 : Classification Backend (4h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 3.1 | Creer `src/knowbase/api/services/assertion_classifier.py` | 2h |
| 3.2 | Implementer `compute_support_score()` (cross-encoder) | 30min |
| 3.3 | Implementer `detect_contradiction()` (NLI) | 30min |
| 3.4 | Implementer `classify_assertions()` avec algo 4 etapes | 30min |
| 3.5 | Tests unitaires classification (cas FACT/INFERRED/FRAGILE/CONFLICT) | 30min |

### Phase 4 : Construction InstrumentedAnswer (2h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 4.1 | Creer `src/knowbase/api/services/instrumented_answer_builder.py` | 1h |
| 4.2 | Implementer `build_truth_contract()` | 15min |
| 4.3 | Implementer `build_proof_tickets()` (top 3-5 assertions) | 30min |
| 4.4 | Implementer `build_sources()` (avec excerpts et thumbnails) | 15min |

### Phase 5 : Integration API (2h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 5.1 | Modifier `src/knowbase/api/services/search.py` pour appeler le nouveau pipeline | 1h |
| 5.2 | Ajouter flag `use_instrumented=true` pour activer progressivement | 15min |
| 5.3 | Modifier schema reponse `/search` pour inclure `instrumented_answer` | 30min |
| 5.4 | Tests integration API | 15min |

### Phase 6 : Frontend - Composants de Base (4h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 6.1 | Creer `AssertionRenderer.tsx` (rend une assertion avec style) | 1.5h |
| 6.2 | Creer `TruthContractBadge.tsx` (ligne compacte) | 30min |
| 6.3 | Creer `AssertionPopover.tsx` (hover details) | 1h |
| 6.4 | Creer `ProofTicketCard.tsx` (carte de preuve) | 1h |

### Phase 7 : Frontend - Integration (3h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 7.1 | Modifier `SearchResultDisplay.tsx` pour afficher `instrumented_answer` | 1h |
| 7.2 | Remplacer `SynthesizedAnswer.tsx` par assemblage d'assertions | 1h |
| 7.3 | Supprimer/simplifier `KnowledgeProofPanel.tsx` et `ReasoningTracePanel.tsx` | 30min |
| 7.4 | Tests visuels et ajustements | 30min |

### Phase 8 : Polish et Documentation (2h)

| Tache | Fichier | Effort |
|-------|---------|--------|
| 8.1 | Tooltip educatif premier hover | 30min |
| 8.2 | Gestion des cas limites (0 assertions, erreurs) | 30min |
| 8.3 | Documentation API dans Swagger | 30min |
| 8.4 | Mise a jour CLAUDE.md avec nouvelles conventions | 30min |

---

## 9. Estimation Totale

| Phase | Effort |
|-------|--------|
| Phase 1 : Schemas | 2h |
| Phase 2 : Prompt LLM | 3h |
| Phase 3 : Classification | 4h |
| Phase 4 : InstrumentedAnswer | 2h |
| Phase 5 : Integration API | 2h |
| Phase 6 : Frontend Base | 4h |
| Phase 7 : Frontend Integration | 3h |
| Phase 8 : Polish | 2h |
| **Total** | **~22h** |

---

## 10. Decisions de Design Validees

| Decision | Choix |
|----------|-------|
| Granularite | 1 assertion = 1 claim logique |
| Markdown | Dans text_md, pas de headings/tables/code |
| Nombre assertions | 6-14 par reponse |
| Thumbnails | Dans popover assertion, pas carousel global |
| KG | Cache par defaut, bouton "Voir structure" |
| Hover | Tooltip educatif premiere fois |
| Statuts | 4 seulement : FACT/INFERRED/FRAGILE/CONFLICT |

---

## 11. Fichiers a Creer/Modifier

### Backend (Python)

| Action | Fichier |
|--------|---------|
| CREER | `src/knowbase/api/schemas/instrumented.py` |
| CREER | `src/knowbase/api/services/assertion_generator.py` |
| CREER | `src/knowbase/api/services/assertion_classifier.py` |
| CREER | `src/knowbase/api/services/instrumented_answer_builder.py` |
| MODIFIER | `src/knowbase/api/services/search.py` |
| MODIFIER | `config/prompts.yaml` |

### Frontend (TypeScript)

| Action | Fichier |
|--------|---------|
| CREER | `frontend/src/types/instrumented.ts` |
| CREER | `frontend/src/components/chat/AssertionRenderer.tsx` |
| CREER | `frontend/src/components/chat/TruthContractBadge.tsx` |
| CREER | `frontend/src/components/chat/AssertionPopover.tsx` |
| CREER | `frontend/src/components/chat/ProofTicketCard.tsx` |
| MODIFIER | `frontend/src/components/ui/SearchResultDisplay.tsx` |
| SUPPRIMER/SIMPLIFIER | `frontend/src/components/chat/KnowledgeProofPanel.tsx` |
| SUPPRIMER/SIMPLIFIER | `frontend/src/components/chat/ReasoningTracePanel.tsx` |

---

## 12. Risques et Mitigations

| Risque | Mitigation |
|--------|------------|
| LLM ne genere pas JSON valide | Retry + fallback sur synthese classique |
| Cross-encoder trop lent | Cache embeddings, batch processing |
| Trop d'assertions (> 14) | Fusion par le backend, pas le LLM |
| Pas assez de sources | Fallback FRAGILE systematique |
| Utilisateur ne decouvre pas hover | Tooltip educatif + indication visuelle |

---

## 13. Criteres de Succes

1. **Fonctionnel** : L'API retourne `instrumented_answer` avec assertions classifiees
2. **Visuel** : Les 4 statuts sont visuellement distincts
3. **Comprehensible** : Le TruthContract remplace le score de confiance
4. **Performant** : Latence < 500ms supplementaire vs synthese classique
5. **Maintenable** : Seuils de classification configurables

---

**Document de reference pour l'implementation. Ne pas supprimer.**

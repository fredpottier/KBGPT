# ADR — Runtime Parse → Plan → Execute → Evaluate → Synthesize (Phase A3.0)

> **Status** : 🟢 Draft v1.2 (rédigé 2026-05-21, amendé v1.1 + v1.2 même jour suite 2 passes review Claude Web — 9.2/10 production-ready) — à valider par Fred
> **Phase** : A3 (Refondation runtime KG-first — architecture Parse+Evaluate)

**Changelog** :
- **v1.0** (2026-05-21 matin) — Draft initial. 13 sections, alignement VISION+ROADMAP, schémas Pydantic, prompts Parse/Evaluate/Synthesize, 8 gates A3, 5 alternatives écartées, plan migration V5.1.
- **v1.2** (2026-05-21 après 2ème passe Claude Web, score 9.2/10) — 5 clarifications d'implémentation NON-bloquantes :
  - §2.5 : note spike 0.5j A3.5 pour valider faisabilité `citation_coverage_rate ≥95%` (sinon descendre 90%)
  - §2.10 : arbre de décision explicit si tous modèles bake-off <85% (Option A / B / C selon best score)
  - §3.1.1 : précision templating Jinja2 + stratégie context window
  - §7.1 GA3-8 : budget tuning baseline V5.1 = 2-3 itérations max (fairness ablation)
  - §7.1 GA3-9 : construire 30q ciblées **à partir des conflits connus** (pas random) pour mesure significative
- **v1.1** (2026-05-21 après review Claude Web) — 6 P0 + 3 P1 intégrés :
  - **§2.3** coverage_signal : formule heuristique exacte par priority (P0-6)
  - **§2.4** EvaluateOutput.re_plan_hint : vocabulaire contrôlé `Literal[...]` (P0-4) + mapping hint→Plan
  - **§2.5** claim segmenter : référence explicite S7.1 GroundingVerifier (P1-9)
  - **§2.10** (nouveau) Model Selection : DeepSeek-V3 + Qwen2.5-7B + bake-off plan (P0-2)
  - **§3.1.1/3.2.1/3.3.1** (nouveau) Few-shot examples 3-5 par prompt (P0-3)
  - **§4.7.1** (nouveau) `_structured_diff` algorithm spécifié (P0-5)
  - **§7.1** GA3-6 : contingence C3 ≥0.40 acceptable + nouveau GA3-9 `conflict_exposure_rate` (P1-7, P1-8)
  - **§7.3** (nouveau) Protocole labellisation evaluator (50 cas, double annotation, Cohen's kappa ≥0.7) (P0-1)
> **Rattaché à** : `doc/VISION.md` §3.5 + §4.4 + `doc/EXECUTION_ROADMAP.md` §2 Phase A3
> **Étend** : `ADR_BITEMPOREL_CLAIMS.md` (filtre bitemporel runtime §4.4) + `ADR_RELATIONS_CLAIM_CLAIM.md` (consommation relations cross-claim)
> **Auteur** : Claude (rédaction sur base VISION + ROADMAP) + Fred (validation)
> **Référence externe** : Corrective RAG / CRAG (arxiv 2401.15884), Iterative Routing (arxiv 2501.07813), QAgent (arxiv 2510.08383), Adaptive RAG (Meilisearch 2026)

---

## 1. Contexte

### 1.1 Diagnostic V5.1 (état brut)

Runtime V5.1 (Reading Agent industrialisé, CH-52) plafonne à **C1 ≈ 0.61** (bench 18/05/2026) sur 12-15 LLM calls/q avec p50 ≈ 60s, p95 ≈ 90s. Architecture single-shot classifier (`answer_shape` factual/list/temporal/comparison/causal) + boucle agentique 6-8 itérations + multiform×5 + verifier HHEM passif.

Diagnostic structurel (VISION §6.4) :
- **Routing irréversible** : si la classification initiale se trompe, tout l'aval tombe — pas de mécanisme de récupération
- **Coût LLM élevé** : 12-15 calls/q, dont beaucoup en pure verification redondante
- **Verifier inopérant** : HHEM-2.1 active mais incapable d'invalider les choix de routing
- **Plafond observé** : aucune amélioration de prompt ou modèle ne fait franchir le 0.65

État de l'art 2026 (CRAG, Adaptive RAG, QAgent, Iterative Routing) prescrit une **architecture en 5 modules avec feedback loop évaluateur** pour atteindre 80%+ de fiabilité.

### 1.2 Acquis Phase A1 + A2

Avant ce runtime, deux fondations sont livrées :

**Phase A1** (terminée 19/05/2026) — Bitemporal Claims :
- 11 622 claims avec 4 timestamps (`valid_from`, `valid_until`, `ingested_at`, `invalidated_at`)
- Filtre runtime obligatoire (§4.4 ADR_BITEMPOREL) :
  ```cypher
  WHERE c.invalidated_at IS NULL
    AND (c.valid_from IS NULL OR c.valid_from <= datetime())
    AND (c.valid_until IS NULL OR c.valid_until >= datetime())
  ```

**Phase A2** (terminée 21/05/2026) — Relations claim-vs-claim :
- 5 relations canoniques : `:SAME_AS`, `:EVOLUTION_OF`, `:SUPERSEDES`, `:CONTRADICTS`, `:REFINES`, `:QUALIFIES`
- `:SUPERSEDES` invalide le claim cible (`invalidated_at` setté)
- `:ConflictPending` matérialise les conflits non-résolus (marker_type='prudence' OU CAS §9.4 ambigus)
- Tous les claims actifs portent timestamps cohérents

**Limite identifiée A2.13** : le LLM (Qwen3-235B) classifie encore des paires co-existantes en `CONTRADICTS` (5/5 faux positifs sur sample post-prompt strict). L'**architecture** protège (seuil `confidence < 0.85 → marker_type='prudence' → :ConflictPending`, jamais :SUPERSEDES). Le runtime A3 doit gérer la présence de `:ConflictPending` sans dépendre de la précision LLM.

### 1.3 Problème à résoudre

Comment construire un runtime qui :

1. **Décompose** la question en sub-goals concrets actionnables (pas de classification figée)
2. **Plan** les tools déterministes pour chaque sub-goal (pas de LLM ici)
3. **Execute** le plan en Cypher/Qdrant déterministes, en respectant les filtres bitemporels A1
4. **Evaluate** la qualité du résultat agrégé (lightweight LLM, ~200-500 tokens) avec verdict 4-classes
5. **Re-plan** si AMBIGUOUS (hard cap max 2 itérations)
6. **Synthesize** la réponse humaine avec citations cliquables + transparence sur les sub-goals non couverts

Et qui :
- **Respecte AX-1** (preuve localisable) — toute affirmation tracée à un Section.charspan
- **Respecte AX-3** (LLM evidence-locked) — étendu : LLM aux 3 points Parse/Evaluate/Synthesize uniquement
- **Respecte AX-14** (abstention qualifiée) — verdict INSUFFICIENT → abstention motivée
- **Gère les :ConflictPending** — exposition transparente au lieu de choisir au hasard
- **Reste domain-agnostic** — schémas Pydantic et prompts universels (pas SAP/médical/légal hardcoded)

---

## 2. Décisions architecturales

### 2.1 Module PARSE — Décomposition en sub-goals (LLM #1)

**Rôle** : convertir la question utilisateur en structure exécutable. Pas de classification figée — sub-goals concrets directement actionnables par le Plan.

**Input** :
```python
class ParseInput(BaseModel):
    question: str                    # texte brut de l'utilisateur
    tenant_id: str
    language_hint: Optional[str] = None  # 'fr' | 'en' | None (auto-detect)
    as_of_date: Optional[datetime] = None  # pour queries point-in-time historiques
```

**Output** (Pydantic, schéma versionné) :
```python
class SubGoal(BaseModel):
    """Un objectif concret extractable du KG, mappable à un tool unique."""
    kind: Literal[
        "fact_lookup",          # "X.predicate = ?"
        "list_enumeration",     # "tous les X tels que ..."
        "comparison",           # "X vs Y sur predicate Z"
        "lifecycle_trace",      # "évolution de X au fil du temps"
        "contradiction_check",  # "y a-t-il des contradictions sur X.predicate ?"
        "definition_lookup",    # "qu'est-ce que X ?"
    ]
    subject_canonical: Optional[str]  # entité focus (peut être None si large)
    predicate_hint: Optional[str]     # verbe ou relation visée (ex: "uses", "released_at")
    object_hint: Optional[str]        # valeur attendue ou pattern (ex: "version", "date")
    expected_value_kind: Optional[Literal["percent", "version", "number", "string", "date", "boolean"]]
    time_filter: Optional[Literal["as_of", "current", "evolution"]] = "current"
    priority: int = 1  # 1 = essentiel, 2 = enrichissement


class ParseOutput(BaseModel):
    sub_goals: List[SubGoal]
    entities: List[str]              # entités canonical détectées dans la question
    language: Literal["fr", "en", "de", "es", "other"]
    raw_question: str
    parse_confidence: float          # 0..1 score auto-évalué par Parse
    parse_warnings: List[str] = []   # ex: "ambiguous subject", "no time filter"
    schema_version: str = "a3.0"
```

**Prompt Parse** (placeholder agnostique) — voir §3.1 pour template complet.

**Garde-fous** :
- `parse_confidence < 0.5` → directement INSUFFICIENT_EVIDENCE en Evaluate (saut Plan/Execute inutile)
- Hard limit : max 5 sub_goals (au-delà = question mal formée, demander reformulation)
- Tous les `subject_canonical` doivent être ré-évalués par Execute (le LLM peut halluciner — Execute fait le sanity check via index canonical entities)

### 2.2 Module PLAN — Mapping déterministe sub_goal → tool

**Rôle** : pour chaque sub-goal, déterminer **quel tool** appeler et **avec quels paramètres**. **100% déterministe** — table de correspondance + Cypher templates paramétrés.

**Tools disponibles** (réutilisent infrastructure A1+A2) :

| Tool | Quand | Cypher / API |
|---|---|---|
| `kg_claims` | `fact_lookup`, `definition_lookup` | `MATCH (c:Claim {subject_canonical: $subj, tenant_id: $tid}) WHERE c.predicate = $pred AND filtre_bitemporel RETURN c` |
| `kg_claims_list` | `list_enumeration` | idem mais sans `predicate` figé, GROUP BY object |
| `lifecycle_query` | `lifecycle_trace`, time_filter='evolution' | `MATCH (c:Claim)-[:EVOLUTION_OF\|SUPERSEDES*0..]->(prev:Claim) WHERE c.subject_canonical = $subj RETURN ordered by valid_from` |
| `contradiction_surface` | `contradiction_check` | `MATCH (a:Claim)-[r:CONTRADICTS]-(b:Claim) WHERE a.subject_canonical = $subj OR b.subject_canonical = $subj RETURN a, b, r` |
| `conflict_pending_surface` | accompagne tous les sub_goals (cf §2.6) | `MATCH (cp:ConflictPending)-[:INVOLVES]->(c:Claim {claim_id: $cid}) RETURN cp` |
| `comparison_query` | `comparison` | 2× `kg_claims` parallèle puis diff |
| `qdrant_sections` | fallback OU enrichissement contextuel | recherche vectorielle e5-large 1024d sur `knowbase_chunks_v2` |

**Pas de tool LLM dans Plan** — c'est exclusivement de la résolution paramétrique. Si un sub-goal ne mappe à aucun tool, il est marqué `unmappable` et l'Execute le passera tel quel au Evaluate (qui décidera fallback).

**Output Plan** :
```python
class ToolCall(BaseModel):
    sub_goal_idx: int                # index dans ParseOutput.sub_goals
    tool: str                        # "kg_claims" | "lifecycle_query" | ...
    params: Dict[str, Any]           # paramètres Cypher / Qdrant
    depends_on: List[int] = []       # autres ToolCall idx qui doivent finir avant
    timeout_s: float = 15.0


class PlanOutput(BaseModel):
    tool_calls: List[ToolCall]
    unmappable_sub_goals: List[int]  # sub_goals sans tool — Evaluate décidera
    schema_version: str = "a3.0"
```

### 2.3 Module EXECUTE — Exécution déterministe + agrégation

**Rôle** : lancer les ToolCall (séquentiels ou parallèles selon `depends_on`), agréger les résultats par sub_goal, et **toujours appliquer les filtres bitemporels** sur les Claims retournés.

**Filtre bitemporel obligatoire sur tout retour Claim** (cf ADR_BITEMPOREL §4.4) :
```cypher
WHERE c.invalidated_at IS NULL
  AND (c.valid_from IS NULL OR c.valid_from <= $as_of_date)
  AND (c.valid_until IS NULL OR c.valid_until >= $as_of_date)
```

avec `$as_of_date = ParseInput.as_of_date` si setté, sinon `datetime()` (now).

**Side-effect critique** : pour chaque Claim ramené, Execute charge aussi les `:ConflictPending` adjacents (via `conflict_pending_surface` tool implicite) — pour exposer la transparence au Synthesize.

**Output Execute** :
```python
class ToolResult(BaseModel):
    sub_goal_idx: int
    tool: str
    claims: List[ClaimSummary]       # claims retournés (déjà filtre bitemporel)
    sections: List[SectionSummary]   # pour citations cliquables AX-1
    conflict_pendings: List[ConflictPendingSummary] = []  # adjacents aux claims
    relations_traced: List[RelationSummary] = []          # :EVOLUTION_OF, :SUPERSEDES, etc.
    coverage_signal: Literal["full", "partial", "empty"]  # cf formule ci-dessous
    duration_s: float
    error: Optional[str] = None
```

**Formule `coverage_signal`** (déterministe, calculée par Execute, P0-6 v1.1) :

```python
def compute_coverage_signal(n_claims: int, sub_goal_priority: int) -> str:
    if n_claims == 0:
        return "empty"
    if sub_goal_priority == 1:  # essentiel
        return "full" if n_claims >= 3 else "partial"
    else:  # priority == 2, enrichissement
        return "full" if n_claims >= 1 else "partial"  # tout résultat = full pour P2
```

**Justification seuils** :
- P1 essentiel : ≥3 claims donne un signal fort, 1-2 est ambigu (peut-être un seul fragment d'evidence partielle)
- P2 enrichissement : 1 claim suffit (le sub_goal est secondaire par construction)
- À calibrer en A3.4-bis si le evaluator confond `partial` avec `empty`

```python
class ExecuteOutput(BaseModel):
    results: List[ToolResult]
    total_duration_s: float
    schema_version: str = "a3.0"


class ExecuteOutput(BaseModel):
    results: List[ToolResult]
    total_duration_s: float
    schema_version: str = "a3.0"
```

**Pas de LLM dans Execute** — c'est exclusivement Cypher + Qdrant + (post-processing déterministe).

### 2.4 Module EVALUATE — Verdict lightweight (LLM #2)

**Rôle** : décider si le résultat agrégé répond aux sub-goals, ou s'il faut re-planifier / fallback / abstention.

**Input** :
```python
class EvaluateInput(BaseModel):
    parse_output: ParseOutput        # pour rappeler les sub_goals
    plan_output: PlanOutput
    execute_output: ExecuteOutput
    iteration: int                   # 0 = 1er pass, 1 = re-plan ; max 2
```

**Output** :
```python
class EvaluateOutput(BaseModel):
    verdict: Literal[
        "CORRECT",           # tous sub_goals couverts par evidence
        "AMBIGUOUS",         # couverture partielle ou conflits non-résolus — re-plan possible
        "INCORRECT",         # evidence contradictoire ou non-pertinente — fallback Qdrant TEXT_ONLY
        "INSUFFICIENT_EVIDENCE",  # tools ont retourné peu/rien → abstention motivée
    ]
    covered_sub_goals: List[int]     # idx couverts
    uncovered_sub_goals: List[int]   # idx restants
    re_plan_hint: Literal[           # P0-4 v1.1 : vocabulaire contrôlé (était str libre)
        "broaden_subject",           # élargir le subject_canonical du sub_goal
        "add_qdrant_fallback",       # ajouter qdrant_sections en tool complémentaire
        "decompose_comparison",      # split sub_goal comparison en 2× fact_lookup
        "check_lifecycle",           # ajouter lifecycle_query (si question implique évolution)
        "narrow_time_filter",        # affiner time_filter (as_of vs current vs evolution)
        "drop_overspecific_filters", # retirer predicate_hint ou object_hint si trop strict
        "none",                      # pas de hint utile (terminer même si AMBIGUOUS, hard cap)
    ] = "none"
    confidence: float                # 0..1
    reasoning: str                   # courte explication (40-80 mots max)
    schema_version: str = "a3.0"
```

**Mapping `re_plan_hint` → modification ToolCall dans Plan** (déterministe, P0-4 v1.1) :

| hint | Action Plan |
|---|---|
| `broaden_subject` | `subject_canonical` du sub_goal mappé → strip qualifiers, garder racine entity uniquement |
| `add_qdrant_fallback` | ajouter ToolCall `qdrant_sections` avec mêmes params à côté du tool primary |
| `decompose_comparison` | si le sub_goal était `kind=comparison`, créer 2× sub_goals `fact_lookup` (subject_a, subject_b) |
| `check_lifecycle` | ajouter ToolCall `lifecycle_query` avec `time_filter='evolution'` |
| `narrow_time_filter` | si time_filter était None → mettre `current` ; si `current` ambigu → demander as_of explicite (réintroduit la question à l'utilisateur via Synthesize warning) |
| `drop_overspecific_filters` | recréer ToolCall sans `predicate_hint`/`object_hint`, garder seulement `subject_canonical` |
| `none` | aucune modification — terminer iteration sans re-plan |

Le LLM Evaluate est contraint d'utiliser ce vocabulaire (Literal type côté Pydantic, validation stricte). Si l'output ne matche pas, retry avec instruction renforcée. Si retry échoue → fallback `none`.

**Prompt Evaluate** (courts ~200-500 tokens) — voir §3.2 pour template complet.

**Logique routing post-Evaluate** :
- `CORRECT` → goto Synthesize
- `AMBIGUOUS` ET `iteration < 2` → BOUCLE retour Plan (avec `re_plan_hint`)
- `AMBIGUOUS` ET `iteration ≥ 2` → fallback Qdrant TEXT_ONLY (cf §2.7 dégradation gracieuse)
- `INCORRECT` → fallback Qdrant TEXT_ONLY immédiat
- `INSUFFICIENT_EVIDENCE` → abstention motivée (§2.8)

**Critère de calibration** (cf §6 ROADMAP) : evaluator doit atteindre **≥85% accuracy** sur 50 cas synthétiques labellisés (CORRECT/AMBIGUOUS/INCORRECT/INSUFFICIENT) avant intégration. Bench dans sous-tâche A3.4-bis (BLOQUANT).

### 2.5 Module SYNTHESIZE — Rédaction réponse humaine (LLM #3, optionnel)

**Rôle** : rédiger la réponse finale humaine. **Contrainte stricte** : zéro création de fait, citations cliquables obligatoires.

**Input** :
```python
class SynthesizeInput(BaseModel):
    parse_output: ParseOutput
    execute_output: ExecuteOutput
    evaluate_output: EvaluateOutput
    response_mode: Literal["concise", "structured", "abstention"] = "structured"
```

**Output** :
```python
class CitedClaim(BaseModel):
    claim_verbatim: str               # texte exact du claim (jamais reformulé par LLM)
    doc_title: str
    section_id: str                   # pour click-to-source
    page: int
    charspan_start: int
    charspan_end: int


class SynthesizeOutput(BaseModel):
    answer_text: str                  # rédaction humaine (peut paraphraser pour fluidité)
    cited_claims: List[CitedClaim]    # toutes les sources mobilisées
    uncovered_sub_goals_warning: Optional[str]  # transparence : "sub_goal X non couvert par le corpus"
    conflict_pending_warning: Optional[str]     # transparence : "claims contradictoires non résolus sur sujet Y"
    mode: Literal["REASONED", "ANCHORED", "TEXT_ONLY", "ABSTENTION"]  # cf VISION §4.5
    schema_version: str = "a3.0"
```

**Prompt Synthesize** — domain-agnostic, mandatory citation, mention explicite des sub_goals manquants + :ConflictPending pertinents.

**Garde-fou AX-1** : chaque phrase factuelle de `answer_text` doit pointer vers ≥1 `CitedClaim`. Validation post-Synthesize via :
- **Claim segmenter** (P1-9 v1.1) : réutilise `src/knowbase/runtime_v51/verifier/claim_segmenter.py` (CH-52.8.1 livré, Pydantic V2) qui découpe `answer_text` en claims atomiques via regex sentence boundary + heuristiques NLI. Référence externe : Tang et al. 2024 "Minicheck" (arxiv 2404.10774) §3 segmentation factuelle.
- **Coverage check** : pour chaque claim segmenté, vérifier qu'au moins 1 `CitedClaim` est référencé dans la phrase d'origine (regex `\[doc_id, section X, page Y\]` ou marqueur équivalent).
- **Failure mode** : si claim segmenté sans citation → escalade en abstention pour ce claim ("information non sourcée — retrait de la réponse").
- Bench validation A3.8 doit mesurer `citation_coverage_rate` (% phrases factuelles avec citation) — cible ≥95%.
- **Spike validation (v1.2)** : avant A3.5 final, faire un spike 0.5j (intégré dans A3.5) qui mesure le `citation_coverage_rate` sur 20 réponses Synthesize sample. Si <95% mais ≥90% → descendre cible à 90% (acceptable). Si <90% → revoir prompt §3.3 + claim segmenter avant de proceed A3.7. Évite de poser un gate inaccessible.

### 2.6 Gestion des :ConflictPending (héritée Phase A2)

Phase A2 a livré **124 :ConflictPending** sur le KG actuel — conflits non-résolus à exposer au runtime au lieu de trancher au hasard.

**Politique runtime** :

| Cas | Décision Evaluate | Action Synthesize |
|---|---|---|
| Aucun :ConflictPending sur les claims retournés | (normal) | rédaction standard |
| 1+ :ConflictPending avec `conflict_type='contradiction'` impactant un sub_goal `fact_lookup`/`comparison` | `AMBIGUOUS` ou `CORRECT` avec warning | section "⚠ Claims contradictoires non résolus" + exposer les 2 (ou N) versions des claims impliqués + leurs sources |
| 1+ :ConflictPending `evolution_ambiguous` | warning seulement | mention transparente "versions parallèles, ordre temporel inconnu" |
| 1+ :ConflictPending `low_confidence_classification` | (ignore par défaut) | non exposé au user (signal de qualité interne uniquement) |

**Cypher tool intégré dans Execute** :
```cypher
MATCH (cp:ConflictPending {tenant_id: $tid, resolution_status: 'unresolved'})
WHERE EXISTS {
    MATCH (cp)-[:INVOLVES]->(c:Claim)
    WHERE c.claim_id IN $returned_claim_ids
}
RETURN cp
```

Appelé systématiquement par Execute après chaque tool principal. Coût négligeable (lookup index).

### 2.7 Trois modes de dégradation gracieuse

Hérité de VISION §4.5 — chaque réponse expose son mode :

| Mode | Déclencheur Evaluate | Fiabilité |
|---|---|---|
| `REASONED` | Verdict CORRECT, sub_goals couverts via `kg_claims`/`lifecycle_query`/`contradiction_surface` (graph paths) | Maximale — claims tracés |
| `ANCHORED` | Verdict CORRECT mais sans path graphe, routing structural via `qdrant_sections` enrichi | Bonne — contexte délimité |
| `TEXT_ONLY` | Verdict INCORRECT OU AMBIGUOUS×2 → fallback Qdrant brut | Dégradée — pas de traçabilité claim-level |
| `ABSTENTION` | Verdict INSUFFICIENT_EVIDENCE | N/A — réponse = abstention motivée |

**Le mode est exposé dans le payload retour API et l'UI** — l'utilisateur sait s'il regarde du KG-grounded vs fallback RAG.

### 2.8 Abstention qualifiée (AX-14)

Sur verdict `INSUFFICIENT_EVIDENCE`, Synthesize produit une réponse type :

```
Aucun claim pertinent trouvé pour répondre à votre question. Sub-goals non couverts :
  - <sub_goal 1 description>
  - <sub_goal 2 description>

Pistes possibles :
  - Reformuler la question avec des termes plus précis
  - Vérifier que le corpus indexé couvre ce sujet
```

**Jamais de fabrication de réponse** quand l'evidence manque. Mode = `ABSTENTION`.

### 2.10 Model Selection (P0-2 v1.1)

Choix de modèles LLM pour les 3 points contrôlés. Tous open-source (charte stricte — pas Anthropic/OpenAI en runtime).

| Module | Modèle primaire | Hosting | Justification |
|---|---|---|---|
| **Parse** (LLM #1) | `deepseek-ai/DeepSeek-V3.1` | DeepInfra | Capacité de décomposition forte (multi-step reasoning), suit bien les contraintes JSON schema. Bench A0 V5.1 = 0.620 (cf mémoire A7). 2-3s latence/q acceptable pour ~5 sub_goals max. |
| **Evaluate** (LLM #2 lightweight) | `Qwen/Qwen2.5-7B-Instruct-AWQ` | vLLM EC2 burst (≈1s/call) | Lightweight ~200-500 tokens output. Modèle déjà déployé EC2 pour ingestion (cf burst state). Bench A3.4-bis validera ≥85% accuracy. Si <85% → bake-off cross-modèle (cf ci-dessous). |
| **Synthesize** (LLM #3) | `deepseek-ai/DeepSeek-V3.1` | DeepInfra | Cohérence rédaction + respect contrainte "zéro création de fait". Latence acceptable (mode SYNTHESIZE optionnel — peut être skippé en mode "concise" si UX permet). |

**Tous open-source, charte respectée.** Aucun appel Anthropic/OpenAI dans le runtime.

**Plan de bake-off cross-modèle pour Evaluate (A3.4-bis)** :

Si Qwen2.5-7B-Instruct-AWQ n'atteint pas 85% accuracy sur les 50 cas synthétiques, tester en cascade :
1. `Qwen/Qwen3-14B` (DeepInfra, plus capable mais 2× plus cher)
2. `microsoft/Phi-4-14B` (mentionné comme higher-quality alternative état de l'art 2026)
3. `meta-llama/Llama-3.3-70B-Instruct-Turbo` (Together AI, plus cher mais top-tier)

Si aucun ne franchit 85% en single-shot → fallback architecture :
- **Option A** : simplifier verdicts à 3-classes (CORRECT / NEEDS_MORE / INSUFFICIENT) en fusionnant AMBIGUOUS+INCORRECT — réduit la difficulté
- **Option B** : ensemble vote majoritaire de 3 LLM (rejeté §9.3 pour coût × 3, mais à reconsidérer si single-shot échoue)
- **Option C** : revoir prompt §3.2 et few-shot examples — peut-être que le verdict 4-classes est mal défini

**Arbre de décision v1.2** (critère explicite selon le meilleur score atteint) :

```
Best single-shot accuracy (parmi 4 modèles testés) :
  ├─ ≥85% global ET ≥75% par catégorie → ACCEPTER ce modèle (cible atteinte)
  ├─ ∈ [80%, 85%[ global → Option C (revoir prompt §3.2 + few-shot) — gap rattrapable
  ├─ ∈ [75%, 80%[ global → Option A (simplifier 3-classes) — l'ambiguïté 4-classes est probable cause
  ├─ ∈ [70%, 75%[ global → Option B (ensemble 2-3 LLM vote majoritaire) — accepter coût × 2-3
  └─ < 70% global → STOP, escalation : revoir architecture Evaluate (peut-être que verdict-based n'est pas la bonne abstraction, considérer score continu 0-1 puis seuils)
```

Décision finale en A3.4-bis selon résultats benchmark + cet arbre.

**Fallback déterministe Parse** (si LLM échoue 2× retry + validation Pydantic) :
```python
def _parse_fallback_deterministic(question: str) -> ParseOutput:
    """Fallback minimal — 1 seul sub_goal fact_lookup naïf, parse_confidence=0.3."""
    return ParseOutput(
        sub_goals=[SubGoal(
            kind="fact_lookup",
            subject_canonical=None,  # Execute fera lookup canonical entities
            predicate_hint=None,
            object_hint=None,
            expected_value_kind=None,
            time_filter="current",
            priority=1,
        )],
        entities=_extract_naive_entities(question),  # NER simple via canonical entities index
        language=_detect_language(question),
        raw_question=question,
        parse_confidence=0.3,
        parse_warnings=["parse_llm_failed_fallback_deterministic_used"],
    )
```

Garde-fou : si `parse_confidence < 0.5` (incluant fallback à 0.3), Evaluate doit prioriser INSUFFICIENT_EVIDENCE plutôt que tenter un re-plan inutile (cf §2.4 logique routing).

### 2.9 Hard caps anti-thrash

Limites strictes pour empêcher la boucle infinie :

| Cap | Valeur | Effet déclencheur |
|---|---|---|
| Max iterations Plan→Execute→Evaluate | **2** | Au-delà : fallback TEXT_ONLY |
| Max sub_goals par ParseOutput | **5** | Au-delà : reject, demander reformulation |
| Max LLM calls totaux par requête | **5** (Parse + Evaluate×2 + Synthesize + abstention possible) | Au-delà : raise budget exception |
| Max latency total | **60s** (kill switch K-7) | Au-delà : abort + abstention |
| Max Cypher query depth | **5 hops** | Au-delà : timeout exception |

Tous mesurés via `BudgetTracker` (réutilisable de V5.1 — déjà existant, cf audit 18/05).

---

## 3. Prompts (Parse + Evaluate + Synthesize)

### 3.1 Prompt Parse (LLM #1)

Domain-agnostic, structuré, ~600 tokens system + question brute en user.

```
You are a query decomposer for a knowledge graph runtime.
Given a user question, produce a list of CONCRETE sub-goals that can be answered by querying a structured knowledge base.

OUTPUT JSON ONLY, matching this schema:
{
  "sub_goals": [
    {
      "kind": "fact_lookup | list_enumeration | comparison | lifecycle_trace | contradiction_check | definition_lookup",
      "subject_canonical": "entity name (or null if too broad)",
      "predicate_hint": "verb or relation (e.g. 'uses', 'released_at', or null)",
      "object_hint": "expected value or pattern (or null)",
      "expected_value_kind": "percent | version | number | string | date | boolean | null",
      "time_filter": "as_of | current | evolution",
      "priority": 1
    }
  ],
  "entities": ["entity1", "entity2"],
  "language": "fr | en | de | es | other",
  "raw_question": "<echo of original question>",
  "parse_confidence": 0.0..1.0,
  "parse_warnings": ["ambiguous subject", ...]
}

GUIDELINES:
- Decompose, don't classify. The output is a list of small, actionable goals — not a single "type".
- A simple question may have just 1 sub_goal. A complex one (comparison, lifecycle) may have 2-3.
- Use "fact_lookup" for "X has predicate Y" style questions.
- Use "list_enumeration" for "all X such that ..." style.
- Use "comparison" when comparing 2 entities — 2 fact_lookups + diff.
- Use "lifecycle_trace" when the question implies evolution over time.
- Use "contradiction_check" when the question explicitly asks about conflicts.
- Use "definition_lookup" for "what is X?" style.
- subject_canonical should be the most specific entity reasonably extractable. If unclear, null.
- time_filter:
    "current" = default, what's true now
    "as_of" = point-in-time historical query
    "evolution" = trace changes over time
- parse_confidence: low when subject ambiguous, multiple interpretations, or out-of-scope.

MAXIMUM 5 sub_goals. If the question is unanswerable, return [] sub_goals + warning + confidence < 0.3.
```

#### 3.1.1 Few-shot examples Parse (P0-3 v1.1)

**Stockés dans `src/knowbase/runtime_a3/prompts/parse_examples.json`** (versionnés, domain-agnostic) :

```json
[
  {
    "question": "What is the maximum number of users allowed for product X v2024?",
    "expected": {
      "sub_goals": [{
        "kind": "fact_lookup",
        "subject_canonical": "product X v2024",
        "predicate_hint": "maximum users",
        "expected_value_kind": "number",
        "time_filter": "current",
        "priority": 1
      }],
      "entities": ["product X v2024"],
      "language": "en",
      "parse_confidence": 0.9
    }
  },
  {
    "question": "Quelle est l'évolution de la stratégie de licence pour le module Y entre 2020 et 2024 ?",
    "expected": {
      "sub_goals": [{
        "kind": "lifecycle_trace",
        "subject_canonical": "module Y",
        "predicate_hint": "licensing strategy",
        "time_filter": "evolution",
        "priority": 1
      }],
      "entities": ["module Y"],
      "language": "fr",
      "parse_confidence": 0.85
    }
  },
  {
    "question": "Compare features of system A vs system B for use case Z",
    "expected": {
      "sub_goals": [
        {"kind": "comparison", "subject_canonical": "system A", "predicate_hint": "features for use case Z", "priority": 1},
        {"kind": "comparison", "subject_canonical": "system B", "predicate_hint": "features for use case Z", "priority": 1}
      ],
      "entities": ["system A", "system B", "use case Z"],
      "language": "en",
      "parse_confidence": 0.85
    }
  },
  {
    "question": "Are there any conflicting requirements between regulations X and Y?",
    "expected": {
      "sub_goals": [{
        "kind": "contradiction_check",
        "subject_canonical": "regulations X Y",
        "predicate_hint": "requirements",
        "priority": 1
      }],
      "entities": ["regulation X", "regulation Y"],
      "language": "en",
      "parse_confidence": 0.8
    }
  },
  {
    "question": "What's the weather like today?",
    "expected": {
      "sub_goals": [],
      "entities": [],
      "language": "en",
      "parse_confidence": 0.1,
      "parse_warnings": ["out_of_scope_for_corpus"]
    }
  }
]
```

À injecter dans le system prompt Parse via templating au moment du LLM call (réduit hallucinations, stabilise output JSON schema).

**Mécanisme d'injection (v1.2)** :
- **Templating engine** : `jinja2` (dépendance Python standard, déjà utilisée par `runtime_v5/prompt_builder.py`)
- **Stratégie** : examples injectés **à chaque LLM call** (pas de prompt caching côté DeepInfra à ce stade — à explorer en optim post-A3 si latence Parse devient bottleneck)
- **Format** : section `## EXAMPLES` insérée entre les guidelines et l'output schema, rendant les examples partie du system prompt
- **Stratégie context window** : DeepSeek-V3.1 supporte 64k tokens. System (~1500 tokens) + 5 examples (~800 tokens) + user question (~200 tokens max attendu) = ~2500 tokens — large marge sous 64k. Si la question utilisateur dépasse 5000 tokens (cas rare), tronquer à 2000 tokens début + 2000 tokens fin avec warning `parse_warnings: ["question_truncated"]`.
- **Versioning** : si on modifie un example, incrémenter le suffixe du fichier (`parse_examples.v1.json`, `parse_examples.v2.json`) — permet rollback et A/B testing évaluator.

Note v1.2 : même approche `jinja2` pour `evaluate_examples.json` et `synthesize_examples.json`.

### 3.2 Prompt Evaluate (LLM #2)

Lightweight ~200-500 tokens, focus verdict + reasoning court.

```
You are a result evaluator for a knowledge graph runtime.
Given a user's sub-goals and the aggregated tool results, decide if the system has enough evidence to answer.

INPUT: sub_goals + per-sub_goal tool results (claims, sections, conflict_pendings).

OUTPUT JSON ONLY:
{
  "verdict": "CORRECT | AMBIGUOUS | INCORRECT | INSUFFICIENT_EVIDENCE",
  "covered_sub_goals": [0, 1],
  "uncovered_sub_goals": [2],
  "re_plan_hint": "if AMBIGUOUS, suggest a fix (e.g. 'broaden subject', 'add qdrant_sections', 'decompose comparison further')",
  "confidence": 0.0..1.0,
  "reasoning": "<40-80 words explaining the verdict>"
}

VERDICTS:
- CORRECT: every sub_goal has ≥1 relevant claim. ConflictPending presence is OK (the synthesizer will expose them).
- AMBIGUOUS: partial coverage OR multiple plausible answers — re-plan can help.
    Examples: 1 sub_goal returned 0 results, but Qdrant might enrich. 2 sub_goals returned conflicting claims that aren't matched by a ConflictPending.
- INCORRECT: results contradict the sub_goals OR no evidence is relevant at all.
- INSUFFICIENT_EVIDENCE: tools returned almost nothing AND re-plan unlikely to help.
    Use this when the question is genuinely off-topic for the corpus.

RULES:
- A ConflictPending on a sub_goal subject is NOT automatically AMBIGUOUS. Mark CORRECT and let synthesizer expose the conflict transparently.
- If iteration == 1 and you already re-planned once, DO NOT mark AMBIGUOUS again — force a verdict between CORRECT, INCORRECT, INSUFFICIENT.
- Coverage signal "empty" on a priority-1 sub_goal + no fallback → INSUFFICIENT.
- coverage signal "partial" → AMBIGUOUS if iteration == 0, else CORRECT (with warning).

Be precise and brief. The synthesizer takes care of style.
```

#### 3.2.1 Few-shot examples Evaluate (P0-3 v1.1)

**Stockés dans `src/knowbase/runtime_a3/prompts/evaluate_examples.json`** :

```json
[
  {
    "case": "CORRECT — clear evidence",
    "input_summary": "sub_goal[0] fact_lookup 'product X.max_users' returned 3 claims with consistent value '500'",
    "expected": {"verdict": "CORRECT", "covered_sub_goals": [0], "uncovered_sub_goals": [], "re_plan_hint": "none", "confidence": 0.92, "reasoning": "Three concordant claims directly answer the question. ConflictPending absent. No re-plan needed."}
  },
  {
    "case": "AMBIGUOUS — partial coverage, re-plan recommended",
    "input_summary": "sub_goal[0] fact_lookup returned 0 claims; coverage_signal='empty'; iteration=0",
    "expected": {"verdict": "AMBIGUOUS", "covered_sub_goals": [], "uncovered_sub_goals": [0], "re_plan_hint": "add_qdrant_fallback", "confidence": 0.65, "reasoning": "No KG claims but the question may have Qdrant-only evidence. Suggest qdrant_sections fallback."}
  },
  {
    "case": "AMBIGUOUS post re-plan (iteration=1) → escalate to CORRECT with warning",
    "input_summary": "iteration=1, sub_goal[0] now has 1 claim partial; sub_goal[1] still empty",
    "expected": {"verdict": "CORRECT", "covered_sub_goals": [0], "uncovered_sub_goals": [1], "re_plan_hint": "none", "confidence": 0.55, "reasoning": "Re-plan didn't fully resolve. Proceed with partial answer + uncovered sub_goal warning."}
  },
  {
    "case": "INCORRECT — results contradict question",
    "input_summary": "Question asks about feature Z in product X; tool returned only claims about product Y (wrong subject)",
    "expected": {"verdict": "INCORRECT", "covered_sub_goals": [], "uncovered_sub_goals": [0], "re_plan_hint": "broaden_subject", "confidence": 0.7, "reasoning": "Results pertain to product Y, not product X. Re-plan with broader subject canonicalization."}
  },
  {
    "case": "INSUFFICIENT_EVIDENCE — out of corpus scope",
    "input_summary": "parse_confidence=0.2 (LLM warning out_of_scope); all tools returned empty",
    "expected": {"verdict": "INSUFFICIENT_EVIDENCE", "covered_sub_goals": [], "uncovered_sub_goals": [0], "re_plan_hint": "none", "confidence": 0.95, "reasoning": "Question is out of corpus scope (Parse confidence 0.2). Abstain rather than fabricate."}
  }
]
```

### 3.3 Prompt Synthesize (LLM #3, optionnel)

```
You are a knowledge synthesizer. Write a clear, factual response to the user's question, based STRICTLY on the cited claims.

INPUT: question + cited claims (verbatim text + source) + evaluation verdict + uncovered/conflict warnings.

RULES (NON-NEGOTIABLE):
- NEVER invent facts. Every factual statement must trace to a cited_claim.
- Quote claims verbatim when they directly answer the question. Otherwise paraphrase WITHOUT changing meaning.
- If sub_goals are uncovered, mention it in a "⚠ Sub-goals not covered" section at the end.
- If ConflictPending exist on the topic, add a "⚠ Conflicting sources" section with both/all versions exposed.
- Citations: for each fact, add [doc_id, section X, page Y] inline. The UI converts these to clickable links.

OUTPUT JSON:
{
  "answer_text": "<natural language answer with inline citations>",
  "cited_claims": [...claim refs...],
  "uncovered_sub_goals_warning": "..." or null,
  "conflict_pending_warning": "..." or null,
  "mode": "REASONED | ANCHORED | TEXT_ONLY | ABSTENTION"
}

Be concise. Respect AX-1 (every fact traced) and AX-14 (abstain if no evidence).
```

#### 3.3.1 Few-shot examples Synthesize (P0-3 v1.1)

**Stockés dans `src/knowbase/runtime_a3/prompts/synthesize_examples.json`** :

```json
[
  {
    "case": "standard answer with inline citations",
    "input_summary": "1 sub_goal CORRECT, 2 cited_claims, no ConflictPending",
    "expected_answer_pattern": "Product X v2024 supports a maximum of 500 users [doc_42, section 3, page 12]. This limit applies to all user types including administrators [doc_42, section 3, page 13]."
  },
  {
    "case": "answer with ConflictPending warning",
    "input_summary": "1 sub_goal CORRECT but 1 ConflictPending of type='contradiction'",
    "expected_answer_pattern": "Product X v2024 supports a maximum of 500 users [doc_42, section 3, page 12].\n\n⚠ Conflicting sources: a separate document mentions a limit of 1000 users [doc_57, section 1, page 4]. The two claims are not temporally ordered — consult both sources for context."
  },
  {
    "case": "abstention (INSUFFICIENT_EVIDENCE)",
    "input_summary": "verdict=INSUFFICIENT_EVIDENCE, 0 cited_claims",
    "expected_answer_pattern": "Aucun claim pertinent trouvé pour répondre à votre question.\n\nSub-goals non couverts :\n  - <description sub_goal 1>\n\nPistes possibles :\n  - Reformuler avec termes plus précis\n  - Vérifier que le corpus indexé couvre ce sujet"
  }
]
```

---

## 4. Tool Registry — Cypher templates paramétrés

Détail des tools utilisés par Plan + Execute. **Tous Cypher déterministes**, aucun LLM appelé dans ces queries.

### 4.1 `kg_claims` (fact_lookup, definition_lookup)

```cypher
MATCH (c:Claim {tenant_id: $tid})
WHERE c.subject_canonical = $subject
  AND ($predicate IS NULL OR c.predicate = $predicate)
  AND c.invalidated_at IS NULL
  AND (c.valid_from IS NULL OR c.valid_from <= $as_of)
  AND (c.valid_until IS NULL OR c.valid_until >= $as_of)
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
LIMIT 50
```

### 4.2 `kg_claims_list` (list_enumeration)

```cypher
MATCH (c:Claim {tenant_id: $tid})
WHERE ($subject_filter IS NULL OR c.subject_canonical = $subject_filter)
  AND ($predicate IS NULL OR c.predicate = $predicate)
  AND c.invalidated_at IS NULL
  AND (c.valid_from IS NULL OR c.valid_from <= $as_of)
  AND (c.valid_until IS NULL OR c.valid_until >= $as_of)
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
ORDER BY c.confidence DESC
LIMIT 100
```

### 4.3 `lifecycle_query` (lifecycle_trace, time_filter='evolution')

```cypher
MATCH (c:Claim {tenant_id: $tid, subject_canonical: $subject})
OPTIONAL MATCH path = (c)-[:EVOLUTION_OF|SUPERSEDES*0..5]-(other:Claim)
WITH collect(DISTINCT c) + collect(DISTINCT other) AS claims_set
UNWIND claims_set AS c
WITH DISTINCT c
WHERE c IS NOT NULL
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
ORDER BY coalesce(c.valid_from, c.ingested_at)
```

**Note** : retourne **toutes** les versions (actives + invalidées) pour permettre la trace historique. Le filtre `invalidated_at` ne s'applique PAS au lifecycle_trace, contrairement à fact_lookup. Le synthesizer affiche la timeline.

### 4.4 `contradiction_surface` (contradiction_check)

```cypher
MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(b:Claim {tenant_id: $tid})
WHERE (a.subject_canonical = $subject OR b.subject_canonical = $subject)
  AND a.invalidated_at IS NULL AND b.invalidated_at IS NULL
OPTIONAL MATCH (a)-[:EVIDENCED_BY]->(sa:Section)
OPTIONAL MATCH (b)-[:EVIDENCED_BY]->(sb:Section)
RETURN a, b, r, collect(sa) AS sections_a, collect(sb) AS sections_b
LIMIT 20
```

### 4.5 `conflict_pending_surface` (transversal, accompagne tous les tools)

```cypher
MATCH (cp:ConflictPending {tenant_id: $tid, resolution_status: 'unresolved'})
WHERE EXISTS {
    MATCH (cp)-[:INVOLVES]->(c:Claim)
    WHERE c.claim_id IN $returned_claim_ids
}
MATCH (cp)-[:INVOLVES]->(involved:Claim)
RETURN cp, collect(involved) AS involved_claims
```

### 4.6 `qdrant_sections` (fallback ou enrichissement)

```python
# Pseudo-code (pas Cypher)
results = qdrant_client.search(
    collection="knowbase_chunks_v2",
    query_vector=embed(question),
    limit=20,
    filter={"tenant_id": tid},
    score_threshold=0.5,
)
return [{"section_id": r.payload["section_id"], "text": r.payload["text"], "score": r.score} for r in results]
```

### 4.7 `comparison_query` (comparison)

Composé : 2× `kg_claims` parallèle puis diff structurée :
```python
def comparison_query(subject_a, subject_b, predicate, as_of, tenant_id):
    claims_a = kg_claims(subject_a, predicate, as_of, tenant_id)
    claims_b = kg_claims(subject_b, predicate, as_of, tenant_id)
    return {
        "subject_a": subject_a, "claims_a": claims_a,
        "subject_b": subject_b, "claims_b": claims_b,
        "diff_summary": _structured_diff(claims_a, claims_b),  # déterministe, cf §4.7.1
    }
```

#### 4.7.1 Algorithme `_structured_diff` (P0-5 v1.1)

Algorithme déterministe (no LLM) pour différencier 2 listes de claims sur le même predicate.

```python
def _structured_diff(claims_a: list[Claim], claims_b: list[Claim]) -> StructuredDiff:
    """Diff deux listes de claims (typiquement comparison de 2 entités sur même predicate).

    Retourne une structure groupée par predicate avec flags par type de différence.
    """
    # 1. Index par predicate
    pred_a = defaultdict(list)
    pred_b = defaultdict(list)
    for c in claims_a: pred_a[c.predicate].append(c)
    for c in claims_b: pred_b[c.predicate].append(c)

    all_predicates = set(pred_a.keys()) | set(pred_b.keys())
    flags = []

    for pred in all_predicates:
        list_a = pred_a.get(pred, [])
        list_b = pred_b.get(pred, [])

        # 2. Predicate présent dans un seul côté
        if not list_a:
            flags.append({
                "predicate": pred,
                "type": "only_in_b",
                "claims_b": [c.claim_id for c in list_b],
                "severity": "medium",  # information manquante dans A
            })
            continue
        if not list_b:
            flags.append({"predicate": pred, "type": "only_in_a", "claims_a": [c.claim_id for c in list_a], "severity": "medium"})
            continue

        # 3. Predicate présent des 2 côtés : comparer les objects
        objects_a = {c.value_normalized or c.value for c in list_a}
        objects_b = {c.value_normalized or c.value for c in list_b}

        if objects_a == objects_b:
            flags.append({"predicate": pred, "type": "identical", "severity": "none"})
        elif objects_a & objects_b:
            # intersection non vide mais différence
            flags.append({
                "predicate": pred,
                "type": "partial_overlap",
                "shared": list(objects_a & objects_b),
                "only_a": list(objects_a - objects_b),
                "only_b": list(objects_b - objects_a),
                "severity": "medium",
            })
        else:
            # disjoints
            flags.append({
                "predicate": pred,
                "type": "value_divergence",
                "values_a": list(objects_a),
                "values_b": list(objects_b),
                "severity": "high",
                # Si value_kind == 'number' / 'percent' / 'version' : c'est probablement une contradiction
                # Si value_kind == 'string' : peut être une variation lexicale (à raffiner par claim_relation_classifier futur)
            })

        # 4. Shift temporel (valid_from différent) — signal d'évolution
        valid_from_a = {c.valid_from for c in list_a if c.valid_from}
        valid_from_b = {c.valid_from for c in list_b if c.valid_from}
        if valid_from_a and valid_from_b:
            min_a, max_a = min(valid_from_a), max(valid_from_a)
            min_b, max_b = min(valid_from_b), max(valid_from_b)
            if max(min_a, min_b) > min(max_a, max_b):  # intervalles disjoints
                flags.append({
                    "predicate": pred,
                    "type": "temporal_shift",
                    "range_a": (min_a, max_a),
                    "range_b": (min_b, max_b),
                    "severity": "low",  # informatif, pas contradictoire
                })

    return StructuredDiff(predicates=flags, summary=_summary_text(flags))


class StructuredDiff(BaseModel):
    predicates: List[Dict]  # liste de flags par predicate
    summary: str            # texte court résumé pour Synthesize
```

**Utilisation Synthesize** : le `StructuredDiff.summary` est passé au prompt Synthesize qui rédige une comparaison naturelle ("X supporte 500 users, tandis que Y en supporte 1000. Sur le predicate Z, X dispose en plus de la feature W absente de Y.").

**Note charte** : aucun vocabulaire SAP/aerospace/médical hardcodé. Tous les flags sont génériques (`identical`, `partial_overlap`, `value_divergence`, `temporal_shift`, `only_in_a/b`).

---

## 5. Schémas Pydantic complets (versionnés)

Tous les schémas exposent un champ `schema_version: str = "a3.0"`. Migration future : `a3.1`, `a4.0` etc. avec backward compat via Pydantic discriminated unions.

Référence à coder dans `src/knowbase/runtime_a3/schemas.py`.

---

## 6. Sous-tâches Phase A3 (mapping vers backlog)

Cf EXECUTION_ROADMAP §2 Phase A3.

| Task # | Sous-tâche | Effort | Dépend |
|---|---|---|---|
| #323 | A3.0 ADR (ce document) | 1j | — |
| TBD | A3.1 Module `parse/` | 1.5-2j | A3.0 |
| TBD | A3.2 Module `plan/` | 1.5j | A3.1 |
| TBD | A3.3 Module `execute/` | 1.5j | A3.2 |
| TBD | A3.4 Module `evaluate/` | 2-3j | A3.3 |
| TBD | **A3.4-bis Bench evaluator isolé (BLOQUANT)** | 1-1.5j | A3.4 |
| TBD | A3.5 Module `synthesize/` | 1j | A3.4 |
| TBD | A3.6 Suppressions ciblées V5.1 | 1j | A3.5 |
| TBD | A3.7 Endpoint `/api/runtime_v6/answer` | 0.5j | A3.5 |
| TBD | A3.8 Bench A3 final (50q SAP stratifiées) | 1j | A3.7 |
| TBD | A3.9 Ablation study (runtime_v6 vs V5.1+prompt tuning) | 1j | A3.8 |

**Total Phase A3** : ~14-17j effectifs + buffer = **3-4 semaines** (cohérent ROADMAP).

---

## 7. Gates et Kill switches

### 7.1 Gates Phase A3

| Gate | Critère | Méthode |
|---|---|---|
| **GA3-1** | Tous les modules Parse/Plan/Execute/Evaluate/Synthesize implémentés avec schémas Pydantic versionnés | Code review + import test |
| **GA3-2** | Evaluator accuracy ≥85% global ET ≥75% par catégorie sur 50 cas synthétiques labellisés (cf §7.3 protocole) | Bench A3.4-bis |
| **GA3-3** | Filtres bitemporels appliqués dans 100% des Cypher claim retrieval | Audit Cypher static + smoke test 10q |
| **GA3-4** | `:ConflictPending` exposés correctement dans answer_text quand présents | Smoke test 5q avec conflits connus |
| **GA3-5** | C1 ≥0.75 sur 50q SAP stratifiées (vs V5.1 ≈0.61) | Bench A3.8 |
| **GA3-6** | C3 ≥0.50 sur lifecycle/évolution (vs V5.1 ≈0.25). **Contingence P1-7 v1.1** : C3 ≥0.40 acceptable comme "progrès significatif" — lifecycle/évolution reste feature Beta en Phase B avec disclaimer UI | Bench A3.8 (sous-set) |
| **GA3-7** | Latence p50 <30s, p95 <60s (vs V5.1 60s/90s) | Bench A3.8 |
| **GA3-8** | Ablation : delta runtime_v6 vs V5.1+prompt-tuning ≥10pp sur C1 ou C3. **Budget tuning baseline V5.1 = 2-3 itérations max** (v1.2) — éviter le moving target qui rendrait le gate inatteignable artificiellement. Tuning baseline réalisé en début de A3.9, gelé avant comparaison. | Bench A3.9 |
| **GA3-9** (P1-8 v1.1) | `conflict_exposure_rate` ≥ 5% sur 30q **ciblées** (v1.2 : construites à partir des claims impliqués dans les `:ConflictPending` du KG actuel, pas random sampling — sinon avec ~12 conflits dans le corpus, le random sampling tape rarement) — vérifie que Synthesize expose correctement les contradictions | Bench A3.8 (sous-set ConflictPending) |

Tous bloquants sauf GA3-6 (contingence ≥0.40). Échec d'un autre gate = ré-examen architecture avant production.

**Note GA3-9** : si <5% des queries appropriées exposent les ConflictPending, soit (a) Synthesize les ignore par bug, soit (b) le matching `:ConflictPending` adjacents échoue côté Execute. Diagnostic et fix avant validation finale.

### 7.2 Kill switches au runtime

| Switch | Déclencheur | Action |
|---|---|---|
| **K-3** (existant ROADMAP) | C1 <0.65 OU C3 <0.40 OU latence p50 >90s post-A3.8 | Pause Phase B, diagnostic |
| **K-7** (existant ROADMAP) | `re_plan_rate >30%` OU `evaluator_accuracy <85%` OU `latency_p95 >60s` | Pause, debug evaluator |

### 7.3 Protocole labellisation Evaluator (P0-1 v1.1) — GA3-2 bloquant

**Objectif** : produire un dataset de 50 cas synthétiques avec ground truth fiable pour mesurer l'accuracy de l'Evaluator. Sans labellisation rigoureuse, GA3-2 est non-vérifiable.

**Composition du dataset** (50 cas, répartition équilibrée) :

| Catégorie | Nb cas | Détails |
|---|---|---|
| factual simple | 10 | sub_goal `fact_lookup`, evidence claire ou absente |
| lifecycle/évolution | 10 | sub_goal `lifecycle_trace`, chains :EVOLUTION_OF/:SUPERSEDES |
| comparison | 10 | 2 sub_goals `fact_lookup` puis diff |
| contradiction_check | 10 | sub_goal explicite + présence :CONTRADICTS ou :ConflictPending |
| unanswerable / edge | 10 | hors-scope corpus, false premise, parse_confidence basse |

**Distribution attendue des verdicts** (sample équilibré, pas de biais en faveur d'un verdict) :
- CORRECT : 15-20 cas
- AMBIGUOUS : 10-15 cas
- INCORRECT : 5-10 cas
- INSUFFICIENT_EVIDENCE : 5-10 cas

**Protocole de labellisation** :
1. **Génération synthétique** des 50 cas par Claude Code à partir du KG actuel (claims réels + sub_goals construits + résultats simulés en variant claims présents/absents/contradictoires).
2. **Double annotation indépendante** :
   - Annotateur A : Fred (utilisateur produit)
   - Annotateur B : Claude Code (en mode "annotation" — relire chaque cas et proposer verdict + reasoning)
3. **Calcul Cohen's kappa** entre les 2 annotateurs sur les 50 verdicts :
   - κ ≥ 0.7 → labellisation acceptée, dataset gold pour A3.4-bis
   - κ < 0.7 → désaccord trop fort → **revoir les définitions de verdicts** dans le prompt Evaluate §3.2 (ambigüité sémantique entre AMBIGUOUS et INCORRECT typiquement)
4. **Résolution désaccords** : pour chaque cas où A ≠ B, discussion + arbitrage explicite. Le résultat arbitré devient ground truth.

**Persistance** : dataset stocké dans `benchmark/evaluator_a3/dataset.json` versionné, schéma :

```json
{
  "case_id": "EVAL_A3_001",
  "category": "factual_simple",
  "input": {
    "parse_output": {...},
    "plan_output": {...},
    "execute_output": {...},
    "iteration": 0
  },
  "ground_truth": {
    "verdict": "CORRECT",
    "covered_sub_goals": [0],
    "uncovered_sub_goals": [],
    "reasoning": "Clear factual answer with 3 concordant claims"
  },
  "annotators": {
    "fred": "CORRECT",
    "claude_code": "CORRECT",
    "kappa_agreement": true
  }
}
```

**Métrique GA3-2** : accuracy = `verdict_predicted == verdict_ground_truth` count / 50.

Cible : **≥ 85%** sur l'ensemble + ≥ 75% par catégorie (éviter qu'une seule catégorie tire la moyenne).

**Compute estimé** : 0.5j génération synthétique + 0.5j double annotation + 0.5j bench cross-modèle = **1.5j** (intégré dans A3.4-bis). Bloquant avant A3.7 (endpoint).

---

## 8. Conséquences

### 8.1 Conséquences positives

- ✅ **Robustesse aux erreurs de classification** : l'evaluator récupère les sub-goals mal décomposés via re-plan
- ✅ **Coût LLM divisé par 3-5** : 2-5 calls/q (vs 12-15 V5.1)
- ✅ **Latence cible atteignable** : p50 <30s vs V5.1 60s
- ✅ **Transparence ConflictPending** : les conflits Phase A2 sont exposés au lieu d'être ignorés
- ✅ **AX-3 renforcé** : 3 points LLM contrôlés (Parse/Evaluate/Synthesize), tout le reste déterministe
- ✅ **Migration progressive** : endpoint `/api/runtime_v6/answer` parallèle V5.1, bench shadow possible
- ✅ **Réutilisation infrastructure V5.1** : 65% du code peut être recyclé (ToolRegistry, BudgetTracker, JobStore, etc. — cf audit 18/05)

### 8.2 Conséquences négatives (assumées)

- ⚠️ **Evaluator = nouveau SPOF** si mal calibré (mitigation : bench A3.4-bis ≥85% accuracy, kill switch K-7)
- ⚠️ **Complexité accrue vs single-shot** : 5 modules + boucle vs 1 classifier (mitigation : ablation A3.9 valide le delta ≥10pp)
- ⚠️ **Coût Cypher complexes** : Lifecycle/contradiction queries peuvent toucher beaucoup de nodes (mitigation : LIMIT 50-100, max 5 hops, timeout 15s/tool)
- ⚠️ **Surface schéma Pydantic large** : 8+ classes à maintenir (mitigation : schema_version explicite + tests contract)

### 8.3 Risques mitigés

| Risque | Mitigation |
|---|---|
| Parse extrait sub-goals incohérents | parse_confidence < 0.5 → INSUFFICIENT direct, pas de Plan/Execute inutile |
| Evaluator boucle infinie sur AMBIGUOUS | Hard cap 2 itérations, fallback TEXT_ONLY |
| LLM Synthesize fabrique des faits | claim_segmenter post-Synthesize (réutilise S7.1 GroundingVerifier), abstention si claim non-cited |
| ConflictPending bruyant (124 dans KG actuel) | Filtre par `conflict_type` (only 'contradiction' et 'evolution_ambiguous' affichés, 'low_confidence_classification' silencieux) |
| LLM Parse ne respecte pas JSON schema | Retry 2× avec validation Pydantic stricte, sinon fallback Parse déterministe minimal (1 sub_goal `fact_lookup` avec entité naïve) |

---

## 9. Alternatives écartées

### 9.1 Single-shot classifier amélioré (V5.1 + prompt tuning)

**Idée** : garder l'architecture V5.1 (`answer_shape` classifier) mais améliorer le prompt + few-shot examples.

**Rejet** : observation V5.1 plafond 0.61 malgré 10+ itérations prompt tuning depuis mars 2026. L'irréversibilité du routing est le problème structurel — pas de mécanisme de récupération possible sans evaluator. Ablation A3.9 va vérifier formellement (gate ≥10pp delta).

### 9.2 Agentic loop libre (ReAct-style)

**Idée** : 1 LLM unique qui appelle tools en boucle libre jusqu'à satisfaction.

**Rejet** : viole **Probability Isolation** (§3.5) — LLM partout = pas de séparation contrôlée. Latence explose (8-15 calls observée V5.1). Pas de hard cap sémantique (re-plan). Pattern V5.1 dont on sort.

### 9.3 Évaluateur multi-shot (5 LLM calls Eval au lieu de 1)

**Idée** : pour augmenter robustesse evaluator, en faire un ensemble (3-5 calls, vote majoritaire).

**Rejet** : 3-5× le coût Eval, latence accrue, complexité d'agrégation. Mitigation préférable = calibration A3.4-bis (≥85% single-shot). Si single-shot ne franchit pas 85%, on revoit le prompt ou le modèle, pas l'architecture.

### 9.4 Pas d'evaluator (Plan→Execute→Synthesize direct)

**Idée** : économiser 1 LLM call en sautant Evaluate, et faire confiance au Plan déterministe.

**Rejet** : sans evaluator, aucun mécanisme de re-plan ni de fallback. Verifier inopérant V5.1 a déjà montré cette limite. L'evaluator EST le chaînon manquant identifié par CRAG.

### 9.5 LLM Parse ET LLM Plan (au lieu de Plan déterministe)

**Idée** : laisser le LLM choisir lui-même les tools après décomposition.

**Rejet** : viole AX-3 et augmente surface incertitude. Le Plan déterministe (table de correspondance) est **vérifiable, testable, débogable**. Le LLM peut se tromper sur sub_goals (récupérable par evaluator) ; il ne doit pas en plus se tromper sur le tool selection.

---

## 10. Plan de migration depuis V5.1

### 10.1 Endpoint parallèle pendant Phase A3

```
V5.1 (existant)  : POST /api/runtime_v5/answer
A3 (nouveau)     : POST /api/runtime_v6/answer
```

Les 2 endpoints coexistent pendant tout A3. Bench tape les 2 en parallèle (shadow mode confirmé faisable par audit 18/05).

### 10.2 Suppressions ciblées V5.1 (A3.6)

Une fois A3 validé (GA3-5 + GA3-6 + GA3-7 atteints) :

- `src/knowbase/runtime_v5/query_reformulator.py` — multiform×5 remplacé par Parse sub_goals
- `src/knowbase/runtime_v5/loop_signature.py` — agentic loop remplacée par Plan déterministe
- `src/knowbase/runtime_v5/execution_plan.py` — idem
- `src/knowbase/runtime_v5/domain_pack_loader.py` — Domain Packs réservés à Phase D (cf mémoire `feedback_domain_agnostic_pipeline_components.md`)
- `src/knowbase/runtime_v5/doc_topics_loader.py` — remplacé par lookup canonical entities
- `src/knowbase/runtime_v5/anthropic_llm_caller.py` — viole charte open-source

Code conservé tant que Phase B (cross-domain) n'est pas validée — fallback de secours.

### 10.3 Réutilisation V5.1 (65% selon audit 18/05)

À conserver et adapter :
- API Pydantic models (S5.1) — extension avec ParseOutput/PlanOutput/etc.
- AdmissionController, IdempotencyStore, JobStore, SSE (S5.2-S5.5)
- OTel/metrics (S6.1-S6.5)
- ToolRegistry (S3.1) — convertir vers ToolCall A3
- Verifier orchestrator (S7.6) — devient module `evaluate/` (claim segmenter S7.1 réutilisé)
- BudgetTracker, CancellationToken (S4.4)

---

## 11. Reviewers à solliciter

| Reviewer | Quoi | Priorité |
|---|---|---|
| **Fred (utilisateur)** | Validation décisions §2 + §3 prompts + gates §7 | **P0** bloquant |
| **Claude Web** | Audit cohérence vs CRAG/Adaptive RAG + détection trous logiques (notamment AMBIGUOUS handling et ConflictPending policy) | **P1** recommandé |
| **ChatGPT (revue externe)** | Sanity check sur trade-off latence/qualité + suggestions calibration evaluator | **P2** optionnel |

---

## 12. Liens

- `doc/VISION.md` §3.5 (Probability Isolation + Récupération d'erreur) + §4.4 (Pipeline runtime 5 modules)
- `doc/EXECUTION_ROADMAP.md` §2 Phase A3 (estimation 14-17j + buffer)
- `doc/ongoing/adr/ADR_BITEMPOREL_CLAIMS.md` §4.4 (filtre runtime obligatoire)
- `doc/ongoing/adr/ADR_RELATIONS_CLAIM_CLAIM.md` §2.6 ConflictPending + §2.1 relations canoniques
- `doc/ongoing/adr/ADR_RUNTIME_V5_READING_AGENT_INDUSTRIALIZATION.md` (CH-52 pour héritage 65%)
- Memory : `project_a2_13_llm_limitation.md` (raison de conserver le seuil 0.85)
- État de l'art : CRAG arxiv 2401.15884, QAgent arxiv 2510.08383, Iterative Routing arxiv 2501.07813

---

## 13. Status

| Acteur | Date | Verdict |
|---|---|---|
| Claude (rédaction) | 2026-05-21 | Draft v1.0 livré |
| Fred (validation produit) | TBD | À solliciter |
| Claude Web (review) | TBD | À solliciter post-validation Fred |

*Cet ADR est le pré-requis bloquant pour les sous-tâches A3.1 à A3.9. Toute modification d'architecture (Parse output, verdicts Evaluate, tool registry, kill switches) passe par une nouvelle version de ce document.*

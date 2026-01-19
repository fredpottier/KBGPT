# ADR: Validation des Coréférences Named↔Named

**Statut:** VALIDÉ
**Date:** 2025-01-15
**Auteurs:** Équipe OSMOSE
**Révisé:** Suite revue ChatGPT - corrections règles de gating
**Validé le:** 2025-01-15

---

## Contexte

### Problème identifié

Le moteur FastCoref (Pass 0.5) détecte des coréférences entre entités nommées qui sont des **faux positifs**. Exemple concret observé:

| Mention A | Mention B | Verdict FastCoref | Réalité |
|-----------|-----------|-------------------|---------|
| SAP S/4HANA | SAP HANA | Coréférents (0.85) | **FAUX** - ERP vs Base de données |

FastCoref retourne une confiance fixe (~0.85) et ne distingue pas les entités ayant des noms similaires mais des référents différents.

### Contrainte fondamentale: Agnosticité

La solution **DOIT** être totalement agnostique au domaine:
- Aucun catalogue spécifique (pas de fichier YAML "SAP_entities.yaml")
- Aucune liste noire/blanche liée à un domaine
- Seule personnalisation autorisée: `domain_context` (chaîne libre fournie par l'utilisateur)

### Architecture existante

```
Pass 0.5 (Linguistic Layer)
├── FastCorefEngine        # Détection coréférences (transformers)
├── CorefGatingPolicy      # Gating pour Pronoun→Entity (existe)
├── coref_models.py        # MentionSpan, CorefDecision, ReasonCode
└── coref_persist.py       # Persistance Neo4j
```

Le `CorefGatingPolicy` actuel gère uniquement les pronoms (il, she, it → antécédent).
Il n'existe **aucun** gating pour les paires Named↔Named.

---

## Proposition: Gating + LLM Arbitration + Cache

### Vue d'ensemble

```
FastCoref détecte paire (A, B)
         │
         ▼
┌─────────────────────────┐
│  NamedNamedGatingPolicy │
│  (heuristiques rapides) │
└─────────────────────────┘
         │
    ┌────┴────┬────────┐
    ▼         ▼        ▼
 ACCEPT    REVIEW    REJECT
    │         │        │
    │         ▼        │
    │   ┌──────────┐   │
    │   │ Cache?   │   │
    │   └────┬─────┘   │
    │        │         │
    │   HIT? ▼ MISS?   │
    │    │      │      │
    │    │      ▼      │
    │    │  ┌───────┐  │
    │    │  │  LLM  │  │
    │    │  │Arbiter│  │
    │    │  └───┬───┘  │
    │    │      │      │
    │    ▼      ▼      │
    └────►  Décision ◄─┘
              │
              ▼
         CorefDecision
         (audit Neo4j)
```

### 1. NamedNamedGatingPolicy - Heuristiques rapides

**Objectif:** Filtrer les cas évidents sans appeler le LLM.

#### Métriques calculées

| Métrique | Description | Bibliothèque |
|----------|-------------|--------------|
| `jaro_winkler(A, B)` | Similarité string (0-1) | `rapidfuzz` |
| `token_jaccard(A, B)` | Overlap tokens normalisés | built-in |
| `head_noun_match(A, B)` | Comparaison têtes nominales | `spaCy` |
| `tfidf_divergence(A, B)` | Divergence contextes locaux | `sklearn` |

#### Règles de décision (modèle "signaux de risque")

**Principe fondamental:** Pas de règles "guillotine". On accumule des signaux
de risque et la décision finale dépend du cumul. Seuls les cas extrêmes
(similarité très faible ou tokens disjoints) justifient un REJECT direct.

```python
def evaluate_named_pair(a: str, b: str, context_a: str, context_b: str) -> Decision:
    risk = 0

    jw = jaro_winkler(a, b)
    tj = token_jaccard(a, b)
    head_match = head_noun_match(a, b)

    # === REJECT direct (cas extrêmes uniquement) ===
    if jw < 0.55:
        return REJECT, "STRING_SIMILARITY_LOW"  # Mentions trop différentes

    if tj == 0:
        return REJECT, "NO_TOKEN_OVERLAP"  # Aucun token commun

    # === ACCEPT direct (similarité très haute) ===
    if jw >= 0.95 and tj >= 0.8:
        return ACCEPT, "HIGH_SIMILARITY"

    # === Accumulation de signaux de risque ===
    if not head_match:
        risk += 1  # Signal, pas blocage

    if tfidf_divergence(context_a, context_b) > 0.6:
        risk += 1  # Signal, pas blocage

    if 0.55 <= jw <= 0.85:
        risk += 1  # Zone de similarité moyenne

    if 0.1 < tj < 0.5:
        risk += 1  # Overlap faible mais non nul

    # === Décision finale ===
    if risk == 0:
        return ACCEPT, "LOW_RISK"

    return REVIEW, "NEEDS_LLM_VALIDATION"  # Zone grise → LLM
```

**Important:** `head_noun_mismatch` et `tfidf_divergence` sont des **signaux**,
jamais des raisons de REJECT seules. Deux mentions peuvent désigner la même
entité avec des têtes différentes ("the platform" ↔ "this service").

#### Exemple: "SAP S/4HANA" vs "SAP HANA"

| Métrique | Valeur | Effet |
|----------|--------|-------|
| Jaro-Winkler | ~0.87 | OK (> 0.55) |
| Token Jaccard | ~0.33 | risk += 1 |
| Head noun | "S/4HANA" ≠ "HANA" | risk += 1 |
| **Risk total** | **2** | **→ REVIEW** |

→ Envoyé au LLM pour arbitrage (pas de REJECT automatique).

### 2. Cache deux niveaux

#### Niveau 1: Cache global (paires normalisées)

```python
def cache_key(a: str, b: str) -> str:
    """Clé canonique indépendante de l'ordre."""
    norm_a = normalize(a)  # lowercase, strip, collapse spaces
    norm_b = normalize(b)
    return f"{min(norm_a, norm_b)}||{max(norm_a, norm_b)}"
```

**Stockage:** Redis ou fichier JSON local
**TTL:** Permanent (décisions stables)
**Exemple:**
```
"sap hana||sap s/4hana" → {same_entity: false, reason: "HEAD_NOUN_MISMATCH"}
```

#### Niveau 2: Cache contextuel (termes courts)

Pour les termes courts/ambigus (< 3 tokens), le contexte compte:

```python
def contextual_cache_key(a: str, b: str, context_hash: str) -> str:
    """Clé incluant le contexte pour termes ambigus."""
    base = cache_key(a, b)
    return f"{base}@{context_hash[:8]}"
```

**Exemple:** "HANA" seul peut désigner la DB ou être une abréviation.
Le contexte "database performance" vs "ERP migration" donne des résultats différents.

### 3. LLM Arbiter

#### Quand appelé

Uniquement pour les paires en **REVIEW** (zone grise) et **CACHE MISS**.

#### Batching

```python
async def arbitrate_batch(
    pairs: List[Tuple[str, str, str, str]],  # (A, B, context_A, context_B)
    domain_context: Optional[str] = None
) -> List[CorefLLMDecision]:
    """Traite plusieurs paires en un seul appel LLM."""
```

**Avantages:**
- Réduit le nombre d'appels API
- Amortit la latence réseau

**Inconvénients:**
- Augmente les tokens par appel
- Risque de confusion si trop de paires

**Recommandation:** Batch de 5-10 paires maximum.

#### Prompt (agnostique)

```
Tu es un expert en résolution de coréférence.

Contexte domaine (optionnel): {domain_context}

Pour chaque paire ci-dessous, détermine si les deux mentions
réfèrent à la MÊME entité dans le monde réel.

Paires à évaluer:
1. Mention A: "{mention_a}"
   Contexte A: "{context_a}"
   Mention B: "{mention_b}"
   Contexte B: "{context_b}"

2. [...]

Réponds en JSON:
{
  "decisions": [
    {
      "pair_index": 1,
      "same_entity": true|false,
      "abstain": true|false,
      "confidence": 0.0-1.0,
      "reason": "explication courte"
    },
    ...
  ]
}

IMPORTANT:
- Deux mentions avec des noms similaires peuvent désigner des entités DIFFÉRENTES
- Analyse le contexte pour comprendre ce que chaque mention désigne
- Si tu ne peux pas trancher avec certitude, utilise "abstain": true
- "abstain": true signifie "je ne sais pas" (différent de "same_entity": false qui signifie "ce sont des entités différentes")
```

#### Réponse structurée

```python
@dataclass
class CorefLLMDecision:
    pair_index: int
    same_entity: bool      # True = même entité, False = entités différentes
    abstain: bool          # True = incapable de trancher (OSMOSE abstention-first)
    confidence: float      # 0.0-1.0
    reason: str            # Explication courte

    @property
    def decision(self) -> str:
        """Convertit en décision OSMOSE."""
        if self.abstain:
            return "ABSTAIN"
        return "ACCEPT" if self.same_entity else "REJECT"
```

**Note:** Le champ `abstain` est essentiel pour distinguer:
- "Je suis sûr que ce sont des entités différentes" → `same_entity=False, abstain=False`
- "Je ne sais pas / contexte insuffisant" → `abstain=True`

En cas d'abstention LLM, OSMOSE ne crée pas la coréférence (philosophie abstention-first).

---

## Alternatives considérées

### Alternative A: Pas de gating, tout au LLM

**Avantages:**
- Simple à implémenter
- Décisions de haute qualité

**Inconvénients:**
- Coût prohibitif (1 appel par paire)
- Latence élevée
- Non scalable

**Verdict:** Rejeté pour raisons de coût/performance.

### Alternative B: Gating seul, pas de LLM

**Avantages:**
- Rapide et gratuit
- Déterministe

**Inconvénients:**
- Les heuristiques ont des limites
- Cas ambigus mal gérés

**Verdict:** Insuffisant pour la qualité attendue.

### Alternative C: Embeddings sémantiques

Comparer les embeddings des mentions + contextes.

**Avantages:**
- Capture la sémantique
- Pas d'appel LLM externe

**Inconvénients:**
- Nécessite un modèle d'embedding chargé
- Seuils difficiles à calibrer
- Moins explicable que le LLM

**Verdict:** À explorer en complément, pas en remplacement.

---

## Questions ouvertes

### Q1: Pertinence de TF-IDF divergence

La divergence TF-IDF ajoute de la complexité:
- Construction d'un vocabulaire local par document
- Calcul de vecteurs sparse

**Décision:** TF-IDF est **optionnelle** mais utile **comme signal**, jamais comme règle dure.

**Approche recommandée:**
1. Implémenter d'abord **sans** TF-IDF (Jaro-Winkler + Token Jaccard + Head noun)
2. Structurer le code pour l'ajouter facilement
3. L'activer si les métriques montrent trop de faux positifs en REVIEW

**Si implémentée:** TF-IDF divergence > 0.6 → `risk += 1` (signal, pas REJECT).

### Q2: Granularité du cache contextuel

Quel niveau de contexte hasher ?
- Phrase seule ?
- Paragraphe ?
- Document entier ?

**Proposition:** Hash des 100 caractères entourant chaque mention.

### Q3: Modèle LLM à utiliser

**Décision:** Utiliser **vLLM Qwen sur EC2** (infrastructure existante OSMOSE).

| Modèle | Coût | Qualité | Latence |
|--------|------|---------|---------|
| GPT-4o | $$$ par token | Excellente | ~2s |
| GPT-4o-mini | $ par token | Bonne | ~1s |
| Claude Haiku | $ par token | Bonne | ~1s |
| **vLLM Qwen EC2** | **Inclus** (coût instance) | Bonne | ~0.5s |

**Avantages vLLM Qwen EC2:**
- Coût marginal nul (instance déjà payée pour autres tâches OSMOSE)
- Latence faible (~500ms)
- Pas de dépendance API externe
- Contrôle total sur la disponibilité
- Déjà intégré via `LLMRouter` existant

**Configuration:** Via `LLMRouter` avec `model_family="qwen"` ou `model_family="default"`.

### Q4: Fallback si LLM indisponible

Que faire si vLLM EC2 est down ou surchargé ?

**Options:**
1. ABSTAIN (ne pas créer la coréférence)
2. ACCEPT avec flag "unvalidated"
3. Queue pour retry ultérieur

**Décision:** Option 1 (ABSTAIN) - parfaitement aligné avec la philosophie "abstention-first" d'OSMOSE.

En cas d'indisponibilité LLM:
- Les paires en REVIEW restent non résolues
- La coréférence n'est pas créée
- Un log d'audit trace l'abstention avec raison "LLM_UNAVAILABLE"

### Q5: Volume estimé de paires REVIEW

Besoin de données réelles pour estimer:
- Combien de paires Named↔Named par document ?
- Quel % passe en REVIEW après gating ?

**Action:** Instrumenter le gating pour collecter des métriques.

---

## Impact sur l'architecture existante

### Nouveaux fichiers

```
src/knowbase/linguistic/
├── coref_gating.py          # EXISTANT - ajouter NamedNamedGatingPolicy
├── coref_named_gating.py    # NOUVEAU - logique Named↔Named
├── coref_llm_arbiter.py     # NOUVEAU - batch LLM validation
└── coref_cache.py           # NOUVEAU - cache deux niveaux
```

### Modifications

| Fichier | Modification |
|---------|--------------|
| `coref_models.py` | Nouveaux ReasonCodes (LLM_REJECTED, etc.) |
| `pass05_coref.py` | Intégrer le gating Named↔Named |
| `requirements.txt` | `rapidfuzz` (si pas déjà présent) |

### Dépendances

- `rapidfuzz` - Jaro-Winkler rapide (déjà dans requirements.txt)
- `spaCy` - Extraction head noun (déjà installé)
- `sklearn` - TF-IDF si implémenté (déjà installé)

---

## Métriques de succès

| Métrique | Cible | Mesure |
|----------|-------|--------|
| Faux positifs Named↔Named | < 5% | Audit manuel échantillon |
| Appels LLM par document | < 10 | Logs |
| Latence ajoutée Pass 0.5 | < 2s | Instrumentation |
| Cache hit rate | > 80% | Métriques cache |

---

## Décision

**VALIDÉ** - Approuvé pour implémentation.

### Résumé des décisions prises

| Question | Décision |
|----------|----------|
| Modèle de gating | Signaux de risque (pas de REJECT durs sur head noun/TF-IDF) |
| TF-IDF | Optionnelle, signal seulement, implémenter plus tard si besoin |
| Cache contextuel | 100 caractères autour de chaque mention |
| Modèle LLM | vLLM Qwen sur EC2 (coût marginal nul) |
| Fallback LLM | ABSTAIN (philosophie abstention-first) |
| Sortie LLM | Inclut champ `abstain` explicite |

### Prochaines étapes

1. Valider cet ADR avec l'équipe
2. Implémenter en mode incrémental:
   - Phase A: `NamedNamedGatingPolicy` (heuristiques seules)
   - Phase B: Cache global
   - Phase C: LLM Arbiter via vLLM
   - Phase D: Cache contextuel (si termes courts problématiques)
3. Instrumenter pour collecter métriques réelles

---

## Références

- [FastCoref GitHub](https://github.com/shon-otmazgin/fastcoref)
- [RapidFuzz Documentation](https://maxbachmann.github.io/RapidFuzz/)
- `doc/phases/PHASE1_SEMANTIC_CORE.md` - Section Pass 0.5
- `src/knowbase/linguistic/coref_gating.py` - Gating existant pour pronoms

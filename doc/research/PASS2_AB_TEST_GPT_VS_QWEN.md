# Test A/B Pass 2 : gpt-4o-mini vs Qwen-14B (vLLM)

**Date** : 2025-01
**Status** : Prêt pour exécution
**Objectif** : Déterminer si Qwen-14B sur EC2 Spot offre un meilleur rapport qualité/prix que gpt-4o-mini pour l'extraction de relations Pass 2.

---

## Contexte

L'extraction de relations Pass 2 utilise actuellement gpt-4o-mini via l'API OpenAI. Cette phase est coûteuse car elle traite segment par segment avec des prompts détaillés.

L'infrastructure Burst (EC2 Spot + vLLM) est déjà opérationnelle pour l'ingestion de documents. On peut la réutiliser pour Pass 2.

### Hypothèse

Qwen2-14B-Instruct-AWQ (7B params quantifié) pourrait offrir :
- **Meilleure qualité** : Modèle plus grand que gpt-4o-mini
- **Coût comparable** : ~1.20€/heure EC2 vs ~$0.50-1.00 OpenAI pour un batch
- **Latence acceptable** : vLLM sur GPU L4 est rapide malgré la distance réseau

---

## Architecture du Test

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TEST A/B PASS 2                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────┐        ┌─────────────────┐                    │
│  │    GROUPE A     │        │    GROUPE B     │                    │
│  │   (gpt-4o-mini) │        │   (Qwen-14B)    │                    │
│  └────────┬────────┘        └────────┬────────┘                    │
│           │                          │                             │
│           ▼                          ▼                             │
│  ┌─────────────────┐        ┌─────────────────┐                    │
│  │  OpenAI API     │        │ EC2 Spot + vLLM │                    │
│  │  (défaut)       │        │ (Burst mode)    │                    │
│  └────────┬────────┘        └────────┬────────┘                    │
│           │                          │                             │
│           └──────────┬───────────────┘                             │
│                      ▼                                             │
│           ┌──────────────────┐                                     │
│           │ Mêmes documents  │                                     │
│           │ Mêmes segments   │                                     │
│           │ Mêmes budgets    │                                     │
│           └──────────────────┘                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Métriques collectées

| Métrique | Description |
|----------|-------------|
| **Précision** | relations validées / relations proposées |
| **Latence** | Temps moyen par segment (ms) |
| **Distribution prédicats** | Répartition des 12 prédicats ADR |
| **Fuzzy score moyen** | Qualité des quotes extraites |
| **Coût** | OpenAI ($) vs EC2 runtime (€→$) |

---

## Procédure d'Exécution

### 1. Pré-requis

```bash
# Vérifier que les services sont démarrés
./kw.ps1 status

# Vérifier qu'on a des documents à tester
docker-compose exec app python -c "
from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
s = get_settings()
c = Neo4jClient(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
with c.driver.session(database='neo4j') as session:
    r = session.run('MATCH (d:Document) RETURN count(d) AS count')
    print(f'Documents disponibles: {r.single()[\"count\"]}')
c.close()
"
```

### 2. Dry Run (recommandé)

Tester le script sans exécuter réellement :

```bash
docker-compose exec app python scripts/pass2_ab_test.py --documents 5 --dry-run
```

Sortie attendue :
```
[ABTest] Starting test ab_pass2_YYYYMMDD_HHMMSS
[ABTest] Max documents: 5, Dry run: True
[ABTest] Selected 5 documents for testing
[ABTest] === GROUP A: gpt-4o-mini (5 documents) ===
[ABTest] DRY RUN - Skipping actual extraction
[ABTest] === GROUP B: Qwen-14B/vLLM (5 documents) ===
[ABTest] DRY RUN - Skipping EC2 deployment and extraction
```

### 3. Exécution Réelle

```bash
docker-compose exec app python scripts/pass2_ab_test.py --documents 20 --execute
```

**Attention** :
- EC2 Spot sera déployé (~2-5 min de démarrage)
- Coût estimé : ~1.20€/heure EC2 + tokens OpenAI
- Les relations seront persistées dans Neo4j

### 4. Analyse des Résultats

Les résultats sont sauvegardés dans `data/ab_tests/ab_pass2_XXXXXX.json`.

Exemple de sortie console :

```
══════════════════════════════════════════════════════════════════════
  TEST A/B PASS 2 - RÉSULTATS
  Test ID: ab_pass2_20250101_143022
══════════════════════════════════════════════════════════════════════

📊 Documents testés: 20

┌────────────────────┬──────────────────┬──────────────────┐
│ Métrique           │ gpt-4o-mini      │ Qwen-14B (vLLM)  │
├────────────────────┼──────────────────┼──────────────────┤
│ Segments traités   │               85 │               85 │
│ Relations extraites│              312 │              347 │
│ Précision moyenne  │            72.3% │            78.1% │
│ Latence moyenne    │           450 ms │           680 ms │
│ Coût estimé        │           $0.75  │           $1.30  │
└────────────────────┴──────────────────┴──────────────────┘

⏱️  Temps EC2 total: 2847s

──────────────────────────────────────────────────────────────────────
📈 Différence qualité: +8.0% (Qwen-14B vs gpt-4o-mini)
💰 Différence coût: +73.3%

✅ VERDICT: Qwen-14B offre un meilleur rapport qualité/prix
══════════════════════════════════════════════════════════════════════
```

---

## Coûts Estimés

### OpenAI (gpt-4o-mini)

| Composant | Prix | Estimation/segment |
|-----------|------|-------------------|
| Input tokens | $0.15 / 1M | ~2000 tokens |
| Output tokens | $0.60 / 1M | ~500 tokens |
| **Total/segment** | | ~$0.0006 |
| **20 docs × 50 segments** | | ~$0.60 |

### EC2 Spot (Qwen-14B)

| Composant | Prix |
|-----------|------|
| g6e.xlarge Spot | ~$0.40-0.50/h |
| Startup/shutdown | ~5 min overhead |
| **Estimation 20 docs** | ~$1.00-1.50 |

---

## Points d'Attention

### Latence

La latence EC2 est plus élevée que l'API OpenAI :
- Réseau : ~50-100ms RTT vers eu-west-1
- vLLM batch : efficace mais pas instantané
- Première requête : warmup GPU

### Qualité

Qwen-14B-AWQ a des caractéristiques différentes :
- Format instruction Qwen2 (pas OpenAI)
- Quantification AWQ (léger impact qualité)
- Contexte 32K tokens

### Robustesse

Points de vigilance :
- Spot interruption (rare, handled par Burst)
- Timeout vLLM (augmenté à 120s)
- Parse JSON (même format ADR)

---

## Décision Post-Test

### Si Qwen-14B gagne (qualité ≥ +5%)

1. Modifier `pass2_config.mode` pour supporter `gpu_burst`
2. Créer workflow automatisé : démarrer EC2 → Pass 2 → arrêter EC2
3. Considérer batch nocturne pour optimiser coûts

### Si gpt-4o-mini gagne

1. Garder le mode actuel
2. Considérer gpt-4o (plus cher mais meilleur)
3. Explorer fine-tuning gpt-4o-mini sur corpus OSMOSE

### Si égalité (< 5% différence)

1. Préférer gpt-4o-mini (simplicité, pas d'infra à gérer)
2. Garder EC2 pour les pics (mode Burst ingestion)

---

## Fichiers Associés

| Fichier | Description |
|---------|-------------|
| `scripts/pass2_ab_test.py` | Script de test A/B |
| `src/knowbase/ingestion/burst/orchestrator.py` | Orchestration EC2 Spot |
| `src/knowbase/ingestion/burst/provider_switch.py` | Switch LLM/Embeddings |
| `src/knowbase/relations/segment_window_relation_extractor.py` | Extraction ADR-compliant |
| `data/ab_tests/*.json` | Résultats des tests |

---

## Historique

| Date | Action |
|------|--------|
| 2025-01-01 | Création du script et documentation |
| - | Premier test prévu |

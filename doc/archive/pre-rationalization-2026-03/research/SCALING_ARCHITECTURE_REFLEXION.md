# Architecture Scaling OSMOSE - Reflexion

*Document de travail - A retravailler*
*Date: 2024-12-30*

## Contexte

Actuellement, le pipeline OSMOSE ingere ~2-3 documents/heure, ce qui est inacceptable pour une mise en production commerciale. Ce document capture les reflexions sur l'evolution de l'architecture pour atteindre une scalabilite acceptable.

---

## Analyse des Bottlenecks Actuels

### Pipeline OSMOSE - Temps par etape

| Etape | Ressource | Bottleneck |
|-------|-----------|------------|
| Segmentation | CPU | Faible |
| **LLM (extraction concepts)** | GPU/API | **MAJEUR** - 60-70% du temps |
| **Embeddings** | GPU | **SIGNIFICATIF** - 20-25% |
| Chunking | CPU | Faible |
| Persistance (Qdrant/Neo4j) | I/O | Modere |

### Infrastructure actuelle (Mode Burst)

- Instance: g6.2xlarge (L4 24GB VRAM)
- vLLM: Qwen 14B AWQ (~2-3 tokens/sec par requete)
- TEI: E5-large (batches limites par VRAM)
- Traitement: **Sequentiel** (segments un par un)

---

## Le Probleme Commercial

### Deux modes d'usage distincts

```
ONBOARDING (J1-J7)              USAGE CONTINU (J8+)
────────────────────────────────────────────────────
Client importe sa base          Quelques docs/jour
existante : 500-5000 docs       Recherche intensive
Attente : "quelques heures"     Attente : "temps reel"

CRITIQUE pour adoption          Moins critique
```

**Deal-breaker** : Un client qui doit attendre 2 semaines pour importer sa documentation ne signera jamais.

### Benchmarks marche

| Solution | Vitesse ingestion | Comment ils font |
|----------|-------------------|------------------|
| Notion AI | ~instant | Embeddings simples, pas de KG |
| Glean | ~minutes/doc | Infra massive, extraction legere |
| Guru | ~secondes | Pas d'extraction semantique |
| Kendra (AWS) | ~1-2 min/doc | Infra managee scalable |

**Differentiation OSMOSE** (extraction concepts, KG, relations) justifie un temps plus long, mais pas 20-30 min/doc.

---

## Options d'Evolution Infrastructure

### Option 1 : GPU Plus Puissant (A100/H100)

```
Instance      GPU           VRAM    Cout/h    Gain estime
─────────────────────────────────────────────────────────
g6.2xlarge    1x L4         24GB    ~$0.80    (baseline)
p4d.24xlarge  8x A100       320GB   ~$32      4-6x throughput LLM
p5.48xlarge   8x H100       640GB   ~$98      8-12x throughput LLM
```

**Avantages :**
- Tensor parallelism (split modele sur multi-GPU)
- Batch size embeddings x10-20
- Modeles plus gros possibles (70B+)

**Inconvenients :**
- Cout spot ~$10-15/h meme pour A100
- Overkill pour 1 document

### Option 2 : Architecture Worker Parallele

```
┌─────────────────────────────────────────────────┐
│  Orchestrator (leger, CPU)                      │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │Worker 1 │  │Worker 2 │  │Worker 3 │  ...   │
│  │ (GPU)   │  │ (GPU)   │  │ (GPU)   │        │
│  │ Doc A   │  │ Doc B   │  │ Doc C   │        │
│  └─────────┘  └─────────┘  └─────────┘        │
│                                                 │
│  ┌──────────────────────────────────────┐      │
│  │  Shared: vLLM (multi-replica)        │      │
│  │  Shared: TEI (multi-replica)         │      │
│  └──────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘
```

**Principe :** Traiter N documents en parallele plutot qu'accelerer 1 document.

### Option 3 : Services Manages

| Service | Avantage | Inconvenient |
|---------|----------|--------------|
| AWS Bedrock | Pas d'infra, scalable | Cout/token, latence API |
| SageMaker Endpoints | Autoscaling, managed | Complexite setup |
| Modal.com | GPU a la demande | Vendor lock-in |

### Option 4 : Optimisations Algorithmiques

1. **Speculative decoding** : vLLM le supporte, gain 2-3x
2. **Chunked prefill** : Reduire latence premier token
3. **Continuous batching** : Deja actif, mais tunable
4. **Parallelisation intra-document** : Traiter segments en parallele

---

## Architecture Cible SaaS

```
                         ┌──────────────────┐
                         │   Load Balancer  │
                         └────────┬─────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   API Gateway   │    │   API Gateway   │    │   API Gateway   │
│   (Tenant A)    │    │   (Tenant B)    │    │   (Tenant C)    │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │    Redis Queue        │
                    │  (priorite par tier)  │
                    └───────────┬───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│  Worker Pool  │      │  Worker Pool  │      │  Worker Pool  │
│  STANDARD     │      │  PREMIUM      │      │  BURST        │
│  (2x g6)      │      │  (4x g6)      │      │  (Spot, 0-N)  │
│  Shared       │      │  Dedicated    │      │  Onboarding   │
└───────────────┘      └───────────────┘      └───────────────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  GPU Cluster (partage)│
                    │  vLLM + TEI replicas  │
                    │  Auto-scaling         │
                    └───────────────────────┘
```

---

## Leviers d'Optimisation (par impact)

### 1. Parallelisation Intra-Document (QUICK WIN)

Actuellement le pipeline traite les segments **sequentiellement**.

```python
# Actuel (simplifie)
for segment in segments:
    concepts = await extract_concepts(segment)  # 30s
    # Total: 20 segments x 30s = 10 min

# Cible
concepts = await asyncio.gather(*[
    extract_concepts(seg) for seg in segments
])  # Total: ~60s (limite par GPU)
```

**Gain potentiel : 5-10x** sans changer l'infra.

### 2. Tiering de Traitement

| Mode | Extraction | Temps estime | Use case |
|------|------------|--------------|----------|
| **FAST** | Embeddings only | ~10s/doc | Onboarding initial |
| **STANDARD** | + Concepts basiques | ~2 min/doc | Usage normal |
| **DEEP** | + Relations + KG complet | ~10 min/doc | Documents critiques |

**Idee** : Import rapide en mode FAST, enrichissement DEEP en background.

### 3. Pre-processing Intelligent

```
Document recu
     │
     ▼
┌─────────────────┐
│ Triage rapide   │  <- 2 secondes
│ - Taille        │
│ - Type          │
│ - Langue        │
│ - Complexite    │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
 SIMPLE    COMPLEXE
 (fast)    (full OSMOSE)
```

80% des documents corporate sont des slides/PDF simples qui ne necessitent pas l'artillerie lourde.

---

## Modele de Cout Estime

### Infrastructure Cible (Production)

| Composant | Spec | Cout/mois |
|-----------|------|-----------|
| API + Workers (2x) | c6i.xlarge | ~$200 |
| GPU Pool (base) | 2x g6.2xlarge | ~$1,200 |
| GPU Pool (burst) | Spot auto-scale | ~$500 variable |
| Qdrant | r6i.xlarge | ~$200 |
| Neo4j | r6i.xlarge | ~$200 |
| Redis | cache.m6g.large | ~$100 |
| **Total base** | | **~$2,400/mois** |

### Capacite Estimee

Avec cette infra + optimisations :
- **Throughput continu** : ~50-100 docs/heure
- **Burst onboarding** : ~200-500 docs/heure (avec spot)
- **Onboarding 1000 docs** : ~2-5 heures

---

## Pricing SaaS Possible

| Tier | Prix/mois | Docs inclus | Vitesse |
|------|-----------|-------------|---------|
| **Starter** | 299€ | 500 docs | Standard |
| **Business** | 899€ | 2000 docs | Priority |
| **Enterprise** | Sur devis | Illimite | Dedicated |

Break-even estime : ~10 clients Business.

---

## Roadmap Infrastructure

```
ACTUEL           PHASE 1              PHASE 2              PHASE 3
(Dev/POC)        (Beta clients)       (Production)         (Scale)
─────────────────────────────────────────────────────────────────────
1 worker         Parallelisation      Multi-worker         Kubernetes
Sequentiel       intra-doc            + Tiering            Auto-scale
2-3 doc/h        20-30 doc/h          100+ doc/h           500+ doc/h
```

### Phase 1 : Quick Wins (Code only)

- [ ] Paralleliser extraction concepts par segment
- [ ] Paralleliser embeddings par batch
- [ ] Optimiser batch sizes vLLM/TEI
- [ ] Implementer tiering FAST/STANDARD/DEEP

### Phase 2 : Multi-Worker

- [ ] Architecture queue avec priorites
- [ ] Pool de workers GPU
- [ ] Metriques et monitoring
- [ ] Auto-scaling basique

### Phase 3 : Production Scale

- [ ] Kubernetes / EKS
- [ ] Auto-scaling avance
- [ ] Multi-region
- [ ] SLA et monitoring

---

## Notes et Questions Ouvertes

- Quel modele LLM optimal pour le ratio qualite/vitesse ?
- Faut-il proposer un mode "preview" rapide pendant l'onboarding ?
- Comment gerer les pics de charge (plusieurs clients onboarding en meme temps) ?
- Quelle strategie de cache pour les embeddings ?

---

*Document a retravailler lors de la phase de preparation production*

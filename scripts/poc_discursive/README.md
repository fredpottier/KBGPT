# POC Discursive Relation Discrimination

## Objectif

Ce POC teste une hypothese critique pour OSMOSIS :

> **Un systeme peut-il distinguer de maniere fiable et reproductible :**
> - une **relation implicitement determinee par le texte** (Type 1)
> - d'une **relation deduite par raisonnement externe** (Type 2) ?

## Contexte

Voir l'ADR de cadrage : `doc/ongoing/ADR_POC_DISCURSIVE_RELATION_DISCRIMINATION.md`

## Structure

```
scripts/poc_discursive/
├── models.py          # Modeles Pydantic
├── test_cases.py      # Jeu de cas v1 (initial)
├── test_cases_v2.py   # Jeu de cas v2 (calibre)
├── test_cases_v3.py   # Jeu de cas v3 (final - 48 cas, 3 documents)
├── discriminator.py   # Discriminateur LLM
├── runner.py          # Runner v1
├── runner_v2.py       # Runner v2
├── runner_v3.py       # Runner v3 (final)
├── __init__.py        # Package init
└── README.md          # Ce fichier
```

## Version Finale (v3)

Le POC v3 couvre **48 cas de test** repartis sur **3 documents SAP** :

| Document | Type 1 (ACCEPT) | Type 2 (REJECT) | Total |
|----------|-----------------|-----------------|-------|
| RISE (doc 020) | 6 | 6 | 12 |
| Conversion Guide (doc 010) | 8 | 6 | 14 |
| Operations Guide (doc 017) | 8 | 8 | 16 |
| **Total** | **22** | **20** | **42** |

### Patterns testes

**Type 1 (ACCEPT)** - Relations textuellement determinees :
- DEFAULT + exception ("considered X unless Y")
- CAN_HAVE options ("X or Y")
- Assertions explicites ("uses", "requires", "relies on")
- Prerequisites ("as a prerequisite, you have to")

**Type 2 (REJECT)** - Relations necessitant raisonnement externe :
- ALWAYS vs exceptions ("unless" present)
- HAS_EXACT vs alternatives ("or" present)
- Causalite non affirmee
- Cross-pages sans pont textuel
- Connaissance externe SAP

## Types de Relations

### Type 1 - Discursivement Determinees (ACCEPT)

Relations ou le lien est entierement contenu dans le document :
- Continuite discursive (maintien du referent)
- Aucun concept intermediaire requis
- Aucune connaissance externe necessaire

### Type 2 - Deduites par Raisonnement (REJECT)

Relations necessitant :
- Chaine transitive (A → C → B)
- Connaissance externe au texte
- Causalite non affirmee

### ABSTAIN

Quand le contexte est insuffisant ou ambigu.

## Execution

### Version finale (v3)

```bash
# Depuis la racine du projet
cd scripts/poc_discursive
python runner_v3.py
```

Necessite la variable d'environnement `ANTHROPIC_API_KEY`.

### Mode mock (sans API)

```bash
python runner_v3.py --mock
```

Retourne les verdicts attendus sans appeler l'API.

### Options

```bash
python runner_v3.py --help

Options:
  --mock        Mode mock (sans appel API)
  --output-dir  Repertoire de sortie (default: ./results)
  --quiet       Mode silencieux
```

### Versions precedentes

```bash
python runner.py      # v1 - version initiale
python runner_v2.py   # v2 - version calibree
```

## Criteres d'Echec v3

Le POC est en echec si :

| Critere | Seuil |
|---------|-------|
| Faux positifs Type 2 | > 10% |
| Taux Type 1 corrects | < 80% |
| Acceptations sans citation | > 0 |

## Resultats

Les resultats sont sauvegardes dans `./results/poc_v3_results_YYYYMMDD_HHMMSS.json`

Le fichier JSON contient :
- Metriques globales Type 1 / Type 2
- Metriques par document (RISE, Conversion, Operations)
- Details de chaque verdict
- Conclusion et recommendations

## Verdicts Possibles du POC

| Verdict | Signification | Action |
|---------|---------------|--------|
| FAILURE | Distinction non operable | Revoir l'approche KG |
| PARTIAL_SUCCESS | Partiellement operable | Ameliorations necessaires |
| SUCCESS | Distinction operable (>85%) | Poursuivre le developpement KG |

## Documents Sources

Les cas de test utilisent des extraits reels de 3 documents SAP :

1. **020_RISE_with_SAP_Cloud_ERP_Private_full.pdf**
   - Business Continuity (RTO, RPO, SLA)
   - Connectivity et Firewall
   - WAF et securite

2. **010_SAP_S4HANA_Cloud_Private_Edition_2025_Conversion_Guide.pdf**
   - Options de deploiement (embedded/standalone)
   - Outils requis (SUM, Maintenance Planner)
   - Prerequisites de migration

3. **017_SAP_S4HANA_2023_Operations_Guide.pdf**
   - Output Management (bgRFC, BRFplus)
   - User Management
   - System Landscape

## Avertissement

**Ce code est jetable et non destine a la production.**

Il sert uniquement a eclairer une decision strategique concernant
la pertinence de poursuivre le developpement du Knowledge Graph.

# Architecture de Déploiement - OSMOSE / KnowWhere

**Date décision :** 2025-12-18
**Status :** Validé

---

## Décision : 1 Instance = 1 Client

OSMOSE utilise une architecture **d'instances dédiées par client** plutôt qu'un multi-tenancy logique.

```
┌─────────────────────────────────────────────────────────────────┐
│                        INFRASTRUCTURE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Instance        │  │ Instance        │  │ Instance        │  │
│  │ Client Pharma   │  │ Client SAP      │  │ Client Finance  │  │
│  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤  │
│  │ • Neo4j         │  │ • Neo4j         │  │ • Neo4j         │  │
│  │ • Qdrant        │  │ • Qdrant        │  │ • Qdrant        │  │
│  │ • Redis         │  │ • Redis         │  │ • Redis         │  │
│  │ • App + Worker  │  │ • App + Worker  │  │ • App + Worker  │  │
│  │ • Frontend      │  │ • Frontend      │  │ • Frontend      │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                  │
│  Config spécifique   Config spécifique   Config spécifique      │
│  pharma_rules.yaml   sap_rules.yaml      finance_rules.yaml     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pourquoi ce choix ?

### Comparaison

| Critère | Multi-tenant logique | 1 instance / client |
|---------|---------------------|---------------------|
| **Isolation données** | Logique (tenant_id) | Physique (bases séparées) |
| **Sécurité** | Risque de fuite | Isolation totale |
| **Audit conformité** | Complexe à prouver | Simple et évident |
| **Argument commercial** | "Données partagées" | "Votre instance dédiée" |
| **Coût infra** | Mutualisé | Par client |
| **Maintenance** | Centralisée | Par instance |
| **Personnalisation** | Via config tenant | Via fichiers config |

### Facteurs décisifs

1. **Exigences enterprise** - Les grands comptes exigent une isolation totale
2. **Secteurs réglementés** - Pharma, finance, santé : audits stricts
3. **Confiance client** - Plus facile à vendre "votre propre instance"
4. **Simplicité code** - Pas de filtrage tenant_id partout

---

## Structure d'une Instance Client

```
instance_client_pharma/
├── docker-compose.yml          # Orchestration services
├── .env                        # Variables environnement
│
├── config/
│   ├── feature_flags.yaml      # Features activées pour ce client
│   ├── domain_context.yaml     # Contexte métier (optionnel)
│   │
│   ├── rules/
│   │   └── pharma_rules.yaml   # Règles métier pharma
│   │
│   └── ontologies/
│       ├── pharma_fda_terms.json
│       └── custom_terms.json   # Termes spécifiques client
│
├── data/
│   ├── docs_in/                # Documents à importer
│   ├── docs_done/              # Documents traités
│   └── extraction_cache/       # Cache extractions
│
└── volumes/
    ├── neo4j/                  # Données Neo4j
    ├── qdrant/                 # Données Qdrant
    └── redis/                  # Données Redis
```

---

## Déploiement Nouveau Client

### Étape 1 : Cloner le template

```bash
# Depuis le repo principal
git clone https://github.com/your-org/knowwhere.git instance_client_xxx
cd instance_client_xxx
```

### Étape 2 : Personnaliser la configuration

```bash
# Copier le template de config
cp config/feature_flags.yaml.template config/feature_flags.yaml

# Éditer pour ce client
vim config/feature_flags.yaml
```

### Étape 3 : Ajouter les règles métier

```bash
# Créer les règles spécifiques au client
cp config/rules/pharma_rules.yaml config/rules/client_rules.yaml
vim config/rules/client_rules.yaml
```

### Étape 4 : Configurer les credentials

```bash
# Éditer .env avec les credentials client
cp .env.template .env
vim .env

# Variables importantes :
# - OPENAI_API_KEY (ou clé client si compte dédié)
# - NEO4J_PASSWORD
# - Ports (éviter conflits si même serveur)
```

### Étape 5 : Déployer

```bash
# Démarrer l'instance
./kw.ps1 start

# Vérifier le status
./kw.ps1 status
```

---

## Gestion Multi-Instances sur un Serveur

Si plusieurs instances sur le même serveur, modifier les ports :

```yaml
# Instance Client A - .env
APP_PORT=8000
FRONTEND_PORT=3000
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
QDRANT_PORT=6333

# Instance Client B - .env
APP_PORT=8100
FRONTEND_PORT=3100
NEO4J_HTTP_PORT=7574
NEO4J_BOLT_PORT=7787
QDRANT_PORT=6433
```

Ou utiliser un reverse proxy (Nginx/Traefik) avec sous-domaines :
- `pharma.knowwhere.io` → Instance Pharma
- `sap.knowwhere.io` → Instance SAP

---

## Impact sur le Code

### Ce qui reste

- Le paramètre `tenant_id` existe toujours dans le code
- Valeur par défaut : `"default"` (ou nom client pour les logs)
- Les Business Rules utilisent toujours `tenant_id` dans le YAML

### Ce qui est simplifié

- Pas de sections `tenants:` dans feature_flags.yaml
- Pas de logique de résolution multi-tenant
- Pas d'isolation logique à maintenir

### Exemple de code

```python
# Avant (multi-tenant logique)
def get_concepts(tenant_id: str):
    return neo4j.query(
        "MATCH (c:Concept) WHERE c.tenant_id = $tid",
        tid=tenant_id
    )

# Maintenant (1 instance = 1 client)
def get_concepts():
    return neo4j.query("MATCH (c:Concept) RETURN c")
    # Pas besoin de filtrer - toute la base appartient au client
```

---

## Migration Future vers Multi-Tenant

Si un jour nécessaire (SaaS grand volume), le code supporte toujours `tenant_id`.

Étapes de migration :
1. Réactiver les sections `tenants:` dans feature_flags.yaml
2. Ajouter `tenant_id` aux requêtes Neo4j/Qdrant
3. Implémenter l'isolation Redis (préfixes clés)

Mais pour l'instant, l'architecture "1 instance = 1 client" est plus adaptée au marché enterprise cible.

---

*Dernière mise à jour : 2025-12-18*

# 🏗️ OSMOSE - Architecture Multi-Tenant & Contextes Métiers

**Date :** 2025-11-17
**Status :** 📋 Architecture Future - Phase 2+
**Contexte :** DomainContextPersonalizer (Composant 0 bis)

---

## 🎯 Vision Architecturale

### Principe Fondamental

**1 instance KnowWhere = 1 entreprise cliente** (isolation infrastructure totale)

Pas de mutualisation entre entreprises pour garantir :
- ✅ Étanchéité totale des données
- ✅ Conformité RGPD / confidentialité
- ✅ Performance dédiée
- ✅ Personnalisation maximale

---

## 📅 Évolution par Phases

### **Phase 1 : Corpus Corporate Unique** (Actuel)

**Architecture :**
```
1 Instance KnowWhere = 1 Entreprise
└── tenant_id = "default"
    └── Corpus documentaire corporate (partagé par tous les utilisateurs)
```

**Cas d'usage :**
- Entreprise SAP déploie KnowWhere
- Documents SAP corporate accessibles à tous les employés
- Contexte métier unique : SAP enterprise software
- `tenant_id = "default"` pour tous les documents

**Limitations :**
- ❌ Pas de docs personnels par utilisateur
- ❌ Pas de contextes métiers multiples
- ❌ Tous les utilisateurs voient les mêmes résultats de recherche

---

### **Phase 2 : Tenants Utilisateurs** (Future)

**Architecture :**
```
1 Instance KnowWhere = 1 Entreprise
├── tenant_id = "default" (Corporate)
│   └── Docs corporate SAP (accessibles à TOUS)
│
├── tenant_id = "user_john_doe"
│   └── Docs personnels de John (uniquement lui)
│
├── tenant_id = "user_jane_smith"
│   └── Docs personnels de Jane (uniquement elle)
│
└── tenant_id = "user_alex_martin"
    └── Docs personnels d'Alex (uniquement lui)
```

**Cas d'usage :**
- **John** (Finance) :
  - Accès : Docs corporate SAP + ses docs finance persos
  - Recherche : "SAP S/4HANA financials" → docs corporate + ses notes persos

- **Jane** (Sales) :
  - Accès : Docs corporate SAP + ses docs sales persos
  - Recherche : "SuccessFactors pricing" → docs corporate + ses slides clients

- **Alex** (Tech) :
  - Accès : Docs corporate SAP + ses docs techniques persos
  - Recherche : "BTP API integration" → docs corporate + ses exemples code

**Bénéfices :**
- ✅ Docs personnels isolés (pas de pollution du corpus corporate)
- ✅ Recherche personnalisée par utilisateur
- ✅ Traçabilité (qui a uploadé quoi)
- ✅ Droits d'accès granulaires

**Logique de Recherche :**
```python
# Recherche multi-tenant pour user_john_doe
results = search(
    query="SAP financials",
    tenants=["default", "user_john_doe"]  # Corporate + perso
)
```

---

## 🌍 Cas d'Usage Avancé : Contextes Multi-Sectoriels

### Problématique : Jane, Account Manager SAP pour Clients Pharma

**Contexte :**
- Jane travaille chez **SAP** (contexte corporate = SAP enterprise software)
- Ses clients sont des **entreprises pharmaceutiques**
- Elle doit traiter des questions liées aux **2 domaines** :
  - SAP : ERP, S/4HANA, BTP, SuccessFactors
  - Pharma : GMP, FDA, API, clinical trials, drug development

**Exemple de question client :**
> "Comment SAP S/4HANA gère-t-il les exigences GMP pour la production de médicaments ?"

**Problème avec contexte unique :**
- Contexte SAP seul : ✅ Reconnaît S/4HANA, ❌ Ne connaît pas GMP
- Contexte Pharma seul : ❌ Ne connaît pas S/4HANA, ✅ Reconnaît GMP

**Solution : Contexte Multi-Sectoriel Hybride**

---

### **Phase 3 : Contextes Hybrides** (Future avancé)

**Architecture :**
```
tenant_id = "user_jane_smith"
├── Contexte Primary: "sap_enterprise_software"
│   └── ERP, S/4HANA, BTP, SAC, SuccessFactors, Ariba, Concur
│
└── Contexte Secondary: "pharmaceutical"
    └── GMP, FDA, API, clinical_trials, drug_development
```

**Implémentation Possible :**

#### **Option A : Contexte Hybride Fusionné**
```json
{
  "tenant_id": "user_jane_smith",
  "industry": "sap_pharmaceutical_solutions",
  "primary_context": "sap_enterprise_software",
  "secondary_contexts": ["pharmaceutical"],
  "common_acronyms": {
    // SAP
    "SAC": "SAP Analytics Cloud",
    "BTP": "Business Technology Platform",
    "ERP": "Enterprise Resource Planning",
    // Pharma
    "GMP": "Good Manufacturing Practice",
    "FDA": "Food and Drug Administration",
    "API": "Active Pharmaceutical Ingredient"  // ⚠️ Conflit avec API = Application Programming Interface !
  },
  "key_concepts": [
    "SAP S/4HANA", "SuccessFactors", "SAP BTP",
    "Clinical Trials", "Drug Development", "FDA Compliance"
  ],
  "llm_injection_prompt": "You are analyzing documents for Jane, SAP Account Manager for pharmaceutical clients. Recognize both SAP products (S/4HANA, BTP, SAC) AND pharmaceutical concepts (GMP, FDA, clinical trials). When encountering 'API', disambiguate based on context: programming → Application Programming Interface, pharma → Active Pharmaceutical Ingredient."
}
```

**Avantages :**
- ✅ Jane bénéficie des 2 contextes simultanément
- ✅ Acronymes des 2 domaines reconnus
- ✅ Recherche intelligente cross-domaine

**Challenges :**
- ⚠️ **Conflits d'acronymes** (API = programming vs pharma)
- ⚠️ **Complexité prompts LLM** (2 domaines = risque confusion)
- ⚠️ **Maintenance** (mettre à jour 2 contextes)

---

#### **Option B : Contexte Hiérarchique avec Fallback**

```python
# Logique de résolution contexte pour Jane
def get_context_for_user(user_id: str, query: str) -> str:
    """
    Résout contexte métier pour un utilisateur avec fallback hiérarchique.
    """
    # 1. Contexte user personnel (si existe)
    user_context = get_user_context(user_id)
    if user_context:
        return user_context

    # 2. Contexte corporate (défaut entreprise)
    corporate_context = get_context("default")
    if corporate_context:
        return corporate_context

    # 3. Domain-agnostic (générique)
    return None  # Pas de contexte spécifique


# Pour Jane avec contexte hybride
jane_context = {
    "tenant_id": "user_jane_smith",
    "contexts": [
        {"source": "corporate", "weight": 0.7},  # SAP corporate (prioritaire)
        {"source": "pharmaceutical", "weight": 0.3}  # Pharma client (secondaire)
    ]
}

# LLM prompt injection devient :
"""
[PRIMARY CONTEXT - 70% weight]
{sap_corporate_context}

[SECONDARY CONTEXT - 30% weight]
{pharmaceutical_context}

When encountering ambiguous terms (e.g., 'API'), prioritize PRIMARY context unless
clear pharmaceutical indicators are present (GMP, FDA, clinical trials).
"""
```

**Avantages :**
- ✅ Pondération explicite (SAP prioritaire, Pharma secondaire)
- ✅ Désambiguïsation claire (API → SAP par défaut, pharma si contexte clair)
- ✅ Évolutif (ajouter 3ème contexte si besoin)

---

### Cas d'Usage Concrets Jane

| Requête | Contexte Utilisé | Résultat Attendu |
|---------|------------------|------------------|
| "SAP S/4HANA GMP compliance" | SAP (70%) + Pharma (30%) | ✅ Reconnaît S/4HANA (SAP) + GMP (Pharma) |
| "API Management BTP" | SAP (100%) | ✅ API = Application Programming Interface |
| "API production workflow" | Pharma (70%) + SAP (30%) | ✅ API = Active Pharmaceutical Ingredient (contexte pharma dominant) |
| "SuccessFactors for pharmaceutical HR" | SAP (70%) + Pharma (30%) | ✅ SuccessFactors (SAP) + pharmaceutical HR (Pharma) |

---

## 🚀 Roadmap Implémentation

### **Phase 1 : Corpus Corporate** ✅ ACTUEL

**Status :** ✅ Implémenté (nov 2025)

**Fonctionnalités :**
- Contexte métier corporate sur `tenant_id = "default"`
- Extraction LLM depuis texte libre utilisateur
- Injection automatique dans prompts LLM
- Persistance Neo4j

**Limitations :**
- Un seul contexte par instance
- Tous les utilisateurs partagent le même corpus

---

### **Phase 2 : Tenants Utilisateurs** 🔮 FUTURE (Q1 2026?)

**Objectifs :**
- [ ] Créer tenant par utilisateur (`user_*`)
- [ ] Logique de recherche multi-tenant (corporate + user)
- [ ] Isolation docs personnels
- [ ] UI upload "personnel" vs "corporate"

**Impact Architecture :**
```python
# Import document avec tenant utilisateur
upload_document(
    file="presentation_client_pharma.pptx",
    tenant_id="user_jane_smith",  # ← Personnel Jane
    access="private"  # Uniquement Jane
)

# Recherche multi-tenant
search(
    query="SAP pharma solutions",
    tenants=["default", "user_jane_smith"]  # Corporate + perso Jane
)
```

---

### **Phase 3 : Contextes Hybrides** 🔮 FUTURE (Q2 2026?)

**Objectifs :**
- [ ] Support multi-contextes par tenant
- [ ] Pondération contextes (primary/secondary)
- [ ] Désambiguïsation acronymes intelligente
- [ ] Gestion conflits cross-domaine

**Impact DomainContextProfile :**
```python
class DomainContextProfile(BaseModel):
    tenant_id: str
    primary_context: str  # ← Nouveau : contexte principal
    secondary_contexts: List[str] = []  # ← Nouveau : contextes secondaires
    context_weights: Dict[str, float] = {}  # ← Nouveau : pondération

    # Reste identique
    common_acronyms: Dict[str, str]
    key_concepts: List[str]
    llm_injection_prompt: str
```

---

## 📝 Notes Implémentation

### Décisions Actuelles (Phase 1)

1. **Tenant par défaut = "default"** ✅
   - Tous les documents corporate sur tenant "default"
   - Paramètre par défaut dans tout le code
   - Simple et fonctionnel immédiatement

2. **1 contexte métier par instance** ✅
   - SAP enterprise software pour instance SAP
   - Pharma pour instance pharma client
   - Pas encore de support multi-contextes

3. **Modifications code minimales** ✅
   - 2 lignes modifiées dans gatekeeper.py
   - Paramètre `tenant_id` ajouté, valeur par défaut "default"
   - Rétro-compatible (pas de breaking change)

### Préparation Future (Phase 2+)

1. **Schéma Neo4j évolutif** ✅
   - DomainContextProfile extensible (Pydantic)
   - Peut ajouter champs sans migration complexe

2. **API d'import prête** 🔄
   - Ajouter paramètre `tenant_id` dans endpoints
   - Endpoint `/upload` → `/upload?tenant_id=user_jane`

3. **Recherche multi-tenant** 🔄
   - Endpoint `/search` → `/search?tenants=default,user_jane`
   - Fusion résultats avec pondération

---

## 🎯 Décision Immédiate

**Pour Phase 1 (actuel) :**
- ✅ Utiliser `tenant_id = "default"` pour contexte corporate
- ✅ Modifications gatekeeper.py faites
- ✅ Migration contexte SAP vers "default" terminée
- ✅ Prêt pour ingestion avec contexte métier SAP

**Pour Phase 2+ (future) :**
- 📋 Documenté dans ce fichier
- 📋 Architecture claire pour tenants utilisateurs
- 📋 Cas d'usage multi-sectoriel (Jane) planifié
- 📋 Options implémentation évaluées

---

**Dernière mise à jour :** 2025-11-17
**Responsable :** Domain Context Personalizer (Composant 0 bis)
**Références :**
- `doc/specs/OSMOSE_PHASE2_DOMAIN_CONTEXT_PERSONALIZER.md`
- `doc/tracking/OSMOSE_PHASE2_TRACKING.md`

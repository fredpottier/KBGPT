# 🌊 OSMOSE Phase 2 - DomainContextPersonalizer

**Version:** 1.0
**Date Création:** 2025-11-17
**Status:** 📋 SPÉCIFICATION

---

## 🎯 Objectif

Permettre aux utilisateurs de **personnaliser le contexte métier** dans lequel le système opère, sans compromettre la **généricité architecturale** du moteur.

### Principe Fondamental

- ✅ **Code moteur** : Domain-agnostic (aucun biais métier hardcodé)
- ✅ **Contexte utilisateur** : Domain-specific (personnalisé par tenant)
- ✅ **Prompt engineering** : Injection dynamique du contexte métier dans les prompts LLM

---

## 🧠 Concept

L'utilisateur fournit une **description textuelle libre** du domaine métier via le frontend. Le système utilise un **appel LLM** pour extraire un **DomainContextProfile** structuré, qui sera ensuite **injecté automatiquement** dans tous les prompts LLM (canonicalization, relation extraction, taxonomy building, etc.).

---

## 📝 User Story

**En tant qu'** administrateur tenant
**Je veux** définir le contexte métier de mon organisation
**Afin que** le système comprenne mieux mes documents et génère des ontologies/relations/taxonomies pertinentes

### Exemple d'Input Utilisateur

```
La solution sera utilisée par les collaborateurs de la société SAP qui édite
des logiciels notamment cloud comme l'ERP S/4HANA, SuccessFactors, Concur, etc.
Les documents seront donc notamment techniques, marketing et fonctionnel en majorité.

Nos utilisateurs sont principalement des consultants, architectes solutions,
et équipes avant-vente qui ont besoin de comprendre rapidement les dépendances
entre produits, les évolutions de versions, et les intégrations possibles.

Acronymes courants dans notre contexte : SAC (SAP Analytics Cloud), BTP (Business
Technology Platform), SF (SuccessFactors), HCM (Human Capital Management).
```

### Output Structuré (DomainContextProfile)

```json
{
  "tenant_id": "sap_emea_sales",
  "domain_summary": "Enterprise software ecosystem focusing on SAP cloud products",
  "industry": "enterprise_software",
  "sub_domains": ["ERP", "HCM", "Analytics", "Integration Platform"],
  "target_users": ["consultants", "solution_architects", "pre-sales"],
  "document_types": ["technical", "marketing", "functional"],
  "common_acronyms": {
    "SAC": "SAP Analytics Cloud",
    "BTP": "Business Technology Platform",
    "SF": "SuccessFactors",
    "HCM": "Human Capital Management"
  },
  "key_concepts": [
    "SAP S/4HANA",
    "SuccessFactors",
    "Concur",
    "SAP Analytics Cloud",
    "Business Technology Platform"
  ],
  "context_priority": "high",
  "llm_injection_prompt": "You are analyzing documents from SAP enterprise software ecosystem. Common products include S/4HANA (ERP), SuccessFactors (HCM), SAP Analytics Cloud (BI), and Business Technology Platform (integration). When you see acronyms like SAC, BTP, SF, or HCM, interpret them in this SAP context unless context clearly suggests otherwise.",
  "created_at": "2025-11-17T20:45:00Z",
  "updated_at": "2025-11-17T20:45:00Z"
}
```

---

## 🏗️ Architecture

### Composants

#### 1. **DomainContextExtractor** (LLM-powered)

**Input :** Texte libre utilisateur (2-500 mots)

**Output :** `DomainContextProfile` Pydantic model

**Méthode :**
- Appel LLM (gpt-4o-mini ou Claude Sonnet)
- Prompt spécialisé pour extraction structurée
- Validation Pydantic

**Fichier :** `src/knowbase/ontology/domain_context_extractor.py`

```python
class DomainContextProfile(BaseModel):
    """Profil contexte métier pour un tenant."""
    tenant_id: str
    domain_summary: str
    industry: str
    sub_domains: List[str]
    target_users: List[str]
    document_types: List[str]
    common_acronyms: Dict[str, str]  # acronyme → expansion
    key_concepts: List[str]
    context_priority: Literal["low", "medium", "high"]
    llm_injection_prompt: str  # Texte prêt pour injection
    created_at: datetime
    updated_at: datetime

class DomainContextExtractor:
    """Extracteur LLM pour profil contexte métier."""

    async def extract_from_text(
        self,
        user_text: str,
        tenant_id: str
    ) -> DomainContextProfile:
        """
        Extrait profil structuré depuis texte libre utilisateur.

        Args:
            user_text: Description libre du domaine métier
            tenant_id: ID tenant

        Returns:
            DomainContextProfile structuré
        """
        # Appel LLM avec prompt spécialisé
        # Validation + structuration Pydantic
        pass
```

#### 2. **DomainContextStore** (Persistence)

**Storage :** Neo4j (tenant-specific nodes)

**Node Label :** `:DomainContextProfile`

**Properties :**
- tenant_id (unique index)
- domain_summary
- industry
- sub_domains (JSON)
- common_acronyms (JSON)
- llm_injection_prompt
- created_at, updated_at

**Fichier :** `src/knowbase/ontology/domain_context_store.py`

```python
class DomainContextStore:
    """Stockage et récupération profils contexte métier."""

    def __init__(self, neo4j_driver):
        self.driver = neo4j_driver

    def save_profile(self, profile: DomainContextProfile) -> None:
        """Sauvegarde (upsert) profil contexte."""
        pass

    def get_profile(self, tenant_id: str) -> Optional[DomainContextProfile]:
        """Récupère profil contexte pour un tenant."""
        pass

    def delete_profile(self, tenant_id: str) -> None:
        """Supprime profil contexte."""
        pass
```

#### 3. **DomainContextInjector** (Middleware)

**Rôle :** Injecter automatiquement le contexte métier dans **tous les prompts LLM**

**Intégration Points :**
- `LLMCanonicalizer` (canonicalization concepts)
- `LLMRelationExtractor` (extraction relations)
- `TaxonomyBuilder` (clustering/classification)
- `TemporalDiffEngine` (analyse changements)

**Fichier :** `src/knowbase/ontology/domain_context_injector.py`

```python
class DomainContextInjector:
    """Middleware injection contexte métier dans prompts LLM."""

    def __init__(self, context_store: DomainContextStore):
        self.context_store = context_store

    def inject_context(
        self,
        base_prompt: str,
        tenant_id: str
    ) -> str:
        """
        Injecte contexte métier dans prompt LLM.

        Args:
            base_prompt: Prompt système générique
            tenant_id: ID tenant

        Returns:
            Prompt enrichi avec contexte métier

        Example:
            base_prompt = "You are a concept canonicalization expert..."
            enriched = injector.inject_context(base_prompt, "sap_sales")
            # → "You are a concept canonicalization expert...
            #    [DOMAIN CONTEXT: SAP enterprise software ecosystem...]"
        """
        profile = self.context_store.get_profile(tenant_id)

        if not profile or profile.context_priority == "low":
            return base_prompt

        # Injection du contexte métier
        context_section = f"""

[DOMAIN CONTEXT - Priority: {profile.context_priority.upper()}]
{profile.llm_injection_prompt}

Common acronyms in this domain:
{self._format_acronyms(profile.common_acronyms)}

Key concepts to recognize:
{', '.join(profile.key_concepts[:10])}
[END DOMAIN CONTEXT]

"""
        return base_prompt + context_section

    def _format_acronyms(self, acronyms: Dict[str, str]) -> str:
        """Formate acronymes pour injection prompt."""
        return "\n".join([f"- {k}: {v}" for k, v in acronyms.items()])
```

---

## 🔌 Intégration avec Composants Existants

### 1. LLMCanonicalizer (Phase 1.5)

**Avant :**
```python
prompt = CANONICALIZATION_SYSTEM_PROMPT  # Générique
response = llm_router.call(prompt + user_input)
```

**Après :**
```python
base_prompt = CANONICALIZATION_SYSTEM_PROMPT  # Générique
enriched_prompt = domain_injector.inject_context(base_prompt, tenant_id)
response = llm_router.call(enriched_prompt + user_input)
```

**Résultat :**
- Si tenant SAP : LLM sait que "SAC" = "SAP Analytics Cloud"
- Si tenant Pharma : LLM sait que "API" = "Active Pharmaceutical Ingredient" (pas "Application Programming Interface")
- Si pas de contexte : Comportement générique (domain-agnostic)

### 2. LLMRelationExtractor (Phase 2)

**Injection similaire** dans le prompt d'extraction relations.

**Bénéfice :**
- Meilleure détection relations spécifiques domaine
- Exemple : "S/4HANA REQUIRES BTP" détecté car contexte SAP connu

### 3. TaxonomyBuilder (Phase 2)

**Injection dans clustering/classification.**

**Bénéfice :**
- Taxonomies adaptées au domaine (hiérarchie produits SAP vs hiérarchie médicaments)

---

## 🎨 Frontend Integration

### Page : `/settings/domain-context`

**UI Components :**

1. **Textarea** : Description libre domaine métier (500 chars max)
2. **Button "Générer Profil"** : Appel API extraction LLM
3. **Preview Panel** : Affichage profil structuré généré
4. **Button "Enregistrer"** : Sauvegarde profil Neo4j
5. **Button "Réinitialiser"** : Suppression profil (retour générique)

**API Endpoints :**

```typescript
// Extraction profil depuis texte libre
POST /api/domain-context/extract
Body: { text: string, tenant_id: string }
Response: DomainContextProfile

// Sauvegarde profil
POST /api/domain-context/save
Body: DomainContextProfile

// Récupération profil actuel
GET /api/domain-context?tenant_id=xxx
Response: DomainContextProfile | null

// Suppression profil
DELETE /api/domain-context?tenant_id=xxx
```

---

## 📊 Cas d'Usage

### UC1 : Équipe SAP Sales

**Input :**
```
Nous sommes une équipe sales SAP EMEA. Nos docs concernent
principalement S/4HANA Cloud, SuccessFactors, SAP Analytics Cloud.
```

**Profil Généré :**
- Industry: `enterprise_software`
- Acronyms: `{ "SAC": "SAP Analytics Cloud", "SF": "SuccessFactors" }`
- Key Concepts: `["SAP S/4HANA Cloud", "SuccessFactors", ...]`

**Impact :**
- Import doc "SAC Product Overview" → Concept canonicalisé "SAP Analytics Cloud" (grâce contexte)
- Relation "S/4HANA INTEGRATES_WITH BTP" mieux détectée

### UC2 : Laboratoire Pharmaceutique

**Input :**
```
Nous sommes un laboratoire pharmaceutique. Nos documents concernent
la R&D, les essais cliniques, et la production de médicaments.
Acronymes courants : API (Active Pharmaceutical Ingredient),
GMP (Good Manufacturing Practice), FDA (Food and Drug Administration).
```

**Profil Généré :**
- Industry: `pharmaceutical`
- Acronyms: `{ "API": "Active Pharmaceutical Ingredient", "GMP": "Good Manufacturing Practice" }`
- Key Concepts: `["Clinical Trials", "Drug Development", "FDA Approval"]`

**Impact :**
- Import doc "API Production Guidelines" → Concept "Active Pharmaceutical Ingredient" (PAS "Application Programming Interface")
- Taxonomie adaptée : Drugs → Clinical Phases → Regulatory Approvals

### UC3 : Startup Tech Générique (Pas de Contexte)

**Input :** *(vide ou skip)*

**Profil Généré :** `null`

**Impact :**
- Comportement domain-agnostic pur (comme actuellement)
- Acronymes interprétés uniquement si universellement connus (GDPR, CRM, SLA)

---

## 🛠️ Implémentation Phase 2

### Placement dans Roadmap

**Option 1 : Composant 0 bis (Fondation)**
→ Implémenté **avant** RelationExtractionEngine
→ Tous les composants Phase 2 bénéficient immédiatement

**Option 2 : Composant 6 (Post-Phase 2)**
→ Implémenté **après** CrossDocRelationMerger
→ Amélioration post-validation

**Recommandation : Option 1 (Fondation)**
→ Maximum d'impact, utilisé par tous les composants

### Timeline Proposée

**Semaine 15 bis (5 jours) - Entre Semaine 15 et 16**

#### Jour 1-2 : Backend Core
- [x] DomainContextProfile Pydantic model
- [x] DomainContextExtractor (LLM extraction)
- [x] Tests unitaires extraction

#### Jour 3 : Persistence
- [x] DomainContextStore (Neo4j)
- [x] Schema Neo4j (constraints, indexes)
- [x] Tests CRUD

#### Jour 4 : Injection Middleware
- [x] DomainContextInjector
- [x] Integration LLMCanonicalizer
- [x] Integration LLMRelationExtractor
- [x] Tests injection

#### Jour 5 : API + Frontend
- [x] API routers (extract, save, get, delete)
- [x] Frontend page `/settings/domain-context`
- [x] Tests E2E
- [x] Documentation

---

## 📐 Schemas Techniques

### Neo4j Schema

```cypher
// Node DomainContextProfile
CREATE CONSTRAINT domain_context_tenant_unique
IF NOT EXISTS
FOR (dcp:DomainContextProfile)
REQUIRE dcp.tenant_id IS UNIQUE;

CREATE INDEX domain_context_industry
IF NOT EXISTS
FOR (dcp:DomainContextProfile)
ON (dcp.industry);
```

### Pydantic Model

```python
from pydantic import BaseModel, Field
from typing import List, Dict, Literal
from datetime import datetime

class DomainContextProfile(BaseModel):
    """Profil contexte métier tenant-specific."""

    tenant_id: str = Field(..., description="Tenant ID unique")
    domain_summary: str = Field(..., max_length=500, description="Résumé domaine métier")
    industry: str = Field(..., description="Industrie principale")
    sub_domains: List[str] = Field(default_factory=list, description="Sous-domaines")
    target_users: List[str] = Field(default_factory=list, description="Profils utilisateurs")
    document_types: List[str] = Field(default_factory=list, description="Types documents")
    common_acronyms: Dict[str, str] = Field(
        default_factory=dict,
        description="Acronymes → Expansions (max 50)"
    )
    key_concepts: List[str] = Field(
        default_factory=list,
        max_items=20,
        description="Concepts clés domaine"
    )
    context_priority: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Priorité injection contexte"
    )
    llm_injection_prompt: str = Field(
        ...,
        max_length=1000,
        description="Texte injection prompt LLM"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_schema_extra = {
            "example": {
                "tenant_id": "sap_emea_sales",
                "domain_summary": "Enterprise software ecosystem focusing on SAP cloud products",
                "industry": "enterprise_software",
                # ... (voir exemple complet plus haut)
            }
        }
```

---

## 🧪 Tests Validation

### Tests Unitaires

1. **test_domain_context_extractor.py**
   - Extraction texte court (50 mots) → profil valide
   - Extraction texte long (500 mots) → profil valide
   - Texte vague → profil générique (low priority)
   - Validation schema Pydantic

2. **test_domain_context_store.py**
   - Save → Get → Vérification identité
   - Update → Vérification updated_at
   - Delete → Get null
   - Tenant isolation

3. **test_domain_context_injector.py**
   - Injection high priority → Contexte présent
   - Injection low priority → Pas d'injection
   - Tenant sans profil → Pas d'injection
   - Vérification format prompt enrichi

### Tests E2E

**Scénario SAP :**
1. Admin définit contexte SAP
2. Import doc "SAC Overview"
3. Vérification concept "SAP Analytics Cloud" créé (pas "Company Analytics Cloud")
4. Vérification alias "SAC" présent

**Scénario Pharma :**
1. Admin définit contexte Pharma
2. Import doc "API Guidelines"
3. Vérification concept "Active Pharmaceutical Ingredient" créé (pas "Application Programming Interface")

---

## 📝 Documentation Utilisateur

### Guide Admin : Configuration Contexte Métier

**Étape 1 :** Accéder à `/settings/domain-context`

**Étape 2 :** Décrire votre domaine métier (2-5 paragraphes)

**Conseils :**
- Mentionner votre industrie/secteur
- Lister produits/services clés
- Indiquer acronymes courants
- Décrire profils utilisateurs
- Préciser types documents traités

**Étape 3 :** Cliquer "Générer Profil" → Vérifier extraction

**Étape 4 :** Ajuster si nécessaire, puis "Enregistrer"

**Impact :**
- Meilleure reconnaissance acronymes
- Ontologies/taxonomies adaptées
- Relations mieux détectées

---

## 🎯 KPIs Succès

| Métrique | Target | Mesure |
|----------|--------|--------|
| **Precision acronyms (avec contexte)** | ≥ 95% | Validation manuelle 100 acronymes |
| **Precision acronyms (sans contexte)** | ≥ 70% | Baseline actuelle |
| **Amélioration canonicalization** | +15% | Comparaison avec/sans contexte |
| **Tenant adoption** | ≥ 60% | % tenants avec profil défini |
| **User satisfaction** | ≥ 4.2/5 | Survey post-feature |

---

## 🔄 Évolutions Futures (Phase 3+)

### V2 : Auto-Learning Context

- Apprentissage automatique depuis documents importés
- Suggestions proactives acronymes détectés
- Raffinement continu profil

### V3 : Multi-Domain Support

- Tenant peut définir **plusieurs** contextes (ex: "SAP" + "Pharma")
- Contexte auto-sélectionné selon document type

### V4 : Shared Context Templates

- Marketplace templates pré-configurés (SAP, Pharma, Retail, etc.)
- Import template → Personnalisation

---

## 📎 Références

- Architecture générique : `CLAUDE.md` (principe domain-agnostic)
- Phase 2 tracking : `doc/ongoing/OSMOSE_PHASE2_TRACKING.md`
- LLMCanonicalizer : `src/knowbase/ontology/llm_canonicalizer.py`
- Neo4j Client : `src/knowbase/common/clients/neo4j_client.py`

---

**FIN Spécification DomainContextPersonalizer v1.0**

**Statut :** 📋 SPÉCIFICATION COMPLÈTE
**Prêt pour :** Implémentation Semaine 15 bis (5 jours)
**Priorité :** 🔴 HAUTE (Fondation Phase 2)

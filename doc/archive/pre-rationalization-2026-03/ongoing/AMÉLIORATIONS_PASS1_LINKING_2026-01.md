# Améliorations Pass 1 Linking - Janvier 2026

**Date:** 2026-01-27
**Statut:** MVP Validé - En route vers Prod
**Source:** Tests qualité + analyses ChatGPT/Claude
**Review:** Validé par ChatGPT (2026-01-27)

---

## Résumé Exécutif

Suite aux tests du 2026-01-27, la couverture sémantique est passée de **11.7% à 81.9%** grâce aux fixes C3 v2.
L'analyse qualitative (Precision@1) révèle des axes d'amélioration pour atteindre un niveau production.

| Métrique | Actuel | Cible MVP | Cible Prod | Status |
|----------|--------|-----------|------------|--------|
| Coverage | 81.9% | >75% | >85% | ✅ MVP |
| Precision@1 (strict) | 62.5% | >70% | >80% | 🔄 En cours |
| Precision@1 (lenient) | 87.5% | >85% | >92% | ✅ MVP |
| Noise leakage (meta) | 12.5% | <5% | <2% | 🔴 À traiter |

---

## ✅ Validation ChatGPT (2026-01-27)

### Verdict Global

> "Le plan est validé. Les résultats sont excellents pour un MVP. Les problèmes restants sont identifiés, circonscrits et non-bloquants."

### Points Validés

1. **Contraintes C1/C2/C3/C4 saines** - Pas de sur-ingénierie
2. **Pass 1.2b = mécanisme d'apprentissage contrôlé** - Pas un hack
3. **Graphe 6.6× plus riche** sans explosion de nœuds
4. **Les ❌ ne sont PAS des hallucinations** - Ce sont des erreurs de périmètre (filtrage)

### Insight Clé : Taxonomie d'Erreurs

> "Ce n'est pas un problème de linking. C'est un problème de filtrage amont."

| Type d'Erreur | Cause | Solution |
|---------------|-------|----------|
| **Erreur de nettoyage** | Meta/disclaimer promu | Filtre Pass 1.3 |
| **Erreur de connaissance** | Mauvaise affectation concept | Améliorer linking |

→ Les erreurs actuelles (12.5%) sont **100% erreurs de nettoyage**, pas de linking.

---

## 🛡️ GARDE-FOUS - NE PAS CASSER

> "Ce que tu as construit, c'est un moteur de vérité documentaire, pas un moteur de rappel exhaustif."

### ❌ Interdictions Absolues

| Composant | Raison |
|-----------|--------|
| `lexical_triggers` obligatoires | Ancrage factuel, pas de concepts "beaux mais vides" |
| Soft gate + Hard gate (C3 v2) | Évite le coupe-circuit tout en gardant le contrôle |
| Critère C2 (qualité minimale) | Empêche les concepts "poubelle" |
| Saturation contrôlée (C4) | Itération gouvernée, pas d'explosion |

### ❌ Anti-Patterns à Éviter

- "Relâcher le système pour gagner 5% de coverage"
- "Augmenter MAX_CONCEPTS sans critère structurel"
- "Supprimer les triggers pour simplifier"

---

## ✅ FIXES DÉJÀ IMPLÉMENTÉS (2026-01-27)

### 1. Persistence des lexical_triggers
**Fichier:** `src/knowbase/stratified/pass1/persister.py`
**Commit:** `63a1019`

**Problème:** Les `lexical_triggers` n'étaient pas sauvegardés dans Neo4j (NULL).
**Solution:** Ajout du champ dans `_create_concept_tx()`.

### 2. C3 v2 - Soft Gate + Hard Gate
**Fichier:** `src/knowbase/stratified/pass1/assertion_extractor.py`
**Commit:** `63a1019`

**Problème:** C3 original utilisait les triggers doc-level comme test assertion-level → coupe-circuit.
**Solution:**
- Soft gate: pas de trigger → confidence -= 0.20
- Hard gate: rejet si (pas trigger ET pas token du nom) ET conf < 0.55
- Nouvelle méthode `_has_concept_name_token()`

**Résultat:** Coverage 11.7% → 81.9%

---

## 🔴 À IMPLÉMENTER - PRIORITÉ 1 (Bloquant Prod)

### A. Filtre META/DISCLAIMER/PROCESS en Pass 1.3

**Problème identifié:**
5/40 assertions (12.5%) sont du contenu "meta" qui pollue le graphe :
- Disclaimers légaux ("forward-looking statements", "not a commitment")
- Process internes ("requires approval via CISA")
- User flows ("user opens the URL", "click", "navigate")

**Pourquoi c'est prioritaire:**
> "Les ❌ ne sont pas des erreurs de linking, ce sont des erreurs de filtrage."
Résoudre ce point = **+10-15% Precision@1 strict** immédiat.

**Solution proposée:**
Ajouter un filtre en Pass 1.3 (avant linking) avec :

```python
META_PATTERNS = [
    # Legal disclaimers
    r"forward-looking statements?",
    r"not a commitment",
    r"confidential and proprietary",
    r"for informational purposes",
    r"subject to change",
    r"without (prior )?notice",
    r"may not be disclosed",

    # Process/workflow
    r"requires approval",
    r"via (CISA|Cyber Legal|ticket)",
    r"escalation (process|procedure)",
    r"R&R|roles and responsibilities",

    # User flow/navigation
    r"user (opens?|clicks?|navigates?)",
    r"(open|click|navigate to) (the )?(URL|link|button)",
    r"in (your|the) browser",
    r"login (to|into)",
]
```

**Sortie:** `type=META`, `status=REJECTED`, `reason=meta_content`

**Fichier à modifier:** `src/knowbase/stratified/pass1/assertion_extractor.py`

**Impact attendu:** Precision@1 strict 62.5% → **72-77%**

---

### B. Traiter le Concept "Aspirateur"

**Problème identifié:**
```
"infrastructure SAP": 108/244 liens (44%)
```
Ce n'est pas un bug - c'est un **signal structurel** : quand le système hésite, il tombe sur le concept le plus permissif.

**⚠️ STRATÉGIE VALIDÉE (ChatGPT):**

> "Ne supprime pas infrastructure SAP. Dégrade-le en CONTEXTUAL, et empêche-le d'être CENTRAL sans triggers discriminants."

**Actions:**

1. **DÉGRADER** "infrastructure SAP" de CENTRAL → CONTEXTUAL
2. **DÉCOMPOSER** en concepts STANDARD plus typés :
   - "connectivité réseau" (VPC, peering, Direct Connect, private link)
   - "sécurité périmétrique" (WAF, NSG, FWaaS)
   - "sécurité hôte/OS" (vulnerability mgmt, patching)
   - "services plateforme" (LogServ, ECS services, monitoring)

3. **RÈGLE C1b renforcée:**
   - Interdire un concept CENTRAL s'il n'a pas de triggers discriminants (< 1% fréquence)
   - Un concept sans trigger rare ne peut être que STANDARD ou CONTEXTUAL

**Impact attendu:**
- Répartition plus équilibrée des liens
- Precision@1 strict +5-10%
- Meilleure navigabilité du graphe

---

## 🟡 À IMPLÉMENTER - PRIORITÉ 2 (Amélioration Prod)

### C. Budget Conceptuel Adaptatif

**Référence:** `doc/ongoing/IDEA_ADAPTIVE_CONCEPT_BUDGET.md`

**Problème:** MAX_CONCEPTS=30 fixe inadapté aux gros documents SAP (1500+ pages).

**Solution validée:**
```python
MAX_CONCEPTS = clamp(25, 80, 15 + sqrt(sections) * 3)
```

**⚠️ CRITÈRE D'ACTIVATION (ChatGPT):**

> "Garde 30 comme plancher MVP. Active le budget adaptatif uniquement pour les docs 'long-form'."

| Type Document | Sections | Budget |
|---------------|----------|--------|
| Whitepaper simple | < 50 | 30 (fixe) |
| Admin guide SAP | 50-200 | 30-50 (adaptatif) |
| Pavé 1500 pages | > 200 | 50-80 (adaptatif) |

**Logging obligatoire:**
```python
logger.info(f"[OSMOSE:Budget] sections={sections} → max_concepts={max_concepts}")
```

---

### D. Métriques de Pilotage Séparées

**Nouvelle taxonomie d'erreurs:**

| Métrique | Formule | Ce qu'elle mesure |
|----------|---------|-------------------|
| `Precision@1 (knowledge-only)` | Correct / (Total - Meta) | Score core system |
| `Noise leakage rate` | Meta promu / Total promu | % pollution |
| `Coverage (quality)` | Promoted / (Total - Rejected) | Couverture effective |

**Bénéfice:** Permet de **diagnostiquer précisément** si un problème vient du filtrage ou du linking.

---

## 🟢 À IMPLÉMENTER - PRIORITÉ 3 (Nice to Have)

### E. Multi-linking Quality Check

Vérifier que le multi-linking ne "double-compte" pas artificiellement.
Test : assertions avec 3+ concepts → vérifier pertinence de chaque lien.

⚠️ **Note:** Dès que le système dépassera régulièrement 2-3 concepts/assertion, ce check deviendra critique pour éviter un double-comptage flatteur des métriques.

### F. Concept "Frère" Detection

Pour les concepts trop larges, suggérer automatiquement des concepts "frères" plus spécifiques.

---

## 📐 Notes d'Architecture Future

> Remarques non-bloquantes pour évolutions post-MVP

### 1. Filtre META → Phase Identifiée

**Situation actuelle:** Le filtre META est un correctif dans Pass 1.3.

**Évolution recommandée:**
- Soit créer un **Pass 1.2.5 – Content Hygiene** dédié
- Soit ajouter un flag explicite `assertion.category = META | KNOWLEDGE`

**Bénéfice:**
- Métriques "knowledge-only" structurellement propres
- Évite les débats de périmètre lors d'audits/démos client
- Traçabilité claire dans les logs et Neo4j

**Implémentation suggérée:**
```python
class AssertionCategory(str, Enum):
    KNOWLEDGE = "KNOWLEDGE"  # Contenu factuel/prescriptif
    META = "META"            # Disclaimers, legal, boilerplate
    PROCESS = "PROCESS"      # Workflows, approvals (voir note 2)
```

### 2. Type PROCESS_INFO (Réserve)

**Situation actuelle:** Les contenus "process" sont rejetés avec les META.

**Observation:** Certains clients voudront cartographier responsabilités & processus sans polluer le knowledge graph factuel.

**Évolution possible:**
- Type `PROCESS_INFO` : non promu vers Concept, mais conservé séparément
- Permet un graphe "Process & Responsibilities" parallèle au knowledge graph
- Activation par feature flag client

**Non prioritaire** - mais l'architecture actuelle permet cette extension.

### 3. Séparation Graphe Factuel / Graphe Process

**Vision long terme:**
```
Knowledge Graph (OSMOSE v1)
├── Concepts ← Information (KNOWLEDGE)
└── Assertions factuelles

Process Graph (OSMOSE v2?)
├── Roles & Responsibilities
├── Approval Workflows
└── Assertions PROCESS_INFO
```

Cette séparation permettrait de répondre à deux besoins clients distincts sans compromis.

---

## Roadmap MVP → Prod

> Source: Recommandation ChatGPT

### Phase 1 : Nettoyage (Immédiat)
1. ✅ Filtre META en Pass 1.3
2. ✅ Décomposition concept aspirateur
3. → **Cible: Precision@1 strict > 75%**

### Phase 2 : Scalabilité (Court terme)
4. Budget conceptuel adaptatif
5. Métriques séparées knowledge/noise
6. → **Cible: Fonctionne sur docs 500+ sections**

### Phase 3 : Production (Moyen terme)
7. Tests de régression automatisés
8. Monitoring temps réel des métriques
9. → **Cible: Precision@1 strict > 80%, Noise < 2%**

---

## Tests de Validation Requis

### Test A : Precision@1 après filtre META
1. Implémenter filtre META_PATTERNS
2. Relancer Pass 1+2
3. Re-échantillonner 40 assertions
4. Calculer Precision@1 (cible: strict >70%)

### Test B : Analyse concepts aspirateurs
1. Lister les 30 concepts avec leur distribution d'assertions
2. Identifier ceux avec >15% des assertions
3. Dégrader en CONTEXTUAL + décomposer
4. Valider répartition après

### Test C : Multi-linking quality
1. Extraire assertions avec 2+ concepts
2. Vérifier pertinence des liens secondaires
3. Calculer "secondary link precision"

---

## Historique des Tests

### 2026-01-27 - Test Initial C3 v2

**Configuration:**
- Document: RISE SAP Cloud ERP Private (206 sections, 2091 unités)
- Concepts: 30 (après 3 itérations Pass 1.2b)
- Coverage: 81.9%

**Échantillon Precision@1 (n=40):**
- ✅ Correct: 25 (62.5%)
- ⚠️ Acceptable: 10 (25%)
- ❌ Incorrect: 5 (12.5%)

**Analyse des erreurs:**
- 5/5 erreurs = contenu META (pas erreur de linking)
- 4x disclaimers légaux → "infrastructure SAP"
- 1x process interne → "infrastructure SAP"

**Distribution des liens par concept:**
```
"infrastructure SAP": 108 (44%) ← ASPIRATEUR
"responsabilité de sécurité partagée": 21 (9%)
"exigences de sécurité des données": 19 (8%)
"gestion des données": 19 (8%)
"services cloud SAP": 16 (7%)
... (reste < 5% chacun)
```

---

## Annexes

### Liste des 30 concepts (à compléter)

```cypher
MATCH (c:Concept) WHERE c.tenant_id='default'
RETURN c.name, c.role, c.lexical_triggers
ORDER BY c.role, c.name
```

### Patterns META détectés dans l'échantillon

1. "The information in this presentation is not a commitment, promise or legal obligation..."
2. "The information in this presentation is confidential and proprietary to SAP..."
3. "All forward-looking statements are subject to various risks..."
4. "Requires approval from Cyber Legal via CISA Ticket..."
5. "User opens the URL for SAC in his browser..."

---

## Références

- `doc/ongoing/IDEA_ADAPTIVE_CONCEPT_BUDGET.md` - Détail budget adaptatif
- Plan d'implémentation: `doc/ongoing/reflective-jingling-matsumoto.md`
- Commit fixes C3 v2: `63a1019`

---

*Document vivant - Mis à jour au fur et à mesure des tests*
*Dernière mise à jour: 2026-01-27 (intégration review ChatGPT)*

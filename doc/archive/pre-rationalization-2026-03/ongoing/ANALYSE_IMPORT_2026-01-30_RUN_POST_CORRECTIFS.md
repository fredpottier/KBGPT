# Analyse Run Post-Correctifs — RISE with SAP Cloud ERP Private Security

**Date :** 2026-01-30
**Document :** RISE with SAP Cloud ERP Private — Security (230 pages, EN)
**Pipeline :** Stratified V2 (GlobalView 16K) + 5 correctifs + ADR HOSTILE v2
**LLM :** Qwen2.5-14B-Instruct-AWQ via vLLM Burst (16K context)
**Run :** 2026-01-30 11h31 → 12h06 (~35 min)

---

## 1. Métriques Globales — Run 2 (post-rebuild container)

| Métrique | Run 1 (ancien container) | **Run 2 (post-correctifs)** | Cible | Statut |
|----------|--------------------------|----------------------------|-------|--------|
| Informations extraites | 135 | **119** | > 120 | ⚠️ |
| Concepts créés | 61 | **61** (dont 1 SINK) | — | — |
| Thèmes identifiés | 32 | **19** | — | ✅ |
| Relations Pass 2 | 0 (JSON parse) | **0** (JSON parse ❌) | > 0 | ❌ |
| SINK | 67/135 = **50%** | **32/119 = 27%** | 15-30% | ✅ |
| Concepts vides (0 info) | 40/60 = 67% | **37/60 = 62%** | < 25% | ❌ |
| Calibration | **Fallback** (spread<0.05) | **Auto** (spread=0.084) | Auto | ✅ |
| Assertions rejetées | — | 213 (policy_rejected) | — | ⚠️ |
| Assertions abstained | — | 70 (54 no_concept + 16 cross_docitem) | — | ⚠️ |
| Max concept métier | — | Security Architecture = **29 (24%)** | < 20% | ⚠️ |
| DocItems | 6743 | 6743 (1697 indexés en unités) | — | — |
| DocItem types | — | 1691 texts + 9 tables | — | — |

### Verdict Run 2

**Améliorations majeures :**
- ✅ SINK passé de 50% à **27%** (dans la cible 15-30%)
- ✅ Auto-calibration activée (spread 0.084 > seuil 0.03)
- ✅ Seuils adaptatifs : band1=0.449, band3=0.533

**Problèmes persistants :**
- ❌ **62% de concepts vides** (37/60 non-SINK) — amélioration marginale vs 67%
- ❌ **Security Architecture aspire 29 infos (24%)** — toujours un aspirateur dominant
- ❌ **Pass 2 crash** (JSON parse error → 0 relations)
- ⚠️ **213 rejections policy_rejected** — trop élevé, possible perte d'information

---

## 2. Calibration Détaillée (Run 2)

```
mode=auto Q10=0.600 Q50=0.645 Q75=0.684
band1=0.449 band3=0.533 spread=0.084
offset=0.151 n=135 conf_orig=0.479 conf_final=0.379
gap_min=0.034 margin=0.042
raw_Q20=0.600 raw_Q50=0.600
```

**Analyse :**
- Spread = 0.084 (vs 0.050 en Run 1) — le correctif `min_score_spread: 0.03` a permis l'auto-calibration
- Les seuils band1 (0.449) et band3 (0.533) sont plus bas qu'en fallback → moins d'assertions routées en SINK
- Le gap_min (0.034) est étroit — la discrimination fine est encore limitée

### Distribution provisoire Pass 1 (2-Pass)

```
Pass 1: 135 assertions, 22 concepts actifs
Top aspirateurs:
  concept_1 = Tenant Isolation:       62 assertions (46%)
  concept_53 = Surveillance audits:   17 assertions (13%)
  concept_38 = ?:                     12 assertions (9%)
  concept_2 = ?:                       10 assertions (7%)
  concept_34 = ?:                       5 assertions (4%)
```

**Tenant Isolation aspire 62 assertions (46%)** en provisoire → pénalité Phase 3 (0.60).
Après reranking : **Security Architecture absorbe 29 infos finales (24%)** — aspirateur réduit mais toujours au-dessus du seuil 20%.

### Saturation Penalty Logs

```
Saturation:Phase3-near-block: concept_1 (Tenant Isolation): count=62, mean=8.0, penalty=0.60
Saturation:Phase2-agressive: concept_53 (Surveillance audits): count=17, mean=8.0, penalty=0.78
```

Exemples de score post-pénalité :
- `assert_ca043eb1 → Tenant Isolation: conf 0.65 → 0.39 (penalty=0.60)` → **SINK** (< band1 0.449)
- `assert_9396e70b → Surveillance audits: conf 0.65 → 0.50 (penalty=0.78)` → **entre band1 et band3** (zone grise)
- `assert_55be3eba → concept_10: conf 0.85 → 1.00 (lex=1.25, penalty=0.99)` → **PROMU** (score fort)

---

## 3. Thèmes (19)

*(Les noms de thèmes sont en français — le meta-document GlobalView est encore généré en FR malgré le correctif Issue 3. La langue est correctement détectée comme "en" mais le LLM GlobalView rédige en FR.)*

---

## 4. Concepts — Top 15 par densité

| # | Concept | Rôle | Infos |
|---|---------|------|-------|
| 1 | **Assertions non classées** | **SINK** | **32** |
| 2 | Security Architecture | CONTEXTUAL | 29 |
| 3 | Volume Encryption | CONTEXTUAL | 17 |
| 4 | Compliance Scans | CONTEXTUAL | 8 |
| 5 | Ransomware Defense | CONTEXTUAL | 6 |
| 6 | Golden Images | CONTEXTUAL | 5 |
| 7 | FWaaS | CONTEXTUAL | 3 |
| 8 | External Fiori access | CONTEXTUAL | 2 |
| 9 | Secure by Design | CONTEXTUAL | 2 |
| 10 | SAP Cloud ERP Private VPC | CONTEXTUAL | 1 |
| 11 | Security policies and compliance | CONTEXTUAL | 1 |
| 12 | Customer managed deployment | CONTEXTUAL | 1 |
| 13 | SAP Cloud ERP Private | CONTEXTUAL | 1 |
| 14 | SOC2 Type II certification | STANDARD | 1 |
| 15 | Internet Access Control | CONTEXTUAL | 1 |

**Observation critique :** Seuls **23 concepts** ont ≥1 information. 37 concepts (62%) sont complètement vides.

### 4.1 Concepts CENTRAL — Nouveau run

| Concept | Rôle | Infos |
|---------|------|-------|
| SAP Cloud ERP Private deployment | CENTRAL | **0** |
| *(autres CENTRAL non identifiés dans ce run — vérification nécessaire)* | | |

*(Note : le run 2 a généré des concepts différents du run 1. Les 5 concepts CENTRAL du run 1 ne sont pas forcément les mêmes.)*

### 4.2 Concepts vides (37 — 0 informations)

AWS Transit Gateway, Azure Storage Account, C5 Type II certification, Compliance to Cybersecurity Laws, Compliance to Data Protection Laws, Compliance to Data Security Laws, Compliance to Government Regulations, Compliance to Industry Regulations, Compliance to Personal Information Protection Laws, Customer Specific Clients, Customer Specific Deck, Key Rotation, Key Rotation and Destruction, Measures of Data Cross-Border Transfer Security Assessment, Patch Execution and Upgrades, Patch Management and Upgrades, Personal Information Protection Law, Privacy by Design, SAP Cloud ERP Private CDC Option, **SAP Cloud ERP Private deployment** (CENTRAL), SAP Cloud ERP Private deployment models, SAP Cloud Identity Services, SAP Cloud Services Vulnerability Advisory Services, SAP Global Security (SGS), SAP Personal Data Processing Agreement, SAP Secure Login Client, SOC1 Type II certification, SOC1 and SOC2 audits, Secure Login Service, Secure by Design and Default, Security Architecture Design, Security Operational Tasks, Shared security responsibility, Surveillance audits, Tenant Isolation, Tenant isolation in RISE, X.509 Certificate Provisioning

**Observations :**
- Beaucoup de concepts "Compliance to X" vides → probablement des doublons sémantiques non fusionnés
- **Tenant Isolation** est vide (0 info) alors qu'il aspirait 62 assertions en provisoire → toutes pénalisées sous le seuil → SINK
- Patch Management vide alors que des assertions sur le patching existent en SINK
- **SAP Cloud ERP Private deployment (CENTRAL)** vide → problème persistant des concepts CENTRAL

---

## 5. Assertions — Distribution par statut et raison

| Status | Reason | Count | % |
|--------|--------|-------|---|
| **PROMOTED** | promoted | **119** | 30% |
| **REJECTED** | policy_rejected | **213** | 53% |
| **ABSTAINED** | no_concept_match | **54** | 13% |
| **ABSTAINED** | cross_docitem | **16** | 4% |
| **Total** | | **402** | 100% |

### 5.1 REJECTED — policy_rejected (213 = 53%)

Ce sont des assertions rejetées par la politique de qualité **avant** le linking. Plus de la moitié des assertions n'atteignent jamais le reranking.

**Échantillons :**
- `[PERMISSIVE]` "Customer's Choice – AWS, Azure or Google Cloud" — trop vague
- `[PRESCRIPTIVE]` "Only use an in-date presentation downloaded from Cyber Security Hub" — meta-instruction
- `[FACTUAL]` "Incident Management 24x7 (Prod) Service Request Management (24x7)..." — liste de services brute
- `[PROCEDURAL]` "Browser requests live data based on meta definition..." — description technique procédurale longue
- `[FACTUAL]` "/var/log/messages /var/log/Localmessages /var/log/kernel..." — liste de fichiers brute

**Diagnostic :** La politique est probablement trop agressive. Certaines rejections sont légitimes (listes brutes, fragments) mais d'autres semblent être des assertions valides rejetées par des critères trop stricts.

### 5.2 ABSTAINED — no_concept_match (54)

Assertions pour lesquelles le LLM n'a trouvé aucun concept correspondant.

**Échantillons :**
- "Secure Infrastructure as a Code" → devrait matcher un concept infra/hardening
- "Network Access Control & Security Group" → devrait matcher un concept réseau
- "Each customer landscape are connected to shared management" → devrait matcher tenant isolation
- "All internet accesses must be encrypted in transit (via TLS)" → devrait matcher Volume Encryption ou TLS

**Diagnostic :** Ces 54 assertions n'ont été liées à aucun concept. **CAUSE PROBABLE : `concepts[:30]` — les concepts pertinents étaient au-delà de l'index 30 et invisibles au LLM.**

### 5.3 ABSTAINED — cross_docitem (16)

Assertions qui référencent un DocItem différent de celui de l'assertion.

**Échantillons :**
- "Web Application Firewall to protect against OWASP"
- "SAP Cloud Platform Identity Authentication tenant configured as trusted app in Azure AD"
- "SAP Business Technology Platform supports SCIM/SAML2.0/OpenID Connect"

---

## 6. SINK — 32 Informations Orphelines (27%)

**Échantillons :**
- "The customer requires compartmentalization"
- "The SAP Trust Center is a public-facing website designed to provide unified and easy access to trust related content"
- "Rule 3(1) of the Accounts Rules has been amended..." (régulation indienne)
- "Manage 2 Internet VPN terminations at Internet access points"
- "Perform VAPT for cloud services; customer to provide downtime for infra patching"
- "Customer is entirely responsible" (fragment)
- "Providing qualified DC or colocation facility to host infrastructure; firewall and network traffic controls"

**Analyse :** Le SINK à 27% est dans la cible (15-30%). Les assertions SINK sont un mélange de :
1. Fragments trop courts/vagues ("Customer is entirely responsible")
2. Assertions valides mais sans concept correspondant visible (compartmentalization → Tenant Isolation, mais ce concept est saturé)
3. Contenu réglementaire spécifique (Inde, Chine) sans concept dédié

---

## 7. Diagnostic — Problèmes Persistants

### 7.1 PROBLÈME MAJEUR : 62% de concepts vides

Malgré la baisse du SINK (50%→27%), 37/60 concepts sont toujours vides. Les informations se concentrent sur un petit nombre de concepts :

| Concepts | Infos | % du total |
|----------|-------|-----------|
| Top 3 (Security Arch + Volume Enc + Compliance) | 54 | 45% |
| Top 5 | 65 | 55% |
| Reste (18 concepts peuplés) | 54 | 45% |
| **37 concepts vides** | **0** | **0%** |

**Causes identifiées :**
1. **`concepts[:30]`** — 31 concepts invisibles au linker (cause persistante depuis Run 1)
2. **Aspirateur dominant** — Tenant Isolation absorbe 62/135 liens provisoires, puis saturation → SINK au lieu de redistribution
3. **Concepts quasi-doublons** — 6× Compliance to X, 3× Tenant Isolation, 2× Patch Management dispersent les triggers
4. **GF-A activation_rate=0%** sur ~25 concepts — bonus lexical réduit → jamais sélectionnés

### 7.2 PROBLÈME : Pass 2 crash (JSON parse)

```
Parse JSON échoué: Expecting value: line 1 column 1 (char 0)
0 relations extraites (0 filtrées par garde-fou)
```

Le LLM retourne une réponse vide ou non-JSON pour l'extraction de relations. Besoin d'investiguer le prompt Pass 2 et la réponse LLM.

### 7.3 AMÉLIORATION : Calibration auto fonctionnelle

Le correctif `min_score_spread: 0.03` a débloqué l'auto-calibration :
- Run 1 : spread=0.050 → **fallback** (seuil exact 0.05, floating point edge case)
- Run 2 : spread=0.084 → **auto** (> 0.03)

Les seuils auto sont plus nuancés que le fallback et permettent une meilleure discrimination.

### 7.4 Toxicité des triggers

```
[OSMOSE:Rerank:Toxicity] 1 triggers toxiques (>8%): {'sap': 0.2804}
```

Le trigger "sap" apparaît dans 28% des assertions — toxique. Bien détecté et neutralisé.

---

## 8. Plan de Correctifs V2 — Priorités

### 8.1 CRITIQUE — Supprimer la limite `concepts[:30]`

**Fichier :** `assertion_extractor.py:888`
**Impact :** 31/61 concepts invisibles au linker

**Options :**
- (A) Supprimer `[:30]` → 61 concepts (~3K tokens) + assertions → faisable dans 16K context
- (B) TF-IDF par batch → top-40 concepts pertinents par assertion group
- (C) Multi-passes : 2 batches de 30, merger des liens

**Recommandation :** Option A si ≤70 concepts. Option C si >70 concepts.

### 8.2 CRITIQUE — Redistribution post-saturation

**Fichier :** `assertion_extractor.py` — `_apply_margin_and_topk()`
**Impact :** ~20-30 assertions perdues (score pénalisé < band1 sans alternative)

Quand le top-1 est saturé ET score < band1 :
1. Chercher 2nd best concept NON-saturé parmi les multi-liens
2. Si score 2nd ≥ band1 → promouvoir vers 2nd
3. Sinon → accepter le 1st malgré saturation (tag `SATURATED_ACCEPTED`)
4. SINK uniquement si AUCUN candidat n'a score brut ≥ band1

### 8.3 HAUTE — Fusion des quasi-doublons conceptuels

6× "Compliance to X", 3× Tenant Isolation variants, 2× Patch Management → fusionner en concepts uniques pour concentrer les triggers.

### 8.4 HAUTE — Investiguer policy_rejected (213 = 53%)

Plus de la moitié des assertions sont rejetées avant le linking. Besoin d'analyser les critères de rejet et potentiellement les assouplir.

### 8.5 MOYENNE — Bonus CENTRAL inconditionnel

Concepts CENTRAL avec activation_rate=0% → jamais sélectionnés. Ajouter un bonus inconditionnel de +5%.

### 8.6 BASSE — Fix Pass 2 JSON parse

Le LLM retourne du non-JSON en Pass 2. Besoin de retry avec structured output ou fallback regex.

---

## 9. Données Brutes pour ChatGPT

### 9.1 Résumé Exécutif

```
Run 2 post-correctifs (rebuild container + min_score_spread 0.03):
- SINK: 27% (✅ vs 50% en Run 1)
- Calibration: AUTO (✅ vs FALLBACK en Run 1)
- Concepts vides: 62% (❌ — marginal vs 67% en Run 1)
- Max aspirateur: Security Architecture 29/119 = 24% (⚠️)
- Policy rejected: 213/402 = 53% (⚠️ — n'atteignent jamais le linking)
- Abstained: 70/402 = 17% (54 no_concept + 16 cross_docitem)
- Pass 2: CRASH (JSON parse error → 0 relations)
```

### 9.2 Distribution complète status × reason

```
PROMOTED       | promoted                       | 119  (30%)
REJECTED       | policy_rejected                | 213  (53%)
ABSTAINED      | no_concept_match               |  54  (13%)
ABSTAINED      | cross_docitem                  |  16  (4%)
Total                                           | 402  (100%)
```

### 9.3 Pipeline des assertions (entonnoir)

```
6743 DocItems (cache Docling)
  → 1697 DocItems indexés (texts=1691, tables=9)  [UnitIndexer]
  → 2091 unités d'extraction  [Pass 1.3 POINTER]
  → 402 assertions extraites
      → 213 REJECTED (53%) — policy_rejected
      → 189 assertions envoyées au linking
          → 135 assertions calibrées (N dans calibration)
          → 54 ABSTAINED no_concept_match
          → 16 ABSTAINED cross_docitem
          → 119 PROMOTED (dont 32 SINK = 27%)
              → 87 informations métier (23 concepts)
              → 32 informations SINK
```

### 9.4 Top aspirateurs (provisoire → final)

| Concept | Provisoire | Saturation | Final |
|---------|-----------|------------|-------|
| Tenant Isolation | **62** (46%) | Phase3 penalty=0.60 | **0** (100% vers SINK) |
| Surveillance audits | **17** (13%) | Phase2 penalty=0.78 | **0** (⚠️ vide) |
| Security Architecture | ? | Phase1? penalty≈0.85? | **29** (24%) |
| Volume Encryption | ? | — | **17** (14%) |

### 9.5 Concepts vides les plus "choquants"

1. **SAP Cloud ERP Private deployment (CENTRAL)** — le concept central du document = 0 infos
2. **Tenant Isolation** — aspirait 62 provisoires → 0 finales (tout SINK'd)
3. **Patch Management and Upgrades** — thème majeur du document = 0 infos
4. **Shared security responsibility** — thème récurrent = 0 infos
5. **SAP Global Security (SGS)** — entité clé = 0 infos
6. **Surveillance audits** — aspirait 17 provisoires → 0 finales
7. **SOC1 and SOC2 audits** — certification majeure = 0 infos

### 9.6 Questions pour ChatGPT (V2 — post Run 2)

1. **Le SINK est corrigé (27%) mais les concepts vides persistent (62%).** L'auto-calibration a résolu le routing massif vers SINK, mais le problème de fond est que les assertions ne sont liées qu'à ~23 concepts sur 60. La cause `concepts[:30]` est-elle suffisante pour expliquer ça, ou y a-t-il un problème plus profond dans la granularité/qualité des concepts identifiés ?

2. **213 rejections policy_rejected (53%)** — Plus de la moitié des assertions n'atteignent jamais le linking. Est-ce normal ? Faut-il investiguer les critères de rejet pour les assouplir ?

3. **Tenant Isolation → 62 provisoires → 0 finales.** La saturation pénalise correctement l'aspirateur, mais au lieu de redistribuer vers d'autres concepts, tout part en SINK. La redistribution post-saturation résoudrait-elle aussi le problème des concepts vides ?

4. **Pass 2 crash (JSON parse)** — 0 relations extraites. Priorité basse ou bloquant ?

5. **Séquençage V2 :**
   1. Fix `concepts[:30]` → tous les concepts visibles
   2. Redistribution post-saturation → concepts vides peuplés
   3. Investiguer policy_rejected 53% → plus d'assertions dans le pipeline
   4. Fix Pass 2 JSON → relations entre concepts
   5. Fusion quasi-doublons conceptuels → meilleure granularité

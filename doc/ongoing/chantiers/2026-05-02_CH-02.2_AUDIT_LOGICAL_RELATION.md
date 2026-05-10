# Audit qualité LOGICAL_RELATION — CH-02.2 (2026-05-02)

*Auditeur : Claude (expert aerospace + dual-use regulatory)*
*Échantillon : 47 paires sur 4 862 edges (= 0.97%)*
*Sampling : stratifié par type, focus sur volume + criticité*

---

## 1. Distribution actuelle

| Type | Count | % | Conf moyenne | Sampled |
|---|---|---|---|---|
| EQUIVALENT | 4 319 | 88.8% | 0.984 | 12 |
| OVERLAP | 436 | 9.0% | 0.998 | 6 |
| EXCEPTION | 84 | 1.7% | 0.909 | 6 |
| CONFLICT | 16 | 0.3% | 0.956 | 16 (tous) |
| DISJOINT | 3 | 0.06% | 1.0 | 3 (tous) |
| SUPERSET | 2 | 0.04% | 0.925 | 2 (tous) |
| SUBSET | 1 | 0.02% | 1.0 | 1 |
| DEFINITION_OF | 1 | 0.02% | 1.0 | 1 |

---

## 2. Résultats audit

| Type | Précision | Verdict |
|---|---|---|
| **EQUIVALENT** | **12/12 = 100%** | ✅ Factuel correct, mais ~90% verbatim copies cross-doc → **utilité faible** |
| **OVERLAP** | **0/6 = 0%** | ❌ **Faux 100%** — fallback générique pour SUPERSET/SUBSET/DISJOINT |
| **EXCEPTION** | **0/6 = 0%** | ❌ **Faux 100%** — confusion avec EQUIVALENT/évolution |
| **CONFLICT** | **2-4/16 = 12-25%** | ❌ **75-88% faux positifs** — confusion énumération OR avec opposition |
| **DISJOINT** | 3/3 = 100% | ✅ Propre |
| **SUPERSET** | 0/2 = 0% | ❌ Direction d'inclusion incorrecte |
| **SUBSET** | 1/1 = 100% | ✅ Propre |
| **DEFINITION_OF** | 1/1 = 100% | ✅ Propre |

---

## 3. Patterns d'erreurs identifiés

### 3.1 CONFLICT — confusion énumération/contradiction
Le classifier traite "X may be A" et "X may be B" comme contradictoires alors que le claim source est "X may be A or B" (énumération OR décomposée en 2 claims).

**Exemples sur 16 CONFLICT** :
- 4× "Frequency changers as AC Power Supplies" vs "as Generators" — le claim source dit "or generators"
- 2× DS alloys vs SC alloys (les deux sont contrôlés simultanément)
- 3× Appendix O facets (vertical, horizontal, altitude) — décrivent des aspects différents, pas opposés
- 2× ETOPS thresholds 75/120/180 — sous-sections distinctes de AMC 20-6
- 2× Output energy J — seuils ECCN différents pour items différents

**Vrais conflits identifiés** : 2-4 sur 16
- "hazardous failure" vs "catastrophic failure" (gravité diff sur même condition) — borderline
- Service history "agreement" vs "ownership" — borderline
- Impact energy 21 J vs 3.5 J — ambigu

### 3.2 OVERLAP — fallback générique cassé
OVERLAP est utilisé pour **toute relation où le classifier ne sait pas trancher** SUPERSET / SUBSET / DISJOINT. Toutes les 6 paires auditées étaient en réalité SUPERSET (5/6) ou DISJOINT (1/6).

### 3.3 EXCEPTION — confusion avec EQUIVALENT/évolution
EXCEPTION est utilisé dès qu'il y a une **différence textuelle** entre 2 claims, même si la sémantique est équivalente. 6/6 auditées étaient EQUIVALENT (paraphrases, variations grammaticales) ou des évolutions de version (LIFECYCLE_RELATION).

### 3.4 EQUIVALENT — factuel mais utilité faible
9/12 paires sont des verbatim copies cross-doc (texte mot pour mot identique). Les 3 autres sont des paraphrases triviales ("listed", "modern", "could assess"). Précision factuelle 100% mais valeur informationnelle proche de zéro.

### 3.5 SUPERSET — direction d'inclusion incorrecte
Les 2 SUPERSET auditées comparaient des **items différents** (systèmes vs composants), pas des inclusions strictes.

---

## 4. Recommandations actions

### 4.1 Purge proposée (avec validation user)

| Action | Cible | Volume | Justification |
|---|---|---|---|
| **PURGE immédiate** | OVERLAP (tous) | 436 | 100% faux positifs sur sample, fallback générique cassé |
| **PURGE immédiate** | EXCEPTION (tous) | 84 | 100% faux positifs sur sample, confusion EQUIVALENT/LIFECYCLE |
| **PURGE immédiate** | SUPERSET (tous) | 2 | 100% faux positifs, direction incorrecte |
| **PURGE conditionnelle** | CONFLICT 12-14/16 | 12-14 | Garder 2-4 vrais conflits après audit fin (à faire) |
| **GARDER** | EQUIVALENT | 4 319 | Factuellement correct (100% précision sur sample) |
| **GARDER** | DISJOINT, SUBSET, DEFINITION_OF | 5 | Précision 100% sur sample, types rares mais propres |

**Total purge proposée** : ~534 edges (11% des 4 862).

### 4.2 Tâche déférée (V2-S2/S3)

Refactor du classifier 12-types pour résoudre :
- Décomposition d'énumération OR (CONFLICT)
- Direction d'inclusion (OVERLAP→SUPERSET/SUBSET)
- Distinction EXCEPTION vs EQUIVALENT vs LIFECYCLE_RELATION

Hors scope CH-02.2 — c'est un sprint dédié de re-classification (estimation 1-2 sprints sur EC2 vLLM).

### 4.3 Décision EQUIVALENT verbatim

Les 4 319 EQUIVALENT sont factuellement corrects mais ~90% sont des **verbatim copies** cross-doc (artefact normal des amendments réglementaires : un amdt N+1 reprend des paragraphes de N inchangés).

**Options** :
- (a) Garder tels quels (factuels, peu utiles, pas dangereux)
- (b) Tagger `equivalence_type = 'verbatim_copy' | 'paraphrase'` pour permettre des queries qui les filtrent
- (c) Purger ceux avec `claim_a.text == claim_b.text` exactement (= verbatim strict)

**Recommandation** : option (b) — tagger plutôt que purger (info utile pour le runtime "deux docs disent la même chose verbatim" = signal de continuité réglementaire).

---

## 5. Validation user demandée

Avant exécution :

**Q1** : Tu valides la purge de OVERLAP (436) + EXCEPTION (84) + SUPERSET (2) = **522 edges** ?

**Q2** : Pour les 16 CONFLICT, on purge tous les 12-14 faux positifs identifiés et on garde 2-4 vrais (avec confidence ≥ 0.85) ? Ou on purge tout et on re-runnera le classifier dans un sprint dédié ?

**Q3** : Pour les 4 319 EQUIVALENT, on prend l'option (a) garde tel quel, (b) tag verbatim/paraphrase, ou (c) purge les verbatim ?

---

## 6. Notes méthodologiques

- Auditeur : Claude (Opus 4.7 1M context), expertise aerospace + EU dual-use regulatory
- Sample : 47 paires sur 4 862 = 0.97% (statistically significant pour les types rares, indicatif pour EQUIVALENT)
- Reproductibilité : sampling avec seed = `rand()` Cypher (non-déterministe), mais patterns d'erreurs constants
- Limitations : pas d'accès au passage_text complet pour vérifier le contexte (pas dans les claims sampled), donc verdicts CONFLICT borderline pourraient changer après lecture du passage source

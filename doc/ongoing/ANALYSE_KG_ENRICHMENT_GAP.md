# Analyse — Gap d'enrichissement KG en mode DIRECT

**Date** : 4 avril 2026
**Statut** : Probleme identifie, pistes a valider
**Priorite** : HAUTE — affecte directement la valeur differenciante d'OSMOSIS
**Contexte** : Suite a l'implementation de l'architecture V3 Response Modes

---

## 1. Situation

L'architecture V3 a resolu le probleme de pollution KG : le mode DIRECT (RAG pur, zero KG dans le prompt) produit des reponses correctes sur les questions simples. Le benchmark montre une amelioration significative (+9.4pp score global, +36pp sur both_sides_surfaced).

Cependant, un nouveau probleme emerge : **le KG detecte des contradictions importantes mais ne peut pas les surfacer en mode DIRECT.**

---

## 2. Le probleme demontre par des tests

### Test 1 : JIT control cycle Reschedule

**Question** : "Qu'est-ce qui declenche le Reschedule dans le JIT control cycle ?"

**Ce que le KG sait** (contradiction cross-doc, confidence 0.95) :
- Doc 025 (Feature Scope 2023) : "changes to the **safety time**" declenchent le Reschedule
- Doc 024 (Cloud Private Edition FSD) : "changes to the **transfer time**" declenchent le Reschedule

**Ce que le RAG retourne** : aucun chunk pertinent (les deux docs ne sont pas remontes)

**Reponse OSMOSIS (mode DIRECT)** : "Les sources disponibles ne contiennent pas d'information specifique"

**Resultat** : le KG possede la reponse exacte (avec la contradiction) mais OSMOSIS dit "pas d'info".

### Test 2 : Direction des dialog calls AR/Collections

**Question** : "Dans quel sens les dialog calls s'effectuent-ils entre Accounts Receivable et Collections Management ?"

**Ce que le KG sait** (contradiction cross-doc, confidence 0.95) :
- Doc 027 (Security Guide 2023) : "from the **Accounts Receivable** system to the Collections Management system"
- Doc 028 (Security Guide 2022) : "from the **Collections Management** system to the Accounts Receivable system"

**Ce que le RAG retourne** : uniquement des chunks du doc 027 (2023)

**Reponse OSMOSIS (mode DIRECT)** : "bidirectionnel" — repond avec le doc 2023 seulement, ne mentionne pas que le doc 2022 dit l'inverse

**Resultat** : le RAG donne une reponse incomplete. Le KG sait que l'autre version contredit mais ne l'injecte pas.

### Test 3 : Authorization object S_Program report

**Question** : "Sur quel rapport est base l'authorization object S_Program ?"

**Ce que le KG sait** (contradiction cross-doc, confidence 0.95) :
- Doc 028 (Security Guide 2022) : rapport **RPCIPD00**
- Doc 027 (Security Guide 2023) : rapport **RPCIPS00**

**Ce que le RAG retourne** : uniquement des chunks du doc 027 (2023)

**Reponse attendue** : "RPCIPS00 (2023), mais attention, c'etait RPCIPD00 dans la version 2022"

---

## 3. Cause racine

L'architecture V3 classifie les questions par **intention de l'utilisateur** :
- Question factuelle simple → mode DIRECT → zero KG dans le prompt
- Question demandant une comparaison → mode TENSION → template contradictions

Le probleme : **l'utilisateur ne sait pas qu'il devrait demander une comparaison.** Il pose une question factuelle ("quel rapport ?") et attend UNE reponse. Il ne sait pas que deux versions de la documentation se contredisent.

C'est exactement le differenciateur d'OSMOSIS : **detecter ce que l'utilisateur ne sait pas qu'il devrait demander.**

### Le dilemme architectural

```
Question factuelle simple
    |
    v
Classificateur → DIRECT (correct : la question est simple)
    |
    v
Mode DIRECT → graph_context_text = "" (zero KG)
    |
    v
LLM repond avec les chunks RAG seuls
    |
    v
PROBLEME : le KG sait qu'il y a une contradiction
           mais n'a aucun moyen de l'exprimer
```

Le mode DIRECT protege contre la pollution (resolu) mais empeche aussi le KG d'enrichir (nouveau probleme).

---

## 4. Ce que le KG devrait faire

Le KG ne devrait pas injecter du texte narratif (cause de pollution, deja prouve). Mais il devrait pouvoir :

### 4.1 Forcer l'inclusion de chunks du document contradictoire

Si le KG detecte une contradiction forte (confidence >= 0.85) entre un document present dans les chunks RAG et un document absent :

```
RAG retourne : chunks du doc 027 (2023)
KG detecte : doc 028 (2022) contredit doc 027 sur ce sujet
Action : ajouter les chunks pertinents du doc 028 aux chunks RAG
```

Le LLM voit alors les deux cotes sans texte KG narratif — juste des chunks de documents. Il peut naturellement presenter les deux positions.

### 4.2 Reclassifier le mode de reponse

Si le KG detecte une contradiction forte sur une question classee DIRECT :

```
Classificateur → DIRECT (intent utilisateur = factuel)
KG signal → contradiction forte sur le sujet (confidence >= 0.85)
Reclassification → TENSION (le KG promouvoit le mode)
```

La question reste la meme mais le mode de reponse change car le KG a des preuves que la reponse simple serait trompeuse.

### 4.3 Ajouter une Insight Card sans modifier la reponse

Si la contradiction est moins forte ou si on veut etre conservateur :

```
Reponse DIRECT normale (RAG pur)
+ Insight Card : "⚠️ Le Security Guide 2022 indique une valeur differente (RPCIPD00 vs RPCIPS00)"
```

L'Insight Card ne modifie pas la reponse mais alerte l'utilisateur.

---

## 5. Les 3 pistes

### Piste A : KG-driven doc injection (enrichissement retrieval)

**Principe** : le KG force l'ajout de chunks du document contradictoire dans le contexte RAG, AVANT la synthese. Le LLM ne sait pas que le KG a agi — il voit juste plus de chunks.

**Avantage** : zero texte KG narratif, le LLM decide naturellement de presenter les deux cotes
**Risque** : peut recreer le probleme de dilution (ajouter des chunks = plus de contexte = attention diluee)
**Garde-fou** : limiter a 2-3 chunks du doc contradictoire, uniquement si confidence >= 0.85

**Implementation** : modifier le mode DIRECT pour qu'il ne soit pas "zero KG" mais "zero texte KG + doc injection conditionnelle"

### Piste B : Reclassification KG → TENSION

**Principe** : le resolver 2 etages ajoute un 3e critere au-dela de "la question demande une tension" — "le KG detecte une tension forte que l'utilisateur devrait connaitre".

```python
# Etage A : intent utilisateur
if classifier says TENSION → candidate = TENSION

# Etage A-bis : KG override (NOUVEAU)
if candidate == DIRECT and KG has strong contradiction (>= 0.85):
    candidate = TENSION
    reason = "kg_promoted: strong contradiction detected"

# Etage B : validation par preuves (inchange)
if paired_evidence and kg_trust >= 0.4 → TENSION confirme
```

**Avantage** : reutilise le prompt TENSION existant (template Position A / Position B)
**Risque** : peut reclassifier trop de questions (retour au probleme initial si le seuil est trop bas)
**Garde-fou** : seuil tres conservateur (confidence >= 0.85 ET les deux docs sont identifies)

### Piste C : Hybride (A + Insight Card)

**Principe** : 
1. Toujours rester en mode DIRECT pour la reponse principale
2. Injecter les chunks du doc contradictoire (piste A)
3. Si le LLM ne mentionne pas la contradiction → ajouter une Insight Card

**Avantage** : la reponse est toujours RAG-pure (pas de pollution), l'Insight Card est un filet de securite
**Risque** : complexite d'implementation (detection post-synthese + generation de card)
**Garde-fou** : l'Insight Card n'apparait que si la contradiction est forte ET non mentionnee dans la reponse

---

## 6. Donnees disponibles pour chaque piste

### Ce qui existe deja dans le code

| Brique | Fichier | Utilisable pour |
|---|---|---|
| `_search_claims_vector()` | search.py:152 | Detecte les claims avec tensions |
| `contradiction_envelope` | search.py:1115 | Identifie les paires contradictoires |
| `_retrieve_chunks(doc_filter=...)` | retriever.py:57 | Recupere des chunks d'un doc specifique |
| `tension_doc_ids` | signal_policy.py:29 | Doc IDs des documents en tension |
| `fetch_missing_tension_docs` | signal_policy.py:28 | Flag pour chercher les docs manquants |
| KG doc scoping | search.py:845-884 | Ajoute des chunks de docs en tension |

**Le mecanisme de doc injection existe deja** (lignes 845-884 de search.py) — il est actuellement skip en mode DIRECT. Il suffirait de le reactiver de maniere ciblee.

### Ce qui n'existe pas encore

| Besoin | Pour quelle piste |
|---|---|
| Seuil de confidence sur les contradictions KG | A, B, C |
| Verification que le doc contradictoire est ABSENT du RAG | A, B |
| Reclassification de mode post-signal | B |
| Generation d'Insight Card post-synthese | C |
| Validation que la contradiction est mentionnee dans la reponse | C |

---

## 7. Questions pour ChatGPT

1. **Piste A vs B vs C** : laquelle est la plus robuste dans l'esprit "KG = control plane" de l'ADR V3 ? La piste A (doc injection) est la plus simple mais elle agit "en silence" — l'utilisateur ne sait pas pourquoi il voit des chunks de 2 docs differents. La piste B (reclassification) est plus explicite mais risque de recreer la sur-activation. La piste C est la plus complete mais la plus complexe.

2. **Le seuil** : a partir de quelle confidence de contradiction le KG devrait-il overrider le mode DIRECT ? 0.85 est-il trop conservateur (rate des contradictions utiles) ou trop permissif (sur-active) ?

3. **Le paradigme** : est-ce qu'on est en train de revenir a "le KG influence la reponse" (ce qu'on voulait eviter) ou est-ce que c'est fondamentalement different car le KG agit via les chunks (piste A) et non via du texte narratif ?

4. **La generalisation** : si on implemente la piste A (doc injection pour contradictions fortes), est-ce que le meme mecanisme pourrait servir pour les evolutions temporelles ? (ex: "la valeur etait X en 2022, elle est Y en 2023")

5. **Le risque de regression** : si on re-active le KG doc scoping en mode DIRECT, comment s'assurer qu'on ne retombe pas dans le probleme de pollution ? Le doc scoping existant (lignes 845-884) ajoutait des chunks qui diluaient le contexte.

---

## 8. Contrainte cle

> **Le KG ne doit pas parler au LLM. Il contraint ce que le LLM a le droit de voir.**

La piste A respecte ce principe : le KG ne met aucun texte dans le prompt. Il selectionne des chunks de documents (des preuves) que le LLM voit comme du contenu RAG ordinaire. Le LLM ne sait pas que le KG a agi.

La piste B aussi : le KG change le mode, pas le contenu. Le prompt TENSION structure la reponse.

La piste C combine les deux avec un filet de securite UI.

---

## 9. Impact attendu

Si on resout ce gap :
- La question "quel rapport pour S_Program" donnerait : "RPCIPS00 (2023), mais le guide 2022 indiquait RPCIPD00"
- La question "direction des dialog calls" donnerait : "AR→Collections (2023), mais le guide 2022 indiquait l'inverse"
- La proactive_detection du benchmark serait reellement differenciante (pas juste cosmetique)
- Le differenciateur OSMOSIS serait demontre sur des cas concrets ou le RAG seul est trompe

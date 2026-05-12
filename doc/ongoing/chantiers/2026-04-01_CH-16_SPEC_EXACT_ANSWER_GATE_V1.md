# Specification — Exact Answer Gate V1

**Date** : 1er avril 2026
**Statut** : Draft pour validation multi-IA
**Objectif** : Implementer un mecanisme de rejet pre-LLM pour les questions dont la reponse n'existe pas dans le corpus, sans degrader les reponses aux questions ou l'information est disponible.

---

## 1. Contexte et contraintes

### Probleme mesure
- unanswerable = 10% (hallucine 7/8)
- Prompt tuning (V3) monte a 40% mais degrade false_premise (-18pp), conditional (-13pp)
- Le LLM ne sait pas dire "je ne sais pas" → il faut une decision **avant** le LLM

### Contraintes non negociables
- **Domain-agnostic** (INV-6) : aucune regle specifique a SAP, medical, juridique ou tout autre domaine
- **Pas de regex pour le langage naturel** : les regex sont adaptees aux formats normes (email, URL) mais pas au langage libre multilingue
- **Pas de LLM supplementaire** : le gate doit etre rapide et deterministe, pas un second appel LLM
- **Multilingue** : les questions peuvent etre en francais, anglais, ou mixte
- **Faux negatif minimal** : mieux vaut laisser passer une question unanswerable que bloquer une question answerable

### Perimetre V1 — volontairement restreint
On ne traite que les questions a **reponse structuree attendue** ou le hard reject est sur :
- EXACT_NUMERIC : prix, cout, nombre, statistique, pourcentage
- EXACT_IDENTIFIER : code, transaction, reference, identifiant technique
- VERSION_DATE : version precise, date precise

Les questions ouvertes (pourquoi, comment, synthese, comparaison) ne sont PAS filtrees par le gate.

---

## 2. Architecture

```
Question utilisateur
        │
        ▼
┌─────────────────────┐
│ 1. Question Classifier │  ← classify(question) → family + confidence
│    (NLP leger, pas LLM) │
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ 2. Retriever (existant) │  ← chunks + claims + scores
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ 3. Answer Form Detector │  ← les chunks contiennent-ils une forme
│    (NER + heuristiques)  │     de reponse compatible ?
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ 4. Gate Decision        │  ← ANSWERABLE / UNANSWERABLE / UNCERTAIN
└─────────────────────┘
        │
        ├── ANSWERABLE → LLM synthese (pipeline normal)
        ├── UNCERTAIN → LLM synthese + flag "partial_coverage"
        └── UNANSWERABLE → reponse deterministe (pas de LLM)
```

Le gate s'insere entre le retriever et la synthese LLM dans `search.py`. Il ne modifie pas le retrieval.

---

## 3. Composant 1 — Question Classifier

### Role
Determiner la **famille de reponse attendue** par la question.

### Familles V1

| Famille | Description | Exemples de questions |
|---|---|---|
| EXACT_NUMERIC | La reponse attendue est un nombre, un montant, une statistique, un pourcentage | "Combien coute...", "Quel est le prix...", "Combien de clients...", "Quel pourcentage...", "Quelle est la duree moyenne..." |
| EXACT_IDENTIFIER | La reponse attendue est un code, un nom technique, une reference precise | "Quel code transaction...", "Quelle SAP Note...", "Quel objet d'autorisation...", "Quel nom de rapport..." |
| VERSION_DATE | La reponse attendue est une version precise ou une date | "Depuis quelle version...", "A quelle date...", "Quel prerequis version..." |
| OPEN | La reponse est explicative, comparative, synthese, liste ouverte | "Comment fonctionne...", "Pourquoi...", "Quelles sont les differences...", "Decrivez..." |

### Approche de classification — PAS de regex

**Option A — Classification par embeddings de prototypes (recommandee)**

Creer un petit ensemble de prototypes (10-20 phrases) par famille. A la reception d'une question, calculer la similarite embedding avec chaque prototype. La famille dont les prototypes sont les plus proches gagne.

Exemple de prototypes EXACT_NUMERIC :
```
"Quel est le prix de ce produit ?"
"Combien coute la licence annuelle ?"
"Quel est le nombre total d'utilisateurs ?"
"Combien de temps prend le processus ?"
"Quel pourcentage de clients utilise cette fonctionnalite ?"
"Quelle est la duree moyenne de migration ?"
"How much does the license cost?"
"How many users are there?"
```

Exemple de prototypes EXACT_IDENTIFIER :
```
"Quel est le code transaction pour cette operation ?"
"Quelle note SAP decrit cette restriction ?"
"Quel objet d'autorisation controle cet acces ?"
"Quel est le nom du rapport a executer ?"
"Quel parametre de configuration faut-il modifier ?"
"What authorization object is required?"
"Which transaction code should I use?"
```

Avantages :
- Domain-agnostic : les prototypes ne contiennent pas de termes metier
- Multilingue : on peut ajouter des prototypes FR + EN
- Pas de regex : la similarite embedding capture le sens, pas la forme
- Extensible : ajouter un prototype = une ligne
- On utilise deja e5-large pour les embeddings (pas de nouveau modele)

Inconvenient :
- Necessite un calcul d'embedding par question (mais c'est deja fait pour le retrieval)
- Les prototypes doivent etre bien choisis (garbage in = garbage out)

**Option B — Classification par mots-cles ponderes (alternative simple)**

Si l'approche embedding est trop lourde, une alternative plus simple :

Definir des "signal words" par famille avec des poids :
```
EXACT_NUMERIC_SIGNALS = {
    "combien": 0.8, "cout": 0.9, "prix": 0.9, "tarif": 0.9,
    "nombre": 0.7, "pourcentage": 0.8, "duree": 0.6,
    "how much": 0.9, "how many": 0.8, "cost": 0.9, "price": 0.9,
    "average": 0.5, "total": 0.5, "percentage": 0.8,
}
```

Score = somme des poids des signal words trouves dans la question.
Si score > seuil → famille classifiee.

Avantages : ultra rapide, pas de modele
Inconvenients : plus fragile que les embeddings, depend du vocabulaire

**Decision recommandee** : Option A (embeddings de prototypes) car plus robuste et deja compatible avec l'infra existante. Option B en fallback si performance insuffisante.

### Cas limites et decisions

| Question | Classification correcte | Piege potentiel |
|---|---|---|
| "Quel est le cout de licence ?" | EXACT_NUMERIC | Aucun — cas clair |
| "Combien de modules supportent SSO ?" | EXACT_NUMERIC | Mais la reponse est peut-etre dans les chunks sous forme d'enumeration, pas de nombre |
| "Quelle transaction utiliser pour monitorer les RFC ?" | EXACT_IDENTIFIER | Aucun — cas clair |
| "Quel est l'objet d'autorisation pour Credit Management ?" | EXACT_IDENTIFIER | Aucun — cas clair |
| "Comment fonctionne le cout de licence ?" | OPEN (pas EXACT_NUMERIC) | Le mot "cout" est present mais la question est explicative |
| "Pourquoi le code transaction SM59 est-il important ?" | OPEN (pas EXACT_IDENTIFIER) | Le code est mentionne mais la question est causale |
| "Quels sont les prerequis pour S/4HANA 2023 ?" | OPEN | Pas une version precise demandee — c'est une question de liste |
| "Depuis quelle version SNC est-il supporte ?" | VERSION_DATE | Cas clair |

**Regle d'or** : En cas de doute, classifier comme OPEN (pas de hard reject).

---

## 4. Composant 2 — Answer Form Detector

### Role
Determiner si les chunks recuperes contiennent une **forme de reponse compatible** avec la famille identifiee.

### Approche — NER (Named Entity Recognition) avec spaCy

spaCy est un outil NLP eprouve, multilingue, qui detecte automatiquement :
- CARDINAL : nombres (42, 1.5 million, trois)
- MONEY : montants monetaires ($100, 50 EUR)
- DATE : dates (2023, january, 15 mars)
- PERCENT : pourcentages (15%, 0.5%)
- ORG/PRODUCT : noms de produits/organisations
- Et des entites custom si necessaire

**Pas de regex** — spaCy utilise des modeles statistiques entraines sur du texte reel.

### Mapping famille → entites recherchees

| Famille question | Entites spaCy recherchees dans les chunks | Condition de match |
|---|---|---|
| EXACT_NUMERIC | CARDINAL, MONEY, PERCENT, QUANTITY | Au moins 1 entite numerique dans les top 5 chunks |
| EXACT_IDENTIFIER | Tokens alphanumeriques en MAJUSCULES, patterns `X_Y_Z`, codes entre guillemets | Au moins 1 identifiant technique dans les top 5 chunks |
| VERSION_DATE | DATE, patterns version (X.Y, vX, YYYY) | Au moins 1 date/version dans les top 5 chunks |

### Detection d'identifiants techniques (sans regex metier)

Pour EXACT_IDENTIFIER, on ne cherche pas des patterns SAP-specifiques. On cherche des **formes universelles** d'identifiants techniques :
- Tokens contenant un underscore : `F_UKM_SGMT`, `S_APPL_LOG`
- Tokens en MAJUSCULES de 3+ caracteres : `SNC`, `RFC`, `SSO`, `SAML`
- Tokens alphanumeriques mixtes : `SM59`, `SFW5`, `RPCIPS00`
- Tokens entre guillemets ou backticks dans le texte source

spaCy ne detecte pas nativement ces patterns, mais un **component custom spaCy** (ou un simple scan tokenise) peut les identifier sans regex complexe :

```python
def find_technical_identifiers(text: str) -> list[str]:
    """Trouve les identifiants techniques dans un texte (domain-agnostic)."""
    tokens = text.split()
    identifiers = []
    for token in tokens:
        clean = token.strip(".,;:()[]\"'")
        if len(clean) < 3:
            continue
        has_upper = any(c.isupper() for c in clean)
        has_special = "_" in clean or "/" in clean
        has_digit = any(c.isdigit() for c in clean)
        # Token avec underscore (ex: F_UKM_SGMT)
        if has_special and has_upper:
            identifiers.append(clean)
        # Token alphanumerique mixte en majuscules (ex: SM59, RPCIPS00)
        elif has_upper and has_digit and clean == clean.upper():
            identifiers.append(clean)
    return identifiers
```

Ce n'est pas une regex — c'est une analyse caractere par caractere des tokens. C'est domain-agnostic car les identifiants techniques ont une **forme universelle** (majuscules + chiffres + underscores) dans tous les domaines (medical, juridique, technique, finance).

### Cas limites

| Situation | Chunks | Decision |
|---|---|---|
| Q: "Quel est le cout ?" + chunks contiennent des nombres | CARDINAL trouve | ANSWERABLE (le LLM decidera si le nombre est pertinent) |
| Q: "Quel est le cout ?" + chunks = texte narratif sans aucun nombre | Aucun CARDINAL | UNANSWERABLE |
| Q: "Quel code transaction ?" + chunks contiennent SM59 | Identifiant trouve | ANSWERABLE |
| Q: "Quel code transaction ?" + chunks = descriptions fonctionnelles sans codes | Aucun identifiant | UNANSWERABLE |
| Q: "Combien de modules supportent SSO ?" + chunks listent 3 modules | CARDINAL "3" present | ANSWERABLE (meme si la reponse est implicite) |

---

## 5. Composant 3 — Gate Decision

### Logique de decision

```
SI question_family == OPEN:
    → ANSWERABLE (toujours, pas de gate)

SI question_family in [EXACT_NUMERIC, EXACT_IDENTIFIER, VERSION_DATE]:
    SI answer_forms_found >= 1:
        → ANSWERABLE (passer au LLM normalement)
    SI answer_forms_found == 0 ET max_chunk_score > 0.7:
        → UNCERTAIN (passer au LLM avec flag)
    SI answer_forms_found == 0 ET max_chunk_score <= 0.7:
        → UNANSWERABLE (court-circuiter le LLM)
```

### Le flag UNCERTAIN

Quand le gate est incertain (pas de forme de reponse trouvee mais chunks proches), on passe au LLM avec un signal leger dans le contexte :

"Note: The retrieved sources discuss this topic but may not contain the specific [number/identifier/version] asked about. If you cannot find the exact answer in the sources, say so."

C'est un signal, pas une regle agressive. Le LLM garde sa liberte.

### Comportement UNANSWERABLE

Quand le gate decide UNANSWERABLE, on ne genere PAS de reponse LLM. On retourne directement :

```json
{
  "synthesis": {
    "synthesized_answer": "Les documents disponibles ne contiennent pas [le chiffre/l'identifiant/la version] demandé(e). Le corpus couvre [thèmes des chunks les plus proches] mais pas [le type d'information spécifique demandé].",
    "gate_decision": "UNANSWERABLE",
    "gate_reason": "Question de type EXACT_NUMERIC, aucun candidat numérique trouvé dans les sources."
  },
  "confidence": 0.0
}
```

Le message est construit de maniere deterministe. Pas de LLM, pas d'hallucination possible.

---

## 6. Risques et mitigations

### Risque 1 — Faux negatif (refuse a tort)

**Scenario** : La reponse existe mais sous une forme que le detector ne reconnait pas.
Exemple : "Combien de modules supportent SSO ?" → la reponse est "SAP E-Recruiting, CA-TS, ISF" (une liste, pas un nombre). Le gate cherche un CARDINAL, ne le trouve pas, et refuse.

**Mitigation** :
- Le seuil UNCERTAIN (max_chunk_score > 0.7) rattrape ce cas : si les chunks sont tres pertinents, on laisse passer meme sans forme de reponse
- La classification devrait reconnaitre que "combien de modules" peut recevoir une reponse de type liste → OPEN plutot que EXACT_NUMERIC
- Regle d'or : **en cas de doute, ANSWERABLE**

**Mesure de controle** : Apres implementation, relancer le benchmark complet (robustesse + T2/T5 + RAGAS) et verifier qu'aucune categorie hors unanswerable n'a baisse.

### Risque 2 — Le gate masque un probleme de retrieval

**Scenario** : L'information existe dans le corpus mais le retriever ne l'a pas trouvee. Le gate dit UNANSWERABLE alors que c'est un probleme de retrieval.

**Mitigation** :
- Logger tous les cas UNANSWERABLE pour audit
- Inclure les scores de retrieval dans le log (si max_score est eleve mais aucune forme trouvee → cas suspect)
- Dashboard de monitoring des rejets (nombre de rejets/jour, taux par famille)

### Risque 3 — Le classifieur de questions se trompe

**Scenario** : "Comment fonctionne le pricing de SAP ?" est classifie EXACT_NUMERIC (a cause de "pricing") alors que c'est une question OPEN.

**Mitigation** :
- L'approche par embeddings de prototypes est plus robuste que les mots-cles car elle capture le sens global de la question
- Les prototypes EXACT_NUMERIC contiennent "Quel est le prix" pas "Comment fonctionne le prix"
- Ajouter un seuil de confiance : si le classifieur n'est pas sur (distance < marge), classifier comme OPEN

### Risque 4 — Dependance a spaCy

**Scenario** : spaCy n'est pas installe ou le modele de langue n'est pas disponible.

**Mitigation** :
- spaCy est une dependance stable et legere
- Fallback : si spaCy n'est pas disponible, le gate est desactive (tout passe au LLM, comportement actuel)
- Le gate est optionnel, jamais bloquant

---

## 7. Impact attendu

### Sur le benchmark robustesse

| Categorie | Avant (V2) | Apres gate (estimee) | Explication |
|---|---|---|---|
| unanswerable | 10% | **60-70%** | Les 6-7 questions de type EXACT sont rejetees par le gate |
| false_premise | 61% | **61%** | Pas impacte (questions OPEN) |
| conditional | 40% | **40%** | Pas impacte (questions OPEN) |
| causal_why | 60% | **60%** | Pas impacte (questions OPEN) |
| temporal | 57% | **57%** | Pas impacte (questions OPEN) |
| Autres | inchange | inchange | Le gate ne touche que unanswerable |

### Sur RAGAS

Le gate devrait ameliorer la faithfulness en empechant les hallucinations sur les questions factuelles precises. Impact estime : +2-3pp.

### Sur T2/T5

Aucun impact (les questions T2/T5 sont des questions OPEN sur les contradictions/tensions).

---

## 8. Implementation

### Dependances
- spaCy (modele `xx_ent_wiki_sm` ou `en_core_web_sm` + `fr_core_news_sm`)
- Embeddings e5-large (deja disponible)
- ~50 prototypes de questions (a creer)

### Fichiers a modifier
- `src/knowbase/api/services/search.py` : inserer le gate entre retrieval et synthese
- Nouveau : `src/knowbase/api/services/answer_gate.py` : classifieur + detector + decision

### Effort estime
- Classification par prototypes : 2-3h (creer les prototypes, coder le classifieur)
- Answer form detector (spaCy + identifiants) : 2-3h
- Integration dans search.py : 1h
- Tests + benchmark : 2h
- **Total : ~1 jour**

---

## 9. Questions pour validation

1. L'approche par embeddings de prototypes est-elle suffisamment robuste pour la classification de questions, ou faut-il un modele dedie ?
2. Le seuil UNCERTAIN (max_chunk_score > 0.7) est-il trop ou pas assez conservateur ?
3. Faut-il un mecanisme d'apprentissage des cas limites (les faux negatifs detectes enrichissent les prototypes) ?
4. spaCy est-il le bon outil pour la detection de formes de reponse, ou existe-t-il une alternative plus legere ?
5. Le scope V1 (3 familles + OPEN) est-il suffisant ou faut-il ajouter d'autres familles (CLOSED_BOOLEAN) ?

---

*Specification pour validation multi-IA. Implementation apres consensus.*

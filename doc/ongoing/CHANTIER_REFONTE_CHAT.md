# Chantier — Refonte complete de la page Chat

**Date** : 2 avril 2026
**Statut** : Diagnostic + vision — a implementer
**Priorite** : HAUTE — le chat est le point d'entree principal des utilisateurs

---

## 1. Diagnostic : pourquoi le chat actuel est mauvais

### Problemes identifies par l'utilisateur

**1. Score de confiance visible (62%) — fait peur**

Un score de 62% communique "il y a 40% de chances que ce soit faux". Aucun utilisateur n'acceptera ca. C'est un indicateur technique interne qui n'a rien a faire dans l'interface utilisateur. Meme a 85%, un score affiche cree du doute.

Comparaison : ChatGPT ne montre jamais un score de confiance. Google ne montre pas un "score de pertinence" sur ses resultats. L'utilisateur veut une reponse, pas une probabilite.

**2. Bloc "verite documentaire" — incomprehensible et redondant**

- "4 fragiles" — fragiles quoi ? Claims ? Chunks ? L'utilisateur ne comprend pas le vocabulaire interne.
- Le bloc reprend les memes informations que la reponse principale mais en plus condense et technique.
- Le "point resolu" mentionne n'a pas d'interet pour l'utilisateur.
- Ce bloc donne l'impression d'un debug panel, pas d'une fonctionnalite produit.

**3. Le KG n'est pas mis en valeur quand il apporte quelque chose**

Quand le KG detecte des tensions, des evolutions ou des complements cross-doc, ca ne se voit pas. L'utilisateur ne sait pas que OSMOSIS a fait quelque chose de different d'un RAG classique. Le differenciateur est invisible.

**4. La reponse prend trop de place et est mal organisee**

- Trop de blocs empiles (reponse + verite documentaire + sources)
- Pas de hierarchie visuelle claire
- Les sources sont un bloc separe au lieu d'etre integrees dans le texte

**5. Aucune difference visible avec ChatGPT/Gemini**

Un utilisateur qui pose la meme question sur ChatGPT et sur OSMOSIS ne verra pas pourquoi OSMOSIS est meilleur. La page chat ne communique aucune valeur ajoutee.

### Problemes identifies par l'analyse technique

**6. Les sources ne sont pas cliquables/navigables**

Les noms de sources sont des identifiants bruts ("027_SAP_S4HANA_2023_Security_Guide_c160af0e") au lieu de noms lisibles ("Security Guide 2023"). Pas de lien vers le document ou la page specifique.

**7. Pas de distinction entre ce qui vient du RAG et ce qui vient du KG**

La reponse melange les informations des chunks Qdrant et les signaux du KG sans indiquer leur origine. L'utilisateur ne sait pas quelle partie est "basique" (RAG) et quelle partie est "valeur ajoutee" (KG cross-doc).

**8. Les insights proactifs ne sont pas exploites**

Le backend genere des `insight_hints` (contradictions detectees, concepts structurants, coverage gaps) mais ils sont soit invisibles soit mal presentes dans le frontend. Ce sont pourtant les differenciateurs les plus forts.

**9. Le mode "assertion-centric" n'est pas utilise**

Il existe un mode `use_instrumented` qui genere des reponses structurees en assertions avec statuts de verite. C'est exactement ce qu'il faudrait pour montrer la valeur du KG, mais il n'est pas active par defaut.

**10. Pas de contextualisation temporelle**

Quand la reponse mentionne des informations de documents de differentes annees (2021, 2022, 2023), il n'y a pas d'indication visuelle de la fraicheur. L'utilisateur ne sait pas si l'info vient du guide le plus recent ou d'une version obsolete.

**11. Le chat ne guide pas l'utilisateur**

Pas de suggestions de questions. Pas d'indication du type "le corpus couvre X, Y, Z". L'utilisateur arrive sur une page vide et ne sait pas quoi demander ni ce que le systeme sait faire.

**12. Pas d'indicateur de ce que le systeme ne sait PAS**

Quand la reponse est basee sur des chunks peu pertinents (haute entropie, faible score), il n'y a aucun signal visuel. L'utilisateur ne sait pas s'il doit faire confiance ou non.

---

## 2. Vision cible

### Principe directeur

> Le chat doit ressembler a une conversation avec un expert du domaine qui a lu toute la documentation, pas a un moteur de recherche qui crache des resultats.

### Architecture de la reponse

**Zone principale — La reponse** (90% de l'espace visible)

- Texte propre, structure, bien redige en Markdown
- Sources integrees dans le texte sous forme de micro-references cliquables : "Les connexions RFC peuvent etre protegees par SNC [Sec.Guide 2023]"
- Pas de score de confiance visible
- Pas de metadata technique

**Zone contextuelle — Insights OSMOSIS** (visible UNIQUEMENT quand pertinent)

Un ou plusieurs encarts colores qui apparaissent SOUS la reponse quand le KG apporte de la valeur :

```
⚠️ Point d'attention
Les documents divergent sur ce sujet : le Security Guide 2022 mentionne
TLS 1.2 tandis que le Security Guide 2023 impose TLS 1.3.
La reponse ci-dessus se base sur la version la plus recente.
```

```
📅 Evolution detectee
Ce point a change entre les versions 2022 et 2023 du Security Guide.
La version 2023 ajoute l'exigence d'activation en plus de la visibilite.
```

```
➕ Eclairage complementaire
D'autres documents apportent des informations supplementaires :
le Feature Scope Description 2023 precise que cette fonctionnalite
est disponible uniquement en edition Cloud Private.
```

Si le KG n'apporte rien → pas d'encart. La reponse est clean et complete.
Si le KG detecte une tension → l'encart rend la valeur ajoutee VISIBLE et COMPRENSIBLE.

**Zone sources — Discrete et utile**

- Pas un bloc separe imposant
- Une ligne en bas : "Sources : Sec.Guide 2023 (p.41), Ops.Guide 2023 (p.12), ..."
- Cliquable → ouvre le document/page
- Icone de fraicheur (recente / ancienne)

### Indicateurs discrets

**Au lieu du score 62%** :
- 🟢 Petit point vert dans le coin de la reponse = reponse bien fondee (haute confiance, sources multiples)
- 🟡 Point orange = reponse partielle (sources limitees)
- 🔴 Point rouge = attention, information non verifiee (basse confiance, haute entropie)
- Au hover du point → tooltip expliquant pourquoi (ex: "Base sur 3 sources de 2 documents differents")

### Suggestions et guidage

**Page vide** (avant la premiere question) :
- 3-4 suggestions de questions basees sur le corpus : "Demandez-moi par exemple..."
- Indication du domaine couvert : "Je connais 23 documents techniques SAP S/4HANA"

**Apres une reponse** :
- Suggestions de questions de suivi : "Vous pourriez aussi demander..."
- Lien vers les articles Atlas lies (quand disponibles)

---

## 3. Ce qu'il faut supprimer

- ❌ Score de confiance numerique visible
- ❌ Bloc "verite documentaire" (knowledge_proof)
- ❌ Identifiants techniques des sources (hash, prefixes numeriques)
- ❌ Compteurs de claims/chunks/facettes visibles
- ❌ Mode debug dans l'interface principale

## 4. Ce qu'il faut garder

- ✅ Mise en page Markdown de la reponse (gras, listes, titres)
- ✅ Citations des sources dans le texte
- ✅ Historique de conversation
- ✅ Possibilite de poser des questions de suivi

## 5. Ce qu'il faut ajouter

- ➕ Encarts d'insights KG (tensions, evolutions, complements)
- ➕ Indicateur de confiance discret (point colore)
- ➕ Noms de sources lisibles + cliquables
- ➕ Suggestions de questions (page vide + apres reponse)
- ➕ Indicateur de fraicheur des sources
- ➕ Entropie comme signal backend (pas affichee, mais influence l'indicateur)

---

## 6. Exemples de rendu cible

### Cas 1 : Reponse simple, pas de tension

```
Q: Quels sont les mecanismes de securite pour les connexions RFC ?

Les connexions RFC dans SAP S/4HANA peuvent etre protegees par
**Secure Network Communications (SNC)**, qui assure le chiffrement
des donnees en transit [Sec.Guide 2023].

SAP S/4HANA supporte les mecanismes SSO fournis par la technologie
Application Server ABAP, notamment les **logon tickets** pour
l'authentification via navigateur web [Sec.Guide 2023].

Il est recommande de configurer des profils de scan antivirus
pour les communications entrantes [Ops.Guide 2023].

Sources : Security Guide 2023 · Operations Guide 2023
                                                    🟢
```

Pas d'encart KG — le KG n'a rien de special a signaler. Reponse clean.

### Cas 2 : Tension detectee

```
Q: Quel report de suppression utiliser pour les donnees de plan de controle ?

Pour supprimer les donnees de plan de controle, un job regulier
doit etre planifie pour appeler l'un des reports de suppression :
**CNS_CP_DELETE** ou **CNS_DP_DELETE_MULT** [Sec.Guide 2023].

Sources : Security Guide 2023 · Security Guide 2022

⚠️ Point d'attention — Evolution entre versions
Le Security Guide 2022 mentionne "CNS_CP_DELETE_MULT" tandis que
le Security Guide 2023 utilise "CNS_DP_DELETE_MULT". Le nom du
second report a change entre les deux versions. La reponse ci-dessus
utilise la version la plus recente (2023).
                                                    🟢
```

L'encart KG montre immediatement la valeur ajoutee : OSMOSIS a detecte une evolution que ni ChatGPT ni un RAG classique ne verraient.

### Cas 3 : Information non trouvee

```
Q: Quel est le cout de licence de SAP S/4HANA ?

Les documents disponibles ne contiennent pas d'information sur
les couts de licence de SAP S/4HANA. Le corpus couvre la
documentation technique (guides de securite, d'installation,
de conversion et de fonctionnalites) mais pas les aspects
commerciaux.

                                                    🔴
```

Pas d'encart. Indicateur rouge (le systeme admet ne pas savoir). Honnete et utile.

---

## 7. Architecture dual-mode automatique

### Principe

L'utilisateur ne choisit pas de mode. Le systeme decide en fonction de ce qu'il a trouve.

**Pas de tension detectee → Mode Reponse (80% des cas)**
- Reponse clean, ChatGPT-like
- Sources discretes
- Indicateur vert
- Aucun bruit

**Tension/contradiction/evolution detectee → Mode Exploration (20% des cas)**
- Reponse PLUS positions documentaires visibles
- Le format change automatiquement pour exposer la realite multi-source
- L'utilisateur VOIT immediatement que OSMOSIS fait quelque chose de different

### Signal de switch (deja dans le backend)

```python
# Le backend retourne deja ces donnees :
if contradiction_envelope.has_tension:
    mode = "exploration"  # positions documentaires visibles
elif signal_report.has_signal("coverage_gap"):
    mode = "exploration"  # docs manquants signales
elif signal_report.has_signal("temporal_evolution"):
    mode = "exploration"  # evolution detectee
else:
    mode = "response"     # reponse clean standard
```

### Mode Reponse (clean)

```
┌─────────────────────────────────────────────────┐
│ Reponse structuree en Markdown                  │
│                                                 │
│ Les connexions RFC peuvent etre protegees par   │
│ **SNC** [Sec.Guide 2023] et **TLS** [Ops.Guide]│
│                                                 │
│ Sources : Security Guide 2023 · Ops Guide 2023  │
│                                              🟢 │
└─────────────────────────────────────────────────┘
```

### Mode Exploration (tensions detectees)

```
┌─────────────────────────────────────────────────┐
│ Reponse structuree en Markdown                  │
│                                                 │
│ Pour la suppression des donnees de plan de      │
│ controle, un job doit etre planifie pour        │
│ appeler CNS_CP_DELETE ou CNS_DP_DELETE_MULT     │
│ [Sec.Guide 2023].                               │
│                                                 │
├─────────────────────────────────────────────────┤
│ ⚠️ Positions documentaires                      │
│                                                 │
│ Ce sujet fait l'objet de DIFFERENCES entre      │
│ les documents :                                 │
│                                                 │
│ 📄 Security Guide 2023                          │
│    CNS_CP_DELETE ou CNS_DP_DELETE_MULT          │
│    (version la plus recente)                    │
│                                                 │
│ 📄 Security Guide 2022                          │
│    CNS_CP_DELETE ou CNS_CP_DELETE_MULT          │
│    (version anterieure)                         │
│                                                 │
│ → Le nom du second report a change entre les    │
│   versions. La reponse utilise la version 2023. │
│                                                 │
│ Sources : Security Guide 2023 · Security Guide  │
│ 2022                                         🟡 │
└─────────────────────────────────────────────────┘
```

### Pourquoi dual-mode automatique

| Approche | Avantage | Risque |
|---|---|---|
| Chat-only (Claude V1) | Adoption rapide | Differenciateur invisible |
| Exploration-only (ChatGPT radical) | Forte differenciation | Friction sur les 80% simples |
| **Dual-mode automatique** | **Adoption + differenciation** | **Aucun** — simple par defaut, riche quand necessaire |

Le switch est invisible pour l'utilisateur. Il recoit toujours "la meilleure reponse possible" — parfois c'est une reponse simple, parfois c'est une exploration documentaire. Le systeme decide.

### Ce qui declenche le mode Exploration

| Signal backend | Deja disponible ? | Ce que l'utilisateur voit |
|---|---|---|
| `contradiction_envelope.has_tension` | ✅ Oui | Bloc "Positions documentaires" avec les claims des deux cotes |
| `insight_hints` type "contradiction" | ✅ Oui | Encart "Point d'attention" |
| `insight_hints` type "evolution" | ✅ Oui | Encart "Evolution detectee entre versions" |
| `signal_report` "coverage_gap" | ✅ Oui | Encart "Certains documents n'ont pas ete trouves" |
| `entropy.flag == "high"` | ✅ Oui | Indicateur 🟡 au lieu de 🟢 |
| Aucun signal | — | Mode Reponse clean (pas d'encart) |

---

## 8. Plan d'implementation en 2 phases

### Phase 1 — Mode Reponse clean (2-3 jours)

Objectif : le chat ressemble a ChatGPT mais mieux source.

1. **Supprimer** : score %, bloc "verite documentaire", vocabulaire interne
2. **Nettoyer sources** : noms lisibles, cliquables, integrees dans le texte
3. **Indicateur discret** : point colore (vert/orange/rouge) au lieu du score
4. **Suggestions** : questions de depart sur page vide

Resultat : un chat propre qui ne fait pas peur.

### Phase 2 — Mode Exploration automatique (2-3 jours)

Objectif : quand le KG detecte quelque chose, le montrer intelligemment.

1. **Detecter** le mode (Reponse vs Exploration) a partir des signaux backend
2. **Bloc "Positions documentaires"** : quand contradiction_envelope.has_tension, afficher les claims des deux cotes avec les sources
3. **Encarts contextuels** : evolution, coverage gap, complement
4. **Indicateur adapte** : 🟡 quand tensions, 🟢 quand clean

Resultat : la valeur du KG est visible exactement quand elle est pertinente.

---

## 9. Implementation technique

### Donnees deja disponibles dans le backend

Le backend retourne deja tout ce qu'il faut (mais le frontend ne l'exploite pas) :

- `synthesis.synthesized_answer` : la reponse textuelle
- `signal_report.signals` : tensions, evolutions, coverage gaps
- `contradiction_envelope` : paires de claims en tension avec sources
- `insight_hints` : liste de hints proactifs (contradictions, concepts structurants)
- `entropy.score` + `entropy.flag` : indicateur d'incertitude
- `confidence` : score numerique (a transformer en point colore)
- `results` : chunks avec `source_file`, `slide_index`

### Modifications frontend necessaires

1. **Supprimer** le bloc knowledge_proof
2. **Transformer** le score en point colore (vert > 0.7, orange 0.5-0.7, rouge < 0.5)
3. **Creer** les encarts d'insights a partir de `insight_hints` et `contradiction_envelope`
4. **Nettoyer** les noms de sources (enlever hash, prefixes, afficher nom lisible)
5. **Integrer** les sources dans le texte (micro-references cliquables)
6. **Ajouter** les suggestions de questions

### Effort estime

- Refonte du composant de reponse : 1 jour
- Encarts KG insights : 0.5 jour
- Sources cliquables + nettoyage : 0.5 jour
- Suggestions de questions : 0.5 jour
- Total : **2-3 jours**

---

*Document pour reflexion conjointe avec ChatGPT. Le chat est le point d'entree principal — il doit etre impeccable.*

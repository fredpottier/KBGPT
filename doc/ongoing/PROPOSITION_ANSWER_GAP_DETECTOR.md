# Proposition alternative — Answer Gap Detector

**Date** : 1er avril 2026
**Contexte** : Les approches V1 (coverage lexical) et V1.1 (candidate answer) ne couvrent que 37% des questions unanswerable car elles classifient la question par sa forme syntaxique. Le vrai signal est dans le gap entre la question et les chunks.

---

## 1. Pourquoi l'approche par classification de question echoue

Sur 8 questions unanswerable du benchmark, seules 3 sont classifiables comme EXACT_NUMERIC/IDENTIFIER. Les 5 autres sont syntaxiquement OPEN :

- "Quelle est la performance benchmark TPS..." → ressemble a EXACT mais formulation OPEN
- "Quelles sont les alternatives open-source..." → demande une liste
- "Quel est le temps moyen de migration..." → demande une duree
- "Quels sont les salaires moyens..." → demande un chiffre
- "Comment configurer l'integration avec Salesforce..." → demande une procedure

Ces questions ont une propriete commune : les chunks recuperes ne parlent PAS du sujet demande, meme s'ils parlent du domaine general.

**Le probleme n'est pas la forme de la question. C'est le gap entre la question et les chunks.**

---

## 2. Proposition : Answer Gap Detector

### Principe

Au lieu de classifier la question puis chercher des formes dans les chunks, on mesure directement si les chunks REPONDENT a la question. Pas par similarite embedding (qui capture le domaine) mais par **recouvrement des termes specifiques** de la question dans les chunks.

### Intuition

Quand un utilisateur demande "Quel est le cout de licence ?", les chunks recuperes parlent de "SAP S/4HANA", "features", "security" — le domaine est le meme (score embedding eleve) mais aucun chunk ne contient "cout", "licence", "prix", "tarif", "pricing", "fee". Il y a un GAP entre les termes specifiques de la question et le contenu des chunks.

A l'inverse, quand un utilisateur demande "Quel objet d'autorisation pour Credit Management ?", les chunks contiennent "authorization object", "F_UKM_SGMT", "Credit Management" — les termes specifiques sont presents. Pas de gap.

### Mecanisme

**Etape 1 — Extraire les termes specifiques de la question**

Pas tous les mots — seulement ceux qui sont SPECIFIQUES a cette question et pas des termes generiques du domaine.

Methode : TF-IDF inverse sur le corpus. Les mots qui apparaissent dans > 20% des chunks sont "generiques" (ex: "SAP", "S/4HANA", "system", "data"). Les mots qui apparaissent dans < 5% des chunks sont "specifiques" (ex: "cout", "licence", "Salesforce", "salaire", "performance benchmark").

On extrait les 3-5 termes les plus specifiques de la question.

Exemple :
- "Quel est le cout de licence annuel de SAP S/4HANA ?"
  - Termes generiques (ignores) : SAP, S/4HANA, annuel
  - Termes specifiques : "cout", "licence"

- "Comment configurer l'integration avec Salesforce CRM ?"
  - Termes generiques (ignores) : configurer, integration
  - Termes specifiques : "Salesforce", "CRM"

- "Quel objet d'autorisation pour Credit Management ?"
  - Termes generiques (ignores) : objet
  - Termes specifiques : "autorisation", "Credit Management"

**Etape 2 — Verifier la presence de ces termes dans les chunks recuperes**

Pour chaque terme specifique, verifier s'il (ou un lemme/synonyme proche) apparait dans au moins un des top-K chunks.

```
gap_score = 1 - (termes_specifiques_trouves / total_termes_specifiques)
```

- gap_score = 0 → tous les termes specifiques sont dans les chunks → ANSWERABLE
- gap_score = 0.5 → la moitie des termes manquent → UNCERTAIN
- gap_score = 1.0 → aucun terme specifique dans les chunks → probable UNANSWERABLE

**Etape 3 — Decision combinee**

```python
if gap_score >= 0.8 AND max_chunk_score < 0.75:
    → UNANSWERABLE
elif gap_score >= 0.6:
    → UNCERTAIN (passer au LLM avec flag)
else:
    → ANSWERABLE (pipeline normal)
```

### Pourquoi c'est different des approches precedentes

| Approche | Ce qu'elle mesure | Faiblesse |
|---|---|---|
| V1 Coverage lexical | Mots de la question dans les chunks | Confond termes generiques et specifiques |
| V1.1 Candidate answer | Formes de reponse (nombres, codes) dans les chunks | Ne couvre que les questions a reponse structuree |
| **Answer Gap** | Termes SPECIFIQUES de la question absents des chunks | Fonctionne pour TOUT type de question |

### Couverture sur les 8 questions unanswerable

| Question | Termes specifiques | Dans les chunks ? | Gap score |
|---|---|---|---|
| Cout de licence | cout, licence | ❌ | ~1.0 → UNANSWERABLE |
| Nombre de clients | clients, nombre, production, monde | ❌ | ~1.0 → UNANSWERABLE |
| Performance TPS 128Go | performance, benchmark, TPS, 128, RAM | ❌ | ~1.0 → UNANSWERABLE |
| Alternatives open-source | alternatives, open-source | ❌ | ~1.0 → UNANSWERABLE |
| Temps moyen migration | temps, moyen, migration, duree | ❌ (partiellement "migration") | ~0.7 → UNCERTAIN |
| Plugin Chrome Fiori | plugin, Chrome | ❌ | ~1.0 → UNANSWERABLE |
| Salaires consultants | salaires, consultants | ❌ | ~1.0 → UNANSWERABLE |
| Integration Salesforce | Salesforce | ❌ | ~1.0 → UNANSWERABLE |

**Couverture estimee : 7/8** (vs 3/8 pour V1.1)

---

## 3. Avantages

1. **Pas de classification de question** necessaire — fonctionne pour TOUT type de question (OPEN inclus)
2. **Pas de detection de forme** dans les chunks — pas de "is_number_like" ou spaCy
3. **Domain-agnostic** par construction — les termes specifiques sont definis par IDF sur le corpus, pas par des regles metier
4. **Multilingue** — IDF fonctionne sur n'importe quelle langue
5. **Robuste au changement de LLM** — decision purement deterministe
6. **S'integre naturellement comme signal** dans l'architecture existante

---

## 4. Risques

### Risque 1 — Faux negatif (refuse a tort)

**Scenario** : L'utilisateur utilise un terme que le corpus ne mentionne pas mais la reponse existe sous un synonyme. Ex: "Quel est le MFA dans SAP ?" alors que le corpus dit "multi-factor authentication".

**Mitigation** :
- Ajouter une couche de lemmatisation (MFA → multi-factor authentication) ?
- Ou combiner gap_score avec le score embedding : si embedding tres eleve mais gap eleve → UNCERTAIN (pas UNANSWERABLE)
- Accepter que ce cas existe mais qu'il est rare

### Risque 2 — Faux positif (laisse passer a tort)

**Scenario** : Un terme specifique est present dans les chunks mais dans un contexte different. Ex: "migration" dans un chunk sur la migration de base de donnees alors que la question porte sur la migration organisationnelle.

**Mitigation** : Le LLM gere — si les chunks contiennent le terme, il y a de bonnes chances que le sujet soit au moins partiellement couvert

### Risque 3 — L'IDF depend du corpus

**Scenario** : Sur un petit corpus de 5 documents, les frequences IDF sont instables. Un terme "specifique" sur 23 docs peut devenir "generique" sur 5000.

**Mitigation** :
- Recalculer l'IDF a chaque ingestion (ou periodiquement)
- Utiliser un seuil adaptatif base sur la distribution des IDF, pas un seuil fixe

### Risque 4 — Le gap ne capture pas les questions implicites

**Scenario** : "Pourquoi faut-il migrer vers S/4HANA ?" — les termes "migrer" et "S/4HANA" sont partout dans les chunks (gap = 0) mais la RAISON n'est pas documentee explicitement.

**Mitigation** : Ce cas est OPEN et le gap sera faible → le LLM est appele normalement. Si le LLM hallucine une raison, c'est un probleme de synthese, pas de negative rejection. On ne peut pas tout resoudre avec un gate.

---

## 5. Implementation

### Pre-requis
- Index IDF sur le corpus (calculable a partir de Qdrant : compter les chunks contenant chaque terme)
- Tokenisation basique (split + lowercase + lemme optionnel)
- Pas de modele NLP supplementaire

### Cout
- Calcul IDF : une fois a l'ingestion, O(vocabulaire × chunks)
- Par requete : O(termes_question × termes_chunks_topK) — negligeable

### Integration
Nouveau signal dans `signal_detector.py` :

```python
Signal(
    type="answer_gap",
    strength=gap_score,
    evidence={
        "specific_terms": [...],
        "terms_found": [...],
        "terms_missing": [...],
    }
)
```

Consomme par `signal_policy.py` pour decider ANSWERABLE/UNCERTAIN/UNANSWERABLE.

---

## 6. Questions ouvertes

1. L'IDF sur le corpus est-il suffisamment stable pour servir de base a la detection des termes specifiques ?
2. Faut-il une couche de synonymes/lemmes pour eviter les faux negatifs (MFA vs multi-factor authentication) ?
3. Le gap_score devrait-il etre combine avec d'autres signaux existants (exactness, tension) ?
4. Cette approche est-elle trop simple ou est-ce justement sa force ?

---

*Proposition alternative pour analyse multi-IA. A comparer avec V1 et V1.1.*

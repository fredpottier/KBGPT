# OSMOSE Pure - Guide de Test

**Date:** 2025-10-14

---

## 🎯 Test Rapide (5 minutes)

### Étape 1: Préparer un Fichier PPTX Test

Choisir un deck PPTX avec :
- 15-30 slides
- Quelques diagrammes / schémas
- Contenu technique ou RH (pas que du texte)

```bash
# Copier dans le répertoire d'import
cp votre_deck.pptx C:/Project/SAP_KB/data/docs_in/
```

### Étape 2: Lancer l'Ingestion

**Option A: Via Interface (Recommandé)**
1. Ouvrir http://localhost:3000/documents/import
2. Upload le fichier PPTX
3. Observer progression en temps réel

**Option B: Directement via Worker**
```bash
# Le worker surveille data/docs_in/ automatiquement
docker-compose logs -f worker
```

### Étape 3: Vérifier les Logs

**Chercher ces messages clés:**
```
[OSMOSE PURE] Utilisation de 3 workers pour 25 slides
[OSMOSE PURE] Début génération de 25 résumés Vision
Slide 1 [VISION SUMMARY]: 347 chars collectés
Slide 2 [VISION SUMMARY]: 412 chars collectés
...
[OSMOSE PURE] 25 résumés Vision collectés
[OSMOSE PURE] Texte enrichi construit: 8742 chars depuis 25 slides
================================================================================
[OSMOSE PURE] Lancement du traitement sémantique (remplace ingestion legacy)
================================================================================
[OSMOSE PURE] ✅ Traitement réussi:
  - 42 concepts canoniques
  - 15 connexions cross-documents
  - 8 topics segmentés
  - Proto-KG: 42 concepts + 35 relations + 42 embeddings
  - Durée: 14.2s
================================================================================
🎉 INGESTION TERMINÉE - votre_deck.pptx - OSMOSE Pure
```

**❌ Si erreur:**
```
[OSMOSE PURE] ❌ Erreur traitement sémantique: ...
```
→ Copier message d'erreur complet et me le transmettre

### Étape 4: Vérifier Proto-KG dans Neo4j

```bash
# Accéder à Neo4j
docker-compose exec neo4j cypher-shell -u neo4j -p password

# Requêtes de vérification
> MATCH (c:CanonicalConcept) RETURN count(c);
# Attendu: > 20 pour un deck moyen

> MATCH (c:CanonicalConcept) RETURN c.canonical_name, c.concept_type LIMIT 10;
# Voir les concepts extraits

> MATCH (c:CanonicalConcept) WHERE size(c.languages) > 1 RETURN c;
# Voir concepts cross-linguals (si doc multilingue)

> MATCH (c:CanonicalConcept)-[r]->(t:CanonicalConcept) RETURN c.canonical_name, type(r), t.canonical_name LIMIT 10;
# Voir relations entre concepts
```

### Étape 5: Vérifier Qdrant

```bash
# Vérifier collection concepts_proto
curl http://localhost:6333/collections/concepts_proto

# Attendu dans la réponse:
{
  "result": {
    "status": "green",
    "vectors_count": 42,  # Nombre de concepts
    ...
  }
}
```

---

## 🔍 Validation Qualité

### 1. Résumés Vision

**Ouvrir les logs worker et chercher:**
```
Slide 5 [VISION SUMMARY]: 347 chars collectés
```

**Questions à valider:**
- ✅ Longueur > 150 chars par slide ?
- ✅ Résumés décrivent aspects visuels (diagrammes, layouts) ?
- ✅ Pas de slides timeout (> 5min) ?

**Exemple bon résumé:**
```
"Cette slide présente l'architecture de sécurité SAP en trois couches.
La couche supérieure montre les points d'entrée externes (Web, Mobile, API)
tous passant par un API Gateway central. La couche intermédiaire contient
les services d'authentification (OAuth 2.0, SAML) et d'autorisation (RBAC).
En bas, la couche de données illustre le chiffrement au repos avec des
icônes de cadenas sur les bases de données."
```

### 2. Concepts Canoniques

**Requête Neo4j:**
```cypher
MATCH (c:CanonicalConcept)
RETURN c.canonical_name, c.concept_type, c.quality_score, c.languages
ORDER BY c.quality_score DESC
LIMIT 20;
```

**Validation:**
- ✅ Concepts pertinents par rapport au contenu ?
- ✅ Quality score > 0.5 pour la majorité ?
- ✅ Types corrects (SOLUTION, PRACTICE, TECHNOLOGY, etc.) ?
- ✅ Unification multi-lingue si applicable ?

### 3. Relations Sémantiques

**Requête Neo4j:**
```cypher
MATCH (s:CanonicalConcept)-[r:RELATED_TO]->(t:CanonicalConcept)
RETURN s.canonical_name, r.relation_type, t.canonical_name
LIMIT 20;
```

**Validation:**
- ✅ Relations logiques (ex: SAP HANA → Column Store = CONTAINS) ?
- ✅ Pas de relations absurdes ?

---

## 📊 Métriques de Succès

### Temps de Traitement
- Deck 20 slides : **< 30 secondes**
- Deck 50 slides : **< 60 secondes**
- Deck 100+ slides : **< 120 secondes**

### Extraction
- **Concepts:** > 1.5 concept/slide en moyenne
- **Quality:** > 60% concepts avec score > 0.7
- **Coverage:** Tous les concepts majeurs du deck identifiés

### Stabilité
- **Aucune erreur** OSMOSE
- **Aucun timeout** Vision (< 5min par slide)
- **Proto-KG complet** (Neo4j + Qdrant synchronized)

---

## 🐛 Troubleshooting

### Erreur: "Text too short"
```
[OSMOSE PURE] ❌ Text too short (47 chars)
```

**Cause:** Résumés Vision trop courts ou vides

**Solution:**
- Vérifier que Vision est activé (`use_vision=True`)
- Vérifier images slides générées correctement
- Vérifier logs Vision pour erreurs API

### Erreur: "OSMOSE processing failed"
```
[OSMOSE PURE] ❌ OSMOSE processing failed: ...
```

**Solutions:**
1. Vérifier Neo4j up : `docker-compose ps neo4j`
2. Vérifier Qdrant up : `docker-compose ps qdrant`
3. Vérifier logs OSMOSE : `docker-compose logs osmose` (si service dédié)
4. Vérifier clé API OpenAI : `echo $OPENAI_API_KEY`

### Erreur: "Future n'est pas done après attente"
```
Slide 12 [VISION SUMMARY]: Future n'est pas done après attente
```

**Cause:** Vision timeout (> 5min)

**Solutions:**
- Vérifier connexion internet
- Vérifier quota API OpenAI
- Réduire MAX_WORKERS (3 → 1) si rate limiting

### Proto-KG Vide
```
> MATCH (c:CanonicalConcept) RETURN count(c);
0
```

**Causes possibles:**
1. Erreur OSMOSE non loggée → Vérifier logs complets
2. Neo4j credentials incorrectes → Vérifier .env
3. Transaction non committed → Vérifier ProtoKGService.close()

**Debug:**
```bash
# Vérifier Neo4j accessible
docker-compose exec neo4j cypher-shell -u neo4j -p password "RETURN 1;"

# Vérifier tous les noeuds (pas que CanonicalConcept)
docker-compose exec neo4j cypher-shell -u neo4j -p password "MATCH (n) RETURN labels(n), count(n);"
```

---

## 📝 Checklist Complète

### Avant Test
- [ ] Docker services up (`docker-compose ps`)
- [ ] Neo4j accessible (http://localhost:7474)
- [ ] Qdrant accessible (http://localhost:6333/dashboard)
- [ ] API Keys configurées (.env)
- [ ] Fichier PPTX test préparé (15-30 slides)

### Pendant Test
- [ ] Logs worker affichent `[OSMOSE PURE]`
- [ ] Résumés Vision générés (chars > 100)
- [ ] Pas de timeouts Vision
- [ ] OSMOSE traitement lancé
- [ ] Métriques Proto-KG affichées

### Après Test
- [ ] Neo4j contient CanonicalConcepts
- [ ] Qdrant collection concepts_proto existe
- [ ] Nombre concepts cohérent (> 1/slide)
- [ ] Quality scores corrects (> 0.5)
- [ ] Relations sémantiques logiques
- [ ] Fichier déplacé vers docs_done/

---

## 🚀 Tests Avancés (Optionnel)

### Test Multi-Documents
1. Ingérer 2-3 PPTX sur même thématique (ex: 3 decks SAP)
2. Vérifier concepts cross-documents unifiés
3. Requête Neo4j :
```cypher
MATCH (c:CanonicalConcept)
WHERE size(c.source_documents) > 1
RETURN c.canonical_name, c.source_documents;
```

### Test Multi-Lingue
1. Ingérer 1 PPTX FR + 1 PPTX EN sur même sujet
2. Vérifier unification concepts FR/EN
3. Requête Neo4j :
```cypher
MATCH (c:CanonicalConcept)
WHERE size(c.languages) > 1
RETURN c.canonical_name, c.aliases, c.languages;
```

### Test PDF + PPTX
1. Ingérer 1 PDF (OSMOSE Pure déjà implémenté)
2. Ingérer 1 PPTX (OSMOSE Pure nouveau)
3. Vérifier Proto-KG unifié pour les 2 types

---

## 📧 Reporting

**Si succès:**
- Captures logs clés (`[OSMOSE PURE] ✅ Traitement réussi`)
- Nombre concepts extraits
- Temps traitement total
- Exemples concepts pertinents

**Si échec:**
- Logs d'erreur complets
- Contexte (fichier test, taille, contenu)
- Steps reproduire erreur
- Screenshots si applicable

---

**Status:** Prêt pour test
**Durée estimée:** 5-10 minutes
**Niveau:** Utilisateur

**Version:** 1.0
**Date:** 2025-10-14

- #adr #decision #architecture #hybrid-search
- adr-number:: 002
- date:: [[2025-10-09]]
- status:: ACCEPTED
- related-phases:: [[Phase 3 - Semantic Overlay & Provenance]]
-
- ## Contexte
	- Système hybride : Qdrant (vector search) + Neo4j (structured knowledge)
	- Questions utilisateur ont des **intents différents** :
		- Factual lookup : "Quel est le SLA ?"
		- Conceptual exploration : "Parle-moi de S/4HANA"
		- Relationship navigation : "Quels modules dépendent de FI ?"
	- Performance : Neo4j direct = 200ms, Qdrant + LLM = 2-5s
	- Besoin de router intelligemment selon l'intent
-
- ## Décision
	- **Implémenter un Query Router intelligent**
	- Intent detection via LLM léger ou règles
	- Routage vers :
		- Neo4j first (facts structurés)
		- Qdrant first (exploration sémantique)
		- Hybride (enrichissement mutuel)
	-
	- ### Stratégies de Routage
		- **FACTUAL_LOOKUP** : Neo4j → Qdrant (enrichissement)
		- **CONCEPTUAL_EXPLORATION** : Qdrant → Neo4j (relations)
		- **RELATIONSHIP_NAVIGATION** : Neo4j pur (graph traversal)
		- **OPEN_QUESTION** : Hybride (vector + graph)
-
- ## Conséquences
	-
	- ### ✅ Positives
		- **Performance** : 10x plus rapide pour faits (200ms vs 2-5s)
		- **Précision** : 95%+ pour faits vs 60-70% vector seul
		- **Coût** : -66% tokens LLM (moins de synthesis)
		- **Confiance** : Sources traçables
	-
	- ### ❌ Négatives
		- Complexité supplémentaire (router à maintenir)
		- Intent detection peut échouer (fallback nécessaire)
		- Tests e2e plus complexes
	-
	- ### ⚠️ Risques
		- Mauvaise classification d'intent → mauvaise performance
		- **Mitigation** : Fallback hybride si doute, A/B testing
-
- ## Alternatives Considérées
	-
	- ### Option 1 : Toujours Qdrant
		- ❌ Performance médiocre pour faits
		- ❌ Pas de traçabilité
		- ❌ Coût LLM élevé
	-
	- ### Option 2 : Toujours Neo4j
		- ❌ Mauvais pour exploration sémantique
		- ❌ Pas de similarité vectorielle
	-
	- ### Option 3 : Toujours hybride
		- ❌ Overhead inutile pour faits simples
		- ❌ Latency élevée systématiquement
-
- ## Implémentation Proposée
	- ```python
	  class QueryRouter:
	      def route(self, query: str) -> QueryPlan:
	          intent = self.detect_intent(query)

	          if intent == "FACTUAL_LOOKUP":
	              return QueryPlan(
	                  primary="neo4j",
	                  secondary="qdrant",
	                  strategy="fact_first"
	              )
	          elif intent == "CONCEPTUAL_EXPLORATION":
	              return QueryPlan(
	                  primary="qdrant",
	                  secondary="neo4j",
	                  strategy="semantic_first"
	              )
	          # etc.
	  ```
-
- ## Métriques de Succès
	- Intent detection accuracy : 90%+
	- P95 latency faits : < 500ms
	- P95 latency concepts : < 3s
	- User satisfaction : +25%
-
- ## Références
	- [[KG_VALUE_PROPOSITION_CONCRETE]] - Exemples concrets
	- [[Phase 3 - Semantic Overlay & Provenance]]
	- [[Back2Promise Project]]

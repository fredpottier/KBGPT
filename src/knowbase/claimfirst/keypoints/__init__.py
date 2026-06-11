"""KeyPoint layer — clé « même question » pour co-localiser des claims qui
répondent à la même interrogation, MÊME en sens opposé.

Motivation (11-12/06/2026) : tout le pipeline aval (cluster_cross_doc par Jaccard
de tokens, détection de contradictions par claim-key sujet|prédicat, perspectives
par HDBSCAN d'embeddings, Atlas) groupe par SIMILARITÉ DE SURFACE — ce qui est
structurellement le mauvais signal pour « même sujet, claim opposé ». Exemple :
GBD2018 « le niveau d'alcool minimisant le risque = ZÉRO » et GBD2020 « TMREL
non-nul pour 40+ » ne se rapprochent jamais (tokens/embeddings éloignés, sujets
canoniques différents « alcohol consumption » vs « TMREL », triplets manquants).

Approche (littérature) :
- EDC « Define » (EMNLP 2024) : on ne fait pas confiance au sujet de surface — on
  re-dérive la QUESTION normalisée que le claim adresse (acronymes dépliés via le
  glossaire du domaine = side-information CESI, WWW 2018).
- Key Point Analysis (Bar-Haim, IBM, EMNLP 2020) : grouper par le POINT ; une
  contradiction = deux stances opposées sous le même KeyPoint.

Le `normative_question` est cadré NEUTREMENT pour que deux réponses opposées
partagent la même question → bucket exact → contradictions/Atlas/retrieval par
le bon axe.
"""

from .extractor import KeyPointExtractor, KeyPointSignature

__all__ = ["KeyPointExtractor", "KeyPointSignature"]

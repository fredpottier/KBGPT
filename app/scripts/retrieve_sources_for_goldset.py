"""Pour chaque question du gold-set SAP, retrouve les top-5 chunks Qdrant
pertinents (doc_id, page, snippet) et génère un fichier markdown que le user
peut utiliser pour rédiger ses réponses sans biais LLM."""
import sys
sys.path.insert(0, "/app/src")

import json
from pathlib import Path
from knowbase.common.clients.embeddings import get_embedding_manager
from knowbase.common.clients import get_qdrant_client

# Les 30 questions du gold-set SAP PCE
QUESTIONS = [
    # 1. False premise (3)
    ("Q1.1", "false_premise", "Comment activer le module Embedded Reporting Studio dans S/4HANA Cloud Private Edition 2024 ?"),
    ("Q1.2", "false_premise", "Quelle est la procédure de migration directe depuis SAP Business One vers S/4HANA Cloud Private Edition ?"),
    ("Q1.3", "false_premise", "Comment configurer le multi-tenant strict sur un déploiement S/4HANA Cloud Private Edition ?"),
    # 2. Lifecycle / temporal (3)
    ("Q2.1", "lifecycle", "À partir de quelle release SPS le support de HANA 1.0 s'arrête-t-il pour S/4HANA Cloud Private Edition ?"),
    ("Q2.2", "lifecycle", "Quelle version de S/4HANA Cloud Private Edition introduit l'obligation de migrer du Classic Asset Accounting vers New Asset Accounting ?"),
    ("Q2.3", "lifecycle", "À partir de quelle release le Customer/Vendor Master Data classique est-il remplacé par Business Partner obligatoire ?"),
    # 3. Causal / why (3)
    ("Q3.1", "causal", "Pourquoi SAP recommande-t-il ABAP RAP plutôt que CDS View Extensions pour les nouveaux développements custom sur S/4HANA Cloud Private Edition ?"),
    ("Q3.2", "causal", "Pour quelle raison technique S/4HANA Cloud Private Edition impose-t-il HANA exclusivement (pas de support multi-DB) ?"),
    ("Q3.3", "causal", "Pourquoi le Cash Management Classic doit-il être remplacé lors de la conversion vers S/4HANA Cloud Private Edition ?"),
    # 4. Comparison cross-doc (3)
    ("Q4.1", "comparison", "Quelles sont les différences précises de scope fonctionnel entre S/4HANA Cloud Private Edition et S/4HANA Cloud Public Edition ?"),
    ("Q4.2", "comparison", "Compare les modèles d'extensibilité entre S/4HANA Cloud Private Edition et S/4HANA on-premise (in-app, side-by-side BTP, key user extensions) ?"),
    ("Q4.3", "comparison", "Différences entre RISE with SAP et GROW with SAP appliquées à S/4HANA Cloud Private Edition ?"),
    # 5. Negation / exception (3)
    ("Q5.1", "negation", "Quelles fonctionnalités du standard S/4HANA on-premise ne sont PAS disponibles dans S/4HANA Cloud Private Edition ?"),
    ("Q5.2", "negation", "Quels modules ne sont jamais inclus dans le scope standard de S/4HANA Cloud Private Edition (nécessitent un addon séparé) ?"),
    ("Q5.3", "negation", "Pour quelles opérations système le customer n'a-t-il PAS d'accès direct en S/4HANA Cloud Private Edition (vs on-premise) ?"),
    # 6. Listing exhaustif (3)
    ("Q6.1", "listing", "Liste tous les rôles standards définis dans le contrat RISE with SAP Operations & Support pour S/4HANA Cloud Private Edition."),
    ("Q6.2", "listing", "Quelles sont toutes les options de déploiement de S/4HANA Cloud Private Edition (hyperscalers AWS/Azure/GCP, datacenter SAP) ?"),
    ("Q6.3", "listing", "Liste tous les types de patches appliqués automatiquement par SAP en S/4HANA Cloud Private Edition (OS, DB, kernel, support packs, security)."),
    # 7. Multi-hop reasoning (3)
    ("Q7.1", "multi_hop", "Pour un client sur SAP ECC EHP6 avec un addon HR custom, quelle est la séquence de migration recommandée vers S/4HANA Cloud Private Edition 2024, et dans quel ordre les modules doivent-ils être reconfigurés ?"),
    ("Q7.2", "multi_hop", "Architecture hybride SAP Datasphere + S/4HANA Cloud Private Edition + BW/4HANA : quelle est la séquence d'installation recommandée et quelles dépendances entre eux ?"),
    ("Q7.3", "multi_hop", "Conversion Classic Asset Accounting vers New Asset Accounting lors d'un passage vers S/4HANA Cloud Private Edition : quels prérequis et étapes intermédiaires ?"),
    # 8. Contextual constraint (3)
    ("Q8.1", "contextual", "Pour un client EU avec contraintes GDPR strictes, quelles options de résidence des données sont disponibles pour S/4HANA Cloud Private Edition ?"),
    ("Q8.2", "contextual", "Pour un client public sector US (FedRAMP/GovCloud), S/4HANA Cloud Private Edition est-il disponible et avec quelles certifications ?"),
    ("Q8.3", "contextual", "Déploiement S/4HANA Cloud Private Edition sur AWS région Frankfurt : garanties d'uptime réseau et modalités de DR cross-region ?"),
    # 9. Unanswerable (3)
    ("Q9.1", "unanswerable", "Quelle est la roadmap S/4HANA Cloud Private Edition 2027 annoncée par SAP ?"),
    ("Q9.2", "unanswerable", "Quel est le prix exact d'une licence S/4HANA Cloud Private Edition pour 500 users en France ?"),
    ("Q9.3", "unanswerable", "Combien de clients ont migré vers S/4HANA Cloud Private Edition en Europe en 2024 ?"),
    # 10. Quantitative (3)
    ("Q10.1", "quantitative", "Quel est le SLA d'uptime contractuel de S/4HANA Cloud Private Edition (en % de disponibilité mensuelle) ?"),
    ("Q10.2", "quantitative", "Combien de mises à jour OS par an sont incluses dans le contrat RISE Premium Supplier pour S/4HANA Cloud Private Edition ?"),
    ("Q10.3", "quantitative", "Quelle est la durée typique d'une upgrade d'une release N à N+1 sur S/4HANA Cloud Private Edition ?"),
]


def main():
    em = get_embedding_manager()
    qc = get_qdrant_client()
    collection = "knowbase_chunks_v2"

    out = []
    out.append("# Gold-set SAP PCE — Sources candidates par question\n")
    out.append("Pour chaque question, top-5 chunks Qdrant les plus pertinents.\n")
    out.append("Lis les snippets, ouvre les docs source (data/docs_done/...), rédige ta réponse experte.\n\n")
    out.append("---\n\n")

    for qid, category, question in QUESTIONS:
        out.append(f"## {qid} [{category}]\n")
        out.append(f"**Q:** {question}\n\n")
        out.append(f"### Sources candidates\n\n")

        # Embed la question
        try:
            embedding = em.encode([question])[0]
        except Exception as e:
            out.append(f"_(embedding failed: {e})_\n\n")
            continue

        # Search top-5
        try:
            results = qc.search(
                collection_name=collection,
                query_vector=embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding),
                limit=5,
                with_payload=True,
            )
        except Exception as e:
            out.append(f"_(search failed: {e})_\n\n")
            continue

        if not results:
            out.append("_(aucun chunk pertinent trouvé — possiblement question hors corpus, à confirmer)_\n\n")
        else:
            for i, hit in enumerate(results, 1):
                payload = hit.payload or {}
                doc_id = payload.get("doc_id") or payload.get("document_id") or "?"
                # Try multiple page field names
                page = payload.get("page") or payload.get("page_index") or payload.get("source_page") or "?"
                # Try multiple content fields
                content = payload.get("text") or payload.get("content") or payload.get("verbatim") or payload.get("full_text") or ""
                snippet = content[:400].replace("\n", " ")
                score = hit.score if hasattr(hit, 'score') else 0
                out.append(f"**{i}. {doc_id}** (page={page}, score={score:.3f})\n")
                out.append(f"> {snippet}{'...' if len(content) > 400 else ''}\n\n")

        out.append("### Ta réponse (à rédiger)\n\n")
        out.append("```json\n")
        out.append(json.dumps({
            "id": f"GOLD_SAP_{qid.replace('.', '_')}",
            "question": question,
            "primary_type": category,
            "language": "fr",
            "ground_truth": {
                "answer": "<TO FILL: réponse experte rédigée depuis les sources ci-dessus + ta connaissance SAP>",
                "exact_identifiers": ["<liste mots-clés exacts attendus>"],
                "supporting_doc_ids": ["<liste doc_ids de la réponse>"],
                "answerability": "answerable" if category != "unanswerable" else "unanswerable",
                "false_premise": category == "false_premise"
            },
            "annotation_meta": {
                "annotator": "user_fred_sap_expert",
                "reviewed_at": "2026-05-12"
            }
        }, indent=2, ensure_ascii=False))
        out.append("\n```\n\n---\n\n")

    output_file = Path("/app/benchmark/questions/gold_set_sap_v1_sources.md")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(out), encoding="utf-8")
    print(f"\n✓ Written: {output_file}")
    print(f"  Total questions: {len(QUESTIONS)}")
    print(f"  Total lines: {len(out)}")


if __name__ == "__main__":
    main()

"""
OSMOSE Verification API Router

Endpoints for verifying text against Knowledge Graph.

Author: Claude Code
Date: 2026-02-03
"""

import io
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse

from knowbase.api.schemas.verification import (
    VerifyRequest,
    VerifyResponse,
    CorrectRequest,
    CorrectResponse,
)
from knowbase.api.services.verification_service import get_verification_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/verify",
    tags=["verification"],
    responses={
        500: {"description": "Internal server error"}
    }
)


@router.post(
    "/analyze",
    response_model=VerifyResponse,
    summary="Analyser et vérifier un texte",
    description="""
Analyse un texte et vérifie chaque affirmation contre le Knowledge Graph.

**Processus:**
1. Découpe le texte en assertions vérifiables (via LLM)
2. Recherche des claims similaires dans Neo4j
3. Si pas de claim trouvé, fallback vers recherche Qdrant
4. Détermine le statut de chaque assertion

**Statuts possibles:**
- `confirmed`: Un claim confirme l'assertion
- `contradicted`: Un claim contredit l'assertion
- `incomplete`: Information partielle trouvée
- `fallback`: Trouvé dans Qdrant seulement (pas de claim)
- `unknown`: Aucune information trouvée
"""
)
async def analyze_text(request: VerifyRequest) -> VerifyResponse:
    """
    Analyse un texte et vérifie chaque assertion contre le KG.

    Args:
        request: Texte à vérifier et tenant_id

    Returns:
        Texte original avec assertions annotées et résumé
    """
    try:
        service = get_verification_service(tenant_id=request.tenant_id)
        result = await service.analyze(request.text)
        logger.info(
            f"[VERIFY_API] Analyzed text: {result.summary['total']} assertions, "
            f"{result.summary['confirmed']} confirmed, "
            f"{result.summary['contradicted']} contradicted"
        )
        return result

    except Exception as e:
        logger.error(f"[VERIFY_API] Analysis failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'analyse: {str(e)}"
        )


@router.post(
    "/correct",
    response_model=CorrectResponse,
    summary="Corriger un texte basé sur les vérifications",
    description="""
Génère une version corrigée du texte basée sur les assertions vérifiées.

**Processus:**
1. Filtre les assertions problématiques (contredites ou incomplètes)
2. Utilise un LLM pour réécrire le texte avec les corrections
3. Retourne le texte corrigé avec la liste des changements

**Note:** Seules les assertions `contradicted` et `incomplete` sont corrigées.
Les assertions `unknown` ou `fallback` ne sont pas modifiées.
"""
)
async def correct_text(request: CorrectRequest) -> CorrectResponse:
    """
    Génère une version corrigée du texte basée sur les claims.

    Args:
        request: Texte original et assertions vérifiées

    Returns:
        Texte corrigé avec liste des changements
    """
    try:
        service = get_verification_service(tenant_id=request.tenant_id)
        result = await service.correct(request.text, request.assertions)
        logger.info(
            f"[VERIFY_API] Generated corrections: {len(result.changes)} changes"
        )
        return result

    except Exception as e:
        logger.error(f"[VERIFY_API] Correction failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la correction: {str(e)}"
        )


@router.post(
    "/upload-docx",
    summary="Uploader et verifier un document Word",
    description="""
Uploade un document Word (.docx), analyse chaque affirmation contre le corpus
et retourne le meme document avec des commentaires de review dans la marge.

**Processus:**
1. Extraction des paragraphes du document
2. Decoupage en sections (max 12000 chars)
3. Pour chaque section : extraction des assertions → verification KG/Qdrant
4. Generation des commentaires Word (confirme/contredit/nuance/inconnu)
5. Retour du document annote en telechargement

**Commentaires ajoutes par OSMOSIS:**
- ✅ Confirme — assertion confirmee par le corpus
- ❌ Contredit — assertion contredite avec preuve
- ⚠️ Nuance — le corpus apporte une nuance importante
- ❓ Non verifiable — aucune information dans le corpus
"""
)
async def upload_and_verify_docx(
    file: UploadFile = File(...),
    annotate_confirmed: bool = Query(False, description="Annoter aussi les assertions confirmees"),
    tenant_id: str = Query("default", description="Tenant ID"),
):
    """
    Upload .docx → analyse → retourne .docx annote.
    """
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .docx sont acceptes")

    try:
        from docx import Document
        from knowbase.verification.docx_processor import (
            extract_paragraphs,
            chunk_paragraphs,
            annotate_document,
            compute_review_metrics,
            document_to_bytes,
            AssertionVerdict,
            CorpusPosition,
        )

        # 1. Lire le document
        content = await file.read()
        doc = Document(io.BytesIO(content))
        logger.info(f"[VERIFY_DOCX] Uploaded: {file.filename} ({len(content)} bytes)")

        # 2. Extraire les paragraphes
        paragraphs = extract_paragraphs(doc)
        if not paragraphs:
            raise HTTPException(status_code=400, detail="Document vide ou sans texte exploitable")

        # 3. Verifier par chunks
        service = get_verification_service(tenant_id=tenant_id)
        all_verdicts: list[AssertionVerdict] = []

        chunks = chunk_paragraphs(paragraphs)
        for chunk_idx, chunk in enumerate(chunks):
            chunk_text = "\n".join(p["text"] for p in chunk)
            first_para_index = chunk[0]["index"]

            logger.info(f"[VERIFY_DOCX] Processing chunk {chunk_idx + 1}/{len(chunks)} ({len(chunk_text)} chars)")

            # Appel au pipeline existant
            result = await service.analyze(chunk_text)

            # Convertir les assertions en AssertionVerdict V3-ready
            for assertion in result.assertions:
                # Mapper le status existant vers les nouveaux statuts
                status_map = {
                    "confirmed": "confirmed",
                    "contradicted": "contradicted",
                    "incomplete": "qualified",
                    "fallback": "incomplete",
                    "unknown": "unknown",
                }

                corpus_positions = []
                for ev in (assertion.evidence or []):
                    corpus_positions.append(CorpusPosition(
                        doc_id=getattr(ev, "source_doc", "") or "",
                        doc_title=getattr(ev, "source_doc", "") or "",
                        claim_text=getattr(ev, "claim_text", "") or "",
                        relation="CONFIRMS" if assertion.status == "confirmed" else "CONTRADICTS" if assertion.status == "contradicted" else "QUALIFIES",
                        confidence=assertion.confidence or 0.0,
                    ))

                verdict = AssertionVerdict(
                    assertion_id=assertion.id,
                    assertion_text=assertion.text,
                    paragraph_index=first_para_index + (assertion.start_index // max(len(chunk_text) // len(chunk), 1)),
                    status=status_map.get(assertion.status, "unknown"),
                    severity="high" if assertion.status == "contradicted" else "medium" if assertion.status == "incomplete" else "low",
                    confidence=assertion.confidence or 0.0,
                    reasoning_type="evidence_match",
                    corpus_positions=corpus_positions,
                    explanation=_build_explanation(assertion),
                )
                all_verdicts.append(verdict)

        # 4. Annoter le document
        doc = annotate_document(doc, paragraphs, all_verdicts, annotate_confirmed=annotate_confirmed)

        # 5. Metriques
        metrics = compute_review_metrics(all_verdicts)
        logger.info(
            f"[VERIFY_DOCX] Review complete: {metrics.total_confirmed} confirmed, "
            f"{metrics.total_contradicted} contradicted, {metrics.total_qualified} qualified, "
            f"{metrics.total_unknown} unknown (reliability={metrics.reliability_score:.0%})"
        )

        # 6. Retourner le document annote
        doc_bytes = document_to_bytes(doc)
        annotated_filename = file.filename.replace(".docx", "_osmosis_review.docx")

        return StreamingResponse(
            io.BytesIO(doc_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{annotated_filename}"',
                "X-Osmosis-Reliability": str(round(metrics.reliability_score, 3)),
                "X-Osmosis-Contradicted": str(metrics.total_contradicted),
                "X-Osmosis-Confirmed": str(metrics.total_confirmed),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VERIFY_DOCX] Upload verification failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la verification: {str(e)}"
        )


def _build_explanation(assertion) -> str:
    """Construit l'explication textuelle a partir d'une assertion verifiee."""
    if not assertion.evidence:
        return "Aucune information trouvee dans le corpus."

    ev = assertion.evidence[0]
    source = getattr(ev, "source_doc", "source inconnue") or "source inconnue"
    claim = getattr(ev, "claim_text", "") or ""

    if assertion.status == "confirmed":
        return f"Confirme par {source}."
    elif assertion.status == "contradicted":
        return f"Le corpus indique : \"{claim[:150]}\"\nSource : {source}"
    elif assertion.status == "incomplete":
        return f"Information complementaire dans {source} : \"{claim[:150]}\""
    elif assertion.status == "fallback":
        return f"Information trouvee dans {source} (non structuree)."
    else:
        return "Aucune information dans le corpus sur ce point."

# Backlog - Améliorations Mode Burst

## 1. Fallback PPTX → PDF quand Docling échoue

**Priorité**: Moyenne
**Date**: 2026-01-07
**Contexte**: Certains fichiers PPTX contiennent des shapes non reconnus par Docling/python-pptx, causant `NotImplementedError: Shape instance of unrecognized shape type`

### Problème
- Le fichier `RISE_with_SAP_Cloud_ERP_Private.pptx` échoue avec "Pipeline SimplePipeline failed"
- Erreur dans `docling/backend/mspowerpoint_backend.py` - shape type non supporté

### Solution proposée
1. **Dockerfile** - Ajouter LibreOffice headless (~500MB):
   ```dockerfile
   RUN apt-get update && apt-get install -y libreoffice-impress --no-install-recommends
   ```

2. **Nouveau helper** `src/knowbase/ingestion/components/extractors/pptx_to_pdf_converter.py`:
   ```python
   import subprocess
   from pathlib import Path

   def convert_pptx_to_pdf(pptx_path: Path) -> Path:
       """Convertit PPTX en PDF via LibreOffice headless."""
       subprocess.run([
           "libreoffice", "--headless", "--convert-to", "pdf",
           "--outdir", str(pptx_path.parent), str(pptx_path)
       ], check=True, timeout=120)
       return pptx_path.with_suffix(".pdf")
   ```

3. **Dans DoclingExtractor** - Fallback automatique:
   ```python
   try:
       result = self._extract_with_docling(file_path)
   except RuntimeError as e:
       if "SimplePipeline failed" in str(e) and file_path.suffix.lower() == ".pptx":
           logger.warning(f"[FALLBACK] PPTX extraction failed, converting to PDF: {file_path.name}")
           pdf_path = convert_pptx_to_pdf(file_path)
           result = self._extract_with_docling(pdf_path)
           # Nettoyer le PDF temporaire après
           pdf_path.unlink(missing_ok=True)
   ```

### Impact
- +500MB image Docker (LibreOffice)
- Temps de conversion: ~5-10s par fichier
- Meilleure compatibilité avec PPTX "exotiques"

---

## 2. [À documenter] Autres améliorations futures

- [ ] Retry automatique sur interruption Spot avec backoff exponentiel
- [ ] Notification Slack/Email quand batch terminé
- [ ] Estimation du temps restant basée sur throughput moyen

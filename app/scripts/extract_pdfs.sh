#!/bin/bash
mkdir -p /app/data/oracle_pdf_text
cd /data/docs_done
for pdf in dualuse_reg_2021_821_original.pdf cs25_amdt_28.pdf cs25_amdt_22.pdf cs25_amdt_26.pdf dualuse_del_2024_2547.pdf dualuse_del_2024_2025.pdf dualuse_reg_428_2009_original.pdf dualuse_del_2023_996.pdf; do
  base="${pdf%.pdf}"
  txt="/app/data/oracle_pdf_text/${base}.txt"
  pdftotext -layout "$pdf" "$txt"
  if [ -f "$txt" ]; then
    wc -l "$txt"
  fi
done

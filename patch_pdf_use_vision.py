#!/usr/bin/env python
"""
Script pour patcher le pdf_pipeline avec le branchement use_vision.
"""
import re

# Lire le fichier
pdf_pipeline_path = r"C:\Project\SAP_KB\src\knowbase\ingestion\pipelines\pdf_pipeline.py"

with open(pdf_pipeline_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern à remplacer
old_pattern = r'''        for page_index, img_path in image_paths\.items\(\):
            logger\.info\(f".*Page {page_index}/{len\(image_paths\)}"\)
            # Optionnel : extraire le texte de la page individuellement si besoin
            chunks = ask_gpt_slide_analysis\(
                img_path, pdf_text, pdf_path\.name, page_index, custom_prompt
            \)
            logger\.info\(f".*Page {page_index}: chunks générés = {len\(chunks\)}"\)
            ingest_chunks\(chunks, doc_meta, pdf_path\.stem, page_index\)
            total_chunks \+= len\(chunks\)'''

# Nouveau code avec branchement
new_code = '''        for page_index, img_path in image_paths.items():
            logger.info(f"📸 Page {page_index}/{len(image_paths)}")

            # Choisir entre Vision ou Text-only selon use_vision
            if use_vision:
                # Mode VISION : Utiliser GPT-4 Vision avec l'image
                chunks = ask_gpt_slide_analysis(
                    img_path, pdf_text, pdf_path.name, page_index, custom_prompt
                )
                logger.info(f"🧩 Page {page_index} [VISION]: chunks générés = {len(chunks)}")
                ingest_chunks(chunks, doc_meta, pdf_path.stem, page_index)
                total_chunks += len(chunks)
            else:
                # Mode TEXT-ONLY : Utiliser LLM rapide sans image
                result = ask_gpt_page_analysis_text_only(
                    pdf_text, pdf_path.name, page_index, custom_prompt
                )
                # Format nouveau : dict avec concepts, facts, entities, relations
                concepts = result.get("concepts", [])
                logger.info(f"🧩 Page {page_index} [TEXT-ONLY]: {len(concepts)} concepts générés")

                # Ingérer concepts dans Qdrant (conversion au format ancien pour compatibilité)
                chunks_compat = [{"text": c.get("full_explanation", ""), "meta": c.get("meta", {})} for c in concepts]
                ingest_chunks(chunks_compat, doc_meta, pdf_path.stem, page_index)
                total_chunks += len(chunks_compat)'''

# Remplacer en utilisant regex flexible
content_patched = re.sub(old_pattern, new_code, content, flags=re.DOTALL)

# Vérifier si le remplacement a fonctionné
if content_patched != content:
    with open(pdf_pipeline_path, 'w', encoding='utf-8') as f:
        f.write(content_patched)
    print("✅ Patch appliqué avec succès !")
else:
    print("⚠️ Pattern non trouvé, essai avec approche alternative...")

    # Approche alternative : chercher et remplacer ligne par ligne
    lines = content.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Détecter le début du bloc à remplacer
        if 'for page_index, img_path in image_paths.items():' in line and i > 415:
            # Ajouter la ligne for
            new_lines.append(line)
            i += 1

            # Skip logger.info Page
            while i < len(lines) and 'logger.info' in lines[i] and 'Page' in lines[i]:
                i += 1

            # Injecter le nouveau code
            new_lines.append('')
            new_lines.append('            # Choisir entre Vision ou Text-only selon use_vision')
            new_lines.append('            if use_vision:')
            new_lines.append('                # Mode VISION : Utiliser GPT-4 Vision avec l\'image')

            # Garder l'appel ask_gpt_slide_analysis mais indenté
            while i < len(lines) and ('chunks = ask_gpt_slide_analysis' in lines[i] or 'img_path' in lines[i] or ')' in lines[i]):
                new_lines.append('    ' + lines[i])  # Ajouter indentation
                i += 1
                if ')' in lines[i-1] and 'custom_prompt' in lines[i-1]:
                    break

            # Ajouter les logs et ingest pour Vision
            new_lines.append('                logger.info(f"🧩 Page {page_index} [VISION]: chunks générés = {len(chunks)}")')
            new_lines.append('                ingest_chunks(chunks, doc_meta, pdf_path.stem, page_index)')
            new_lines.append('                total_chunks += len(chunks)')

            # Skip les anciennes lignes logger.info et ingest_chunks
            while i < len(lines) and (('logger.info' in lines[i] and 'chunks générés' in lines[i]) or
                                      'ingest_chunks' in lines[i] or
                                      'total_chunks +=' in lines[i]):
                i += 1

            # Ajouter le else pour Text-only
            new_lines.append('            else:')
            new_lines.append('                # Mode TEXT-ONLY : Utiliser LLM rapide sans image')
            new_lines.append('                result = ask_gpt_page_analysis_text_only(')
            new_lines.append('                    pdf_text, pdf_path.name, page_index, custom_prompt')
            new_lines.append('                )')
            new_lines.append('                # Format nouveau : dict avec concepts, facts, entities, relations')
            new_lines.append('                concepts = result.get("concepts", [])')
            new_lines.append('                logger.info(f"🧩 Page {page_index} [TEXT-ONLY]: {len(concepts)} concepts générés")')
            new_lines.append('')
            new_lines.append('                # Ingérer concepts dans Qdrant (conversion au format ancien pour compatibilité)')
            new_lines.append('                chunks_compat = [{"text": c.get("full_explanation", ""), "meta": c.get("meta", {})} for c in concepts]')
            new_lines.append('                ingest_chunks(chunks_compat, doc_meta, pdf_path.stem, page_index)')
            new_lines.append('                total_chunks += len(chunks_compat)')

            continue

        new_lines.append(line)
        i += 1

    # Écrire le résultat
    with open(pdf_pipeline_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))

    print("✅ Patch appliqué avec approche alternative !")

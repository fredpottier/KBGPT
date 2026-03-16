"""
Téléchargement du corpus pré-éclampsie depuis PMC + Thermo Fisher.

Usage:
    python app/scripts/download_preeclampsia_corpus.py
    python app/scripts/download_preeclampsia_corpus.py --output-dir data/corpus/preeclampsia
"""

import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import requests

# ===========================================================================
# PMC IDs identifiés
# ===========================================================================

PMC_IDS = [
    # Ratio sFlt-1/PlGF — diagnostic/prédiction
    "PMC11202363",  # Dynamic prediction model using sFlt-1/PLGF ratio
    "PMC4369131",   # Implementation of sFlt-1/PlGF ratio for prediction
    "PMC10500221",  # Predictive value of sFlt-1/PlGF ratio (update review)
    "PMC7006116",   # Diagnostic accuracy of sFlt1/PlGF ratio
    "PMC11239699",  # sFlt1/PlGF considering hypertensive status
    "PMC8870556",   # sFlt-1/PlGF ratio in clinical routine (real-world)
    "PMC7098437",   # Combining biomarkers — Angiogenic-Placental Syndrome
    "PMC5736685",   # Evaluation of sFlt-1/PlGF for predicting & improving

    # Pathophysiologie
    "PMC8884164",   # Imbalances in circulating angiogenic factors
    "PMC3063446",   # Angiogenic Factors and Preeclampsia
    "PMC4515231",   # Imbalance in angiogenic/anti-angiogenic factors
    "PMC6472952",   # Pre-eclampsia: pathogenesis, diagnostics and therapies
    "PMC12452302",  # Understanding Preeclampsia: pathophysiology, biomarkers

    # Screening 1er trimestre
    "PMC9361843",   # First-trimester sequential screening (multicenter)
    "PMC9507456",   # Reviewing accuracy of first trimester screening
    "PMC7235780",   # Diagnostic performance uterine artery + risk factors
    "PMC8913542",   # Prediction using uterine artery Doppler and PAPP-A
    "PMC12461270",  # First-trimester prediction using PAPP-A and MAP

    # Revues / Guidelines / HTA
    "PMC11131432",  # Biomarkers for Early Prediction: Comprehensive Review
    "PMC8649230",   # Decision threshold Kryptor sFlt-1/PlGF (BRAHMS)
    "PMC10241193",  # PlGF-based biomarker testing (Health Technology Assessment)
    "PMC9962022",   # Recent advances in predicting, preventing, managing PE

    # Extras
    "PMC10928726",  # PE37 study protocol (screening with sFlt1/PlGF)
    "PMC9413067",   # Prediction model using machine learning (China)
    "PMC4127237",   # Early Prediction of Preeclampsia
    "PMC3407628",   # Early Detection of Maternal Risk
    "PMC12476626",  # Non-coding RNAs as diagnostic biomarkers
    "PMC2846114",   # Change in angiogenic factors between trimesters
]

# ===========================================================================
# Thermo Fisher / BRAHMS documents
# ===========================================================================

THERMOFISHER_DOCS = [
    {
        "id": "TF_lit_review_pe_ratio",
        "title": "Pre-eclampsia diagnosis and prognosis - Literature Review (Thermo Fisher BRAHMS)",
        "url": "https://documents.thermofisher.com/TFS-Assets/CDD/Reference-Materials/Lit_Review_PNS_PE_Ratio-Ratio-BMKT001314.1_EN_OUS-SCREEN-v6.pdf",
        "type": "pdf",
    },
    {
        "id": "TF_lit_review_1st_trimester",
        "title": "First trimester pre-eclampsia screening - Literature Review (Thermo Fisher BRAHMS)",
        "url": "https://documents.thermofisher.com/TFS-Assets/CDD/Reference-Materials/Lit_Review_PNS_PE_1stT_BMKT001300.1_EN_OUS-v8-Final.pdf",
        "type": "pdf",
    },
    {
        "id": "TF_datasheet_us_pe",
        "title": "PlGF and sFlt-1 assays on KRYPTOR - US Datasheet (Thermo Fisher BRAHMS)",
        "url": "https://documents.thermofisher.com/TFS-Assets/CDD/Datasheets/Datasheet-US-pre-eclampsia-Diagnosis-BMKT001031.2%20EN-SCREEN.pdf",
        "type": "pdf",
    },
    {
        "id": "TF_brochure_pe",
        "title": "Preeclampsia Management Brochure (Thermo Fisher BRAHMS)",
        "url": "https://documents.thermofisher.com/TFS-Assets/CDD/brochures/Brochure-US-PNS-Pre-eclampsia-Diagnosis-BMKT001029.2-EN-SCREEN.pdf",
        "type": "pdf",
    },
    {
        "id": "TF_datasheet_ous_plgf_sflt1",
        "title": "Pre-eclampsia throughout pregnancy PAPP-A PlGF sFlt-1 (Thermo Fisher BRAHMS OUS)",
        "url": "https://documents.thermofisher.com/TFS-Assets/CDD/Datasheets/PNS_datasheet_PlGF_sFlt-1_BMKT001066.2_EN_OUS%20(1).pdf",
        "type": "pdf",
    },
    {
        "id": "TF_fda_clearance",
        "title": "FDA Clearance Document BRAHMS sFlt-1 PlGF KRYPTOR (DEN220027)",
        "url": "https://www.accessdata.fda.gov/cdrh_docs/pdf22/DEN220027.pdf",
        "type": "pdf",
    },
]

THERMOFISHER_PAGES = [
    {
        "id": "TF_clinical_solutions",
        "title": "PreClara Ratio sFlt-1 PlGF for Preeclampsia Management - Clinical Solutions (Thermo Fisher)",
        "url": "https://www.thermofisher.com/us/en/home/clinical/diagnostic-testing/brahms/prenatal-screening/preeclampsia-screening/clinical-solutions.html",
    },
    {
        "id": "TF_understanding_pe",
        "title": "Understanding Preeclampsia (Thermo Fisher Scientific)",
        "url": "https://www.thermofisher.com/us/en/home/clinical/diagnostic-testing/brahms/prenatal-screening/preeclampsia-screening/understanding-preeclampsia.html",
    },
    {
        "id": "TF_lab_solutions",
        "title": "BRAHMS Lab Solutions Preeclampsia Management (Thermo Fisher)",
        "url": "https://www.thermofisher.com/us/en/home/clinical/diagnostic-testing/brahms/prenatal-screening/preeclampsia-screening/lab-solutions.html",
    },
]


# ===========================================================================
# PMC Download
# ===========================================================================

PMC_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMC_OA_API = "https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi"


def fetch_pmc_article(pmc_id: str) -> Optional[dict]:
    """Fetch un article PMC via l'API efetch (XML full text)."""
    numeric_id = pmc_id.replace("PMC", "")

    # Essayer l'API efetch d'abord
    url = f"{PMC_API}/efetch.fcgi?db=pmc&id={numeric_id}&rettype=xml"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  [WARN] HTTP {resp.status_code} for {pmc_id}")
            return None

        root = ET.fromstring(resp.content)
        article = root.find(".//article")
        if article is None:
            print(f"  [WARN] No <article> in XML for {pmc_id}")
            return None

        # Extraire le titre
        title_el = article.find(".//article-title")
        title = "".join(title_el.itertext()).strip() if title_el is not None else pmc_id

        # Extraire l'abstract
        abstract_parts = []
        for abstract in article.findall(".//abstract"):
            for p in abstract.findall(".//p"):
                text = "".join(p.itertext()).strip()
                if text:
                    abstract_parts.append(text)
        abstract = "\n\n".join(abstract_parts)

        # Extraire le body
        body_parts = []
        for body in article.findall(".//body"):
            for sec in body.findall(".//sec"):
                sec_title = sec.find("title")
                if sec_title is not None:
                    body_parts.append(f"\n## {''.join(sec_title.itertext()).strip()}\n")
                for p in sec.findall(".//p"):
                    text = "".join(p.itertext()).strip()
                    if text:
                        body_parts.append(text)

        body = "\n\n".join(body_parts)

        # Extraire les auteurs
        authors = []
        for contrib in article.findall(".//contrib[@contrib-type='author']"):
            surname = contrib.find("name/surname")
            given = contrib.find("name/given-names")
            if surname is not None:
                name = "".join(surname.itertext())
                if given is not None:
                    name = "".join(given.itertext()) + " " + name
                authors.append(name)

        # Extraire le journal et l'année
        journal_el = article.find(".//journal-title")
        journal = "".join(journal_el.itertext()).strip() if journal_el is not None else ""
        year_el = article.find(".//pub-date/year")
        year = "".join(year_el.itertext()).strip() if year_el is not None else ""

        return {
            "pmc_id": pmc_id,
            "title": title,
            "authors": authors,
            "journal": journal,
            "year": year,
            "abstract": abstract,
            "body": body,
        }

    except Exception as e:
        print(f"  [ERROR] {pmc_id}: {e}")
        return None


def article_to_markdown(article: dict) -> str:
    """Convertit un article en Markdown."""
    parts = [f"# {article['title']}\n"]

    if article.get("authors"):
        parts.append(f"**Authors:** {', '.join(article['authors'][:10])}\n")
    if article.get("journal"):
        parts.append(f"**Journal:** {article['journal']}")
    if article.get("year"):
        parts.append(f"**Year:** {article['year']}")
    parts.append(f"**PMC ID:** {article['pmc_id']}\n")

    if article.get("abstract"):
        parts.append("## Abstract\n")
        parts.append(article["abstract"])

    if article.get("body"):
        parts.append("\n" + article["body"])

    return "\n\n".join(parts)


def sanitize_filename(title: str, pmc_id: str) -> str:
    """Crée un nom de fichier propre."""
    clean = re.sub(r'[^\w\s-]', '', title.lower())
    clean = re.sub(r'\s+', '_', clean.strip())
    clean = clean[:80]
    return f"{pmc_id}_{clean}"


# ===========================================================================
# Thermo Fisher Download
# ===========================================================================

def fetch_thermofisher_page(url: str) -> Optional[str]:
    """Extrait le contenu textuel d'une page web Thermo Fisher."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None

        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
                self.skip_tags = {"script", "style", "nav", "footer", "header"}
                self.current_skip = 0

            def handle_starttag(self, tag, attrs):
                if tag in self.skip_tags:
                    self.current_skip += 1
                if tag in ("h1", "h2", "h3"):
                    self.text_parts.append(f"\n## ")
                elif tag == "p":
                    self.text_parts.append("\n\n")
                elif tag == "li":
                    self.text_parts.append("\n- ")

            def handle_endtag(self, tag):
                if tag in self.skip_tags:
                    self.current_skip -= 1

            def handle_data(self, data):
                if self.current_skip <= 0:
                    text = data.strip()
                    if text:
                        self.text_parts.append(text + " ")

        parser = TextExtractor()
        parser.feed(resp.text)
        text = "".join(parser.text_parts)

        # Nettoyer
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()

    except Exception as e:
        print(f"  [ERROR] Page fetch: {e}")
        return None


def fetch_pdf_text(url: str) -> Optional[str]:
    """Télécharge un PDF et en extrait le texte (fallback: juste les métadonnées)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            print(f"  [WARN] HTTP {resp.status_code} for PDF")
            return None

        # Essayer PyPDF si disponible
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(resp.content))
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            if text_parts:
                return "\n\n".join(text_parts)
        except ImportError:
            pass

        # Fallback: sauvegarder le PDF et indiquer qu'il faudra le traiter
        return f"[PDF document - {len(resp.content)} bytes - requires OCR/extraction pipeline]"

    except Exception as e:
        print(f"  [ERROR] PDF fetch: {e}")
        return None


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/corpus/preeclampsia")
    parser.add_argument("--pending-dir", default="data/burst/pending")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    pending_dir = Path(args.pending_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pending_dir.mkdir(parents=True, exist_ok=True)

    total_files = 0

    # === PMC Articles ===
    print(f"\n{'='*60}")
    print(f"Téléchargement de {len(PMC_IDS)} articles PMC")
    print(f"{'='*60}")

    for i, pmc_id in enumerate(PMC_IDS, 1):
        print(f"\n[{i}/{len(PMC_IDS)}] {pmc_id}...")
        article = fetch_pmc_article(pmc_id)
        if not article:
            print(f"  [SKIP] Pas de contenu")
            continue

        md = article_to_markdown(article)

        # Vérifier que le contenu a de la substance
        if len(md) < 500:
            print(f"  [SKIP] Contenu trop court ({len(md)} chars)")
            continue

        filename = sanitize_filename(article["title"], pmc_id)

        # Sauvegarder dans corpus
        corpus_path = output_dir / f"{filename}.md"
        corpus_path.write_text(md, encoding="utf-8")

        # Copier dans pending pour import
        pending_path = pending_dir / f"{filename}.md"
        pending_path.write_text(md, encoding="utf-8")

        print(f"  OK: {article['title'][:60]}... ({len(md)} chars)")
        total_files += 1

        # Rate limit PMC API
        time.sleep(0.5)

    # === Thermo Fisher Pages ===
    print(f"\n{'='*60}")
    print(f"Extraction de {len(THERMOFISHER_PAGES)} pages Thermo Fisher")
    print(f"{'='*60}")

    for i, doc in enumerate(THERMOFISHER_PAGES, 1):
        print(f"\n[{i}/{len(THERMOFISHER_PAGES)}] {doc['title'][:60]}...")
        content = fetch_thermofisher_page(doc["url"])
        if not content or len(content) < 200:
            print(f"  [SKIP] Pas de contenu exploitable")
            continue

        md = f"# {doc['title']}\n\n**Source:** Thermo Fisher Scientific\n**URL:** {doc['url']}\n\n{content}"
        filename = doc["id"]

        corpus_path = output_dir / f"{filename}.md"
        corpus_path.write_text(md, encoding="utf-8")
        pending_path = pending_dir / f"{filename}.md"
        pending_path.write_text(md, encoding="utf-8")

        print(f"  OK: {len(md)} chars")
        total_files += 1

    # === Thermo Fisher PDFs ===
    print(f"\n{'='*60}")
    print(f"Téléchargement de {len(THERMOFISHER_DOCS)} PDFs Thermo Fisher")
    print(f"{'='*60}")

    for i, doc in enumerate(THERMOFISHER_DOCS, 1):
        print(f"\n[{i}/{len(THERMOFISHER_DOCS)}] {doc['title'][:60]}...")
        content = fetch_pdf_text(doc["url"])
        if not content or len(content) < 200:
            print(f"  [SKIP] Pas de contenu exploitable")
            continue

        if content.startswith("[PDF document"):
            print(f"  [INFO] PDF brut sauvegardé (pas de PyPDF)")
            # Sauvegarder quand même avec les métadonnées
            md = f"# {doc['title']}\n\n**Source:** Thermo Fisher Scientific / BRAHMS\n**URL:** {doc['url']}\n**Type:** PDF Technical Document\n\n{content}"
        else:
            md = f"# {doc['title']}\n\n**Source:** Thermo Fisher Scientific / BRAHMS\n**URL:** {doc['url']}\n**Type:** PDF Technical Document\n\n{content}"

        filename = doc["id"]
        corpus_path = output_dir / f"{filename}.md"
        corpus_path.write_text(md, encoding="utf-8")
        pending_path = pending_dir / f"{filename}.md"
        pending_path.write_text(md, encoding="utf-8")

        print(f"  OK: {len(md)} chars")
        total_files += 1

    # === Résumé ===
    print(f"\n{'='*60}")
    print(f"CORPUS PRÉ-ÉCLAMPSIE TERMINÉ")
    print(f"{'='*60}")
    print(f"Fichiers créés: {total_files}")
    print(f"Corpus: {output_dir}")
    print(f"Pending: {pending_dir}")


if __name__ == "__main__":
    main()

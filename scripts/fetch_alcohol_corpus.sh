#!/usr/bin/env bash
# Télécharge le corpus open-access « Alcool & santé » dans un dossier de STAGING
# (data/corpus_alcohol_health/), PAS dans docs_in → pas d'auto-ingestion dans le
# corpus actif (aero) par le folder_watcher. Demain : activer le corpus
# alcohol_health, puis déplacer ces PDF dans data/docs_in/.
#
# PMC = via l'API Europe PMC (open-access fiable en curl). Direct = éditeur/gouv.
set -u
OUT="data/corpus_alcohol_health"
mkdir -p "$OUT"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
ok=0; fail=0

dl_pmc() {  # $1=PMCID  $2=filename
  local f="$OUT/$2"
  curl -sL -A "$UA" "https://europepmc.org/api/getPdf?pmcid=$1&blobtype=pdf" -o "$f"
  _check "$f" "$2"
}
dl_url() {  # $1=url  $2=filename
  local f="$OUT/$2"
  curl -sL -A "$UA" "$1" -o "$f"
  _check "$f" "$2"
}
_check() {  # $1=path $2=name
  if [ -s "$1" ] && head -c 5 "$1" | grep -q '%PDF' && [ "$(wc -c < "$1")" -gt 20000 ]; then
    echo "  OK   $2 ($(($(wc -c < "$1")/1024)) KB)"; ok=$((ok+1))
  else
    echo "  FAIL $2"; rm -f "$1"; fail=$((fail+1))
  fi
}

echo "== Mortalité / méthodologie =="
dl_pmc PMC10066463 "Zhao2023_alcohol_all-cause-mortality_metaanalysis_JAMANetwOpen.pdf"
dl_pmc PMC4803651  "Stockwell2016_moderate-drinkers-mortality-abstainer-bias_JSAD.pdf"
dl_pmc PMC3043109  "Ronksley2011_alcohol-cardiovascular-outcomes_metaanalysis_BMJ.pdf"

echo "== Cardiovasculaire / randomisation mendélienne =="
dl_url "https://www.bmj.com/content/bmj/349/bmj.g4164.full.pdf" "Holmes2014_alcohol-CVD-mendelian-randomization_BMJ.pdf"
dl_pmc PMC8956974  "Biddinger2022_habitual-alcohol-CVD-mendelian_JAMANetwOpen.pdf"
dl_pmc PMC11629435 "MVP2024_alcohol-cardiometabolic-mendelian_MillionVeteran.pdf"

echo "== AVC =="
dl_pmc PMC2888740  "Patra2010_alcohol-stroke-types-morbidity-mortality_metaanalysis.pdf"
dl_pmc PMC5121939  "Larsson2016_alcohol-different-stroke-types_metaanalysis.pdf"

echo "== Cancers =="
dl_pmc PMC10867516 "2023_cancer-risk-by-alcohol-consumption-levels_metaanalysis.pdf"
dl_pmc PMC11629438 "Sohi2024_alcohol-breast-cancer_metaanalysis_ACER.pdf"
dl_pmc PMC4551426  "2015_moderate-alcohol-breast-cancer-mechanisms.pdf"
dl_pmc PMC4788838  "2016_alcohol-pancreatic-cancer_dose-response-metaanalysis.pdf"

echo "== Démence / cerveau =="
dl_pmc PMC11405827 "2024_alcohol-dementia_mendelian-randomization_eClinicalMedicine.pdf"
dl_pmc PMC7057166  "2020_alcohol-alzheimer_mendelian-randomization.pdf"
dl_pmc PMC9282660  "Topiwala2022_moderate-alcohol-brain-iron-cognition_PLOSMed.pdf"
dl_url "https://www.nature.com/articles/s41467-022-28735-5.pdf" "2022_alcohol-grey-white-matter-volume_UKBiobank_NatureComms.pdf"

echo "== Métabolique =="
dl_pmc PMC2768203  "Baliunas2009_alcohol-type2-diabetes_metaanalysis.pdf"
dl_pmc PMC10510850 "2023_alcohol-blood-pressure_dose-response-metaanalysis_Hypertension.pdf"
dl_pmc PMC11251509 "2024_alcohol-hypertension-risk_dose-response-metaanalysis.pdf"

echo "== Autres comorbidités (parfois protectrices) =="
dl_pmc PMC8907587  "2022_alcohol-atrial-fibrillation_dose-response-metaanalysis.pdf"
dl_pmc PMC3299482  "Irving2009_alcohol-pancreatitis_metaanalysis.pdf"
dl_url "https://www.nature.com/articles/s41598-021-89618-1.pdf" "2021_alcohol-rheumatoid-arthritis-activity_metaanalysis_SciRep.pdf"
dl_url "https://www.frontiersin.org/articles/10.3389/fnut.2022.940689/pdf" "2022_alcohol-gallstone-disease_dose-response-mendelian_Frontiers.pdf"

echo "== Guidelines / prises de position (lignée temporelle + normatif) =="
dl_url "https://www.ccsa.ca/sites/default/files/2023-01/CCSA_Canadas_Guidance_on_Alcohol_and_Health_Final_Report_en.pdf" "CCSA2023_Canada-guidance-alcohol-health_2drinks-week.pdf"
dl_pmc PMC7067094  "2020_MACH15-alcohol-industry-involvement_cancelled-trial.pdf"
dl_url "https://www.thelancet.com/action/showPdf?pii=S2468-2667%2822%2900317-6" "2023_low-levels-alcohol-cancer-risks_LancetPublicHealth.pdf"

echo ""
echo "== BILAN : $ok téléchargés, $fail échecs =="
ls -1 "$OUT"/*.pdf 2>/dev/null | wc -l
rm -f "$OUT"/_test_*.pdf

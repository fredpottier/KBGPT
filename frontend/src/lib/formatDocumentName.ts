/**
 * Format human-readable document names from raw source paths.
 *
 * Use cases :
 *   "data/docs_in/027_SAP_S4HANA_2023_Security_Guide_c160af0e.pdf"
 *     → "SAP S/4HANA 2023 Security Guide"
 *   "dualuse_reg_2021_821_original_65eef5dc.pdf"
 *     → "Dualuse Reg 2021 821 Original"
 *   "cs25_amdt_28_32f1a9ac.pdf"
 *     → "Cs25 Amdt 28"
 *
 * Helpers exposés :
 *   - formatDocumentName(sourceFile) : nom lisible (sans path, ext, hash, prefix)
 *   - getFileExtension(sourceFile) : extension uppercase (PDF, PPTX, etc.) ou 'FILE'
 *
 * Centralisé dans CH-05.2 (cf. doc/ongoing/TRACKING_CHANTIERS_2026-05-02.md).
 * Remplace 3 implémentations dupliquées dans SearchResultDisplay, SourcesSection,
 * ThumbnailCarousel.
 */

const HASH_SUFFIX_RE = /_[a-f0-9]{6,}$/i;
const NUMERIC_PREFIX_RE = /^\d{3}_(\d+_)?/;
const EXTENSION_RE = /\.\w+$/;

/** Tronque à `max` chars avec "…" si dépassement. */
function truncate(str: string, max = 55): string {
  if (str.length <= max) return str;
  return str.substring(0, max - 3) + "...";
}

/**
 * Retourne le nom lisible d'un document à partir du source_file brut.
 *
 * Étapes :
 *   1. Extrait le filename (path/to/file.ext → file.ext)
 *   2. Retire le hash final (ex: `_c160af0e`)
 *   3. Retire le préfixe numérique (ex: `027_`, `027_1212_`)
 *   4. Retire l'extension
 *   5. Remplace underscores et tirets par espaces, capitalise chaque mot
 *   6. Tronque à 55 chars
 */
export function formatDocumentName(sourceFile: string | undefined | null): string {
  if (!sourceFile) return "";
  let name = sourceFile.split("/").pop() || sourceFile;
  name = name.replace(HASH_SUFFIX_RE, "");
  name = name.replace(NUMERIC_PREFIX_RE, "");
  name = name.replace(EXTENSION_RE, "");
  name = name.replace(/[_-]+/g, " ").trim();
  // Title case basique : capitalise chaque mot tout en respectant les acronymes/numéros
  name = name
    .split(" ")
    .map((tok) => {
      if (!tok) return tok;
      if (/^\d/.test(tok)) return tok; // commence par un chiffre → laisser tel quel
      if (tok === tok.toUpperCase() && tok.length > 1) return tok; // acronyme déjà uppercase
      return tok.charAt(0).toUpperCase() + tok.slice(1);
    })
    .join(" ");
  return truncate(name) || sourceFile;
}

/**
 * Retourne l'extension uppercase d'un source_file (avant tout cleanup).
 *
 * Ex: "027_SAP_S4HANA_2023_Security_Guide_c160af0e.pdf" → "PDF"
 *     "data/docs_in/file.pptx" → "PPTX"
 *     "no-extension" → "FILE"
 */
export function getFileExtension(sourceFile: string | undefined | null): string {
  if (!sourceFile) return "FILE";
  const filename = sourceFile.split("/").pop() || sourceFile;
  const match = filename.match(EXTENSION_RE);
  if (!match) return "FILE";
  return match[0].slice(1).toUpperCase();
}

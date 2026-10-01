import { validateBudgetFile, validateMappingFile } from "../services/api";

const PL_ALLOWED_EXTENSIONS = ["xlsx", "xls"];
const WORKBOOK_MAX_SIZE_BYTES = 50 * 1024 * 1024; // Budget & Mapping: 50 MB, same as backend MAX_FILE_SIZE_MB
const PL_MAX_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB

const TB_ALLOWED_EXTENSIONS = ["txt", "xlsx", "xls"];
const TB_MAX_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB
const TB_LABELS = {
  tb_current: "Current Year Trial Balance",
  tb_previous: "Previous Year Trial Balance",
};

// Same flexfield pattern and revenue GL range the backend uses when it reads
// TXT trial balances (backend/services/file_reader.py -> read_txt_trial_balance).
const TB_FLEX_PATTERN =
  /\b(\d{2}\.\d{1,5}\.\d{1,4}\.\d{1,4}\.\d{1,5}\.(\d{5,7})\.\d{1,4}\.\d{1,4}\.\d{1,5})\b/;
const REVENUE_GL_MIN = 400000;
const REVENUE_GL_MAX = 429999;

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

const getExtension = (file) =>
  file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";

const fail = (title, errorMessage) => ({ isValid: false, title, errorMessage });

/**
 * Reads the first bytes of a file and reports its container type:
 * "zip" (.xlsx), "ole" (legacy .xls) or null (anything else).
 */
function readExcelSignature(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const bytes = new Uint8Array(e.target.result || []);
      // .xlsx is a ZIP container: 50 4B 03 04 ("PK..")
      if (bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04) {
        resolve("zip");
        return;
      }
      // .xls is an OLE2 compound document: D0 CF 11 E0 A1 B1 1A E1
      if (
        bytes[0] === 0xd0 && bytes[1] === 0xcf && bytes[2] === 0x11 && bytes[3] === 0xe0 &&
        bytes[4] === 0xa1 && bytes[5] === 0xb1 && bytes[6] === 0x1a && bytes[7] === 0xe1
      ) {
        resolve("ole");
        return;
      }
      resolve(null);
    };
    reader.onerror = () => resolve(null);
    reader.readAsArrayBuffer(file.slice(0, 8));
  });
}

const isExcelSignatureValid = (ext, signature) =>
  (ext === "xlsx" && signature === "zip") || (ext === "xls" && (signature === "ole" || signature === "zip"));

/**
 * Validates the PL / Total Revenue workbook before upload.
 * Checks: file present, not empty, .xlsx/.xls extension, size limit, and
 * the file signature (so a renamed non-Excel file is rejected).
 * @param {File} file - The file object from the input.
 */
export async function validatePLFile(file) {
  if (!file) {
    return fail("No File Selected", "Please choose a PL Excel file (.xlsx or .xls) before uploading.");
  }

  const ext = getExtension(file);
  if (!PL_ALLOWED_EXTENSIONS.includes(ext)) {
    return fail(
      "Unsupported File Format",
      `"${file.name}" is not a supported file. The PL / Total Revenue upload only accepts Excel workbooks (.xlsx or .xls).`
    );
  }

  if (file.size === 0) {
    return fail("Empty File", `"${file.name}" is empty (0 KB). Please select a PL workbook that contains data.`);
  }

  if (file.size > PL_MAX_SIZE_BYTES) {
    return fail(
      "File Too Large",
      `"${file.name}" is ${(file.size / (1024 * 1024)).toFixed(1)} MB. The maximum allowed size for a PL workbook is 25 MB.`
    );
  }

  const signature = await readExcelSignature(file);
  if (!isExcelSignatureValid(ext, signature)) {
    return fail(
      "Invalid Excel File",
      `"${file.name}" has an Excel extension but is not a valid Excel workbook. It may be corrupted or a renamed file. Please export the PL report again from Excel and retry.`
    );
  }

  return { isValid: true, title: null, errorMessage: null };
}

/**
 * Validates a Current / Previous Year Trial Balance file.
 *
 * All files: extension (.txt/.xlsx/.xls), not empty, size limit.
 * Excel files: file signature (renamed / corrupted files are rejected).
 * TXT files:
 *   - must be a real text file (not a renamed binary)
 *   - must be a "PTD - Shared Revenue only" report, not a standard YTD TB (original rule)
 *   - must be an Oracle "Detail Trial Balance" report
 *   - must contain account rows with flexfields
 *   - must contain revenue GL codes 400000-429999 (the range the GL filter keeps)
 *   - must cover exactly one period ("Period to date for Jun-26")
 *
 * @param {File} file - The file object from the input.
 * @param {string} key - "tb_current" or "tb_previous".
 * @returns {Promise<{isValid, title, errorMessage, period}>} period is
 *   { month, year, label } for TXT files, null when it cannot be read.
 */
export async function validateTrialBalanceFile(file, key) {
  const label = TB_LABELS[key] || "Trial Balance";

  if (!file) {
    return fail("No File Selected", `Please choose a ${label} file (.txt, .xlsx or .xls).`);
  }

  const ext = getExtension(file);
  if (!TB_ALLOWED_EXTENSIONS.includes(ext)) {
    return fail(
      "Unsupported File Format",
      `"${file.name}" is not a supported file. The ${label} only accepts the 'PTD - Shared Revenue only' report as a .txt file, or an Excel workbook (.xlsx or .xls).`
    );
  }

  if (file.size === 0) {
    return fail("Empty File", `"${file.name}" is empty (0 KB). Please select a ${label} file that contains data.`);
  }

  if (file.size > TB_MAX_SIZE_BYTES) {
    return fail(
      "File Too Large",
      `"${file.name}" is ${(file.size / (1024 * 1024)).toFixed(1)} MB. The maximum allowed size for a Trial Balance file is 50 MB.`
    );
  }

  if (ext !== "txt") {
    const signature = await readExcelSignature(file);
    if (!isExcelSignatureValid(ext, signature)) {
      return fail(
        "Invalid Excel File",
        `"${file.name}" has an Excel extension but is not a valid Excel workbook. It may be corrupted or a renamed file.`
      );
    }
    return { isValid: true, title: null, errorMessage: null, period: null };
  }

  let content;
  try {
    content = await file.text();
  } catch (err) {
    console.error("Error reading Trial Balance text file:", err);
    return fail("Unreadable File", `"${file.name}" could not be read. Please check the file and try again.`);
  }

  if (content.includes("\u0000")) {
    return fail(
      "Invalid Text File",
      `"${file.name}" has a .txt extension but is not a text file. It may be a renamed Excel, PDF or other binary file.`
    );
  }

  if (!content.trim()) {
    return fail("Empty File", `"${file.name}" contains only blank lines. Please select a ${label} file that contains data.`);
  }

  // Original rule: standard (YTD) Trial Balance files are rejected; only the
  // "PTD - Shared Revenue only" report is accepted.
  const lowerContent = content.toLowerCase();
  const isYTD = lowerContent.includes("year to date as of");
  const isPTD = lowerContent.includes("period to date for") || lowerContent.includes("period to date");
  if (isYTD || !isPTD) {
    return fail(
      "Unsupported File Format",
      "This file is not supported. Standard Trial Balance files cannot be uploaded to the system. Please upload the 'PTD - Shared Revenue only' file."
    );
  }

  if (!lowerContent.includes("detail trial balance")) {
    return fail(
      "Unrecognised Report Layout",
      `"${file.name}" is not an Oracle 'Detail Trial Balance' report. Please export the 'PTD - Shared Revenue only' Detail Trial Balance and upload that file.`
    );
  }

  let accountRows = 0;
  let revenueRows = 0;
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.replace(/\f/g, "").trim();
    const match = TB_FLEX_PATTERN.exec(line);
    if (!match) continue;
    accountRows += 1;

    // Same GL code rule as the backend: leading account number, else flexfield segment 6
    const firstToken = line.slice(0, match.index).trim().split(/\s+/)[0];
    const glCode = /^\d+$/.test(firstToken) ? Number(firstToken) : Number(match[2]);
    if (glCode >= REVENUE_GL_MIN && glCode <= REVENUE_GL_MAX) {
      revenueRows += 1;
    }
  }

  if (accountRows === 0) {
    return fail(
      "No Account Rows Found",
      `"${file.name}" does not contain any account lines (e.g. "411101  Initiation - Gross  01.1121.000.11.265.411101.12.00.000 ..."). The file may be truncated or exported in the wrong format.`
    );
  }

  if (revenueRows === 0) {
    return fail(
      "No Revenue GL Codes",
      `"${file.name}" has ${accountRows.toLocaleString()} account lines, but none use a revenue GL code (${REVENUE_GL_MIN}–${REVENUE_GL_MAX}). Please upload the 'PTD - Shared Revenue only' report.`
    );
  }

  const periods = new Map();
  for (const m of content.matchAll(/period to date for\s+([a-z]{3})-(\d{2,4})/gi)) {
    const monthIdx = MONTHS.indexOf(m[1].toLowerCase());
    if (monthIdx === -1) continue;
    const year = m[2].length === 2 ? 2000 + Number(m[2]) : Number(m[2]);
    const periodLabel = `${m[1][0].toUpperCase()}${m[1].slice(1).toLowerCase()} ${year}`;
    periods.set(periodLabel, { month: monthIdx + 1, year, label: periodLabel });
  }

  if (periods.size > 1) {
    return fail(
      "Multiple Periods Found",
      `"${file.name}" contains more than one period (${[...periods.keys()].join(", ")}). A Trial Balance file must cover a single month.`
    );
  }

  const period = periods.size === 1 ? [...periods.values()][0] : null;
  console.log(`File accepted: PTD Shared Revenue file confirmed for ${key}`, { accountRows, revenueRows, period });
  return { isValid: true, title: null, errorMessage: null, period };
}

/**
 * Shared checks for the Budget and Mapping workbooks.
 *
 * In the browser: .xlsx only (the backend readers use openpyxl, which cannot
 * open legacy .xls), not empty, size limit, real Excel file signature.
 * Then the server validator reads the workbook contents.
 *
 * @param {File} file - The file object from the input.
 * @param {string} label - e.g. "Revenue Budget Workbook".
 * @param {(file: File) => Promise<{is_valid, errors}>} serverCheck - API call.
 * @returns {Promise<{isValid, title, errorMessage, check}>} check is the server response.
 */
async function validateServerCheckedWorkbook(file, label, serverCheck) {
  if (!file) {
    return fail("No File Selected", `Please choose a ${label} (.xlsx).`);
  }

  const ext = getExtension(file);
  if (ext === "xls") {
    return fail(
      "Unsupported File Format",
      `"${file.name}" is an old Excel 97-2003 (.xls) file. Please open it in Excel and use Save As > Excel Workbook (.xlsx), then upload the .xlsx file.`
    );
  }
  if (ext !== "xlsx") {
    return fail(
      "Unsupported File Format",
      `"${file.name}" is not a supported file. The ${label} must be an Excel workbook (.xlsx).`
    );
  }

  if (file.size === 0) {
    return fail("Empty File", `"${file.name}" is empty (0 KB). Please select a ${label} that contains data.`);
  }

  if (file.size > WORKBOOK_MAX_SIZE_BYTES) {
    return fail(
      "File Too Large",
      `"${file.name}" is ${(file.size / (1024 * 1024)).toFixed(1)} MB. The maximum allowed size for the ${label} is 50 MB.`
    );
  }

  const signature = await readExcelSignature(file);
  if (!isExcelSignatureValid(ext, signature)) {
    return fail(
      "Invalid Excel File",
      `"${file.name}" has an Excel extension but is not a valid Excel workbook. It may be corrupted or a renamed file.`
    );
  }

  let check;
  try {
    check = await serverCheck(file);
  } catch (err) {
    return fail(
      "Validation Unavailable",
      `"${file.name}" could not be checked because the server did not respond (${err.message}). Please try again.`
    );
  }

  if (!check.is_valid) {
    return fail(`Invalid ${label.replace("Revenue ", "")}`, `"${file.name}": ${check.errors.join(" ")}`);
  }

  return { isValid: true, title: null, errorMessage: null, check };
}

/**
 * Validates the Revenue Budget workbook.
 * Server checks (/api/validate-budget): 'FRM' sheet, 'Operating Revenue' heading,
 * Jan-Dec month columns for one year, coded revenue lines, numeric targets with
 * no Excel error values (#REF! etc.), and lines that map to the slide categories.
 *
 * @param {File} file - The file object from the input.
 * @returns {Promise<{isValid, title, errorMessage, meta}>} meta is
 *   { budget_year, months_with_data } when valid.
 */
export async function validateBudgetWorkbook(file) {
  const result = await validateServerCheckedWorkbook(file, "Revenue Budget Workbook", validateBudgetFile);
  if (!result.isValid) return result;

  const { check } = result;
  return {
    isValid: true,
    title: null,
    errorMessage: null,
    meta: { budget_year: check.budget_year, months_with_data: check.months_with_data || [] },
  };
}

/**
 * Validates the Revenue Mapping workbook.
 * Server checks (/api/validate-mapping): 'Code Mapping' sheet, the A-L header
 * row (Heading in Revenue Slide ... BUSINESS_LINE_TO), numeric FROM/TO codes with
 * FROM <= TO, revenue account codes (400000-499999), no catch-all rules, and
 * headings that cover every revenue slide category.
 *
 * @param {File} file - The file object from the input.
 */
export async function validateMappingWorkbook(file) {
  const result = await validateServerCheckedWorkbook(file, "Revenue Mapping Workbook", validateMappingFile);
  if (!result.isValid) return result;
  return { isValid: true, title: null, errorMessage: null };
}

/**
 * Checks the budget covers the Current Year Trial Balance period: same year,
 * and non-zero targets for that month.
 *
 * @param {{budget_year, months_with_data}|undefined} budgetMeta
 * @param {{month, year, label}|null|undefined} currentPeriod - Period of the Current Year TB.
 */
export function validateBudgetAgainstTrialBalance(budgetMeta, currentPeriod) {
  if (!budgetMeta?.budget_year || !currentPeriod) {
    return { isValid: true, title: null, errorMessage: null };
  }

  if (budgetMeta.budget_year !== currentPeriod.year) {
    return fail(
      "Budget Year Mismatch",
      `The Revenue Budget Workbook is for ${budgetMeta.budget_year}, but the Current Year Trial Balance is for ${currentPeriod.label}. Please upload the ${currentPeriod.year} budget.`
    );
  }

  if (!budgetMeta.months_with_data.includes(currentPeriod.month)) {
    return fail(
      "No Budget for This Month",
      `The Revenue Budget Workbook has no budget figures for ${currentPeriod.label}, the month of the Current Year Trial Balance.`
    );
  }

  return { isValid: true, title: null, errorMessage: null };
}

/**
 * Cross-checks the Current and Previous Year Trial Balance files once both
 * are selected: they must be different files, for the same month, one year apart.
 *
 * @param {string} key - The field being changed ("tb_current" or "tb_previous").
 * @param {{file: File, period: object|null}} entry - The newly selected file.
 * @param {{file: File, period: object|null}|undefined} other - The file in the other TB field.
 */
export function validateTrialBalancePair(key, entry, other) {
  if (!other?.file) {
    return { isValid: true, title: null, errorMessage: null };
  }

  const { file } = entry;
  const otherLabel = key === "tb_current" ? TB_LABELS.tb_previous : TB_LABELS.tb_current;

  if (
    file.name === other.file.name &&
    file.size === other.file.size &&
    file.lastModified === other.file.lastModified
  ) {
    return fail(
      "Same File Selected",
      `"${file.name}" is already selected as the ${otherLabel}. Please upload a different file for each year.`
    );
  }

  if (!entry.period || !other.period) {
    return { isValid: true, title: null, errorMessage: null };
  }

  const current = key === "tb_current" ? entry.period : other.period;
  const previous = key === "tb_current" ? other.period : entry.period;

  if (current.month !== previous.month) {
    return fail(
      "Period Mismatch",
      `The Current Year Trial Balance is for ${current.label} but the Previous Year Trial Balance is for ${previous.label}. Both files must be for the same month.`
    );
  }

  if (current.year === previous.year) {
    return fail(
      "Same Year Selected",
      `Both Trial Balance files are for ${current.label}. The Previous Year file must be for ${current.label.split(" ")[0]} ${current.year - 1}.`
    );
  }

  if (current.year < previous.year) {
    return fail(
      "Files Swapped",
      `The Current Year file is for ${current.label} but the Previous Year file is for ${previous.label}. It looks like the two files were uploaded to the wrong fields.`
    );
  }

  if (current.year - previous.year !== 1) {
    return fail(
      "Year Gap Detected",
      `The Current Year file is for ${current.label} but the Previous Year file is for ${previous.label}. The Previous Year file must be exactly one year earlier (${current.label.split(" ")[0]} ${current.year - 1}).`
    );
  }

  return { isValid: true, title: null, errorMessage: null };
}

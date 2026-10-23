import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import {
  ThemeProvider,
  createTheme,
  CssBaseline,
  Alert,
  Button,
  Chip,
  LinearProgress,
  MenuItem,
  Paper,
  TextField,
  Tooltip,
} from "@mui/material";
import {
  Assessment as FinancialAnalysisIcon,
  CheckCircle as CheckCircleIcon,
  CloudUpload as UploadIcon,
  Dashboard as DashboardIcon,
  Delete as DeleteIcon,
  Description as FileIcon,
  Download as DownloadIcon,
  ExitToApp as LogoutIcon,
  Person as PersonIcon,
  QueryStats as ForecastIcon,
  Security as SecurityIcon,
  Slideshow as BoardPackIcon,
  TableChart as MappingIcon,
  VerifiedUser as VerifiedUserIcon,
  WarningAmber as WarningIcon,
} from "@mui/icons-material";
import {
  deleteTrialBalance,
  downloadFinancialAnalysis,
  generateFinancialAnalysis,
  getFinancialAnalysisStatus,
  uploadGlMapping,
  uploadTrialBalances,
} from "../services/api";
import { visibleNavItems } from "../config/useCases";
import lightLogo from "../Assets/sltmobitel-logo-png_seeklogo-433080.png";

const theme = createTheme({
  palette: {
    primary: { main: "#0B3041" },
    secondary: { main: "#1B6B93" },
    background: { default: "#F5F7FA" },
  },
  typography: {
    fontFamily: "'Inter', 'Roboto', 'Arial', sans-serif",
  },
});

const NAV_ITEMS = [
  { label: "Dashboard", icon: DashboardIcon, path: "/dashboard" },
  { label: "Revenue Forecasting", icon: ForecastIcon, path: "/forecasting" },
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies" },
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack" },
  { label: "Financial Analysis", icon: FinancialAnalysisIcon, path: "/financial-analysis", active: true },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const REPORT_SECTIONS = [
  "Executive Summary – SLT PLC",
  "Financial Statistics and Key Ratios (YTD)",
  "(A) Quarter vs same quarter last year",
  "(B) Quarter vs preceding quarter",
  "(C) YTD vs last year's YTD",
  "(D) Actuals vs Budget – once a budget is loaded",
  "Annexure – GL accounts behind each movement",
];

const ACCEPTED_EXTENSIONS = [".xlsx", ".xlsm"];
const MAX_FILE_SIZE_MB = 50;

const BUTTON_SX = {
  height: 44,
  px: 3,
  textTransform: "none",
  fontWeight: 900,
  borderRadius: 1.5,
  backgroundColor: "#0B3041",
  "&:hover": { backgroundColor: "#1B6B93" },
};

function validateFile(file) {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `${file.name}: select an Excel file (.xlsx or .xlsm).`;
  }
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return `${file.name} is larger than ${MAX_FILE_SIZE_MB} MB.`;
  }
  return null;
}

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString() : "");

const formatMn = (value) => {
  if (value === null || value === undefined) return "–";
  const text = Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
  return value < 0 ? `(${text})` : text;
};

const formatPct = (value) => {
  if (value === null || value === undefined) return "N/A";
  const text = `${Math.abs(value).toFixed(1)}%`;
  return value < 0 ? `(${text})` : text;
};

function SectionCard({ step, title, subtitle, children }) {
  return (
    <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 } }}>
      <h3 className="text-lg font-black text-[#082f49]">
        {step}. {title}
      </h3>
      {subtitle && <p className="mt-1 text-sm font-semibold text-slate-500">{subtitle}</p>}
      {children}
    </Paper>
  );
}

function SummaryTable({ comparison }) {
  return (
    <div className="mt-4 overflow-x-auto">
      <p className="mb-2 text-sm font-black text-[#082f49]">{comparison.title} (LKR Mn)</p>
      <table className="w-full min-w-[460px] text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-extrabold uppercase text-slate-500">
            <th className="py-2 pr-2" />
            <th className="py-2 pr-2 text-right">Current</th>
            <th className="py-2 pr-2 text-right">Compared</th>
            <th className="py-2 pr-2 text-right">Growth</th>
            <th className="py-2 text-right">%</th>
          </tr>
        </thead>
        <tbody>
          {comparison.rows.map((row) => (
            <tr key={row.key} className="border-b border-slate-100">
              <td className="py-2 pr-2 font-bold text-slate-700">{row.label}</td>
              <td className="py-2 pr-2 text-right font-semibold tabular-nums">{formatMn(row.current)}</td>
              <td className="py-2 pr-2 text-right font-semibold tabular-nums">{formatMn(row.base)}</td>
              <td className="py-2 pr-2 text-right font-semibold tabular-nums">{formatMn(row.variance)}</td>
              <td
                className={`py-2 text-right font-extrabold tabular-nums ${
                  Math.abs(row.variance) < 0.5 ? "text-slate-600" : row.favourable ? "text-emerald-700" : "text-red-700"
                }`}
              >
                {formatPct(row.variance_pct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function FinancialAnalysis() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const tbInputRef = useRef(null);
  const mappingInputRef = useRef(null);
  const currentYear = new Date().getFullYear();

  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [error, setError] = useState("");

  const [mappingUploading, setMappingUploading] = useState(false);
  const [mappingResult, setMappingResult] = useState(null);

  const [tbFiles, setTbFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [tbUploading, setTbUploading] = useState(false);
  const [tbResults, setTbResults] = useState([]);
  const [deleting, setDeleting] = useState("");

  const [selectedQuarter, setSelectedQuarter] = useState("");
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState(null);

  const refreshStatus = useCallback(async () => {
    try {
      const data = await getFinancialAnalysisStatus();
      setStatus(data);
      setSelectedQuarter((current) => {
        if (current && data.quarters.some((q) => q.label === current)) return current;
        const ready = data.quarters.find((q) => q.missing.length === 0);
        return (ready || data.quarters[0])?.label || "";
      });
    } catch (err) {
      setError(err.message || "Unable to load the trial balances");
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const quarter = useMemo(
    () => status?.quarters.find((q) => q.label === selectedQuarter) || null,
    [status, selectedQuarter]
  );

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const handleMappingSelected = async (file) => {
    if (!file) return;
    const problem = validateFile(file);
    if (mappingInputRef.current) mappingInputRef.current.value = "";
    if (problem) {
      setError(problem);
      return;
    }
    setError("");
    setMappingUploading(true);
    try {
      setMappingResult(await uploadGlMapping(file));
      await refreshStatus();
    } catch (err) {
      setError(err.message || "Failed to upload the GL code mapping");
    } finally {
      setMappingUploading(false);
    }
  };

  const addTbFiles = (fileList) => {
    const selected = Array.from(fileList || []);
    if (!selected.length) return;
    const problems = selected.map(validateFile).filter(Boolean);
    setError(problems.join(" "));
    setTbResults([]);
    setTbFiles((current) => {
      const names = new Set(current.map((f) => f.name));
      return [...current, ...selected.filter((f) => !validateFile(f) && !names.has(f.name))];
    });
    if (tbInputRef.current) tbInputRef.current.value = "";
  };

  const handleTbUpload = async () => {
    if (!tbFiles.length) return;
    setTbUploading(true);
    setError("");
    try {
      const data = await uploadTrialBalances(tbFiles);
      setTbResults(data.results);
      setTbFiles([]);
      await refreshStatus();
    } catch (err) {
      setError(err.message || "Failed to upload the trial balances");
    } finally {
      setTbUploading(false);
    }
  };

  const handleDelete = async (period) => {
    if (!window.confirm(`Remove the ${period.label} trial balance?`)) return;
    setDeleting(period.label);
    setError("");
    try {
      await deleteTrialBalance(period.year, period.month);
      await refreshStatus();
    } catch (err) {
      setError(err.message || "Failed to remove the trial balance");
    } finally {
      setDeleting("");
    }
  };

  const handleGenerate = async () => {
    if (!quarter) return;
    setGenerating(true);
    setError("");
    setResult(null);
    try {
      setResult(await generateFinancialAnalysis(quarter.year, quarter.quarter));
    } catch (err) {
      setError(err.message || "Failed to generate the report");
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = async () => {
    if (!result?.filename) return;
    setDownloading(true);
    try {
      await downloadFinancialAnalysis(result.filename);
    } catch (err) {
      setError(err.message || "Failed to download the report");
    } finally {
      setDownloading(false);
    }
  };

  const mapping = status?.mapping;
  const periods = status?.periods || [];
  const canGenerate = Boolean(mapping && quarter && quarter.missing.length === 0 && !generating);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
        <div className="flex min-h-screen">
          <aside className="hidden w-[284px] shrink-0 flex-col justify-between border-r border-white/10 bg-[#071b2a] text-white shadow-[18px_0_48px_rgba(7,27,42,0.16)] lg:flex">
            <div>
              <div className="px-7 pb-6 pt-7">
                <div className="rounded-lg border border-white/10 bg-white/8 p-4">
                  <img src="/logo.png" alt="SLT Mobitel Logo" className="h-12 object-contain" />
                </div>
              </div>

              <nav className="px-4">
                {visibleNavItems(NAV_ITEMS, user).map(({ label, icon: Icon, path, active }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => navigate(path)}
                    className={`mb-2 flex h-12 w-full items-center gap-3 rounded-lg px-4 text-left text-sm font-extrabold transition ${active
                        ? "bg-white text-[#071b2a] shadow-lg"
                        : "text-slate-300 hover:bg-white/10 hover:text-white"
                      }`}
                  >
                    <Icon fontSize="small" />
                    <span>{label}</span>
                  </button>
                ))}
              </nav>
            </div>

            <div className="p-4 border-t border-white/10 mt-auto">
              <Button
                onClick={handleLogout}
                variant="contained"
                fullWidth
                startIcon={<LogoutIcon />}
                sx={{
                  height: 44,
                  backgroundColor: "#E1251B",
                  textTransform: "none",
                  fontWeight: 900,
                  borderRadius: 1.5,
                  boxShadow: "0 10px 18px rgba(225,37,27,0.2)",
                  "&:hover": { backgroundColor: "#C11812" },
                }}
              >
                Sign Out
              </Button>
            </div>
          </aside>

          <main className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="relative flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src={lightLogo} alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">Financial Analysis Report</h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      Quarterly P&amp;L analysis in Word from the detail trial balances
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => navigate("/profile")}
                    className="flex items-center rounded-lg border border-slate-200 bg-white p-2 shadow-[0_8px_20px_rgba(15,23,42,0.06)]"
                    aria-label="User profile"
                  >
                    <div className="grid h-11 w-11 place-items-center rounded-lg bg-[#082f49] text-white shadow-sm">
                      <PersonIcon sx={{ fontSize: 22 }} />
                    </div>
                  </button>
                  <div className="lg:hidden">
                    <Tooltip title="Sign out">
                      <Button
                        onClick={handleLogout}
                        variant="contained"
                        startIcon={<LogoutIcon />}
                        sx={{
                          minWidth: { xs: 42, sm: "auto" },
                          px: { xs: 1.2, sm: 2.4 },
                          height: 42,
                          backgroundColor: "#E1251B",
                          textTransform: "none",
                          fontWeight: 900,
                          borderRadius: 1.5,
                          boxShadow: "0 10px 18px rgba(225,37,27,0.2)",
                          "&:hover": { backgroundColor: "#C11812" },
                        }}
                      >
                        <span className="hidden sm:inline">Sign Out</span>
                      </Button>
                    </Tooltip>
                  </div>
                </div>
              </div>
            </header>

            <div className="flex-1 px-4 py-8 md:px-8 lg:px-10">
              {loadingStatus && <LinearProgress sx={{ mb: 3, borderRadius: 1 }} />}
              {error && (
                <Alert severity="error" sx={{ mb: 3, fontWeight: 600 }} onClose={() => setError("")}>
                  {error}
                </Alert>
              )}

              <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[1.35fr_1fr]">
                <div className="flex min-w-0 flex-col gap-6">
                  {/* 1. GL mapping */}
                  <SectionCard
                    step={1}
                    title="GL code mapping"
                    subtitle="The '6.PL-EBITDA' sheet that maps account ranges to P&L lines. Upload again only when Finance changes it."
                  >
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <MappingIcon sx={{ color: mapping ? "#7AB648" : "#94a3b8" }} />
                        <div className="min-w-0">
                          <p className="truncate text-sm font-extrabold text-slate-800">
                            {mapping ? mapping.filename : "No mapping uploaded yet"}
                          </p>
                          {mapping?.uploaded_at && (
                            <p className="text-xs font-semibold text-slate-500">
                              Uploaded {formatDate(mapping.uploaded_at)}
                              {mapping.uploaded_by ? ` by ${mapping.uploaded_by}` : ""}
                            </p>
                          )}
                        </div>
                      </div>
                      <Button
                        onClick={() => mappingInputRef.current?.click()}
                        disabled={mappingUploading}
                        variant="outlined"
                        startIcon={<UploadIcon />}
                        sx={{ textTransform: "none", fontWeight: 800, borderRadius: 1.5 }}
                      >
                        {mappingUploading ? "Uploading…" : mapping ? "Replace" : "Upload"}
                      </Button>
                      <input
                        ref={mappingInputRef}
                        type="file"
                        accept={ACCEPTED_EXTENSIONS.join(",")}
                        className="hidden"
                        onChange={(e) => handleMappingSelected(e.target.files?.[0])}
                      />
                    </div>
                    {mappingResult?.warnings?.length > 0 && (
                      <Alert severity="info" sx={{ mt: 2 }}>
                        {mappingResult.warnings.map((w) => (
                          <div key={w}>{w}</div>
                        ))}
                      </Alert>
                    )}
                  </SectionCard>

                  {/* 2. Trial balances */}
                  <SectionCard
                    step={2}
                    title="Trial balances"
                    subtitle="Detail TB exports (A/c, GL code, Beginning balance, PTD, YTD). The month is read from the YTD header; loading a month again replaces it."
                  >
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => tbInputRef.current?.click()}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && tbInputRef.current?.click()}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragging(true);
                      }}
                      onDragLeave={() => setDragging(false)}
                      onDrop={(e) => {
                        e.preventDefault();
                        setDragging(false);
                        addTbFiles(e.dataTransfer.files);
                      }}
                      className={`mt-5 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${dragging ? "border-[#1B6B93] bg-sky-50" : "border-slate-300 bg-slate-50 hover:border-[#1B6B93] hover:bg-sky-50/60"
                        }`}
                    >
                      <UploadIcon sx={{ fontSize: 40, color: "#1B6B93" }} />
                      <p className="mt-3 text-sm font-extrabold text-[#082f49]">
                        Drop one or more TB files here or click to browse
                      </p>
                      <p className="mt-1 text-xs font-semibold text-slate-500">.xlsx or .xlsm, up to {MAX_FILE_SIZE_MB} MB each</p>
                      <input
                        ref={tbInputRef}
                        type="file"
                        multiple
                        accept={ACCEPTED_EXTENSIONS.join(",")}
                        className="hidden"
                        onChange={(e) => addTbFiles(e.target.files)}
                      />
                    </div>

                    {tbFiles.length > 0 && (
                      <div className="mt-4 space-y-2">
                        {tbFiles.map((f) => (
                          <div
                            key={f.name}
                            className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-2.5"
                          >
                            <div className="flex min-w-0 items-center gap-3">
                              <FileIcon sx={{ color: "#7AB648" }} />
                              <p className="truncate text-sm font-extrabold text-slate-800">{f.name}</p>
                            </div>
                            <Tooltip title="Remove file">
                              <span>
                                <Button
                                  onClick={() => setTbFiles((cur) => cur.filter((x) => x.name !== f.name))}
                                  disabled={tbUploading}
                                  sx={{ minWidth: 36, color: "#64748b" }}
                                >
                                  <DeleteIcon fontSize="small" />
                                </Button>
                              </span>
                            </Tooltip>
                          </div>
                        ))}
                        <Button onClick={handleTbUpload} disabled={tbUploading} variant="contained" startIcon={<UploadIcon />} sx={{ ...BUTTON_SX, mt: 1 }}>
                          {tbUploading ? "Reading files…" : `Load ${tbFiles.length} file${tbFiles.length > 1 ? "s" : ""}`}
                        </Button>
                        {tbUploading && <LinearProgress sx={{ mt: 1, borderRadius: 1 }} />}
                      </div>
                    )}

                    {tbResults.length > 0 && (
                      <div className="mt-4 space-y-2">
                        {tbResults.map((r) => (
                          <Alert key={r.filename} severity={r.status === "error" ? "error" : r.warnings?.length ? "warning" : "success"}>
                            <span className="font-bold">{r.filename}</span>
                            {r.status === "error"
                              ? `: ${r.error}`
                              : ` – ${r.status === "replaced" ? "replaced" : "loaded"} ${r.period} (${r.accounts} accounts)`}
                            {r.warnings?.map((w) => (
                              <div key={w} className="text-xs">
                                {w}
                              </div>
                            ))}
                          </Alert>
                        ))}
                      </div>
                    )}

                    <div className="mt-5 overflow-x-auto">
                      {periods.length === 0 ? (
                        <p className="text-sm font-semibold text-slate-500">No trial balances loaded yet.</p>
                      ) : (
                        <table className="w-full min-w-[420px] text-sm">
                          <thead>
                            <tr className="border-b border-slate-200 text-left text-xs font-extrabold uppercase text-slate-500">
                              <th className="py-2 pr-2">Period</th>
                              <th className="py-2 pr-2">File</th>
                              <th className="py-2 pr-2 text-right">Accounts</th>
                              <th className="py-2" />
                            </tr>
                          </thead>
                          <tbody>
                            {periods.map((p) => (
                              <tr key={p.label} className="border-b border-slate-100">
                                <td className="py-2 pr-2 font-extrabold text-[#082f49]">{p.label}</td>
                                <td className="max-w-[220px] truncate py-2 pr-2 font-semibold text-slate-600" title={p.filename}>
                                  {p.filename}
                                </td>
                                <td className="py-2 pr-2 text-right font-semibold tabular-nums">{p.accounts}</td>
                                <td className="py-2 text-right">
                                  <Tooltip title={`Remove ${p.label}`}>
                                    <span>
                                      <Button
                                        onClick={() => handleDelete(p)}
                                        disabled={deleting === p.label}
                                        sx={{ minWidth: 36, color: "#64748b" }}
                                      >
                                        <DeleteIcon fontSize="small" />
                                      </Button>
                                    </span>
                                  </Tooltip>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  </SectionCard>

                  {/* 3. Generate */}
                  <SectionCard step={3} title="Generate the Word report">
                    {status && status.quarters.length === 0 ? (
                      <p className="mt-3 text-sm font-semibold text-slate-500">
                        Load a quarter-end trial balance (Mar, Jun, Sep or Dec) to choose a quarter.
                      </p>
                    ) : (
                      <TextField
                        select
                        label="Quarter"
                        value={selectedQuarter}
                        onChange={(e) => {
                          setSelectedQuarter(e.target.value);
                          setResult(null);
                        }}
                        size="small"
                        sx={{ mt: 3, minWidth: 220 }}
                      >
                        {(status?.quarters || []).map((q) => (
                          <MenuItem key={q.label} value={q.label}>
                            {q.label}
                            {q.missing.length ? " – trial balances missing" : ""}
                          </MenuItem>
                        ))}
                      </TextField>
                    )}

                    {quarter?.missing.length > 0 && (
                      <Alert severity="warning" icon={<WarningIcon />} sx={{ mt: 2 }}>
                        {quarter.label} also needs these trial balances: <b>{quarter.missing.join(", ")}</b>
                      </Alert>
                    )}
                    {status && !mapping && (
                      <Alert severity="warning" icon={<WarningIcon />} sx={{ mt: 2 }}>
                        Upload the GL code mapping first.
                      </Alert>
                    )}

                    <div>
                      <Button
                        onClick={handleGenerate}
                        disabled={!canGenerate}
                        variant="contained"
                        startIcon={<FinancialAnalysisIcon />}
                        sx={{ ...BUTTON_SX, mt: 3, px: 4, height: 46 }}
                      >
                        {generating ? "Generating…" : "Generate Report"}
                      </Button>
                    </div>
                    {generating && <LinearProgress sx={{ mt: 2, borderRadius: 1 }} />}

                    {result && (
                      <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5">
                        <div className="flex items-start gap-3">
                          <CheckCircleIcon sx={{ color: "#047857", mt: 0.25 }} />
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-black text-emerald-900">Report ready</p>
                            <p className="mt-1 break-all text-xs font-semibold text-emerald-800">{result.filename}</p>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <Chip size="small" label={result.quarter} sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }} />
                              {!result.budget_available && (
                                <Chip size="small" label="No budget loaded" sx={{ fontWeight: 800, backgroundColor: "#fef3c7", color: "#92400e" }} />
                              )}
                            </div>
                          </div>
                        </div>

                        {result.warnings?.length > 0 && (
                          <Alert severity="warning" icon={<WarningIcon />} sx={{ mt: 3 }}>
                            <ul className="list-disc pl-5 text-sm">
                              {result.warnings.map((w) => (
                                <li key={w}>{w}</li>
                              ))}
                            </ul>
                          </Alert>
                        )}

                        <div className="mt-2 rounded-lg bg-white p-4">
                          {result.comparisons.map((c) => (
                            <SummaryTable key={c.title} comparison={c} />
                          ))}
                        </div>

                        <Button
                          onClick={handleDownload}
                          disabled={downloading}
                          variant="contained"
                          startIcon={<DownloadIcon />}
                          sx={{ ...BUTTON_SX, mt: 3, px: 3.5, backgroundColor: "#7AB648", "&:hover": { backgroundColor: "#6AA038" } }}
                        >
                          {downloading ? "Downloading…" : "Download Word report (.docx)"}
                        </Button>
                      </div>
                    )}
                  </SectionCard>
                </div>

                {/* What's in the report */}
                <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 }, alignSelf: "start" }}>
                  <h3 className="text-lg font-black text-[#082f49]">Sections in the report</h3>
                  <p className="mt-1 text-sm font-semibold text-slate-500">
                    SLT PLC figures in LKR Mn, in the Finance Q2 2026 report format.
                  </p>
                  <ol className="mt-5 space-y-2">
                    {REPORT_SECTIONS.map((title, i) => (
                      <li key={title} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2.5">
                        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[#082f49] text-xs font-black text-white">
                          {i + 1}
                        </span>
                        <span className="text-sm font-bold text-slate-700">{title}</span>
                      </li>
                    ))}
                  </ol>
                  <p className="mt-5 text-xs font-semibold leading-relaxed text-slate-500">
                    A quarter needs four trial balances: its quarter end, the previous quarter end, and the same two
                    months last year (Q1 uses last year's Sep and Dec). Group and Mobitel figures, operational
                    statistics, cash flow and borrowings are not in the trial balance and are left for Finance to add.
                  </p>
                </Paper>
              </div>
            </div>

            <footer className="border-t border-slate-200 bg-white px-4 py-5 md:px-8 lg:px-10">
              <div className="mx-auto flex max-w-5xl flex-col items-center justify-center gap-2 text-center">
                <div className="flex items-center gap-2 text-[#082f49]">
                  <VerifiedUserIcon fontSize="small" />
                  <span className="text-sm font-black">Finance Revenue Automation</span>
                </div>
                <p className="text-xs font-semibold text-slate-500">© {currentYear} SLT-MOBITEL</p>
              </div>
            </footer>
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}

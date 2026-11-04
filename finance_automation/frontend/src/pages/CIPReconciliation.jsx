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
  CircularProgress,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Tooltip,
} from "@mui/material";
import {
  AccountBalance as CIPAccountIcon,
  Assessment as FinancialAnalysisIcon,
  CheckCircle as CheckCircleIcon,
  CloudUpload as UploadIcon,
  Dashboard as DashboardIcon,
  Delete as DeleteIcon,
  Description as FileIcon,
  Download as DownloadIcon,
  ErrorOutline as ErrorIcon,
  ExitToApp as LogoutIcon,
  HourglassEmpty as MissingIcon,
  Person as PersonIcon,
  PlayArrow as ReconcileIcon,
  QueryStats as ForecastIcon,
  Refresh as RefreshIcon,
  Search as SearchIcon,
  Security as SecurityIcon,
  Slideshow as BoardPackIcon,
  TableChart as TableIcon,
  WarningAmber as WarningIcon,
} from "@mui/icons-material";
import {
  deleteCipFile,
  downloadCipReport,
  generateCipReport,
  getCipStatus,
  runCipReconciliation,
  uploadCipFile,
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
  { label: "Financial Analysis", icon: FinancialAnalysisIcon, path: "/financial-analysis" },
  { label: "CIP Reconciliation", icon: CIPAccountIcon, path: "/cip-reconciliation", active: true },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const BUTTON_SX = {
  height: 46,
  px: 4,
  textTransform: "none",
  fontWeight: 800,
  borderRadius: 2,
  backgroundColor: "#0B3041",
  boxShadow: "0 8px 16px rgba(11,48,65,0.18)",
  "&:hover": { backgroundColor: "#1B6B93" },
};

const formatLKR = (val) => {
  if (val == null || isNaN(val)) return "0.00";
  return Number(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

const formatDate = (isoString) => {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    return d.toLocaleString("en-GB", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return isoString;
  }
};

function SectionCard({ step, title, subtitle, children }) {
  return (
    <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 }, bgcolor: "#fff" }}>
      <h3 className="text-lg font-black text-[#082f49]">
        {step}. {title}
      </h3>
      {subtitle && <p className="mt-1 text-sm font-semibold text-slate-500">{subtitle}</p>}
      {children}
    </Paper>
  );
}

// Required source files and the optional prior-period opening-balance report.
const CATEGORY_CONFIG = {
  opening_balances: {
    categoryKey: "opening_balances",
    title: "Prior Period CIP Report (Optional)",
    subtitle: "Prior-period closing balances (.xlsx, .xlsm)",
    description: "Upload the prior-period CIP report to carry forward opening balances and include its projects in this reconciliation.",
    iconColor: "#64748B",
    iconBg: "bg-slate-100 text-slate-700",
    accept: ".xlsx,.xlsm",
    required: false,
  },
  journal_details: {
    categoryKey: "journal_details",
    title: "Journal Details",
    subtitle: "General Ledger journal transactions (.xlsx)",
    description: "Multi-sheet GL journal entries with DR, CR, and project references for accounts 111401 to 111406.",
    iconColor: "#E8A838",
    iconBg: "bg-amber-100 text-amber-700",
    accept: ".xlsx,.xls",
  },
  project_codes: {
    categoryKey: "project_codes",
    title: "Project Details and Codes",
    subtitle: "Project master information (.xlsx)",
    description: "Master list of project identifiers, project names, descriptions, project managers, and end dates.",
    iconColor: "#0F766E",
    iconBg: "bg-teal-100 text-teal-700",
    accept: ".xlsx,.xls",
  },
  interfaced_cip: {
    categoryKey: "interfaced_cip",
    title: "SLT Interfaced CIP/RWIP Amounts",
    subtitle: "Consolidated interfaced files (.xls, .xlsx)",
    description: "Capitalized CIP financial amounts transferred into Fixed Assets across accounts 111401 to 111406.",
    iconColor: "#7C3AED",
    iconBg: "bg-purple-100 text-purple-700",
    accept: ".xls,.xlsx",
  },
  subledger_detail: {
    categoryKey: "subledger_detail",
    title: "SLT Project Subledger Details",
    subtitle: "Project expenditure additions (.xlsx)",
    description: "Detailed expenditure additions per project from Oracle Projects subledger (111401 to 111406).",
    iconColor: "#1B6B93",
    iconBg: "bg-sky-100 text-sky-700",
    accept: ".xlsx,.xls",
  },
};

export default function CIPReconciliation() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const [period, setPeriod] = useState("Jul-26");
  const [statusData, setStatusData] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [uploadingCategory, setUploadingCategory] = useState(null);
  const [reconciling, setReconciling] = useState(false);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [reconResult, setReconResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  // Drag states per category
  const [draggingCat, setDraggingCat] = useState(null);

  // File input refs
  const fileInputRefs = {
    opening_balances: useRef(null),
    journal_details: useRef(null),
    project_codes: useRef(null),
    interfaced_cip: useRef(null),
    subledger_detail: useRef(null),
  };

  // Search & Pagination in project table
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(15);
  const [expandedProject, setExpandedProject] = useState(null);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  // Load status
  const refreshStatus = useCallback(async () => {
    try {
      setLoadingStatus(true);
      const data = await getCipStatus(period);
      setStatusData(data);
    } catch (err) {
      console.error("Status load error:", err);
    } finally {
      setLoadingStatus(false);
    }
  }, [period]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // Handle file upload
  const handleFileUpload = async (category, file) => {
    if (!file) return;
    setErrorMessage("");
    setSuccessMessage("");
    setUploadingCategory(category);
    try {
      await uploadCipFile(category, file, period);
      setSuccessMessage(`Successfully uploaded ${file.name}`);
      await refreshStatus();
    } catch (err) {
      setErrorMessage(err.message || "Failed to upload file");
    } finally {
      setUploadingCategory(null);
    }
  };

  // Handle remove file
  const handleRemoveFile = async (category, label) => {
    if (!window.confirm(`Remove the ${label}?`)) return;
    setErrorMessage("");
    try {
      await deleteCipFile(category, period);
      setSuccessMessage(`Removed file for ${label}`);
      await refreshStatus();
    } catch (err) {
      setErrorMessage(err.message || "Failed to remove file");
    }
  };

  // Run reconciliation
  const handleReconcile = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setReconciling(true);
    try {
      const res = await runCipReconciliation(period);
      setReconResult(res);
      setSuccessMessage("Reconciliation executed successfully!");
    } catch (err) {
      setErrorMessage(err.message || "Reconciliation failed");
    } finally {
      setReconciling(false);
    }
  };

  // Generate & Download Report
  const handleGenerateAndDownload = async () => {
    setErrorMessage("");
    setGeneratingReport(true);
    try {
      const genRes = await generateCipReport(period);
      await downloadCipReport(genRes.filename, period);
      setSuccessMessage("Reconciliation report generated and downloaded successfully.");
    } catch (err) {
      setErrorMessage(err.message || "Failed to generate report");
    } finally {
      setGeneratingReport(false);
    }
  };

  // Filter projects
  const filteredProjects = useMemo(() => {
    if (!reconResult?.projects) return [];
    if (!searchQuery.trim()) return reconResult.projects;
    const q = searchQuery.toLowerCase();
    return reconResult.projects.filter(
      (p) =>
        p.project_no?.toLowerCase().includes(q) ||
        p.project_name?.toLowerCase().includes(q) ||
        p.project_manager?.toLowerCase().includes(q)
    );
  }, [reconResult, searchQuery]);

  // Check if all required files are uploaded; opening balances are optional.
  const allRequiredUploaded = useMemo(() => {
    if (!statusData?.categories) return false;
    const req = ["journal_details", "project_codes", "interfaced_cip", "subledger_detail"];
    return req.every((k) => statusData.categories[k]?.uploaded);
  }, [statusData]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
        <div className="flex min-h-screen">
          {/* Sticky Sidebar matching previous system */}
          <aside className="sticky top-0 h-screen overflow-y-auto hidden w-[284px] shrink-0 flex-col justify-between border-r border-white/10 bg-[#071b2a] text-white shadow-[18px_0_48px_rgba(7,27,42,0.16)] lg:flex">
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
                    className={`mb-2 flex h-12 w-full items-center gap-3 rounded-lg px-4 text-left text-sm font-extrabold transition ${
                      active
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

          {/* Main Content Area */}
          <main className="flex min-w-0 flex-1 flex-col">
            {/* Header matching previous system */}
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="relative flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src={lightLogo} alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">
                      CIP Reconciliation Report
                    </h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      Monthly Construction in Progress (CIP) &amp; RWIP financial reconciliation report
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className="hidden sm:flex items-center space-x-2 bg-slate-50 border border-slate-300 rounded-lg px-3 py-1">
                    <span className="text-xs font-semibold text-slate-600">Period:</span>
                    <TextField
                      select
                      size="small"
                      value={period}
                      onChange={(e) => setPeriod(e.target.value)}
                      variant="standard"
                      InputProps={{ disableUnderline: true }}
                      sx={{ "& .MuiSelect-select": { py: 0.5, fontSize: "0.85rem", fontWeight: 700, color: "#0B3041" } }}
                    >
                      <MenuItem value="Jul-26">July 2026 (Jul-26)</MenuItem>
                      <MenuItem value="Jun-26">June 2026 (Jun-26)</MenuItem>
                      <MenuItem value="Aug-26">August 2026 (Aug-26)</MenuItem>
                      <MenuItem value="Sep-26">September 2026 (Sep-26)</MenuItem>
                    </TextField>
                  </div>

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
                </div>
              </div>
            </header>

            <div className="p-4 md:p-8 max-w-7xl space-y-6 mx-auto w-full">
              {/* Alerts */}
              {errorMessage && (
                <Alert severity="error" onClose={() => setErrorMessage("")}>
                  {errorMessage}
                </Alert>
              )}
              {successMessage && (
                <Alert severity="success" onClose={() => setSuccessMessage("")}>
                  {successMessage}
                </Alert>
              )}

              {/* Section 1: Financial Input Files */}
              <SectionCard
                step={1}
                title="Financial Input Files"
                subtitle="Upload the 4 required source categories. Add the prior-period CIP report to carry forward opening balances and its project list."
              >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                  {Object.entries(CATEGORY_CONFIG).map(([catKey, config]) => {
                    const catStatus = statusData?.categories?.[catKey];
                    const isUploaded = !!catStatus?.uploaded;
                    const isUploading = uploadingCategory === catKey;
                    const isDragging = draggingCat === catKey;

                    return (
                      <Paper
                        key={catKey}
                        elevation={0}
                        sx={{
                          p: 3,
                          borderRadius: 2.5,
                          border: isDragging ? "2px dashed #1B6B93" : isUploaded ? "1px solid #a7f3d0" : "1px solid #dce5ee",
                          backgroundColor: isDragging ? "#f0f7fa" : isUploaded ? "#f0fdf4" : "#fafcff",
                          transition: "all 0.2s ease-in-out",
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          setDraggingCat(catKey);
                        }}
                        onDragLeave={() => setDraggingCat(null)}
                        onDrop={(e) => {
                          e.preventDefault();
                          setDraggingCat(null);
                          const droppedFile = e.dataTransfer.files?.[0];
                          if (droppedFile) handleFileUpload(catKey, droppedFile);
                        }}
                      >
                        <input
                          ref={fileInputRefs[catKey]}
                          type="file"
                          accept={config.accept}
                          className="hidden"
                          onChange={(e) => {
                            const selected = e.target.files?.[0];
                            if (selected) handleFileUpload(catKey, selected);
                            e.target.value = "";
                          }}
                        />

                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-3">
                            <div className={`rounded-lg p-2.5 ${config.iconBg}`}>
                              <FileIcon />
                            </div>
                            <div>
                              <h4 className="text-sm font-black text-[#082f49]">{config.title}</h4>
                              <p className="text-xs font-semibold text-slate-500">{config.subtitle}</p>
                            </div>
                          </div>
                          {isUploaded && (
                            <Chip
                              size="small"
                              label="Enriched"
                              sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }}
                            />
                          )}
                          {!isUploaded && config.required === false && (
                            <Chip
                              size="small"
                              label="Optional"
                              sx={{ fontWeight: 800, backgroundColor: "#e2e8f0", color: "#334155" }}
                            />
                          )}
                        </div>

                        <p className="text-xs text-slate-600 mt-2.5">{config.description}</p>

                        {isUploaded ? (
                          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
                            <p className="truncate text-xs font-bold text-slate-800" title={catStatus.filename}>
                              {catStatus.filename}
                            </p>
                            <p className="mt-1 text-[11px] font-semibold text-slate-500">
                              Uploaded {formatDate(catStatus.uploaded_at)}
                              {catStatus.uploaded_by ? ` by ${catStatus.uploaded_by}` : ""}
                            </p>
                            <div className="mt-3 flex items-center justify-between">
                              <Button
                                size="small"
                                variant="outlined"
                                onClick={() => fileInputRefs[catKey].current?.click()}
                                disabled={isUploading}
                                sx={{ textTransform: "none", fontSize: "12px", fontWeight: 700 }}
                              >
                                Replace
                              </Button>
                              <Button
                                size="small"
                                color="error"
                                onClick={() => handleRemoveFile(catKey, config.title)}
                                startIcon={<DeleteIcon fontSize="small" />}
                                sx={{ textTransform: "none", fontSize: "12px", fontWeight: 700 }}
                              >
                                Remove
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <div className="mt-4 flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white py-5 px-3 text-center">
                            <p className="text-xs font-semibold text-slate-600">Drag and drop file here, or browse</p>
                            <Button
                              variant="outlined"
                              size="small"
                              startIcon={isUploading ? <CircularProgress size={16} color="inherit" /> : <UploadIcon />}
                              onClick={() => fileInputRefs[catKey].current?.click()}
                              disabled={isUploading}
                              sx={{ mt: 2, textTransform: "none", fontWeight: 700, borderColor: "#1B6B93", color: "#1B6B93" }}
                            >
                              {isUploading ? "Uploading..." : "Browse"}
                            </Button>
                          </div>
                        )}
                      </Paper>
                    );
                  })}
                </div>

                {/* Action Bar */}
                <div className="mt-6 pt-4 flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-slate-100">
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-semibold text-slate-500">Status:</span>
                    <Chip
                      size="small"
                      icon={allRequiredUploaded ? <CheckCircleIcon /> : <MissingIcon />}
                      label={allRequiredUploaded ? "All 4 Categories Uploaded" : "Missing Input Files"}
                      color={allRequiredUploaded ? "success" : "warning"}
                      sx={{ fontWeight: 700 }}
                    />
                  </div>

                  <div className="flex items-center space-x-3">
                    <Button
                      variant="text"
                      size="small"
                      startIcon={<RefreshIcon />}
                      onClick={refreshStatus}
                      sx={{ textTransform: "none", color: "#64748b", fontWeight: 700 }}
                    >
                      Refresh
                    </Button>

                    <Button
                      variant="contained"
                      disabled={!allRequiredUploaded || reconciling}
                      onClick={handleReconcile}
                      startIcon={reconciling ? <CircularProgress size={18} color="inherit" /> : <ReconcileIcon />}
                      sx={BUTTON_SX}
                    >
                      {reconciling ? "Running Reconciliation..." : "Run CIP Reconciliation"}
                    </Button>
                  </div>
                </div>
              </SectionCard>

              {/* Step 2: Key Reconciliation Metrics */}
              {reconResult && (
                <div className="space-y-6">
                  <SectionCard
                    step={2}
                    title="Key Reconciliation Metrics"
                    subtitle="Overview of project counts and aggregate financial movements for July 2026."
                  >
                    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4 mt-3">
                      <div className="bg-[#fafcff] p-4 rounded-xl border border-slate-200">
                        <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Total Projects</p>
                        <p className="text-2xl font-black text-[#0B3041] mt-1">{reconResult.metrics.total_projects}</p>
                        <p className="text-[11px] text-teal-700 mt-1 font-semibold">
                          {reconResult.metrics.reconciled_projects} fully reconciled
                        </p>
                      </div>

                      <div className="bg-[#fafcff] p-4 rounded-xl border border-slate-200">
                        <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Opening Balance</p>
                        <p className="text-lg font-black text-slate-800 mt-1">LKR {formatLKR(reconResult.metrics.total_opening)}</p>
                        <p className="text-[11px] text-slate-400 mt-1">From Jun-26 baseline</p>
                      </div>

                      <div className="bg-[#fafcff] p-4 rounded-xl border border-slate-200">
                        <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Subledger Additions</p>
                        <p className="text-lg font-black text-blue-700 mt-1">LKR {formatLKR(reconResult.metrics.total_additions)}</p>
                        <p className="text-[11px] text-slate-400 mt-1">6 accounts subledger</p>
                      </div>

                      <div className="bg-[#fafcff] p-4 rounded-xl border border-slate-200">
                        <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Interfaced CIP</p>
                        <p className="text-lg font-black text-purple-700 mt-1">LKR {formatLKR(reconResult.metrics.total_interface)}</p>
                        <p className="text-[11px] text-slate-400 mt-1">Transferred to FA</p>
                      </div>

                      <div className="bg-[#fafcff] p-4 rounded-xl border border-slate-200">
                        <p className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Closing Balance</p>
                        <p className="text-lg font-black text-teal-700 mt-1">LKR {formatLKR(reconResult.metrics.total_closing)}</p>
                        <p className="text-[11px] text-slate-400 mt-1">Open + Add + Interface</p>
                      </div>
                    </div>
                  </SectionCard>

                  {/* Step 3: Account-Wise GL vs Subledger Variance Table */}
                  <SectionCard
                    step={3}
                    title="Account-Wise GL vs Subledger Variance Reconciliation"
                    subtitle="Compares Subledger additions against GL Journal DR, and Interfaced CIP against GL Journal CR."
                  >
                    <TableContainer className="mt-3 border border-slate-200 rounded-xl overflow-hidden">
                      <Table size="small">
                        <TableHead>
                          <TableRow className="bg-slate-50">
                            <TableCell sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Account</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Subledger Additions</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>GL DR (Additions)</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Additions Variance</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Interfaced CIP</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>GL CR (Interface)</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Interface Variance</TableCell>
                            <TableCell align="center" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Status</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {reconResult.account_reconciliations.map((ar) => (
                            <TableRow key={ar.account} hover>
                              <TableCell sx={{ fontWeight: 700, fontSize: "0.8rem", color: "#0B3041" }}>
                                {ar.account}
                              </TableCell>
                              <TableCell align="right" sx={{ fontSize: "0.8rem", tabularNums: true }}>{formatLKR(ar.subledger_additions)}</TableCell>
                              <TableCell align="right" sx={{ fontSize: "0.8rem", tabularNums: true }}>{formatLKR(ar.gl_additions_dr)}</TableCell>
                              <TableCell
                                align="right"
                                sx={{
                                  fontSize: "0.8rem",
                                  fontWeight: 700,
                                  color: Math.abs(ar.additions_variance) < 0.01 ? "#059669" : "#dc2626",
                                  tabularNums: true,
                                }}
                              >
                                {formatLKR(ar.additions_variance)}
                              </TableCell>
                              <TableCell align="right" sx={{ fontSize: "0.8rem", tabularNums: true }}>{formatLKR(ar.interfaced_cip_total)}</TableCell>
                              <TableCell align="right" sx={{ fontSize: "0.8rem", tabularNums: true }}>{formatLKR(ar.gl_interface_cr)}</TableCell>
                              <TableCell
                                align="right"
                                sx={{
                                  fontSize: "0.8rem",
                                  fontWeight: 700,
                                  color: Math.abs(ar.interface_variance) < 0.01 ? "#059669" : "#dc2626",
                                  tabularNums: true,
                                }}
                              >
                                {formatLKR(ar.interface_variance)}
                              </TableCell>
                              <TableCell align="center">
                                <Chip
                                  size="small"
                                  label={ar.status === "Reconciled" ? "Matched" : "Variance"}
                                  color={ar.status === "Reconciled" ? "success" : "warning"}
                                  sx={{ fontWeight: 700, fontSize: "0.7rem", height: 22 }}
                                />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </SectionCard>

                  {/* Step 4: Project-Level Reconciliation Schedule */}
                  <SectionCard
                    step={4}
                    title="Project-Level Reconciliation Schedule"
                    subtitle="Detailed monthly movement across all 176 project codes."
                  >
                    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mt-3">
                      <TextField
                        size="small"
                        placeholder="Search project number, name or manager..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        sx={{ width: { xs: "100%", sm: 360 } }}
                        InputProps={{
                          startAdornment: (
                            <InputAdornment position="start">
                              <SearchIcon fontSize="small" className="text-slate-400" />
                            </InputAdornment>
                          ),
                        }}
                      />
                      <span className="text-xs text-slate-500 font-medium">
                        Showing {filteredProjects.length} of {reconResult.projects.length} projects
                      </span>
                    </div>

                    <TableContainer className="mt-3 border border-slate-200 rounded-xl overflow-hidden">
                      <Table size="small">
                        <TableHead>
                          <TableRow className="bg-slate-50">
                            <TableCell sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Project No</TableCell>
                            <TableCell sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Project Name</TableCell>
                            <TableCell align="center" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Year</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Jun-26 Opening</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Jul-26 Additions</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Jul-26 Interface</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Sep-26 Closing</TableCell>
                            <TableCell align="center" sx={{ fontWeight: 800, fontSize: "0.75rem", color: "#082f49" }}>Status</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {filteredProjects
                            .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
                            .map((p) => {
                              const isExp = expandedProject === p.project_no;
                              return (
                                <React.Fragment key={p.project_no}>
                                  <TableRow
                                    hover
                                    className="cursor-pointer"
                                    onClick={() => setExpandedProject(isExp ? null : p.project_no)}
                                  >
                                    <TableCell sx={{ fontWeight: 700, fontSize: "0.8rem", color: "#0B3041" }}>
                                      {p.project_no}
                                    </TableCell>
                                    <TableCell sx={{ fontSize: "0.8rem", maxWidth: 280, truncate: true }}>
                                      {p.project_name || "—"}
                                    </TableCell>
                                    <TableCell align="center" sx={{ fontSize: "0.8rem", color: "#64748b" }}>
                                      {p.year || "—"}
                                    </TableCell>
                                    <TableCell align="right" sx={{ fontSize: "0.8rem", fontVariantNumeric: "tabular-nums" }}>
                                      {formatLKR(p.total_opening)}
                                    </TableCell>
                                    <TableCell align="right" sx={{ fontSize: "0.8rem", fontVariantNumeric: "tabular-nums", color: "#1d4ed8" }}>
                                      {formatLKR(p.total_additions)}
                                    </TableCell>
                                    <TableCell align="right" sx={{ fontSize: "0.8rem", fontVariantNumeric: "tabular-nums", color: "#7e22ce" }}>
                                      {formatLKR(p.total_interface)}
                                    </TableCell>
                                    <TableCell align="right" sx={{ fontSize: "0.8rem", fontWeight: 700, color: "#0f766e", fontVariantNumeric: "tabular-nums" }}>
                                      {formatLKR(p.total_closing)}
                                    </TableCell>
                                    <TableCell align="center">
                                      <Chip
                                        size="small"
                                        label={p.is_reconciled ? "Balanced" : "Review"}
                                        color={p.is_reconciled ? "success" : "default"}
                                        sx={{ fontWeight: 700, fontSize: "0.7rem", height: 20 }}
                                      />
                                    </TableCell>
                                  </TableRow>

                                  {isExp && (
                                    <TableRow className="bg-slate-50/70">
                                      <TableCell colSpan={8} sx={{ py: 2, px: 4 }}>
                                        <div className="space-y-2">
                                          <div className="text-xs font-bold text-slate-700">
                                            Per-Account Breakdown for Project {p.project_no} – {p.project_name}
                                          </div>
                                          <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
                                            {["111401", "111402", "111403", "111404", "111405", "111406"].map((acc) => (
                                              <div key={acc} className="p-2 bg-white rounded border border-slate-200 text-xs">
                                                <p className="font-bold text-[#0B3041]">{acc}</p>
                                                <p className="text-[11px] text-slate-500">Open: {formatLKR(p.opening?.[acc])}</p>
                                                <p className="text-[11px] text-blue-600">Add: {formatLKR(p.additions?.[acc])}</p>
                                                <p className="text-[11px] text-purple-600">Int: {formatLKR(p.interface?.[acc])}</p>
                                                <p className="text-[11px] font-bold text-teal-700">Close: {formatLKR(p.closing?.[acc])}</p>
                                              </div>
                                            ))}
                                          </div>
                                        </div>
                                      </TableCell>
                                    </TableRow>
                                  )}
                                </React.Fragment>
                              );
                            })}
                        </TableBody>
                      </Table>
                    </TableContainer>

                    <TablePagination
                      component="div"
                      count={filteredProjects.length}
                      page={page}
                      onPageChange={(_, newPage) => setPage(newPage)}
                      rowsPerPage={rowsPerPage}
                      onRowsPerPageChange={(e) => {
                        setRowsPerPage(parseInt(e.target.value, 10));
                        setPage(0);
                      }}
                      rowsPerPageOptions={[10, 15, 25, 50, 100]}
                      sx={{ borderTop: "1px solid #e2e8f0" }}
                    />
                  </SectionCard>

                  {/* Step 5: Report Generation & Download */}
                  <SectionCard
                    step={5}
                    title="Report Generation & Download"
                    subtitle="Generate the official reconciled Excel report with live calculation formulas."
                  >
                    <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mt-3 p-4 bg-[#fafcff] rounded-xl border border-slate-200">
                      <div>
                        <p className="text-sm font-bold text-[#082f49]">
                          CIP Reconciliation Report ({period})
                        </p>
                        <p className="text-xs text-slate-500 mt-0.5">
                          Includes Sheet1 (176 projects + formulas) and Sheet2 (Reconciliation &amp; GL Variance).
                        </p>
                      </div>

                      <Button
                        variant="contained"
                        onClick={handleGenerateAndDownload}
                        disabled={generatingReport}
                        startIcon={generatingReport ? <CircularProgress size={18} color="inherit" /> : <DownloadIcon />}
                        sx={BUTTON_SX}
                      >
                        {generatingReport ? "Generating Report..." : "Download Reconciled Excel Report"}
                      </Button>
                    </div>
                  </SectionCard>
                </div>
              )}
            </div>
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}

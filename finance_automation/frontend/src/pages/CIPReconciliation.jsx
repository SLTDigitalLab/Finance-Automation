import React, { useCallback, useEffect, useRef, useState } from "react";
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
  Paper,
  TextField,
  Tooltip,
} from "@mui/material";
import {
  AccountBalance as CIPAccountIcon,
  Assessment as FinancialAnalysisIcon,
  CheckCircle as CheckCircleIcon,
  CloudUpload as UploadIcon,
  TrendingUp as TrendingUpIcon,
  Delete as DeleteIcon,
  Description as FileIcon,
  Download as DownloadIcon,
  ExitToApp as LogoutIcon,
  Person as PersonIcon,
  QueryStats as ForecastIcon,
  Refresh as RefreshIcon,
  RestartAlt as ResetIcon,
  Security as SecurityIcon,
  Slideshow as BoardPackIcon,
  Receipt as AccrualReportIcon,
  Paid as DebtorIcon,
  WarningAmber as WarningIcon,
} from "@mui/icons-material";
import {
  deleteCipFile,
  downloadCipJournalReview,
  downloadCipReport,
  generateCipReport,
  getCipStatus,
  resetCipData,
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
  { label: "Revenue Analytics", icon: TrendingUpIcon, path: "/dashboard" },
  { label: "Revenue Forecasting", icon: ForecastIcon, path: "/forecasting" },
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies" },
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack" },
  { label: "Financial Analysis", icon: FinancialAnalysisIcon, path: "/financial-analysis" },
  { label: "CIP Reconciliation", icon: CIPAccountIcon, path: "/cip-reconciliation", active: true },
  { label: "Accrual Entry Report", icon: AccrualReportIcon, path: "/accrual-entry-report" },
  { label: "Debtor Age Analysis", icon: DebtorIcon, path: "/debtor-age-analysis" },
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

const CATEGORY_CONFIG = {
  opening_balances: {
    title: "Prior Period CIP Report",
    subtitle: "Prior-period closing balances (.xlsx, .xlsm)",
    description: "Provides the project-wise opening balances for the selected month.",
    iconBg: "bg-slate-100 text-slate-700",
    accept: ".xlsx,.xlsm",
  },
  journal_details: {
    title: "Journal Details",
    subtitle: "General Ledger journal transactions (.xlsx)",
    description: "Used to validate the additions and interface movements.",
    iconBg: "bg-amber-100 text-amber-700",
    accept: ".xlsx,.xls",
  },
  project_codes: {
    title: "Project Details and Codes",
    subtitle: "Project master information (.xlsx)",
    description: "Maps journal project references to project numbers and names.",
    iconBg: "bg-teal-100 text-teal-700",
    accept: ".xlsx,.xls",
  },
  interfaced_cip: {
    title: "SLT Interfaced CIP/RWIP Amounts",
    subtitle: "Consolidated interfaced files (.xls, .xlsx)",
    description: "Provides monthly capitalized amounts transferred to Fixed Assets.",
    iconBg: "bg-purple-100 text-purple-700",
    accept: ".xls,.xlsx",
  },
  subledger_detail: {
    title: "SLT Project Subledger Details",
    subtitle: "Project expenditure additions (.xlsx)",
    description: "Provides monthly project expenditure additions by account.",
    iconBg: "bg-sky-100 text-sky-700",
    accept: ".xlsx,.xls",
  },
};
const REQUIRED_CATEGORIES = Object.keys(CATEGORY_CONFIG);

function SectionCard({ title, subtitle, children }) {
  return (
    <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 }, bgcolor: "#fff" }}>
      <h3 className="text-lg font-black text-[#082f49]">{title}</h3>
      {subtitle && <p className="mt-1 text-sm font-semibold text-slate-500">{subtitle}</p>}
      {children}
    </Paper>
  );
}

function currentMonthInput() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function periodLabel(monthInput) {
  const [year, month] = monthInput.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return `${date.toLocaleString("en-US", { month: "short" })}-${String(year).slice(-2)}`;
}

function previousPeriodLabel(monthInput) {
  const [year, month] = monthInput.split("-").map(Number);
  const date = new Date(year, month - 2, 1);
  return periodLabel(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`);
}

function formatDate(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CIPReconciliation() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const [period, setPeriod] = useState(currentMonthInput);
  const selectedPeriod = periodLabel(period);
  const previousPeriod = previousPeriodLabel(period);
  const [statusData, setStatusData] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [uploadingCategory, setUploadingCategory] = useState(null);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [downloadingJournalReview, setDownloadingJournalReview] = useState(false);
  const [generatedReport, setGeneratedReport] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [warningMessage, setWarningMessage] = useState("");
  const [draggingCategory, setDraggingCategory] = useState(null);
  const fileInputRefs = useRef({});
  const downloadingArtifact = downloadingReport || downloadingJournalReview;

  const refreshStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      setStatusData(await getCipStatus(selectedPeriod));
    } catch (error) {
      setErrorMessage(error.message || "Failed to load CIP upload status.");
    } finally {
      setLoadingStatus(false);
    }
  }, [selectedPeriod]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const handleFileUpload = async (category, file) => {
    if (!file) return;
    setErrorMessage("");
    setSuccessMessage("");
    setWarningMessage("");
    setGeneratedReport(null);
    setUploadingCategory(category);
    try {
      await uploadCipFile(category, file, selectedPeriod);
      setSuccessMessage(`Uploaded ${file.name}.`);
      await refreshStatus();
    } catch (error) {
      setErrorMessage(error.message || "Failed to upload file.");
    } finally {
      setUploadingCategory(null);
    }
  };

  const handleRemoveFile = async (category, label) => {
    if (!window.confirm(`Remove the ${label}?`)) return;
    setErrorMessage("");
    setWarningMessage("");
    setGeneratedReport(null);
    try {
      await deleteCipFile(category, selectedPeriod);
      setSuccessMessage(`Removed ${label}.`);
      await refreshStatus();
    } catch (error) {
      setErrorMessage(error.message || "Failed to remove file.");
    }
  };

  const handleReset = async () => {
    if (!window.confirm(`Reset uploaded CIP files for ${selectedPeriod}?`)) return;
    setErrorMessage("");
    setSuccessMessage("");
    setWarningMessage("");
    setGeneratedReport(null);
    setResetting(true);
    try {
      const response = await resetCipData(selectedPeriod);
      setSuccessMessage(response.message || "CIP files were reset.");
      await refreshStatus();
    } catch (error) {
      setErrorMessage(error.message || "Failed to reset CIP files.");
    } finally {
      setResetting(false);
    }
  };

  const handleGenerateReport = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setWarningMessage("");
    setGeneratedReport(null);
    setGeneratingReport(true);
    try {
      const response = await generateCipReport(selectedPeriod);
      setGeneratedReport({
        filename: response.filename,
        journalReviewFilename: response.journal_review_filename,
        period: selectedPeriod,
      });
      const warnings = response.warnings || [];
      if (warnings.length) {
        const details = warnings.slice(0, 3).join(" ");
        const remainder = warnings.length > 3
          ? ` ${warnings.length - 3} additional issue(s) require review.`
          : "";
        setWarningMessage(
          `Report generated with ${warnings.length} source-data issue(s). ${details}${remainder}`
        );
      } else {
        setSuccessMessage("CIP reconciliation report generated. Download it when ready.");
      }
    } catch (error) {
      setErrorMessage(error.message || "Failed to generate the CIP report.");
    } finally {
      setGeneratingReport(false);
    }
  };

  const handleDownloadReport = async () => {
    if (!generatedReport || generatedReport.period !== selectedPeriod) return;
    setErrorMessage("");
    setDownloadingReport(true);
    try {
      await downloadCipReport(generatedReport.filename, generatedReport.period);
      setSuccessMessage("CIP reconciliation report downloaded.");
    } catch (error) {
      setErrorMessage(error.message || "Failed to download the CIP report.");
    } finally {
      setDownloadingReport(false);
    }
  };

  const handleDownloadJournalReview = async () => {
    if (!generatedReport?.journalReviewFilename || generatedReport.period !== selectedPeriod) return;
    setErrorMessage("");
    setDownloadingJournalReview(true);
    try {
      await downloadCipJournalReview(generatedReport.journalReviewFilename, generatedReport.period);
      setSuccessMessage("Journal review downloaded.");
    } catch (error) {
      setErrorMessage(error.message || "Failed to download the journal review.");
    } finally {
      setDownloadingJournalReview(false);
    }
  };

  const uploadedCount = REQUIRED_CATEGORIES.filter(
    (key) => statusData?.categories?.[key]?.uploaded
  ).length;
  const allRequiredUploaded = uploadedCount === REQUIRED_CATEGORIES.length;

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
        <div className="flex min-h-screen">
          <aside className="sticky top-0 hidden h-screen w-[284px] shrink-0 flex-col justify-between overflow-y-auto border-r border-white/10 bg-[#071b2a] text-white shadow-[18px_0_48px_rgba(7,27,42,0.16)] lg:flex">
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
            <div className="mt-auto border-t border-white/10 p-4">
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
                  "&:hover": { backgroundColor: "#C11812" },
                }}
              >
                Sign Out
              </Button>
            </div>
          </aside>

          <main className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src={lightLogo} alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">
                      CIP Reconciliation Report
                    </h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      Monthly Construction in Progress (CIP) &amp; RWIP report
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="hidden items-center space-x-2 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1 sm:flex">
                    <span className="text-xs font-semibold text-slate-600">Period:</span>
                    <TextField
                      type="month"
                      size="small"
                      value={period}
                      onChange={(event) => {
                        if (event.target.value) {
                          setPeriod(event.target.value);
                          setGeneratedReport(null);
                          setErrorMessage("");
                          setSuccessMessage("");
                          setWarningMessage("");
                        }
                      }}
                      variant="standard"
                      InputProps={{ disableUnderline: true }}
                      sx={{ "& .MuiInput-input": { py: 0.5, fontSize: "0.85rem", fontWeight: 700, color: "#0B3041" } }}
                    />
                  </div>
                  <Tooltip title={`Reset uploaded files for ${selectedPeriod}`}>
                    <span>
                      <Button
                        variant="outlined"
                        color="error"
                        size="small"
                        startIcon={resetting ? <CircularProgress size={14} color="inherit" /> : <ResetIcon fontSize="small" />}
                        onClick={handleReset}
                        disabled={resetting || generatingReport || downloadingArtifact || !uploadedCount}
                        sx={{ textTransform: "none", fontWeight: 700, borderRadius: 1.5 }}
                      >
                        {resetting ? "Resetting..." : "Reset"}
                      </Button>
                    </span>
                  </Tooltip>
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

            <div className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-8">
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
              {warningMessage && (
                <Alert
                  severity="warning"
                  icon={<WarningIcon />}
                  onClose={() => setWarningMessage("")}
                >
                  {warningMessage}
                </Alert>
              )}

              <SectionCard
                title="Required Source Files"
                subtitle={`Upload the five source files for ${selectedPeriod}. The prior-period CIP report must close in ${previousPeriod}. Trial Balance is not an upload input.`}
              >
                <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                  {Object.entries(CATEGORY_CONFIG).map(([category, config]) => {
                    const categoryStatus = statusData?.categories?.[category];
                    const isUploaded = Boolean(categoryStatus?.uploaded);
                    const isUploading = uploadingCategory === category;
                    const isDragging = draggingCategory === category;

                    return (
                      <Paper
                        key={category}
                        elevation={0}
                        sx={{
                          p: 3,
                          borderRadius: 2.5,
                          border: isDragging
                            ? "2px dashed #1B6B93"
                            : isUploaded
                              ? "1px solid #a7f3d0"
                              : "1px solid #dce5ee",
                          backgroundColor: isDragging ? "#f0f7fa" : isUploaded ? "#f0fdf4" : "#fafcff",
                          transition: "all 0.2s ease-in-out",
                        }}
                        onDragOver={(event) => {
                          event.preventDefault();
                          setDraggingCategory(category);
                        }}
                        onDragLeave={() => setDraggingCategory(null)}
                        onDrop={(event) => {
                          event.preventDefault();
                          setDraggingCategory(null);
                          const file = event.dataTransfer.files?.[0];
                          if (file) handleFileUpload(category, file);
                        }}
                      >
                        <input
                          ref={(element) => {
                            fileInputRefs.current[category] = element;
                          }}
                          type="file"
                          accept={config.accept}
                          className="hidden"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) handleFileUpload(category, file);
                            event.target.value = "";
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
                              label="Uploaded"
                              icon={<CheckCircleIcon />}
                              sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }}
                            />
                          )}
                        </div>
                        <p className="mt-2.5 text-xs text-slate-600">{config.description}</p>
                        {isUploaded ? (
                          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
                            <p className="truncate text-xs font-bold text-slate-800" title={categoryStatus.filename}>
                              {categoryStatus.filename}
                            </p>
                            <p className="mt-1 text-[11px] font-semibold text-slate-500">
                              Uploaded {formatDate(categoryStatus.uploaded_at)}
                              {categoryStatus.uploaded_by ? ` by ${categoryStatus.uploaded_by}` : ""}
                            </p>
                            <div className="mt-3 flex items-center justify-between">
                              <Button
                                size="small"
                                variant="outlined"
                                onClick={() => fileInputRefs.current[category]?.click()}
                                disabled={isUploading || generatingReport || downloadingArtifact}
                                sx={{ textTransform: "none", fontSize: "12px", fontWeight: 700 }}
                              >
                                Replace
                              </Button>
                              <Button
                                size="small"
                                color="error"
                                onClick={() => handleRemoveFile(category, config.title)}
                                disabled={generatingReport || downloadingArtifact}
                                startIcon={<DeleteIcon fontSize="small" />}
                                sx={{ textTransform: "none", fontSize: "12px", fontWeight: 700 }}
                              >
                                Remove
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <div className="mt-4 flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white px-3 py-5 text-center">
                            <p className="text-xs font-semibold text-slate-600">Drag and drop a file here, or browse</p>
                            <Button
                              variant="outlined"
                              size="small"
                              startIcon={isUploading ? <CircularProgress size={16} color="inherit" /> : <UploadIcon />}
                              onClick={() => fileInputRefs.current[category]?.click()}
                              disabled={isUploading || generatingReport || downloadingArtifact}
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

                <div className="mt-6 flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-slate-500">Files:</span>
                    <Chip
                      size="small"
                      icon={allRequiredUploaded ? <CheckCircleIcon /> : <WarningIcon />}
                      label={
                        loadingStatus
                          ? "Checking uploads..."
                          : `${uploadedCount} of ${REQUIRED_CATEGORIES.length} required files uploaded`
                      }
                      color={allRequiredUploaded ? "success" : "warning"}
                      sx={{ fontWeight: 700 }}
                    />
                    <Button
                      variant="text"
                      size="small"
                      startIcon={loadingStatus ? <CircularProgress size={14} /> : <RefreshIcon />}
                      onClick={refreshStatus}
                      disabled={loadingStatus}
                      sx={{ textTransform: "none", color: "#64748b", fontWeight: 700 }}
                    >
                      Refresh
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 sm:ml-auto sm:justify-end">
                    <Button
                      variant="contained"
                      disabled={
                        !allRequiredUploaded ||
                        loadingStatus ||
                        generatingReport ||
                        downloadingArtifact ||
                        resetting ||
                        Boolean(uploadingCategory)
                      }
                      onClick={handleGenerateReport}
                      startIcon={generatingReport ? <CircularProgress size={18} color="inherit" /> : <FileIcon />}
                      sx={BUTTON_SX}
                    >
                      {generatingReport ? "Generating report..." : "Generate Report"}
                    </Button>
                    {generatedReport?.period === selectedPeriod && (
                      <>
                        <Button
                          variant="contained"
                          disabled={generatingReport || downloadingArtifact}
                          onClick={handleDownloadReport}
                          startIcon={
                            downloadingReport
                              ? <CircularProgress size={18} color="inherit" />
                              : <DownloadIcon />
                          }
                          sx={{ ...BUTTON_SX, backgroundColor: "#1B6B93", "&:hover": { backgroundColor: "#155577" } }}
                        >
                          {downloadingReport ? "Downloading report..." : "Download Report"}
                        </Button>
                        {generatedReport.journalReviewFilename && (
                          <Button
                            variant="outlined"
                            disabled={generatingReport || downloadingArtifact}
                            onClick={handleDownloadJournalReview}
                            startIcon={
                              downloadingJournalReview
                                ? <CircularProgress size={18} color="inherit" />
                                : <DownloadIcon />
                            }
                            sx={{
                              ...BUTTON_SX,
                              color: "#1B6B93",
                              backgroundColor: "#fff",
                              border: "1px solid #1B6B93",
                              boxShadow: "none",
                              "&:hover": { backgroundColor: "#eff6ff", borderColor: "#155577" },
                            }}
                          >
                            {downloadingJournalReview ? "Downloading journal review..." : "Download Journal Review"}
                          </Button>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </SectionCard>
            </div>
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}

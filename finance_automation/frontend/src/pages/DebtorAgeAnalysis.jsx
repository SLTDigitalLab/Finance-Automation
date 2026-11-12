import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  LinearProgress,
  Paper,
  Tooltip,
} from "@mui/material";
import {
  AccountBalance as AccountBalanceIcon,
  Assessment as AssessmentIcon,
  CheckCircle as CheckCircleIcon,
  CloudUpload as UploadIcon,
  TrendingUp as TrendingUpIcon,
  Dashboard as DashboardIcon,
  Delete as DeleteIcon,
  Download as DownloadIcon,
  Paid as DebtorIcon,
  Person as PersonIcon,
  PlayArrow as GenerateIcon,
  QueryStats as ForecastIcon,
  Receipt as ReceiptIcon,
  Refresh as RefreshIcon,
  RestartAlt as ResetIcon,
  Security as SecurityIcon,
  Slideshow as BoardPackIcon,
  TableChart as TableIcon,
} from "@mui/icons-material";

import { useAuth } from "../contexts/AuthContext";
import { visibleNavItems } from "../config/useCases";
import {
  deleteDebtorAgeFile,
  downloadDebtorAgeReport,
  generateDebtorAgeReport,
  getDebtorAgeStatus,
  resetDebtorAgeData,
  uploadDebtorAgingFile,
  uploadNettingReportFile,
} from "../services/api";
import lightLogo from "../Assets/sltmobitel-logo-png_seeklogo-433080.png";

const NAV_ITEMS = [
  { label: "Revenue Analytics", icon: TrendingUpIcon, path: "/dashboard" },
  { label: "Revenue Forecasting", icon: ForecastIcon, path: "/forecasting" },
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies" },
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack" },
  { label: "Financial Analysis", icon: AssessmentIcon, path: "/financial-analysis" },
  { label: "CIP Reconciliation", icon: AccountBalanceIcon, path: "/cip-reconciliation" },
  { label: "Accrual Entry Report", icon: ReceiptIcon, path: "/accrual-entry-report" },
  { label: "Debtor Age Analysis", icon: DebtorIcon, path: "/debtor-age-analysis", active: true },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const INPUTS = [
  {
    key: "debtor_aging",
    fileKey: "debtor-aging",
    title: "Debtor Aging (Net of Creditors) Workbook",
    description: "International debtor aging summary in USD (Sheets: Summary, 122105 (Voice), 122107 (Non Voice)).",
  },
  {
    key: "netting_report",
    fileKey: "netting-report",
    title: "SLT AR/AP Netting Report Workbook",
    description: "Transaction-level AR/AP details for international operators with transaction numbers and dates.",
  },
];

function formatBytes(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function InputCard({ input, fileInfo, busy, onUpload, onDelete }) {
  const fileInputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const isUploaded = !!fileInfo?.uploaded;

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onUpload(input.fileKey, dropped);
  };

  return (
    <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-extrabold text-[#082f49]">{input.title}</h3>
            {isUploaded && <span className="text-xs font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">Uploaded</span>}
          </div>
          <p className="mt-1 text-sm text-slate-500">{input.description}</p>
        </div>
        <Chip
          size="small"
          icon={isUploaded ? <CheckCircleIcon /> : <TableIcon />}
          label={isUploaded ? "Ready" : "Required"}
          color={isUploaded ? "success" : "default"}
          variant={isUploaded ? "filled" : "outlined"}
        />
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xls,.xlsm"
        hidden
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) onUpload(input.fileKey, selected);
          event.target.value = "";
        }}
      />

      {!isUploaded ? (
        <div
          onClick={() => !busy && fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={`mt-4 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 cursor-pointer transition-colors ${
            dragging ? "border-[#1B6B93] bg-[#edf4fb]" : "border-slate-300 bg-slate-50 hover:border-[#1B6B93] hover:bg-[#f0f7ff]"
          }`}
        >
          {busy ? (
            <CircularProgress size={32} sx={{ color: "#1B6B93" }} />
          ) : (
            <UploadIcon sx={{ fontSize: 36, color: "#b08a2e" }} />
          )}
          <p className="text-sm font-bold text-[#082f49]">
            {busy ? "Uploading..." : "Drop workbook here or click to browse"}
          </p>
          <p className="text-xs text-slate-500">.xlsx or .xls</p>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            variant="outlined"
            startIcon={busy ? <CircularProgress size={16} /> : <UploadIcon />}
            disabled={busy}
            onClick={() => fileInputRef.current?.click()}
            sx={{ textTransform: "none", fontWeight: 800, borderRadius: 2 }}
          >
            Replace workbook
          </Button>
          <span className="min-w-0 break-all text-sm font-semibold text-slate-600">
            {fileInfo.filename} ({formatBytes(fileInfo.size)})
          </span>
          <Tooltip title={`Remove ${input.title}`}>
            <button
              type="button"
              onClick={() => onDelete(input.fileKey)}
              className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-slate-500 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
              aria-label={`Remove ${input.title}`}
            >
              <DeleteIcon fontSize="small" />
            </button>
          </Tooltip>
        </div>
      )}
    </Paper>
  );
}

export default function DebtorAgeAnalysis() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [busyKey, setBusyKey] = useState("");
  const [generating, setGenerating] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [generationStage, setGenerationStage] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const loadStatus = useCallback(async () => {
    try {
      setLoadingStatus(true);
      const s = await getDebtorAgeStatus();
      setStatus(s);
    } catch (err) {
      setErrorMessage(err.message || "Could not load upload status.");
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleUpload = async (fileKey, file) => {
    setBusyKey(fileKey);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      if (fileKey === "debtor-aging") {
        await uploadDebtorAgingFile(file);
        setSuccessMessage("Debtor Aging file uploaded and validated successfully.");
      } else {
        await uploadNettingReportFile(file);
        setSuccessMessage("AR/AP Netting Report uploaded and validated successfully.");
      }
      await loadStatus();
    } catch (err) {
      setErrorMessage(err.message || "Upload failed.");
    } finally {
      setBusyKey("");
    }
  };

  const handleDelete = async (fileKey) => {
    setErrorMessage("");
    setSuccessMessage("");
    try {
      await deleteDebtorAgeFile(fileKey);
      setSuccessMessage("File removed.");
      await loadStatus();
    } catch (err) {
      setErrorMessage(err.message || "Failed to remove file.");
    }
  };

  const handleGenerate = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setGenerating(true);
    setProgress(15);
    setGenerationStage("Reading uploaded source workbooks...");

    const t1 = setTimeout(() => {
      setProgress(40);
      setGenerationStage("Matching counterparty transactions and invoice numbers...");
    }, 350);

    const t2 = setTimeout(() => {
      setProgress(70);
      setGenerationStage("Calculating days past due and aging buckets (0-30, 31-60, ... 1096+)...");
    }, 700);

    const t3 = setTimeout(() => {
      setProgress(90);
      setGenerationStage("Preserving customer account codes, computing subtotals, and finalizing report...");
    }, 1100);

    try {
      const result = await generateDebtorAgeReport();
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      setProgress(100);
      setGenerationStage("Debtor Age Analysis Report generated successfully!");
      setSuccessMessage(result.message || "Debtor Age Analysis Report generated successfully.");
      await loadStatus();
    } catch (err) {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      setProgress(0);
      setGenerationStage("");
      setErrorMessage(err.message || "Unable to generate Debtor Age Analysis Report.");
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = async () => {
    setErrorMessage("");
    setDownloading(true);
    try {
      await downloadDebtorAgeReport();
      setSuccessMessage("SLT_Debtor_Age_Analysis_Report.xlsx downloaded successfully.");
    } catch (err) {
      setErrorMessage(err.message || "Unable to download report.");
    } finally {
      setDownloading(false);
    }
  };

  const handleReset = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setResetting(true);
    try {
      const res = await resetDebtorAgeData();
      setProgress(0);
      setGenerationStage("");
      setSuccessMessage(res.message || "All uploaded documents and generated reports have been reset to the initial state.");
      await loadStatus();
    } catch (err) {
      setErrorMessage(err.message || "Failed to reset Debtor Age Analysis data.");
    } finally {
      setResetting(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const allReady = !!(status?.debtor_aging?.uploaded && status?.netting_report?.uploaded);
  const reportReady = !!status?.report_ready;

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
      <div className="flex min-h-screen">
        {/* Left Side Navigation Panel */}
        <aside className="sticky top-0 hidden h-screen w-[284px] shrink-0 flex-col justify-between border-r border-white/10 bg-[#071b2a] text-white shadow-[18px_0_48px_rgba(7,27,42,0.16)] lg:flex">
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
                    active ? "bg-white text-[#071b2a] shadow-lg" : "text-slate-300 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  <Icon fontSize="small" />
                  <span>{label}</span>
                </button>
              ))}
            </nav>
          </div>
          <div className="border-t border-white/10 p-4">
            <Button
              onClick={handleLogout}
              variant="contained"
              fullWidth
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

        {/* Main Content Area */}
        <main className="flex min-w-0 flex-1 flex-col">
          {/* Top Bar Header */}
          <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
            <div className="flex items-center justify-between gap-4">
              <img src={lightLogo} alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
              <div className="flex-1 text-center">
                <h1 className="truncate text-lg font-black text-[#082f49] md:text-2xl">Debtor Age Analysis Report</h1>
                <p className="hidden text-sm font-bold text-slate-500 sm:block">
                  Monthly Debtor Age Analysis from AR/AP netting and debtor aging workbooks
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Tooltip title="Reset uploaded workbooks and generated report">
                  <span>
                    <Button
                      variant="outlined"
                      color="error"
                      size="small"
                      startIcon={resetting ? <CircularProgress size={14} color="inherit" /> : <ResetIcon fontSize="small" />}
                      onClick={handleReset}
                      disabled={resetting || generating}
                      sx={{
                        textTransform: "none",
                        fontWeight: 700,
                        borderRadius: 1.5,
                        borderColor: "#fca5a5",
                        color: "#b91c1c",
                        "&:hover": { borderColor: "#ef4444", backgroundColor: "#fef2f2" },
                      }}
                    >
                      {resetting ? "Resetting..." : "Reset"}
                    </Button>
                  </span>
                </Tooltip>
              </div>
            </div>
          </header>

          {/* Page Body */}
          <div className="mx-auto w-full max-w-5xl space-y-6 p-4 md:p-8">
            {errorMessage && (
              <Alert severity="error" onClose={() => setErrorMessage("")}>{errorMessage}</Alert>
            )}
            {successMessage && (
              <Alert severity="success" onClose={() => setSuccessMessage("")}>{successMessage}</Alert>
            )}

            {/* Step 1 Title Header Card */}
            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-black text-[#082f49]">Required Source Workbooks</h2>
                  <p className="mt-1 text-sm font-medium text-slate-500">
                    Upload both input Excel workbooks to compute the invoice-level debtor aging analysis.
                  </p>
                </div>
              </div>
            </Paper>

            {/* File Upload Cards */}
            {loadingStatus && !status ? (
              <div className="flex justify-center py-12"><CircularProgress /></div>
            ) : (
              <div className="space-y-4">
                {INPUTS.map((input) => (
                  <InputCard
                    key={input.key}
                    input={input}
                    fileInfo={status?.[input.key]}
                    busy={busyKey === input.fileKey}
                    onUpload={handleUpload}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}

            {/* Generate & Download Report Card */}
            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6 shadow-sm">
              <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-black text-[#082f49]">Generate Report</h2>
                    <p className="mt-1 text-sm font-medium text-slate-500">
                      Calculates invoice-level age analysis in LKR across all 9 aging buckets, preserving the official Oracle AR format.
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      onClick={handleGenerate}
                      disabled={!allReady || generating || loadingStatus}
                      variant="contained"
                      startIcon={generating ? <CircularProgress size={18} color="inherit" /> : <GenerateIcon />}
                      sx={{
                        minWidth: 170,
                        height: 46,
                        px: 3,
                        textTransform: "none",
                        fontWeight: 800,
                        borderRadius: 2,
                        backgroundColor: "#0B3041",
                        "&:hover": { backgroundColor: "#1B6B93" },
                      }}
                    >
                      {generating ? "Generating..." : reportReady ? "Re-generate Report" : "Generate Report"}
                    </Button>

                    {reportReady && (
                      <Button
                        onClick={handleDownload}
                        disabled={downloading}
                        variant="contained"
                        startIcon={downloading ? <CircularProgress size={18} color="inherit" /> : <DownloadIcon />}
                        sx={{
                          minWidth: 180,
                          height: 46,
                          px: 3,
                          textTransform: "none",
                          fontWeight: 800,
                          borderRadius: 2,
                          backgroundColor: "#059669",
                          "&:hover": { backgroundColor: "#047857" },
                          boxShadow: "0 4px 14px rgba(5,150,105,0.3)",
                        }}
                      >
                        {downloading ? "Downloading..." : "Download Report"}
                      </Button>
                    )}
                  </div>
                </div>

                {/* Progress Indicator */}
                {(generating || reportReady) && (
                  <div className="mt-2 rounded-xl border border-slate-100 bg-[#f8fafc] p-4">
                    <div className="flex items-center justify-between text-xs font-bold text-slate-600 mb-2">
                      <span className="flex items-center gap-2">
                        {generating ? (
                          <CircularProgress size={14} thickness={5} sx={{ color: "#1B6B93" }} />
                        ) : (
                          <CheckCircleIcon sx={{ fontSize: 16, color: "#059669" }} />
                        )}
                        <span className="text-slate-700">{generationStage || "Report is ready for download."}</span>
                      </span>
                      <span className="font-extrabold text-[#0B3041]">{progress || 100}%</span>
                    </div>

                    <LinearProgress
                      variant="determinate"
                      value={progress || 100}
                      sx={{
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: "#e2e8f0",
                        "& .MuiLinearProgress-bar": {
                          borderRadius: 4,
                          backgroundColor: (progress === 100 || reportReady) ? "#059669" : "#1B6B93",
                          transition: "transform 0.4s ease",
                        },
                      }}
                    />

                    {reportReady && (
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-200/70">
                        <p className="text-sm font-bold text-slate-700">
                          File: {status?.report_filename || "SLT_Debtor_Age_Analysis_Report.xlsx"} &middot; Natural Account 122105 (Voice Debtors)
                        </p>
                        <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-800 bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200">
                          <CheckCircleIcon fontSize="inherit" /> Ready to Download
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Paper>

            {/* Informational Card */}
            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
              <h3 className="text-base font-extrabold text-[#082f49] mb-2">Report Specifications</h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                The <strong>SLT Debtor Age Analysis Report</strong> (<code>SLT_Debtor_Age_Analysis_Report.xlsx</code>) is an invoice-level
                aging report covering all outstanding international Voice Receivables (Natural Account <strong>122105</strong>).
                Aging buckets are computed from invoice Due Dates against the report As-on-Date:
              </p>
              <div className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2 text-xs font-semibold text-slate-700">
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Current (not overdue)</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 00 &ndash; 30 days</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 31 &ndash; 60 days</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 61 &ndash; 90 days</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 91 &ndash; 180 days</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 181 &ndash; 365 days</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 366 &ndash; 730 days</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 731 &ndash; 1095 days</span>
                <span className="bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg">&bull; Age 1096+ Above</span>
              </div>
            </Paper>
          </div>
        </main>
      </div>
    </div>
  );
}

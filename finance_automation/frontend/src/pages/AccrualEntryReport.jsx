import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  LinearProgress,
  Paper,
  TextField,
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
  Person as PersonIcon,
  QueryStats as ForecastIcon,
  Security as SecurityIcon,
  PlayArrow as GenerateIcon,
  Receipt as ReceiptIcon,
  Refresh as RefreshIcon,
  RestartAlt as ResetIcon,
  Slideshow as BoardPackIcon,
  TableChart as TableIcon,
  Paid as DebtorIcon,
} from "@mui/icons-material";

import { useAuth } from "../contexts/AuthContext";
import { visibleNavItems } from "../config/useCases";
import {
  deleteAccrualEntryFile,
  downloadAccrualEntryReport,
  generateAccrualEntryReport,
  getAccrualEntryStatus,
  resetAccrualEntryData,
  uploadAccrualEntryFile,
} from "../services/api";
import lightLogo from "../Assets/sltmobitel-logo-png_seeklogo-433080.png";

const INPUTS = [
  {
    key: "payment_details",
    title: "Payment Details",
    description: "Current-period monthly payment schedule (.xlsx)",
  },
  {
    key: "prior_accrual",
    title: "Prior Month Accrual",
    description: "Previous month's accrual workbook (.xlsx)",
  },
  {
    key: "account_analysis",
    title: "Account Analysis",
    description: "Current-period account activity and cleared accruals (.xlsx)",
  },
];

const NAV_ITEMS = [
  { label: "Revenue Analytics", icon: TrendingUpIcon, path: "/dashboard" },
  { label: "Revenue Forecasting", icon: ForecastIcon, path: "/forecasting" },
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies" },
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack" },
  { label: "Financial Analysis", icon: AssessmentIcon, path: "/financial-analysis" },
  { label: "CIP Reconciliation", icon: AccountBalanceIcon, path: "/cip-reconciliation" },
  { label: "Accrual Entry Report", icon: ReceiptIcon, path: "/accrual-entry-report", active: true },
  { label: "Debtor Age Analysis", icon: DebtorIcon, path: "/debtor-age-analysis" },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const toApiPeriod = (monthValue) => {
  if (!monthValue) return "";
  const [year, month] = monthValue.split("-");
  const monthLabel = new Intl.DateTimeFormat("en", { month: "short", timeZone: "UTC" })
    .format(new Date(`${monthValue}-01T00:00:00Z`));
  return `${monthLabel}-${year.slice(-2)}`;
};

function InputCard({ input, file, busy, onSelect, onDelete }) {
  const fileInputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const isUploaded = !!file?.uploaded;

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onSelect(input.key, dropped);
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
          if (selected) onSelect(input.key, selected);
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
          <span className="min-w-0 break-all text-sm font-semibold text-slate-600">{file.filename}</span>
          <Tooltip title={`Remove ${input.title}`}>
            <button
              type="button"
              onClick={() => onDelete(input.key, input.title)}
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

export default function AccrualEntryReport() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [monthValue, setMonthValue] = useState("2026-09");
  const period = toApiPeriod(monthValue);
  const [statusData, setStatusData] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [busyCategory, setBusyCategory] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [generationStage, setGenerationStage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [reportSummary, setReportSummary] = useState(null);

  const refreshStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      setStatusData(await getAccrualEntryStatus(period));
    } catch (error) {
      setErrorMessage(error.message || "Unable to load accrual input status.");
    } finally {
      setLoadingStatus(false);
    }
  }, [period]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const handleUpload = async (category, file) => {
    setErrorMessage("");
    setSuccessMessage("");
    setBusyCategory(category);
    try {
      await uploadAccrualEntryFile(category, file, period);
      setSuccessMessage(`${file.name} uploaded successfully.`);
      setReportSummary(null);
      setProgress(0);
      setGenerationStage("");
      await refreshStatus();
    } catch (error) {
      setErrorMessage(error.message || "Unable to upload workbook.");
    } finally {
      setBusyCategory(null);
    }
  };

  const handleDelete = async (category, label) => {
    if (!window.confirm(`Remove the ${label} workbook for ${period}?`)) return;
    setErrorMessage("");
    try {
      await deleteAccrualEntryFile(category, period);
      setSuccessMessage(`${label} workbook removed.`);
      setReportSummary(null);
      setProgress(0);
      setGenerationStage("");
      await refreshStatus();
    } catch (error) {
      setErrorMessage(error.message || "Unable to remove workbook.");
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
      setGenerationStage("Matching payment schedules and natural accounts...");
    }, 350);

    const t2 = setTimeout(() => {
      setProgress(70);
      setGenerationStage("Carrying forward accruals and processing quarterly entries...");
    }, 700);

    const t3 = setTimeout(() => {
      setProgress(90);
      setGenerationStage("Compiling journal worksheets and verifying balances...");
    }, 1100);

    try {
      const result = await generateAccrualEntryReport(period);
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      setProgress(100);
      setGenerationStage("Accrual entry report generated successfully!");
      setReportSummary(result);
      setSuccessMessage(`Report generated: ${result.journal_entries} journal entries ready for download.`);
    } catch (error) {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      setProgress(0);
      setGenerationStage("");
      setErrorMessage(error.message || "Unable to generate accrual entry report.");
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = async () => {
    if (!reportSummary?.filename) return;
    setErrorMessage("");
    setDownloading(true);
    try {
      await downloadAccrualEntryReport(reportSummary.filename, period);
      setSuccessMessage("Accrual entry report downloaded successfully.");
    } catch (error) {
      setErrorMessage(error.message || "Unable to download report.");
    } finally {
      setDownloading(false);
    }
  };

  const handleReset = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setResetting(true);
    try {
      const res = await resetAccrualEntryData(period);
      setProgress(0);
      setGenerationStage("");
      setReportSummary(null);
      setSuccessMessage(res.message || "All uploaded documents and generated reports have been reset.");
      await refreshStatus();
    } catch (err) {
      setErrorMessage(err.message || "Failed to reset Accrual Entry data.");
    } finally {
      setResetting(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const allReady = INPUTS.every((input) => statusData?.categories?.[input.key]?.uploaded);

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
      <div className="flex min-h-screen">
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

        <main className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
            <div className="flex items-center justify-between gap-4">
              <img src={lightLogo} alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
              <div className="flex-1 text-center">
                <h1 className="truncate text-lg font-black text-[#082f49] md:text-2xl">Accrual Entry Report</h1>
                <p className="hidden text-sm font-bold text-slate-500 sm:block">
                  Monthly journal entries built from payment details, prior accruals, and account analysis
                </p>
              </div>
              <div className="flex items-center gap-3">
                <TextField
                  type="month"
                  size="small"
                  label="Period"
                  value={monthValue}
                  onChange={(event) => {
                    setMonthValue(event.target.value);
                    setReportSummary(null);
                    setProgress(0);
                    setGenerationStage("");
                    setSuccessMessage("");
                  }}
                  InputLabelProps={{ shrink: true }}
                  sx={{ width: 170, "& .MuiInputBase-root": { bgcolor: "white", borderRadius: 2 } }}
                />
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

          <div className="mx-auto w-full max-w-5xl space-y-6 p-4 md:p-8">
            {errorMessage && (
              <Alert severity="error" onClose={() => setErrorMessage("")}>{errorMessage}</Alert>
            )}
            {successMessage && (
              <Alert severity="success" onClose={() => setSuccessMessage("")}>{successMessage}</Alert>
            )}

            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-black text-[#082f49]">Required source workbooks</h2>
                  <p className="mt-1 text-sm font-medium text-slate-500">
                    Upload all three Excel inputs for {period}. The reference output is not used as a source.
                  </p>
                </div>
              </div>
            </Paper>

            {loadingStatus && !statusData ? (
              <div className="flex justify-center py-12"><CircularProgress /></div>
            ) : (
              <div className="space-y-4">
                {INPUTS.map((input) => (
                  <InputCard
                    key={input.key}
                    input={input}
                    file={statusData?.categories?.[input.key]}
                    busy={busyCategory === input.key}
                    onSelect={handleUpload}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}

            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6 shadow-sm">
              <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-black text-[#082f49]">Generate Report</h2>
                    <p className="mt-1 text-sm font-medium text-slate-500">
                      The report carries forward eligible accruals and builds current-period entries from the uploaded data.
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    {/* Separate Generate Button */}
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
                      {generating ? "Generating..." : reportSummary ? "Re-generate Report" : "Generate Report"}
                    </Button>

                    {/* Separate Download Button - Appears once generated */}
                    {reportSummary && (
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

                {/* Visual Progress Bar while generating or when completed */}
                {(generating || reportSummary) && (
                  <div className="mt-2 rounded-xl border border-slate-100 bg-[#f8fafc] p-4">
                    <div className="flex items-center justify-between text-xs font-bold text-slate-600 mb-2">
                      <span className="flex items-center gap-2">
                        {generating ? (
                          <CircularProgress size={14} thickness={5} sx={{ color: "#1B6B93" }} />
                        ) : (
                          <CheckCircleIcon sx={{ fontSize: 16, color: "#059669" }} />
                        )}
                        <span className="text-slate-700">{generationStage}</span>
                      </span>
                      <span className="font-extrabold text-[#0B3041]">{progress}%</span>
                    </div>

                    <LinearProgress
                      variant="determinate"
                      value={progress}
                      sx={{
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: "#e2e8f0",
                        "& .MuiLinearProgress-bar": {
                          borderRadius: 4,
                          backgroundColor: progress === 100 ? "#059669" : "#1B6B93",
                          transition: "transform 0.4s ease",
                        },
                      }}
                    />

                    {reportSummary && (
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-200/70">
                        <p className="text-sm font-bold text-slate-700">
                          {reportSummary.journal_entries} journal entries &middot; {reportSummary.carried_forward_entries} carried forward &middot; {reportSummary.current_period_entries} current period
                        </p>
                        <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-800 bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200">
                          <CheckCircleIcon sx={{ fontSize: 15 }} />
                          <span>{reportSummary.filename} generated</span>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {!allReady && (
                  <p className="mt-1 text-sm font-semibold text-amber-700">
                    Upload the three required workbooks to enable report generation.
                  </p>
                )}
              </div>
            </Paper>
          </div>
        </main>
      </div>
    </div>
  );
}

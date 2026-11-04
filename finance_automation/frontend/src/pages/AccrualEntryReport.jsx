import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Paper,
  TextField,
  Tooltip,
} from "@mui/material";
import {
  AccountBalance as AccountBalanceIcon,
  Assessment as AssessmentIcon,
  CheckCircle as CheckCircleIcon,
  CloudUpload as UploadIcon,
  Dashboard as DashboardIcon,
  Delete as DeleteIcon,
  Download as DownloadIcon,
  Person as PersonIcon,
  Receipt as ReceiptIcon,
  Refresh as RefreshIcon,
  Slideshow as BoardPackIcon,
  TableChart as TableIcon,
} from "@mui/icons-material";

import { useAuth } from "../contexts/AuthContext";
import { visibleNavItems } from "../config/useCases";
import {
  deleteAccrualEntryFile,
  downloadAccrualEntryReport,
  generateAccrualEntryReport,
  getAccrualEntryStatus,
  loadAccrualEntrySample,
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
  { label: "Dashboard", icon: DashboardIcon, path: "/dashboard" },
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack" },
  { label: "Financial Analysis", icon: AssessmentIcon, path: "/financial-analysis" },
  { label: "CIP Reconciliation", icon: AccountBalanceIcon, path: "/cip-reconciliation" },
  { label: "Accrual Entry Report", icon: ReceiptIcon, path: "/accrual-entry-report", active: true },
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
  return (
    <Paper elevation={0} className="rounded-2xl border border-slate-200 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-black text-[#082f49]">{input.title}</h3>
          <p className="mt-1 text-sm font-medium text-slate-500">{input.description}</p>
        </div>
        <Chip
          size="small"
          icon={file?.uploaded ? <CheckCircleIcon /> : <TableIcon />}
          label={file?.uploaded ? "Ready" : "Required"}
          color={file?.uploaded ? "success" : "default"}
          variant={file?.uploaded ? "filled" : "outlined"}
        />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx"
          hidden
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (selected) onSelect(input.key, selected);
            event.target.value = "";
          }}
        />
        <Button
          variant="outlined"
          startIcon={busy ? <CircularProgress size={16} /> : <UploadIcon />}
          disabled={busy}
          onClick={() => fileInputRef.current?.click()}
          sx={{ textTransform: "none", fontWeight: 800, borderRadius: 2 }}
        >
          {file?.uploaded ? "Replace workbook" : "Upload workbook"}
        </Button>
        {file?.uploaded && (
          <>
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
          </>
        )}
      </div>
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
  const [loadingSample, setLoadingSample] = useState(false);
  const [generating, setGenerating] = useState(false);
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
      await refreshStatus();
    } catch (error) {
      setErrorMessage(error.message || "Unable to remove workbook.");
    }
  };

  const handleLoadSample = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setLoadingSample(true);
    try {
      await loadAccrualEntrySample(period);
      setSuccessMessage("Sample September input workbooks loaded.");
      await refreshStatus();
    } catch (error) {
      setErrorMessage(error.message || "Unable to load sample workbooks.");
    } finally {
      setLoadingSample(false);
    }
  };

  const handleGenerate = async () => {
    setErrorMessage("");
    setSuccessMessage("");
    setGenerating(true);
    try {
      const result = await generateAccrualEntryReport(period);
      setReportSummary(result);
      await downloadAccrualEntryReport(result.filename, period);
      setSuccessMessage("Accrual entry report generated and downloaded.");
    } catch (error) {
      setErrorMessage(error.message || "Unable to generate accrual entry report.");
    } finally {
      setGenerating(false);
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
              <div className="min-w-0 text-left md:text-center">
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
                    setSuccessMessage("");
                  }}
                  InputLabelProps={{ shrink: true }}
                  sx={{ width: 170, "& .MuiInputBase-root": { bgcolor: "white", borderRadius: 2 } }}
                />
                <Tooltip title="Refresh input status">
                  <button
                    type="button"
                    onClick={refreshStatus}
                    className="grid h-10 w-10 place-items-center rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    aria-label="Refresh input status"
                  >
                    <RefreshIcon fontSize="small" />
                  </button>
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
                {period === "Sep-26" && (
                  <Button
                    onClick={handleLoadSample}
                    disabled={loadingSample}
                    variant="outlined"
                    startIcon={loadingSample ? <CircularProgress size={16} /> : <UploadIcon />}
                    sx={{ textTransform: "none", fontWeight: 800, borderRadius: 2 }}
                  >
                    Load September sample
                  </Button>
                )}
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

            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-black text-[#082f49]">Generate report</h2>
                  <p className="mt-1 text-sm font-medium text-slate-500">
                    The report carries forward eligible accruals and builds current-period entries from the uploaded data.
                  </p>
                  {reportSummary && (
                    <p className="mt-2 text-sm font-bold text-slate-600">
                      {reportSummary.journal_entries} journal entries · {reportSummary.carried_forward_entries} carried forward · {reportSummary.current_period_entries} current period
                    </p>
                  )}
                </div>
                <Button
                  onClick={handleGenerate}
                  disabled={!allReady || generating || loadingStatus}
                  variant="contained"
                  startIcon={generating ? <CircularProgress size={18} color="inherit" /> : <DownloadIcon />}
                  sx={{
                    minWidth: 210,
                    height: 46,
                    px: 3,
                    textTransform: "none",
                    fontWeight: 900,
                    borderRadius: 2,
                    backgroundColor: "#0B3041",
                    "&:hover": { backgroundColor: "#1B6B93" },
                  }}
                >
                  {generating ? "Generating..." : "Generate & Download"}
                </Button>
              </div>
              {!allReady && (
                <p className="mt-3 text-sm font-semibold text-amber-700">
                  Upload the three required workbooks to enable report generation.
                </p>
              )}
            </Paper>
          </div>
        </main>
      </div>
    </div>
  );
}

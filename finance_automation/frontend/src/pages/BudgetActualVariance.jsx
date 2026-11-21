import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Chip, CircularProgress, Paper, Tooltip } from "@mui/material";
import {
  AccountBalance as AccountBalanceIcon,
  Assessment as AssessmentIcon,
  CloudUpload as UploadIcon,
  Download as DownloadIcon,
  Paid as DebtorIcon,
  Person as PersonIcon,
  QueryStats as ForecastIcon,
  Receipt as ReceiptIcon,
  Security as SecurityIcon,
  Slideshow as BoardPackIcon,
  TrendingUp as TrendingUpIcon,
} from "@mui/icons-material";
import { useAuth } from "../contexts/AuthContext";
import { generateBudgetActualReport } from "../services/api";
import { visibleNavItems } from "../config/useCases";
import lightLogo from "../Assets/sltmobitel-logo-png_seeklogo-433080.png";

const INPUTS = [
  { key: "budget", label: "Upload Budget Excel", description: "Monthly budget workbook" },
  { key: "actual", label: "Upload Actual Excel", description: "Monthly and YTD actual workbook" },
  { key: "mapping", label: "Upload Mapping Excel", description: "ACT code to cost-center mapping" },
];

const NAV_ITEMS = [
  { label: "Revenue Analytics", icon: TrendingUpIcon, path: "/dashboard" },
  { label: "Revenue Forecasting", icon: ForecastIcon, path: "/forecasting" },
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies" },
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack" },
  { label: "Financial Analysis", icon: AssessmentIcon, path: "/financial-analysis" },
  { label: "CIP Reconciliation", icon: AccountBalanceIcon, path: "/cip-reconciliation" },
  { label: "Accrual Entry Report", icon: ReceiptIcon, path: "/accrual-entry-report" },
  { label: "Debtor & Creditor Aging Analysis", icon: DebtorIcon, path: "/debtor-age-analysis" },
  { label: "Budget vs Actual Variance", icon: AssessmentIcon, path: "/budget-actual-variance", active: true },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

export default function BudgetActualVariance() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [files, setFiles] = useState({});
  const [generated, setGenerated] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const refs = useRef({});

  const handleFile = (key, file) => {
    if (!file) return;
    setFiles((current) => ({ ...current, [key]: file }));
    setGenerated(null);
    setError("");
  };

  const generate = async () => {
    if (!INPUTS.every(({ key }) => files[key])) {
      setError("Upload the Budget, Actual, and Mapping Excel workbooks before generating.");
      return;
    }
    setGenerating(true);
    setError("");
    setSuccess("");
    try {
      const result = await generateBudgetActualReport(files);
      setGenerated(result);
      setSuccess("Budget vs Actual Variance report generated successfully.");
    } catch (err) {
      setError(err.message || "Unable to generate report.");
    } finally {
      setGenerating(false);
    }
  };

  const download = () => {
    if (!generated) return;
    const url = URL.createObjectURL(generated.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = generated.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  const signOut = async () => {
    await logout();
    navigate("/login");
  };

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
              onClick={signOut}
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
                <h1 className="truncate text-lg font-black text-[#082f49] md:text-2xl">Budget vs Actual Variance Analysis</h1>
                <p className="hidden text-sm font-bold text-slate-500 sm:block">
                  Monthly and YTD budget versus actual comparison workbook
                </p>
              </div>
            </div>
          </header>
          <div className="mx-auto w-full max-w-5xl space-y-6 p-4 md:p-8">
            {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
            {success && <Alert severity="success" onClose={() => setSuccess("")}>{success}</Alert>}

            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
              <h2 className="text-lg font-black text-[#082f49]">Required Source Workbooks</h2>
              <p className="mt-1 text-sm font-medium text-slate-500">
                Upload the Budget, Actual, and account-mapping Excel workbooks.
              </p>
            </Paper>

            <div className="grid gap-4 md:grid-cols-3">
              {INPUTS.map((input) => {
                const file = files[input.key];
                return (
                  <Paper key={input.key} elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="text-base font-extrabold text-[#082f49]">{input.label}</h3>
                        <p className="mt-1 text-sm text-slate-500">{input.description}</p>
                      </div>
                      <Chip
                        size="small"
                        label={file ? "Ready" : "Required"}
                        color={file ? "success" : "default"}
                        variant={file ? "filled" : "outlined"}
                      />
                    </div>
                    <input
                      ref={(element) => { refs.current[input.key] = element; }}
                      type="file"
                      accept=".xlsx,.xls,.xlsm"
                      hidden
                      onChange={(event) => {
                        handleFile(input.key, event.target.files?.[0]);
                        event.target.value = "";
                      }}
                    />
                    <Button
                      fullWidth
                      startIcon={<UploadIcon />}
                      onClick={() => refs.current[input.key]?.click()}
                      variant="outlined"
                      sx={{
                        mt: 2,
                        height: 46,
                        borderRadius: 2,
                        borderColor: "#1B6B93",
                        color: "#1B6B93",
                        textTransform: "none",
                        fontWeight: 800,
                        "&:hover": { borderColor: "#0B3041", backgroundColor: "#EFF6FA" },
                      }}
                    >
                      {file?.name || "Choose Excel"}
                    </Button>
                  </Paper>
                );
              })}
            </div>

            <Paper elevation={0} className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6 shadow-sm">
              <div className="flex flex-col gap-4">
                <div>
                  <h2 className="text-lg font-black text-[#082f49]">Generate Report</h2>
                  <p className="mt-1 text-sm font-medium text-slate-500">
                    Calculates monthly and YTD variances and produces the six-sheet Excel report.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Tooltip title={!INPUTS.every(({ key }) => files[key]) ? "Upload all three source workbooks" : "Generate the report"}>
                    <span>
                      <Button
                        onClick={generate}
                        disabled={generating || !INPUTS.every(({ key }) => files[key])}
                        variant="contained"
                        startIcon={generating ? <CircularProgress size={18} color="inherit" /> : <AssessmentIcon />}
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
                        {generating ? "Generating..." : "Generate Report"}
                      </Button>
                    </span>
                  </Tooltip>
                  <Button
                    onClick={download}
                    disabled={!generated}
                    variant="outlined"
                    startIcon={<DownloadIcon />}
                    sx={{
                      minWidth: 220,
                      height: 46,
                      px: 3,
                      textTransform: "none",
                      fontWeight: 800,
                      borderRadius: 2,
                    }}
                  >
                    Download Generated Excel
                  </Button>
                </div>
              </div>
            </Paper>
          </div>
        </main>
      </div>
    </div>
  );
}

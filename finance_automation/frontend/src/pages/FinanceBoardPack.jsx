import React, { useRef, useState } from "react";
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
  Paper,
  Tooltip,
} from "@mui/material";
import {
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
  VerifiedUser as VerifiedUserIcon,
  WarningAmber as WarningIcon,
} from "@mui/icons-material";
import { generateBoardPack, downloadBoardPack } from "../services/api";
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
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack", active: true },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const SLIDES = [
  "Executive Summary – Group",
  "Executive Summary – Fixed Business (SLT)",
  "Executive Summary – Mobitel",
  "Executive Summary – SLTS",
  "Group Financials – YTD SLT vs Group",
  "Group Financials – YTD SLT vs Mobitel",
  "Group Financials – YTD SLT / Mobitel / SLTSL",
  "Group Financials – Month SLT vs Group",
  "Group Financials – Month SLT vs Mobitel",
];

const ACCEPTED_EXTENSIONS = [".xlsx", ".xlsm"];
const MAX_FILE_SIZE_MB = 50;

const formatSize = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;

function validateFile(file) {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return "Select the Sub workings Excel file (.xlsx or .xlsm).";
  }
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return `The file is larger than ${MAX_FILE_SIZE_MB} MB.`;
  }
  return null;
}

export default function FinanceBoardPack() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const currentYear = new Date().getFullYear();

  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const selectFile = (selected) => {
    if (!selected) return;
    const problem = validateFile(selected);
    setResult(null);
    if (problem) {
      setFile(null);
      setError(problem);
      return;
    }
    setError("");
    setFile(selected);
  };

  const clearFile = () => {
    setFile(null);
    setResult(null);
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  };

  const handleGenerate = async () => {
    if (!file) return;
    setGenerating(true);
    setError("");
    setResult(null);
    try {
      setResult(await generateBoardPack(file));
    } catch (err) {
      setError(err.message || "Failed to generate the board pack");
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = async () => {
    if (!result?.filename) return;
    setDownloading(true);
    try {
      await downloadBoardPack(result.filename);
    } catch (err) {
      setError(err.message || "Failed to download the board pack");
    } finally {
      setDownloading(false);
    }
  };

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

          <main className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="relative flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src={lightLogo} alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">Finance Board Pack</h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      Generate the monthly board pack PowerPoint from the Sub workings file
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
              <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[1.35fr_1fr]">
                {/* Upload & generate */}
                <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 } }}>
                  <h3 className="text-lg font-black text-[#082f49]">1. Upload the Sub workings workbook</h3>
                  <p className="mt-1 text-sm font-semibold text-slate-500">
                    The first two tabs (INCOME Amalg YTD and BD Slides-SLT-Mobtel-Grp) and the SLTSL tab are used.
                  </p>

                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => inputRef.current?.click()}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDragging(false);
                      selectFile(e.dataTransfer.files?.[0]);
                    }}
                    className={`mt-5 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
                      dragging ? "border-[#1B6B93] bg-sky-50" : "border-slate-300 bg-slate-50 hover:border-[#1B6B93] hover:bg-sky-50/60"
                    }`}
                  >
                    <UploadIcon sx={{ fontSize: 44, color: "#1B6B93" }} />
                    <p className="mt-3 text-sm font-extrabold text-[#082f49]">Drop the Excel file here or click to browse</p>
                    <p className="mt-1 text-xs font-semibold text-slate-500">.xlsx or .xlsm, up to {MAX_FILE_SIZE_MB} MB</p>
                    <input
                      ref={inputRef}
                      type="file"
                      accept={ACCEPTED_EXTENSIONS.join(",")}
                      className="hidden"
                      onChange={(e) => selectFile(e.target.files?.[0])}
                    />
                  </div>

                  {file && (
                    <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <FileIcon sx={{ color: "#7AB648" }} />
                        <div className="min-w-0">
                          <p className="truncate text-sm font-extrabold text-slate-800">{file.name}</p>
                          <p className="text-xs font-semibold text-slate-500">{formatSize(file.size)}</p>
                        </div>
                      </div>
                      <Tooltip title="Remove file">
                        <span>
                          <Button onClick={clearFile} disabled={generating} sx={{ minWidth: 36, color: "#64748b" }}>
                            <DeleteIcon fontSize="small" />
                          </Button>
                        </span>
                      </Tooltip>
                    </div>
                  )}

                  {error && (
                    <Alert severity="error" sx={{ mt: 3, fontWeight: 600 }}>
                      {error}
                    </Alert>
                  )}

                  <h3 className="mt-8 text-lg font-black text-[#082f49]">2. Generate the PowerPoint</h3>
                  <Button
                    onClick={handleGenerate}
                    disabled={!file || generating}
                    variant="contained"
                    startIcon={<BoardPackIcon />}
                    sx={{
                      mt: 2,
                      height: 46,
                      px: 4,
                      textTransform: "none",
                      fontWeight: 900,
                      borderRadius: 1.5,
                      backgroundColor: "#0B3041",
                      "&:hover": { backgroundColor: "#1B6B93" },
                    }}
                  >
                    {generating ? "Generating…" : "Generate Board Pack"}
                  </Button>
                  {generating && <LinearProgress sx={{ mt: 2, borderRadius: 1 }} />}

                  {result && (
                    <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5">
                      <div className="flex items-start gap-3">
                        <CheckCircleIcon sx={{ color: "#047857", mt: 0.25 }} />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-black text-emerald-900">Board pack ready</p>
                          <p className="mt-1 break-all text-xs font-semibold text-emerald-800">{result.filename}</p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Chip size="small" label={`Period: ${result.period}`} sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }} />
                            <Chip size="small" label={`${result.slide_count} slides`} sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }} />
                          </div>
                          <p className="mt-3 text-xs font-semibold text-emerald-900">
                            Tabs read: {result.sheets_used.join(", ")}
                          </p>
                        </div>
                      </div>

                      {result.warnings?.length > 0 && (
                        <Alert severity="warning" icon={<WarningIcon />} sx={{ mt: 3 }}>
                          <p className="font-bold">Check these cells in the workbook:</p>
                          <ul className="mt-1 list-disc pl-5 text-sm">
                            {result.warnings.map((w) => (
                              <li key={w}>{w}</li>
                            ))}
                          </ul>
                        </Alert>
                      )}

                      <Button
                        onClick={handleDownload}
                        disabled={downloading}
                        variant="contained"
                        startIcon={<DownloadIcon />}
                        sx={{
                          mt: 3,
                          height: 44,
                          px: 3.5,
                          textTransform: "none",
                          fontWeight: 900,
                          borderRadius: 1.5,
                          backgroundColor: "#7AB648",
                          "&:hover": { backgroundColor: "#6AA038" },
                        }}
                      >
                        {downloading ? "Downloading…" : "Download PowerPoint (.pptx)"}
                      </Button>
                    </div>
                  )}
                </Paper>

                {/* What's in the pack */}
                <Paper elevation={0} sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 } }}>
                  <h3 className="text-lg font-black text-[#082f49]">Slides in the pack</h3>
                  <p className="mt-1 text-sm font-semibold text-slate-500">
                    Figures in Rs. Mn. Period labels update from the workbook.
                  </p>
                  <ol className="mt-5 space-y-2">
                    {SLIDES.map((title, i) => (
                      <li key={title} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2.5">
                        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[#082f49] text-xs font-black text-white">
                          {i + 1}
                        </span>
                        <span className="text-sm font-bold text-slate-700">{title}</span>
                      </li>
                    ))}
                  </ol>
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

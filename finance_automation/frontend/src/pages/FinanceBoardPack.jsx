import React, { useRef, useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import {
  ThemeProvider,
  createTheme,
  CssBaseline,
  Alert,
  Button,
  Chip,
  Checkbox,
  FormControlLabel,
  LinearProgress,
  Paper,
  Tooltip,
} from "@mui/material";
import {
  CheckCircle as CheckCircleIcon,
  Cancel as CancelIcon,
  CloudUpload as UploadIcon,
  TrendingUp as TrendingUpIcon,
  Delete as DeleteIcon,
  Description as FileIcon,
  Download as DownloadIcon,
  ExitToApp as LogoutIcon,
  Person as PersonIcon,
  QueryStats as ForecastIcon,
  RestartAlt as ResetIcon,
  Security as SecurityIcon,
  Slideshow as BoardPackIcon,
  Assessment as FinancialAnalysisIcon,
  VerifiedUser as VerifiedUserIcon,
  WarningAmber as WarningIcon,
  AccountBalance as CIPAccountIcon,
  Receipt as AccrualReportIcon,
  Paid as DebtorIcon,
  Layers as LayersIcon,
} from "@mui/icons-material";
import {
  inspectBoardPackFiles,
  generateUnifiedBoardPack,
  downloadBoardPack,
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
  { label: "Finance Board Pack", icon: BoardPackIcon, path: "/board-pack", active: true },
  { label: "Financial Analysis", icon: FinancialAnalysisIcon, path: "/financial-analysis" },
  { label: "CIP Reconciliation", icon: CIPAccountIcon, path: "/cip-reconciliation" },
  { label: "Accrual Entry Report", icon: AccrualReportIcon, path: "/accrual-entry-report" },
  { label: "Debtor & Creditor Aging Analysis", icon: DebtorIcon, path: "/debtor-age-analysis" },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const SECTIONS_CONFIG = [
  {
    id: "board_pack",
    label: "Board Pack – 9 slides",
    badge: "9 Slides",
    description: "Executive Summary & Group Financials (SLT, Mobitel, SLTS, Group)",
    requiredInputs: [
      {
        role: "board_pack_excel",
        label: "Sub workings Excel",
        description: "Must contain INCOME Amalg YTD and BD Slides tabs",
      },
    ],
    slides: [
      "Executive Summary – Group",
      "Executive Summary – Fixed Business (SLT)",
      "Executive Summary – Mobitel",
      "Executive Summary – SLTS",
      "Group Financials – YTD SLT vs Group",
      "Group Financials – YTD SLT vs Mobitel",
      "Group Financials – YTD SLT / Mobitel / SLTSL",
      "Group Financials – Month SLT vs Group",
      "Group Financials – Month SLT vs Mobitel",
    ],
  },
  {
    id: "ratio_report",
    label: "Ratio Report – 2 slides",
    badge: "2 Slides",
    description: "Group Balance Sheet & Key Financial Ratios (ROA, ROE, Margins, Leverage)",
    requiredInputs: [
      {
        role: "ratio_excel",
        label: "Ratio & Balance Sheet Excel",
        description: "Must contain Key Financial Ratios and Group Balance Sheet tabs",
      },
    ],
    slides: [
      "Balance Sheet (Group)",
      "Key Financial Ratios (Profitability, Efficiency, Liquidity, Leverage)",
    ],
  },
  {
    id: "mobitel",
    label: "Mobitel – 10 slides",
    badge: "10 Slides",
    description: "Mobile Business Performance, Detailed P&L, BS, CF, Subscribers & ARPU",
    requiredInputs: [
      {
        role: "mobitel_excel",
        label: "Mobitel Performance Excel",
        description: "Extracts SLT Presentation, BS, CF, Subscriber (excludes SLT Income Stat. & Network cost)",
      },
    ],
    slides: [
      "Financial Performance – Mobile Business (Mobitel)*",
      "Summary – Revenue (Mobile Business)",
      "Summary - Direct Costs (Mobile Business)",
      "Summary – Sales & Marketing (Mobile Business)",
      "Summary – Administrative Expenditure (Mobile Business)",
      "Summary - Other Costs/Income Impact to Net profit (Mobile Business)",
      "Summary – Balance Sheet (Mobile Business)",
      "Summary – Cash Flow Statement (Mobile Business)",
      "Summary – Subscribers (Mobile)",
      "Summary – ARPU (Mobile)",
    ],
  },
  {
    id: "telecom_services",
    label: "Telecom Services – 9 slides",
    badge: "9 Slides",
    description: "SLTS Performance: Revenue, Direct Costs, S&M, Admin, Other Costs, BS, CF & Active Subscribers",
    requiredInputs: [
      {
        role: "telecom_info_excel",
        label: "Telecom Services Information Excel",
        description: "Contains Detailed Information for PPT tab (revenue & direct cost categories)",
      },
      {
        role: "telecom_pl_excel",
        label: "SLTS P&L Summary Excel",
        description: "Summary P&L with Month & YTD figures",
      },
      {
        role: "telecom_bscf_pptx",
        label: "Telecom Services BS & CF PowerPoint",
        description: "Supplied deck containing SLTS Balance Sheet and Cash Flow slides",
      },
    ],
    slides: [
      "Financial Performance - SLTS",
      "Summary – Revenue (SLTS)",
      "Summary - Direct Costs (SLTS)",
      "Summary - Sales & Marketing Costs (SLTS)",
      "Summary - Administrative Costs (SLTS)",
      "Summary - Other Costs/Income Impact to Net profit (SLTS)",
      "Summary – Balance Sheet (SLTS)",
      "Summary – Cash Flow Statement (SLTS)",
      "Summary – Active Subscribers (SLTS)",
    ],
  },
];

const ACCEPTED_EXTENSIONS = [".xlsx", ".xlsm", ".pptx"];
const MAX_FILE_SIZE_MB = 50;

const formatSize = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;

const ROLE_DISPLAY_NAMES = {
  board_pack_excel: "Sub workings Workbook (INCOME & BD Slides)",
  ratio_excel: "Ratio & Balance Sheet Workbook",
  mobitel_excel: "Mobitel Performance Workbook",
  telecom_info_excel: "Telecom Services Information Workbook",
  telecom_pl_excel: "SLTS P&L Summary Workbook",
  telecom_bscf_pptx: "Telecom Services BS & CF Presentation",
};

export default function FinanceBoardPack() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const currentYear = new Date().getFullYear();

  // Checkboxes state (all 4 selected by default)
  const [selectedSections, setSelectedSections] = useState({
    board_pack: true,
    ratio_report: true,
    mobitel: true,
    telecom_services: true,
  });

  // Staged files: array of File objects
  const [files, setFiles] = useState([]);
  // Inspection results from backend
  const [inspectedMap, setInspectedMap] = useState({});
  const [inspecting, setInspecting] = useState(false);

  const [dragging, setDragging] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const toggleSection = (id) => {
    setSelectedSections((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
    setResult(null);
    setError("");
  };

  // Inspect staged files on change
  useEffect(() => {
    if (files.length === 0) {
      setInspectedMap({});
      return;
    }

    let isMounted = true;
    const runInspection = async () => {
      setInspecting(true);
      try {
        const res = await inspectBoardPackFiles(files);
        if (isMounted && res?.files) {
          const map = {};
          for (const f of res.files) {
            map[f.original_filename || f.filename] = f;
          }
          setInspectedMap(map);
        }
      } catch (err) {
        console.warn("Structural inspection error:", err);
      } finally {
        if (isMounted) setInspecting(false);
      }
    };

    runInspection();
    return () => {
      isMounted = false;
    };
  }, [files]);

  // Handle file additions
  const handleFilesAdded = (newFileList) => {
    if (!newFileList || newFileList.length === 0) return;
    setError("");
    setResult(null);

    const validFiles = [];
    for (let i = 0; i < newFileList.length; i++) {
      const f = newFileList[i];
      const name = f.name.toLowerCase();
      const extMatch = ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
      if (!extMatch) {
        setError(`File "${f.name}" is not supported. Use .xlsx, .xlsm, or .pptx.`);
        continue;
      }
      if (f.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
        setError(`File "${f.name}" exceeds ${MAX_FILE_SIZE_MB} MB limit.`);
        continue;
      }
      validFiles.push(f);
    }

    // Merge without duplicates
    setFiles((prev) => {
      const existingNames = new Set(prev.map((p) => p.name));
      const filtered = validFiles.filter((vf) => !existingNames.has(vf.name));
      return [...prev, ...filtered];
    });
  };

  const removeFile = (fileName) => {
    setFiles((prev) => prev.filter((f) => f.name !== fileName));
    setResult(null);
  };

  const handleReset = () => {
    setFiles([]);
    setInspectedMap({});
    setResult(null);
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  };

  // Compute available roles from inspected files
  const availableRolesMap = useMemo(() => {
    const roleMap = {};
    Object.values(inspectedMap).forEach((info) => {
      if (info.valid && Array.isArray(info.roles)) {
        info.roles.forEach((r) => {
          if (!roleMap[r]) {
            roleMap[r] = info.filename;
          }
        });
      }
    });
    return roleMap;
  }, [inspectedMap]);

  // Compute requirements checklist for selected sections
  const checklist = useMemo(() => {
    const list = [];
    let allReady = true;
    let selectedCount = 0;

    SECTIONS_CONFIG.forEach((sec) => {
      if (!selectedSections[sec.id]) return;
      selectedCount += 1;

      sec.requiredInputs.forEach((req) => {
        const matchedFilename = availableRolesMap[req.role];
        const isReady = Boolean(matchedFilename);
        if (!isReady) allReady = false;

        list.push({
          sectionId: sec.id,
          sectionLabel: sec.label,
          role: req.role,
          label: req.label,
          description: req.description,
          isReady,
          filename: matchedFilename,
        });
      });
    });

    return {
      items: list,
      allReady: allReady && selectedCount > 0,
      selectedCount,
    };
  }, [selectedSections, availableRolesMap]);

  // Compute ordered slides to preview
  const previewSlides = useMemo(() => {
    const slides = [];
    SECTIONS_CONFIG.forEach((sec) => {
      if (selectedSections[sec.id]) {
        sec.slides.forEach((s) => {
          slides.push({
            title: s,
            section: sec.label,
          });
        });
      }
    });
    return slides;
  }, [selectedSections]);

  const handleGenerate = async () => {
    const activeSectionKeys = Object.keys(selectedSections).filter((k) => selectedSections[k]);
    if (activeSectionKeys.length === 0) {
      setError("Please select at least one section to generate.");
      return;
    }
    if (!checklist.allReady) {
      setError("Missing required inputs for selected sections. Check the requirements checklist below.");
      return;
    }

    setGenerating(true);
    setError("");
    setResult(null);

    try {
      const res = await generateUnifiedBoardPack(files, activeSectionKeys);
      setResult(res);
    } catch (err) {
      setError(err.message || "Failed to generate board pack");
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
          {/* Sidebar */}
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

          {/* Main content */}
          <main className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="relative flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src={lightLogo} alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">
                      Finance Board Pack Generator
                    </h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      Multi-section automated presentation generator for Board Pack, Ratios, Mobitel &amp; Telecom Services
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <Tooltip title="Reset uploaded files and generator state">
                    <span>
                      <Button
                        variant="outlined"
                        color="error"
                        size="small"
                        startIcon={<ResetIcon fontSize="small" />}
                        onClick={handleReset}
                        disabled={generating || (files.length === 0 && !result)}
                        sx={{
                          textTransform: "none",
                          fontWeight: 700,
                          borderRadius: 1.5,
                          borderColor: "#fca5a5",
                          color: "#b91c1c",
                          "&:hover": { borderColor: "#ef4444", backgroundColor: "#fef2f2" },
                        }}
                      >
                        Reset
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

            <div className="flex-1 px-4 py-8 md:px-8 lg:px-10">
              {/* Section 1: Checkbox selection */}
              <Paper
                elevation={0}
                sx={{
                  borderRadius: 3,
                  border: "1px solid #dce5ee",
                  p: { xs: 3, md: 4 },
                  mb: 4,
                  backgroundColor: "#ffffff",
                }}
              >
                <div className="flex items-center gap-2">
                  <LayersIcon sx={{ color: "#1B6B93" }} />
                  <h3 className="text-lg font-black text-[#082f49]">1. Select Sections to Generate</h3>
                </div>
                <p className="mt-1 text-sm font-semibold text-slate-500">
                  Select any combination of the four report sections. When multiple are selected, they will be combined
                  seamlessly in the standard stakeholder presentation order.
                </p>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {SECTIONS_CONFIG.map((sec) => {
                    const isChecked = Boolean(selectedSections[sec.id]);
                    return (
                      <div
                        key={sec.id}
                        onClick={() => toggleSection(sec.id)}
                        className={`flex cursor-pointer flex-col justify-between rounded-xl border p-4 transition ${
                          isChecked
                            ? "border-[#1B6B93] bg-sky-50/70 shadow-sm ring-1 ring-[#1B6B93]"
                            : "border-slate-200 bg-slate-50/60 hover:border-slate-300"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <FormControlLabel
                            control={
                              <Checkbox
                                checked={isChecked}
                                onChange={() => toggleSection(sec.id)}
                                sx={{
                                  color: "#1B6B93",
                                  "&.Mui-checked": { color: "#0B3041" },
                                  p: 0,
                                  mr: 1,
                                }}
                              />
                            }
                            label={
                              <span className="text-sm font-black text-[#082f49]">{sec.label}</span>
                            }
                            sx={{ m: 0 }}
                          />
                          <Chip
                            size="small"
                            label={sec.badge}
                            sx={{
                              fontWeight: 800,
                              fontSize: "0.7rem",
                              height: 20,
                              backgroundColor: isChecked ? "#0B3041" : "#e2e8f0",
                              color: isChecked ? "#ffffff" : "#475569",
                            }}
                          />
                        </div>
                        <p className="mt-2 text-xs font-semibold text-slate-500">{sec.description}</p>
                      </div>
                    );
                  })}
                </div>
              </Paper>

              {/* Main Grid: Upload Area & Requirements + Output */}
              <div className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
                {/* Left Column: Multi-File Upload Area */}
                <div className="flex flex-col gap-6">
                  <Paper
                    elevation={0}
                    sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 } }}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-lg font-black text-[#082f49]">2. Upload Monthly Input Files</h3>
                        <p className="mt-1 text-sm font-semibold text-slate-500">
                          Drop Excel (.xlsx, .xlsm) and PowerPoint (.pptx) files. Files are automatically identified from
                          their internal sheets and structures.
                        </p>
                      </div>
                      {files.length > 0 && (
                        <Button
                          size="small"
                          color="error"
                          onClick={handleReset}
                          disabled={generating}
                          sx={{ textTransform: "none", fontWeight: 700 }}
                        >
                          Clear All
                        </Button>
                      )}
                    </div>

                    {/* Drag and Drop Zone */}
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
                        handleFilesAdded(e.dataTransfer.files);
                      }}
                      className={`mt-4 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-9 text-center transition ${
                        dragging
                          ? "border-[#1B6B93] bg-sky-50"
                          : "border-slate-300 bg-slate-50 hover:border-[#1B6B93] hover:bg-sky-50/60"
                      }`}
                    >
                      <UploadIcon sx={{ fontSize: 44, color: "#1B6B93" }} />
                      <p className="mt-3 text-sm font-extrabold text-[#082f49]">
                        Drop multiple Excel &amp; PowerPoint files here, or browse
                      </p>
                      <p className="mt-1 text-xs font-semibold text-slate-500">
                        Supports .xlsx, .xlsm, .pptx — up to {MAX_FILE_SIZE_MB} MB each
                      </p>
                      <input
                        ref={inputRef}
                        type="file"
                        multiple
                        accept={ACCEPTED_EXTENSIONS.join(",")}
                        className="hidden"
                        onChange={(e) => handleFilesAdded(e.target.files)}
                      />
                    </div>

                    {/* Staged files list with structural role tags */}
                    {files.length > 0 && (
                      <div className="mt-4 space-y-2">
                        <p className="text-xs font-black uppercase tracking-wider text-slate-500">
                          Uploaded Files ({files.length})
                        </p>
                        {files.map((f) => {
                          const info = inspectedMap[f.name];
                          return (
                            <div
                              key={f.name}
                              className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-xs"
                            >
                              <div className="flex min-w-0 items-center gap-3">
                                <FileIcon sx={{ color: "#7AB648" }} />
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-extrabold text-slate-800">{f.name}</p>
                                  <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                                    <span className="text-xs font-semibold text-slate-500">{formatSize(f.size)}</span>
                                    {info && info.roles && info.roles.length > 0 ? (
                                      info.roles.map((r) => (
                                        <Chip
                                          key={r}
                                          size="small"
                                          label={ROLE_DISPLAY_NAMES[r] || r}
                                          sx={{
                                            height: 18,
                                            fontSize: "0.65rem",
                                            fontWeight: 800,
                                            backgroundColor: "#dbeafe",
                                            color: "#1e40af",
                                          }}
                                        />
                                      ))
                                    ) : inspecting ? (
                                      <span className="text-xs text-sky-600 font-semibold">Identifying structure…</span>
                                    ) : (
                                      <Chip
                                        size="small"
                                        label="Unmatched Structure"
                                        sx={{
                                          height: 18,
                                          fontSize: "0.65rem",
                                          fontWeight: 800,
                                          backgroundColor: "#fee2e2",
                                          color: "#991b1b",
                                        }}
                                      />
                                    )}
                                    {info?.period && (
                                      <Chip
                                        size="small"
                                        label={`Period: ${info.period}`}
                                        sx={{
                                          height: 18,
                                          fontSize: "0.65rem",
                                          fontWeight: 800,
                                          backgroundColor: "#dcfce7",
                                          color: "#166534",
                                        }}
                                      />
                                    )}
                                  </div>
                                </div>
                              </div>
                              <Tooltip title="Remove file">
                                <span>
                                  <Button
                                    onClick={() => removeFile(f.name)}
                                    disabled={generating}
                                    sx={{ minWidth: 36, color: "#64748b" }}
                                  >
                                    <DeleteIcon fontSize="small" />
                                  </Button>
                                </span>
                              </Tooltip>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {error && (
                      <Alert severity="error" sx={{ mt: 3, fontWeight: 600 }}>
                        {error}
                      </Alert>
                    )}

                    {/* Action button */}
                    <div className="mt-6 flex flex-col gap-2">
                      <Button
                        onClick={handleGenerate}
                        disabled={!checklist.allReady || generating}
                        variant="contained"
                        size="large"
                        startIcon={<BoardPackIcon />}
                        sx={{
                          height: 48,
                          px: 4,
                          textTransform: "none",
                          fontWeight: 900,
                          borderRadius: 1.5,
                          backgroundColor: "#0B3041",
                          "&:hover": { backgroundColor: "#1B6B93" },
                        }}
                      >
                        {generating
                          ? "Generating Board Pack…"
                          : checklist.allReady
                          ? `Generate Board Pack (${previewSlides.length} slides)`
                          : checklist.selectedCount === 0
                          ? "Select at least one section"
                          : "Upload required inputs to generate"}
                      </Button>
                      {generating && <LinearProgress sx={{ mt: 1, borderRadius: 1 }} />}
                    </div>

                    {/* Success Result */}
                    {result && (
                      <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5">
                        <div className="flex items-start gap-3">
                          <CheckCircleIcon sx={{ color: "#047857", mt: 0.25 }} />
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-black text-emerald-900">Presentation Ready</p>
                            <p className="mt-1 break-all text-xs font-semibold text-emerald-800">{result.filename}</p>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <Chip
                                size="small"
                                label={`Period: ${result.period}`}
                                sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }}
                              />
                              <Chip
                                size="small"
                                label={`${result.slide_count} slides`}
                                sx={{ fontWeight: 800, backgroundColor: "#d1fae5", color: "#065f46" }}
                              />
                            </div>
                            <div className="mt-3">
                              <p className="text-xs font-bold text-emerald-900">
                                Sections: {result.sections_generated?.join(", ")}
                              </p>
                              {result.sheets_used?.length > 0 && (
                                <p className="mt-1 text-xs text-emerald-800">
                                  Sheets read: {result.sheets_used.join(", ")}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>

                        {result.warnings?.length > 0 && (
                          <Alert severity="warning" icon={<WarningIcon />} sx={{ mt: 3 }}>
                            <p className="font-bold">Notices:</p>
                            <ul className="mt-1 list-disc pl-5 text-sm">
                              {result.warnings.map((w, idx) => (
                                <li key={idx}>{w}</li>
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
                </div>

                {/* Right Column: Dynamic Requirements Checklist & Slides Order */}
                <div className="flex flex-col gap-6">
                  {/* Requirements Checklist */}
                  <Paper
                    elevation={0}
                    sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 } }}
                  >
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-black text-[#082f49]">Required Inputs Checklist</h3>
                      <Chip
                        size="small"
                        label={checklist.allReady ? "All Inputs Ready" : "Inputs Required"}
                        sx={{
                          fontWeight: 800,
                          backgroundColor: checklist.allReady ? "#dcfce7" : "#fef3c7",
                          color: checklist.allReady ? "#166534" : "#92400e",
                        }}
                      />
                    </div>
                    <p className="mt-1 text-xs font-semibold text-slate-500">
                      Based on your selected sections, upload the corresponding source files below.
                    </p>

                    <div className="mt-4 space-y-3">
                      {checklist.items.length === 0 ? (
                        <p className="text-sm font-bold text-slate-400">No sections selected.</p>
                      ) : (
                        checklist.items.map((it, idx) => (
                          <div
                            key={idx}
                            className={`rounded-lg border p-3 transition ${
                              it.isReady
                                ? "border-emerald-200 bg-emerald-50/50"
                                : "border-amber-200 bg-amber-50/50"
                            }`}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex items-center gap-2">
                                {it.isReady ? (
                                  <CheckCircleIcon sx={{ fontSize: 18, color: "#166534" }} />
                                ) : (
                                  <CancelIcon sx={{ fontSize: 18, color: "#b45309" }} />
                                )}
                                <span className="text-xs font-black text-slate-800">{it.label}</span>
                              </div>
                              <span
                                className={`text-[10px] font-extrabold uppercase px-2 py-0.5 rounded ${
                                  it.isReady
                                    ? "bg-emerald-100 text-emerald-800"
                                    : "bg-amber-100 text-amber-800"
                                }`}
                              >
                                {it.isReady ? "Detected" : "Missing"}
                              </span>
                            </div>
                            <p className="mt-1 text-xs text-slate-500 pl-6">{it.description}</p>
                            {it.isReady && (
                              <p className="mt-1 text-xs font-bold text-emerald-800 pl-6 truncate">
                                ✓ Identified in: {it.filename}
                              </p>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </Paper>

                  {/* Deck Structure & Slide Order */}
                  <Paper
                    elevation={0}
                    sx={{ borderRadius: 3, border: "1px solid #dce5ee", p: { xs: 3, md: 4 } }}
                  >
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-black text-[#082f49]">Deck Order ({previewSlides.length} slides)</h3>
                      <Chip
                        size="small"
                        label={`Total: ${previewSlides.length}`}
                        sx={{ fontWeight: 800, backgroundColor: "#e2e8f0", color: "#334155" }}
                      />
                    </div>
                    <p className="mt-1 text-xs font-semibold text-slate-500">
                      Slides are output in the required board reporting sequence:
                    </p>

                    <div className="mt-3 max-h-[380px] overflow-y-auto pr-1 space-y-1.5">
                      {previewSlides.map((s, idx) => (
                        <div
                          key={idx}
                          className="flex items-center gap-2.5 rounded-lg bg-slate-50 px-3 py-2 border border-slate-100 text-left"
                        >
                          <span className="grid h-6 w-6 shrink-0 place-items-center rounded bg-[#082f49] text-[11px] font-black text-white">
                            {idx + 1}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-bold text-slate-800">{s.title}</p>
                            <p className="text-[10px] font-semibold text-slate-400">{s.section}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Paper>
                </div>
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

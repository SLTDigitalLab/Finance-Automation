import React, { useState, useCallback, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import {
  ThemeProvider,
  createTheme,
  CssBaseline,
  Box,
  Button,
  Paper,
  Grid,
  Card,
  CardContent,
  IconButton,
  LinearProgress,
  Typography,
  Chip,
  Tooltip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Alert,
  CircularProgress,
  Stack,
  Divider,
} from "@mui/material";
import {
  CloudUpload as UploadIcon,
  Assessment as ReportIcon,
  Download as DownloadIcon,
  Description as FileIcon,
  Delete as DeleteIcon,
  ExitToApp as LogoutIcon,
  Dashboard as DashboardIcon,
  CheckCircle as CheckCircleIcon,
  Schedule as ScheduleIcon,
  Refresh as RefreshIcon,
  Person as PersonIcon,
  VerifiedUser as VerifiedUserIcon,
  QueryStats as ForecastIcon,
  Security as SecurityIcon,
  AccountBalanceWallet as PLIcon,
  TableChart as TableIcon,
  InfoOutlined as InfoIcon,
} from "@mui/icons-material";
import {
  uploadFiles,
  uploadPLFile,
  getPLRevenue,
  generateReport,
  getDownloadUrl,
  generateUnmappedReport,
  getUnmappedDownloadUrl,
  getAdminConfig,
} from "../services/api";
import StatusPanel from "../components/StatusPanel";
import ReportSummaryActions from "../components/ReportSummaryActions";
import ValidationErrorModal from "../components/ValidationErrorModal";
import { validateTrialBalanceFile } from "../utils/fileValidation";

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

const FILE_CONFIGS = [
  { key: "tb_current", label: "Current Year Trial Balance", accept: ".xlsx,.xls,.txt,text/plain", color: "#1B6B93" },
  { key: "tb_previous", label: "Previous Year Trial Balance", accept: ".xlsx,.xls,.txt,text/plain", color: "#4A90B8" },
  { key: "budget", label: "Revenue Budget Workbook", accept: ".xlsx,.xls", color: "#7AB648" },
  { key: "mapping", label: "Revenue Mapping Workbook", accept: ".xlsx,.xls", color: "#E8A838" },
];

const NAV_ITEMS = [
  { label: "Dashboard", icon: DashboardIcon, path: "/dashboard", active: true },
  { label: "Revenue Forecasting", icon: ForecastIcon, path: "/forecasting" },
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies" },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const formatCurrencyMn = (val) => {
  if (val === null || val === undefined || isNaN(Number(val))) return "—";
  return Number(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

export default function UserDashboard() {
  const { user: currentUser, logout } = useAuth();
  const navigate = useNavigate();

  const [adminConfig, setAdminConfig] = useState({
    default_mapping_active: false,
    default_budget_active: false,
    default_mapping_filename: null,
    default_budget_filename: null,
  });

  const [files, setFiles] = useState({});
  const [activeStep, setActiveStep] = useState(() => {
    const saved = sessionStorage.getItem("slt_active_step");
    return saved !== null ? Number(saved) : 0;
  });
  const [uploadResult, setUploadResult] = useState(() => {
    try {
      const saved = sessionStorage.getItem("slt_upload_result");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [reportResult, setReportResult] = useState(() => {
    try {
      const saved = sessionStorage.getItem("slt_report_result");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [unmappedLoading, setUnmappedLoading] = useState(false);
  const [validationErrorMsg, setValidationErrorMsg] = useState(null);

  // PL Upload States
  const [plFile, setPlFile] = useState(null);
  const [plUploading, setPlUploading] = useState(false);
  const [plSuccessMsg, setPlSuccessMsg] = useState(null);
  const [plErrorMsg, setPlErrorMsg] = useState(null);
  const [plRevenueData, setPlRevenueData] = useState(null);

  useEffect(() => {
    if (activeStep > 0) {
      sessionStorage.setItem("slt_active_step", String(activeStep));
    } else {
      sessionStorage.removeItem("slt_active_step");
    }
  }, [activeStep]);

  useEffect(() => {
    if (uploadResult) {
      sessionStorage.setItem("slt_upload_result", JSON.stringify(uploadResult));
    } else {
      sessionStorage.removeItem("slt_upload_result");
    }
  }, [uploadResult]);

  useEffect(() => {
    if (reportResult) {
      sessionStorage.setItem("slt_report_result", JSON.stringify(reportResult));
    } else {
      sessionStorage.removeItem("slt_report_result");
    }
  }, [reportResult]);

  const fetchConfig = useCallback(async () => {
    try {
      const cfg = await getAdminConfig();
      setAdminConfig(cfg);
    } catch (err) {
      console.error("Failed to load admin config:", err);
    }
  }, []);

  const fetchPLRevenueData = useCallback(async () => {
    try {
      const resp = await getPLRevenue();
      if (resp && resp.status === "success" && resp.data) {
        setPlRevenueData(resp.data);
      }
    } catch (err) {
      console.log("No previous PL revenue data available:", err);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
    fetchPLRevenueData();
  }, [fetchConfig, fetchPLRevenueData]);

  const allFilesUploaded =
    (files.tb_current &&
      files.tb_previous &&
      (files.budget || adminConfig.default_budget_active) &&
      (files.mapping || adminConfig.default_mapping_active)) ||
    uploadResult != null;

  const currentYear = new Date().getFullYear();
  const getDefaultLabel = (key) => {
    const filename =
      key === "budget"
        ? adminConfig.default_budget_filename
        : adminConfig.default_mapping_filename;
    return filename || "system global template";
  };

  const handleFileChange = useCallback(async (key, event) => {
    const file = event.target.files[0];
    if (file) {
      const validation = await validateTrialBalanceFile(file, key);
      if (!validation.isValid) {
        setValidationErrorMsg(validation.errorMessage);
        if (event.target) {
          event.target.value = "";
        }
        return;
      }
      setFiles((prev) => ({ ...prev, [key]: file }));
    }
  }, []);

  const handleRemoveFile = useCallback((key) => {
    setFiles((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  // PL File Handlers
  const handlePLFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      const ext = file.name.split(".").pop().toLowerCase();
      if (ext !== "xlsx" && ext !== "xls") {
        setPlErrorMsg("Please select a valid Excel file (.xlsx or .xls).");
        setPlFile(null);
        if (event.target) event.target.value = "";
        return;
      }
      setPlFile(file);
      setPlErrorMsg(null);
      setPlSuccessMsg(null);
    }
  };

  const handlePLUpload = async () => {
    if (!plFile) {
      setPlErrorMsg("Please choose a PL Excel file before uploading.");
      return;
    }

    setPlUploading(true);
    setPlErrorMsg(null);
    setPlSuccessMsg(null);

    try {
      const result = await uploadPLFile(plFile);
      setPlSuccessMsg(result.message || "PL workbook uploaded successfully.");
      setPlRevenueData({
        period_month: result.period_month,
        period_year: result.period_year,
        month_revenue: result.month_revenue,
        ytd_revenue: result.ytd_revenue,
        source_filename: result.filename,
      });
      setPlFile(null);
    } catch (err) {
      setPlErrorMsg(err.message || "Failed to process PL workbook.");
    } finally {
      setPlUploading(false);
    }
  };

  const handleUploadAndGenerate = async () => {
    setLoading(true);
    setError(null);
    setActiveStep(1);

    try {
      const uploadResp = await uploadFiles(files);
      setUploadResult(uploadResp);
      setActiveStep(2);

      const reportResp = await generateReport(uploadResp.session_id);
      setReportResult(reportResp);
      setActiveStep(3);

      // Refresh PL data in case of newly bound period
      if (reportResp.report_month && reportResp.report_year) {
        try {
          const plResp = await getPLRevenue(reportResp.report_month, reportResp.report_year);
          if (plResp && plResp.status === "success" && plResp.data) {
            setPlRevenueData(plResp.data);
          } else {
            setPlRevenueData(null);
          }
        } catch (e) {
          setPlRevenueData(null);
        }
      }
    } catch (err) {
      const msg = err.message || "An error occurred";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!reportResult?.filename) return;
    try {
      const token = localStorage.getItem("token");
      const headers = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const response = await fetch(getDownloadUrl(reportResult.filename), { headers });
      if (!response.ok) throw new Error("Failed to download file");

      const blob = await response.blob();
      const localUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = localUrl;
      a.download = reportResult.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(localUrl);
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to download file");
    }
  };

  const handleReset = () => {
    setFiles({});
    setUploadResult(null);
    setReportResult(null);
    setActiveStep(0);
    setError(null);
    sessionStorage.removeItem("slt_active_step");
    sessionStorage.removeItem("slt_upload_result");
    sessionStorage.removeItem("slt_report_result");
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  // Active revenue summary values
  const revSummary = reportResult?.revenue_summary;
  const activeReportMonth = reportResult?.report_month || revSummary?.period_month || "";
  const activeReportYear = reportResult?.report_year || revSummary?.period_year || "";
  const isReportActive = Boolean(activeReportMonth && activeReportYear);

  const displayPeriodMonth = isReportActive ? activeReportMonth : (plRevenueData?.period_month || "");
  const displayPeriodYear = isReportActive ? activeReportYear : (plRevenueData?.period_year || "");

  const mappedYtd = revSummary?.mapped_ytd ?? (reportResult?.revenue_summary?.mapped_ytd ?? null);
  const mappedMonth = revSummary?.mapped_month ?? (reportResult?.revenue_summary?.mapped_month ?? null);
  const unmappedYtd = revSummary?.unmapped_ytd ?? (reportResult?.revenue_summary?.unmapped_ytd ?? null);
  const unmappedMonth = revSummary?.unmapped_month ?? (reportResult?.revenue_summary?.unmapped_month ?? null);

  const isPlMatchingReport = isReportActive && plRevenueData &&
    plRevenueData.period_month?.toLowerCase()?.slice(0, 3) === activeReportMonth.toLowerCase()?.slice(0, 3) &&
    Number(plRevenueData.period_year) === Number(activeReportYear);

  const plYtd = isReportActive
    ? (revSummary?.pl_ytd_revenue ?? (isPlMatchingReport ? plRevenueData.ytd_revenue : null))
    : (plRevenueData?.ytd_revenue ?? null);
  const plMonth = isReportActive
    ? (revSummary?.pl_month_revenue ?? (isPlMatchingReport ? plRevenueData.month_revenue : null))
    : (plRevenueData?.month_revenue ?? null);

  const hasSummaryData = mappedYtd !== null || plYtd !== null;

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
                {NAV_ITEMS.map(({ label, icon: Icon, path, active }) => (
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
                  <img src="/logo.png" alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">Finance Revenue Automation</h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">Professional revenue reporting dashboard</p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => navigate("/profile")}
                    className="flex items-center rounded-lg border border-slate-200 bg-white p-2 shadow-[0_8px_20px_rgba(15,23,42,0.06)] transition hover:border-sky-200 hover:bg-sky-50"
                    aria-label="Open user profile"
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

            <div className="flex-1 px-4 py-6 md:px-8 lg:px-10">
              <StatusPanel
                activeStep={activeStep}
                uploadResult={uploadResult}
                reportResult={reportResult}
                error={error}
              />

              {/* SECTION 1: MAIN DASHBOARD REVENUE SUMMARY TABLE */}
              {hasSummaryData && (
                <Paper
                  elevation={0}
                  sx={{
                    p: { xs: 2.5, md: 3.5 },
                    mb: 3,
                    borderRadius: 2,
                    border: "1px solid #dce5ee",
                    boxShadow: "0 18px 42px rgba(15, 23, 42, 0.08)",
                    background: "linear-gradient(180deg, #ffffff 0%, #fbfdff 100%)",
                  }}
                >
                  <Box sx={{ mb: 2.5, display: "flex", alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between", flexWrap: "wrap", gap: 1.5 }}>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                      <Box sx={{ width: 40, height: 40, borderRadius: 1.5, display: "grid", placeItems: "center", backgroundColor: "#082f4912" }}>
                        <TableIcon sx={{ color: "#082f49", fontSize: 24 }} />
                      </Box>
                      <Box>
                        <Typography variant="h6" sx={{ fontWeight: 900, color: "#082f49", lineHeight: 1.2 }}>
                          Revenue Reconciliation Summary
                        </Typography>
                        <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700 }}>
                          Comparison of Automated Mapping Engine against Official P&L Reference (Amounts in Rs. Mn)
                        </Typography>
                      </Box>
                    </Box>

                    {displayPeriodMonth && (
                      <Chip
                        label={`Period: ${displayPeriodMonth} ${displayPeriodYear}`}
                        color="primary"
                        sx={{ fontWeight: 900, borderRadius: 1.5, height: 32 }}
                      />
                    )}
                  </Box>

                  <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 1.5, borderColor: "#dce5ee", overflow: "hidden" }}>
                    <Table size="medium">
                      <TableHead sx={{ backgroundColor: "#082f49" }}>
                        <TableRow>
                          <TableCell sx={{ color: "#ffffff", fontWeight: 900, fontSize: "0.875rem", py: 1.5 }}>
                            Period
                          </TableCell>
                          <TableCell align="right" sx={{ color: "#ffffff", fontWeight: 900, fontSize: "0.875rem", py: 1.5 }}>
                            Mapped (Rs. Mn)
                          </TableCell>
                          <TableCell align="right" sx={{ color: "#ffffff", fontWeight: 900, fontSize: "0.875rem", py: 1.5 }}>
                            Unmapped (Rs. Mn)
                          </TableCell>
                          <TableCell align="right" sx={{ color: "#ffffff", fontWeight: 900, fontSize: "0.875rem", py: 1.5 }}>
                            Total Revenue (PL) (Rs. Mn)
                          </TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        <TableRow sx={{ "&:nth-of-type(odd)": { backgroundColor: "#f8fafc" }, "&:hover": { backgroundColor: "#f1f5f9" } }}>
                          <TableCell sx={{ fontWeight: 900, color: "#082f49", fontSize: "0.95rem" }}>
                            YTD
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 800, color: "#047857", fontSize: "0.95rem" }}>
                            {formatCurrencyMn(mappedYtd)}
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 800, color: "#b45309", fontSize: "0.95rem" }}>
                            {formatCurrencyMn(unmappedYtd)}
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 900, color: "#082f49", fontSize: "1rem", backgroundColor: "#f0f9ff" }}>
                            {formatCurrencyMn(plYtd)}
                          </TableCell>
                        </TableRow>
                        <TableRow sx={{ "&:nth-of-type(odd)": { backgroundColor: "#f8fafc" }, "&:hover": { backgroundColor: "#f1f5f9" } }}>
                          <TableCell sx={{ fontWeight: 900, color: "#082f49", fontSize: "0.95rem" }}>
                            Month
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 800, color: "#047857", fontSize: "0.95rem" }}>
                            {formatCurrencyMn(mappedMonth)}
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 800, color: "#b45309", fontSize: "0.95rem" }}>
                            {formatCurrencyMn(unmappedMonth)}
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 900, color: "#082f49", fontSize: "1rem", backgroundColor: "#f0f9ff" }}>
                            {formatCurrencyMn(plMonth)}
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </TableContainer>

                  <Box sx={{ mt: 1.5, display: "flex", alignItems: "center", gap: 1 }}>
                    <InfoIcon sx={{ fontSize: 16, color: "#64748b" }} />
                    <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
                      * Mapped & Unmapped values are derived from Trial Balance automation processing. Total Revenue is dynamically extracted from the uploaded P&L workbook (Row 18 Revenue).
                    </Typography>
                  </Box>
                </Paper>
              )}

              {/* SECTION 2: PL / TOTAL REVENUE UPLOAD */}
              <Paper
                elevation={0}
                sx={{
                  p: { xs: 2.5, md: 3 },
                  mb: 3,
                  borderRadius: 2,
                  border: "1px solid #dce5ee",
                  boxShadow: "0 14px 34px rgba(15, 23, 42, 0.06)",
                  background: "linear-gradient(180deg, #ffffff 0%, #fbfdff 100%)",
                }}
              >
                <Box sx={{ mb: 2, display: "flex", alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between", flexWrap: "wrap", gap: 1.5 }}>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                    <Box sx={{ width: 38, height: 38, borderRadius: 1.5, display: "grid", placeItems: "center", backgroundColor: "#0284c714" }}>
                      <PLIcon sx={{ color: "#0284c7", fontSize: 22 }} />
                    </Box>
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 900, color: "#082f49", lineHeight: 1.2 }}>
                        PL / Total Revenue Upload
                      </Typography>
                      <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700 }}>
                        Upload official P&L workbook (e.g., PL June 26.xlsx) to dynamically establish the benchmark Total Revenue
                      </Typography>
                    </Box>
                  </Box>

                  {isReportActive ? (
                    plYtd !== null && plYtd !== undefined ? (
                      <Chip
                        icon={<CheckCircleIcon />}
                        label={`Active Benchmark: ${activeReportMonth} ${activeReportYear}`}
                        color="success"
                        variant="outlined"
                        size="small"
                        sx={{ fontWeight: 800, borderRadius: 1.5 }}
                      />
                    ) : (
                      <Chip
                        label={`No benchmark uploaded for ${activeReportMonth} ${activeReportYear}`}
                        color="warning"
                        variant="outlined"
                        size="small"
                        sx={{ fontWeight: 800, borderRadius: 1.5 }}
                      />
                    )
                  ) : plRevenueData ? (
                    <Chip
                      icon={<CheckCircleIcon />}
                      label={`Active Benchmark: ${plRevenueData.period_month} ${plRevenueData.period_year}`}
                      color="success"
                      variant="outlined"
                      size="small"
                      sx={{ fontWeight: 800, borderRadius: 1.5 }}
                    />
                  ) : null}
                </Box>

                <Grid container spacing={2} alignItems="center">
                  <Grid item xs={12} sm={8} md={9}>
                    <Box
                      sx={{
                        p: 2,
                        borderRadius: 1.5,
                        border: "1px dashed #94a3b8",
                        backgroundColor: "#f8fafc",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        flexWrap: "wrap",
                        gap: 2,
                      }}
                    >
                      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                        <FileIcon sx={{ color: "#0284c7", fontSize: 24 }} />
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 800, color: "#1e293b" }}>
                            {plFile ? plFile.name : "Select PL Excel File (.xlsx, .xls)"}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#64748b" }}>
                            {plFile
                              ? `${(plFile.size / 1024).toFixed(1)} KB`
                              : isReportActive && plYtd !== null
                              ? `Current: ${plRevenueData?.source_filename || "Uploaded PL Workbook"} (Month: Rs. ${formatCurrencyMn(plMonth)} Mn | YTD: Rs. ${formatCurrencyMn(plYtd)} Mn)`
                              : isReportActive && plYtd === null
                              ? `No benchmark uploaded for ${activeReportMonth} ${activeReportYear}`
                              : plRevenueData
                              ? `Current: ${plRevenueData.source_filename || "Uploaded PL Workbook"} (Month: Rs. ${formatCurrencyMn(plRevenueData.month_revenue)} Mn | YTD: Rs. ${formatCurrencyMn(plRevenueData.ytd_revenue)} Mn)`
                              : "No PL workbook uploaded yet"}
                          </Typography>
                        </Box>
                      </Box>

                      <Button
                        component="label"
                        variant="outlined"
                        size="small"
                        sx={{
                          textTransform: "none",
                          fontWeight: 800,
                          borderRadius: 1.5,
                          borderColor: "#0284c7",
                          color: "#0284c7",
                          "&:hover": { backgroundColor: "#0284c710", borderColor: "#0369a1" },
                        }}
                      >
                        Choose PL Excel File
                        <input
                          type="file"
                          accept=".xlsx,.xls"
                          hidden
                          onChange={handlePLFileSelect}
                        />
                      </Button>
                    </Box>
                  </Grid>

                  <Grid item xs={12} sm={4} md={3}>
                    <Button
                      variant="contained"
                      fullWidth
                      disabled={!plFile || plUploading}
                      onClick={handlePLUpload}
                      startIcon={plUploading ? <CircularProgress size={18} color="inherit" /> : <UploadIcon />}
                      sx={{
                        height: 56,
                        backgroundColor: "#0284c7",
                        textTransform: "none",
                        fontWeight: 900,
                        borderRadius: 1.5,
                        boxShadow: "0 8px 18px rgba(2, 132, 199, 0.25)",
                        "&:hover": { backgroundColor: "#0369a1" },
                        "&.Mui-disabled": { backgroundColor: "#cbd5e1", color: "#64748b" },
                      }}
                    >
                      {plUploading ? "Processing..." : "Upload PL File"}
                    </Button>
                  </Grid>
                </Grid>

                {plSuccessMsg && (
                  <Alert severity="success" sx={{ mt: 2, borderRadius: 1.5 }} onClose={() => setPlSuccessMsg(null)}>
                    {plSuccessMsg}
                  </Alert>
                )}

                {plErrorMsg && (
                  <Alert severity="error" sx={{ mt: 2, borderRadius: 1.5 }} onClose={() => setPlErrorMsg(null)}>
                    {plErrorMsg}
                  </Alert>
                )}
              </Paper>

              {/* SECTION 3: SOURCE WORKBOOKS UPLOAD & GENERATION */}
              <Paper elevation={0} sx={{ p: { xs: 2.5, md: 3.5 }, borderRadius: 2, border: "1px solid #dce5ee", boxShadow: "0 18px 42px rgba(15, 23, 42, 0.08)", background: "linear-gradient(180deg, #ffffff 0%, #fbfdff 100%)" }}>
                <Box sx={{ mb: 3, display: "flex", alignItems: { xs: "flex-start", md: "center" }, justifyContent: "space-between", gap: 2, flexDirection: { xs: "column", md: "row" } }}>
                  <Box>
                    <Typography variant="h5" sx={{ fontWeight: 900, color: "#082f49" }}>
                      Source Workbooks
                    </Typography>
                  </Box>
                  <Chip
                    icon={allFilesUploaded ? <CheckCircleIcon /> : <ScheduleIcon />}
                    label={allFilesUploaded ? "Generation enabled" : "Waiting for files"}
                    sx={{
                      height: 36,
                      borderRadius: 1.5,
                      fontWeight: 900,
                      color: allFilesUploaded ? "#166534" : "#475569",
                      backgroundColor: allFilesUploaded ? "#dcfce7" : "#f1f5f9",
                    }}
                  />
                </Box>

                <Grid container spacing={3}>
                  {FILE_CONFIGS.map((config) => {
                    const isDefaultActive =
                      (config.key === "budget" && adminConfig.default_budget_active) ||
                      (config.key === "mapping" && adminConfig.default_mapping_active);
                    const isUploaded = !!files[config.key];

                    return (
                      <Grid item xs={12} sm={6} key={config.key}>
                        <Card
                          variant="outlined"
                          sx={{
                            height: "100%",
                            borderColor: isUploaded ? config.color : isDefaultActive ? "#86C35C" : "#DCE5EE",
                            borderWidth: 1,
                            borderRadius: 2,
                            backgroundColor: !isUploaded && isDefaultActive ? "#F8FCF6" : "#FFFFFF",
                            transition: "all 0.2s",
                            boxShadow: "0 10px 24px rgba(15, 23, 42, 0.045)",
                            "&:hover": { borderColor: config.color, transform: "translateY(-2px)", boxShadow: "0 16px 34px rgba(15, 23, 42, 0.09)" },
                          }}
                        >
                          <CardContent sx={{ p: 3 }}>
                            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                              <Box sx={{ display: "flex", alignItems: "center" }}>
                                <Box sx={{ width: 38, height: 38, borderRadius: 1.5, display: "grid", placeItems: "center", backgroundColor: `${config.color}14`, mr: 1.5 }}>
                                  <FileIcon sx={{ color: config.color, fontSize: 21 }} />
                                </Box>
                                <Typography variant="subtitle1" sx={{ fontWeight: 900, color: "#1f2937" }}>
                                  {config.label}
                                </Typography>
                              </Box>
                              {!isUploaded && isDefaultActive && (
                                <Chip
                                  label="Admin Default Active"
                                  color="success"
                                  size="small"
                                  variant="outlined"
                                  sx={{ height: 22, fontSize: "0.68rem", fontWeight: 800 }}
                                />
                              )}
                            </Box>

                            {isUploaded ? (
                              <Box>
                                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5, fontWeight: 700, wordBreak: "break-word" }}>
                                  {files[config.key].name}
                                </Typography>
                                <Box sx={{ display: "flex", gap: 1 }}>
                                  <Button
                                    size="small"
                                    component="label"
                                    variant="outlined"
                                    sx={{ textTransform: "none", fontWeight: 800, borderRadius: 1.5 }}
                                  >
                                    Replace Custom
                                    <input
                                      type="file"
                                      accept={config.accept}
                                      hidden
                                      onChange={(e) => handleFileChange(config.key, e)}
                                    />
                                  </Button>
                                  <IconButton
                                    size="small"
                                    color="error"
                                    onClick={() => handleRemoveFile(config.key)}
                                  >
                                    <DeleteIcon fontSize="small" />
                                  </IconButton>
                                </Box>
                              </Box>
                            ) : isDefaultActive ? (
                              <Box>
                                <Typography variant="body2" color="text.secondary" sx={{ mb: 1, fontStyle: "italic" }}>
                                  Using {getDefaultLabel(config.key)} configured by administrator
                                </Typography>
                                <Button
                                  size="small"
                                  component="label"
                                  variant="outlined"
                                  sx={{ textTransform: "none", color: config.color, borderColor: config.color, fontWeight: 800, borderRadius: 1.5 }}
                                >
                                  Upload Custom Override
                                  <input
                                    type="file"
                                    accept={config.accept}
                                    hidden
                                    onChange={(e) => handleFileChange(config.key, e)}
                                  />
                                </Button>
                              </Box>
                            ) : (
                              <Button
                                component="label"
                                variant="outlined"
                                fullWidth
                                startIcon={<UploadIcon />}
                                sx={{
                                  mt: 1,
                                  py: 2,
                                  borderStyle: "dashed",
                                  textTransform: "none",
                                  fontWeight: 900,
                                  borderRadius: 1.5,
                                  color: config.color,
                                  borderColor: config.color,
                                  "&:hover": {
                                    borderStyle: "solid",
                                    backgroundColor: `${config.color}10`,
                                  },
                                }}
                              >
                                Click to upload
                                <input
                                  type="file"
                                  accept={config.accept}
                                  hidden
                                  onChange={(e) => handleFileChange(config.key, e)}
                                />
                              </Button>
                            )}
                          </CardContent>
                        </Card>
                      </Grid>
                    );
                  })}
                </Grid>

                {loading && <LinearProgress sx={{ mt: 3, height: 7, borderRadius: 999 }} />}

                <Box sx={{ mt: 3, display: "flex", gap: 1.5, flexWrap: "wrap", alignItems: "center" }}>
                  <Button
                    variant="contained"
                    size="large"
                    startIcon={<ReportIcon />}
                    disabled={!allFilesUploaded || loading}
                    onClick={handleUploadAndGenerate}
                    sx={{
                      backgroundColor: "#0B3041",
                      textTransform: "none",
                      fontWeight: 900,
                      borderRadius: 1.5,
                      px: 4,
                      "&:hover": { backgroundColor: "#143D52" },
                    }}
                  >
                    Generate Report
                  </Button>

                  {reportResult && (
                    <Button
                      variant="contained"
                      size="large"
                      startIcon={<DownloadIcon />}
                      onClick={handleDownload}
                      sx={{
                        backgroundColor: "#7AB648",
                        textTransform: "none",
                        fontWeight: 900,
                        borderRadius: 1.5,
                        px: 4,
                        "&:hover": { backgroundColor: "#6AA038" },
                      }}
                    >
                      Download PowerPoint
                    </Button>
                  )}

                  <ReportSummaryActions
                    reportResult={reportResult}
                    sessionId={uploadResult?.session_id}
                  />

                  {activeStep > 0 && (
                    <Button
                      variant="outlined"
                      size="large"
                      onClick={handleReset}
                      disabled={loading}
                      startIcon={<RefreshIcon />}
                      sx={{ textTransform: "none", fontWeight: 900, borderRadius: 1.5 }}
                    >
                      Reset
                    </Button>
                  )}
                </Box>
              </Paper>
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
      <ValidationErrorModal
        open={!!validationErrorMsg}
        onClose={() => setValidationErrorMsg(null)}
        message={validationErrorMsg}
      />
    </ThemeProvider>
  );
}

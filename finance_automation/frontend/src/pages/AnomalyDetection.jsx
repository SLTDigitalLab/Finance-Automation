import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import {
  getAnomalySummary,
  getAnomalyMatrix,
  getAnomalyResults,
  getAnomalyFilterOptions,
  triggerAnomalyAnalysis,
} from "../services/api";
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
  Typography,
  Chip,
  Tooltip,
  CircularProgress,
  Alert,
  Select,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  InputAdornment,
  IconButton,
  Collapse,
  Tabs,
  Tab,
} from "@mui/material";
import {
  Dashboard as DashboardIcon,
  QueryStats as ForecastIcon,
  Person as PersonIcon,
  ExitToApp as LogoutIcon,
  Refresh as RefreshIcon,
  CheckCircle as CheckCircleIcon,
  WarningAmber as WarningIcon,
  Security as SecurityIcon,
  Search as SearchIcon,
  FilterList as FilterIcon,
  Clear as ClearIcon,
  KeyboardArrowDown as ArrowDownIcon,
  KeyboardArrowUp as ArrowUpIcon,
  InfoOutlined as InfoIcon,
  CalendarMonth as CalendarIcon,
  Category as CategoryIcon,
  Shield as ShieldIcon,
  Flag as FlagIcon,
  TableChart as TableIcon,
  Tune as TuneIcon,
  Assessment as AssessmentIcon,
  ArrowForward as ArrowForwardIcon,
} from "@mui/icons-material";

// ── SLT-MOBITEL Corporate Theme ──────────────────────────────────────────────
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
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies", active: true },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const cardStyle = {
  p: 2.5,
  borderRadius: 2,
  border: "1px solid #dce5ee",
  bgcolor: "#ffffff",
  boxShadow: "0 10px 24px rgba(15, 23, 42, 0.045)",
};

const RISK_STYLES = {
  high: {
    badgeColor: "#DC2626",
    badgeBg: "#FEE2E2",
    borderColor: "#FECACA",
    dotBg: "#DC2626",
    label: "HIGH",
    colorName: "red",
  },
  medium: {
    badgeColor: "#D97706",
    badgeBg: "#FEF3C7",
    borderColor: "#FDE68A",
    dotBg: "#F59E0B",
    label: "MEDIUM",
    colorName: "yellow",
  },
  low: {
    badgeColor: "#16A34A",
    badgeBg: "#DCFCE7",
    borderColor: "#BBF7D0",
    dotBg: "#22C55E",
    label: "LOW",
    colorName: "green",
  },
  normal: {
    badgeColor: "#16A34A",
    badgeBg: "#DCFCE7",
    borderColor: "#BBF7D0",
    dotBg: "#22C55E",
    label: "NORMAL",
    colorName: "green",
  },
  no_data: {
    badgeColor: "#64748B",
    badgeBg: "#F1F5F9",
    borderColor: "#E2E8F0",
    dotBg: "#CBD5E1",
    label: "NO DATA",
    colorName: "gray",
  },
};

function formatAmount(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function RiskBadge({ level }) {
  const norm = (level || "low").toLowerCase();
  const style = RISK_STYLES[norm] || RISK_STYLES.low;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "3px 10px",
        borderRadius: "9999px",
        fontSize: "11px",
        fontWeight: 800,
        letterSpacing: "0.06em",
        color: style.badgeColor,
        backgroundColor: style.badgeBg,
        border: `1px solid ${style.borderColor}`,
        minWidth: "64px",
      }}
    >
      {style.label}
    </span>
  );
}

function ScoreBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  let color = "#22C55E";
  if (pct >= 70) {
    color = "#DC2626";
  } else if (pct >= 40) {
    color = "#F59E0B";
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 100 }}>
      <div
        style={{
          flex: 1,
          height: 6,
          background: "#E2E8F0",
          borderRadius: 9999,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${Math.min(pct, 100)}%`,
            height: "100%",
            background: color,
            borderRadius: 9999,
            transition: "width 0.4s ease",
          }}
        />
      </div>
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          fontFamily: "monospace",
          color: "#475569",
          minWidth: 32,
          textAlign: "right",
        }}
      >
        {pct}%
      </span>
    </div>
  );
}

export default function AnomalyDetection() {
  const { user: currentUser, logout } = useAuth();
  const navigate = useNavigate();
  const isAdmin = currentUser?.role === "Admin";

  // Tab State: 0=Overview, 1=Category x Month, 2=Anomaly Details, 3=Filters / Analysis
  const [currentTab, setCurrentTab] = useState(0);

  const OPERATING_YEAR = 2026;

  const [summary, setSummary] = useState(null);
  const [matrixData, setMatrixData] = useState(null);
  const [results, setResults] = useState([]);
  const [totalResults, setTotalResults] = useState(0);
  const [filterOptions, setFilterOptions] = useState({ years: [2026], months: [], categories: [] });

  const [loading, setLoading] = useState(true);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [tableLoading, setTableLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState(null);
  const [expandedRowId, setExpandedRowId] = useState(null);

  // Filters State (Strictly Operating Year 2026)
  const [selectedYear, setSelectedYear] = useState(2026);
  const [selectedMonth, setSelectedMonth] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedRisk, setSelectedRisk] = useState("");
  const [searchTerm, setSearchTerm] = useState("");

  // Active Matrix Cell Selection
  const [selectedMatrixCell, setSelectedMatrixCell] = useState(null);

  // Pagination
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 25;

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  // 1. Initial Load: Filter Options, Matrix Data & Summary strictly for 2026
  const loadInitialData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [filtersRes, summaryRes, matrixRes] = await Promise.all([
        getAnomalyFilterOptions().catch(() => ({ years: [OPERATING_YEAR], months: [], categories: [] })),
        getAnomalySummary({ year: OPERATING_YEAR }).catch(() => null),
        getAnomalyMatrix({ year: OPERATING_YEAR }).catch(() => null),
      ]);

      setFilterOptions(filtersRes || { years: [OPERATING_YEAR], months: [], categories: [] });
      setSummary(summaryRes);
      setSelectedYear(OPERATING_YEAR);
      setMatrixData(matrixRes);
    } catch (err) {
      console.error("Failed to load initial anomaly data:", err);
      setError("Unable to load anomaly dashboard data. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInitialData();
  }, [loadInitialData]);

  // 2. Fetch Matrix for Operating Year 2026
  const fetchMatrix = useCallback(async () => {
    setMatrixLoading(true);
    try {
      const data = await getAnomalyMatrix({ year: OPERATING_YEAR });
      setMatrixData(data);
    } catch (err) {
      console.error("Failed to load matrix:", err);
    } finally {
      setMatrixLoading(false);
    }
  }, []);

  // 3. Fetch Paginated Records strictly for 2026
  const fetchRecords = useCallback(async () => {
    setTableLoading(true);
    try {
      const data = await getAnomalyResults({
        year: OPERATING_YEAR,
        period_month: selectedMonth || undefined,
        revenue_category: selectedCategory || undefined,
        risk_level: selectedRisk || undefined,
        search: searchTerm.trim() || undefined,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        sort_by: "anomaly_score",
        sort_order: "desc",
      });
      setResults(data?.results || []);
      setTotalResults(data?.total || 0);
    } catch (err) {
      console.error("Failed to fetch anomaly records:", err);
      setResults([]);
      setTotalResults(0);
    } finally {
      setTableLoading(false);
    }
  }, [selectedMonth, selectedCategory, selectedRisk, searchTerm, page]);

  useEffect(() => {
    if (!loading) {
      fetchRecords();
    }
  }, [loading, fetchRecords]);

  // Handle Cell Click in Category x Month Matrix
  const handleCellClick = (category, month, cell) => {
    if (cell.status === "NO_DATA") return;

    setSelectedMatrixCell({ category, month, cell });
    setSelectedCategory(category);
    setSelectedMonth(month);
    setPage(0);

    // Switch smoothly to Anomaly Details tab
    setCurrentTab(2);
  };

  // Clear all filters
  const handleClearFilters = () => {
    setSelectedMonth("");
    setSelectedCategory("");
    setSelectedRisk("");
    setSearchTerm("");
    setSelectedMatrixCell(null);
    setPage(0);
  };

  // Handle Manual Trigger
  const handleRunAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      await triggerAnomalyAnalysis();
      setTimeout(async () => {
        await loadInitialData();
        setPage(0);
        await fetchRecords();
        setAnalyzing(false);
      }, 3000);
    } catch (err) {
      setError(err.message || "Failed to trigger anomaly detection analysis");
      setAnalyzing(false);
    }
  };

  const totalPages = Math.ceil(totalResults / PAGE_SIZE) || 1;

  const formattedLastAnalyzed = useMemo(() => {
    if (!summary?.last_analyzed_at) return "N/A";
    try {
      const date = new Date(summary.last_analyzed_at);
      return date.toLocaleString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return summary.last_analyzed_at;
    }
  }, [summary]);

  const matrixMonths = matrixData?.months || [];
  const matrixCategories = matrixData?.categories || [];
  const matrixGrid = matrixData?.matrix || {};

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
        <div className="flex min-h-screen">
          {/* ── Left Navigation Sidebar ──────────────────────────────────────── */}
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

          {/* ── Main Content Area ────────────────────────────────────────────── */}
          <main className="flex min-w-0 flex-1 flex-col">
            {/* Top Header */}
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="relative flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src="/logo.png" alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">
                      Finance Revenue Automation
                    </h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      AI Anomaly &amp; Fraud Risk Intelligence Dashboard
                    </p>
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

            {/* Page Body */}
            <div className="flex-1 px-4 py-5 md:px-8 lg:px-10">
              {/* Header Title & Top Controls Bar */}
              <Stack
                direction={{ xs: "column", sm: "row" }}
                justifyContent="space-between"
                alignItems={{ xs: "flex-start", sm: "center" }}
                spacing={2}
                sx={{ mb: 2.5 }}
              >
                <Box>
                  <Typography
                    variant="h5"
                    sx={{
                      fontWeight: 900,
                      color: "#082f49",
                      display: "flex",
                      alignItems: "center",
                      gap: 1.2,
                    }}
                  >
                    <SecurityIcon sx={{ fontSize: 28, color: "#1B6B93" }} />
                    Anomaly &amp; Fraud Detection
                  </Typography>
                  <Typography variant="body2" sx={{ color: "#64748B", fontWeight: 500, mt: 0.3 }}>
                    AI-assisted pattern analysis across Trial Balance transactions. Identify unusual movements for Finance Department review.
                  </Typography>
                </Box>

                <Stack direction="row" spacing={1.5} alignItems="center">
                  <Chip
                    icon={<CheckCircleIcon sx={{ fontSize: "14px !important", color: "#16a34a !important" }} />}
                    label="AI MODEL v1.0.0 ACTIVE"
                    size="small"
                    sx={{
                      bgcolor: "#dcfce7",
                      color: "#166534",
                      fontWeight: 850,
                      fontSize: "0.72rem",
                    }}
                  />
                  {isAdmin && (
                    <Button
                      id="btn-run-anomaly-analysis"
                      onClick={handleRunAnalysis}
                      disabled={analyzing}
                      startIcon={analyzing ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                      variant="outlined"
                      size="small"
                      sx={{
                        textTransform: "none",
                        fontWeight: 800,
                        color: "#082f49",
                        borderColor: "#cbd5e1",
                        bgcolor: "#ffffff",
                        "&:hover": { bgcolor: "#f8fafc", borderColor: "#94a3b8" },
                      }}
                    >
                      {analyzing ? "Running..." : "Run Detection"}
                    </Button>
                  )}
                </Stack>
              </Stack>

              {error && (
                <Alert severity="error" sx={{ mb: 2.5, borderRadius: 2 }} onClose={() => setError(null)}>
                  {error}
                </Alert>
              )}

              {/* ── Tab Navigation Bar ───────────────────────────────────────── */}
              <Paper
                elevation={0}
                sx={{
                  mb: 3,
                  borderRadius: 2,
                  border: "1px solid #dce5ee",
                  bgcolor: "#ffffff",
                  boxShadow: "0 10px 24px rgba(15, 23, 42, 0.045)",
                }}
              >
                <Tabs
                  value={currentTab}
                  onChange={(e, val) => setCurrentTab(val)}
                  variant="scrollable"
                  scrollButtons="auto"
                  sx={{
                    px: 2,
                    "& .MuiTab-root": {
                      fontWeight: 850,
                      fontSize: "0.88rem",
                      textTransform: "none",
                      minHeight: 52,
                      color: "#64748b",
                      "&.Mui-selected": { color: "#082f49" },
                    },
                    "& .MuiTabs-indicator": { backgroundColor: "#082f49", height: 3 },
                  }}
                >
                  <Tab icon={<AssessmentIcon fontSize="small" />} iconPosition="start" label="Overview" />
                  <Tab icon={<CategoryIcon fontSize="small" />} iconPosition="start" label="Category × Month" />
                  <Tab icon={<TableIcon fontSize="small" />} iconPosition="start" label="Anomaly Details" />
                  <Tab icon={<TuneIcon fontSize="small" />} iconPosition="start" label="Filters / Analysis" />
                </Tabs>
              </Paper>

              {/* ══════════════════════════════════════════════════════════════ */}
              {/* TAB 0: OVERVIEW                                                */}
              {/* ══════════════════════════════════════════════════════════════ */}
              {currentTab === 0 && (
                <Box>
                  {/* AI Transparency Notice */}
                  <Alert
                    severity="info"
                    icon={<InfoIcon fontSize="inherit" sx={{ color: "#1B6B93" }} />}
                    sx={{
                      mb: 2.5,
                      backgroundColor: "#F0F9FF",
                      border: "1px solid #BAE6FD",
                      borderRadius: 2,
                      color: "#0369A1",
                      fontWeight: 500,
                      fontSize: 13,
                      py: 0.8,
                    }}
                  >
                    <strong>AI Transparency Notice:</strong> AI anomaly detection identifies unusual financial patterns for human review. An anomaly does not confirm fraud.
                  </Alert>

                  {/* 4 Compact KPI Cards */}
                  <Grid container spacing={2.5} sx={{ mb: 3 }}>
                    <Grid item xs={12} sm={6} lg={3}>
                      <Card sx={cardStyle}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                            <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", textTransform: "uppercase" }}>
                              Total Analyzed
                            </Typography>
                            <CalendarIcon sx={{ fontSize: 18, color: "#1B6B93" }} />
                          </Box>
                          <Typography variant="h5" sx={{ fontWeight: 900, color: "#082f49" }}>
                            {loading ? <CircularProgress size={20} /> : formatAmount(summary?.total_analyzed || 0)}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#0284c7", fontWeight: 750, mt: 0.3, display: "block" }}>
                            Processed TB Records
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    <Grid item xs={12} sm={6} lg={3}>
                      <Card sx={{ ...cardStyle, bgcolor: "#FFF5F5", borderColor: "#FECACA" }}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                            <Typography variant="caption" sx={{ fontWeight: 800, color: "#DC2626", textTransform: "uppercase" }}>
                              High Risk Anomalies
                            </Typography>
                            <FlagIcon sx={{ fontSize: 18, color: "#DC2626" }} />
                          </Box>
                          <Typography variant="h5" sx={{ fontWeight: 900, color: "#DC2626" }}>
                            {loading ? <CircularProgress size={20} color="error" /> : formatAmount(summary?.high_count || 0)}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#EF4444", fontWeight: 750, mt: 0.3, display: "block" }}>
                            Score &ge; 70% &bull; Priority review
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    <Grid item xs={12} sm={6} lg={3}>
                      <Card sx={{ ...cardStyle, bgcolor: "#FFFDF5", borderColor: "#FDE68A" }}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                            <Typography variant="caption" sx={{ fontWeight: 800, color: "#D97706", textTransform: "uppercase" }}>
                              Medium Risk Anomalies
                            </Typography>
                            <WarningIcon sx={{ fontSize: 18, color: "#D97706" }} />
                          </Box>
                          <Typography variant="h5" sx={{ fontWeight: 900, color: "#D97706" }}>
                            {loading ? <CircularProgress size={20} color="warning" /> : formatAmount(summary?.medium_count || 0)}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#F59E0B", fontWeight: 750, mt: 0.3, display: "block" }}>
                            Score 40% &ndash; 69% &bull; Moderate deviation
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    <Grid item xs={12} sm={6} lg={3}>
                      <Card sx={{ ...cardStyle, bgcolor: "#F6FEF9", borderColor: "#BBF7D0" }}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                            <Typography variant="caption" sx={{ fontWeight: 800, color: "#16A34A", textTransform: "uppercase" }}>
                              Latest Month Status
                            </Typography>
                            <CheckCircleIcon sx={{ fontSize: 18, color: "#16A34A" }} />
                          </Box>
                          <Typography variant="h6" sx={{ fontWeight: 900, color: "#082f49", lineHeight: 1.2 }}>
                            {summary?.latest_month || "All Data Ready"}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#16A34A", fontWeight: 750, mt: 0.3, display: "block" }}>
                            Analyzed: {formattedLastAnalyzed}
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  </Grid>

                  {/* Summary Breakdown Cards */}
                  <Grid container spacing={2.5}>
                    <Grid item xs={12} md={6}>
                      <Paper sx={cardStyle}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 850, color: "#082f49", mb: 1.5 }}>
                          Risk Distribution Overview
                        </Typography>
                        <Typography variant="body2" sx={{ color: "#64748B", mb: 2 }}>
                          Breakdown of all {formatAmount(summary?.total_analyzed || 0)} analyzed Trial Balance transactions by AI composite risk tier:
                        </Typography>

                        <Stack spacing={2}>
                          <div>
                            <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#DC2626" }}>
                                High Risk Anomalies
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#082f49" }}>
                                {formatAmount(summary?.high_count || 0)} ({summary?.total_analyzed ? ((summary.high_count / summary.total_analyzed) * 100).toFixed(2) : 0}%)
                              </Typography>
                            </Box>
                            <div className="h-2.5 w-full rounded-full bg-red-100 overflow-hidden">
                              <div
                                className="h-full bg-red-600 rounded-full"
                                style={{
                                  width: `${summary?.total_analyzed ? (summary.high_count / summary.total_analyzed) * 100 : 0}%`,
                                  minWidth: summary?.high_count ? "4px" : "0px",
                                }}
                              />
                            </div>
                          </div>

                          <div>
                            <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#D97706" }}>
                                Medium Risk Anomalies
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#082f49" }}>
                                {formatAmount(summary?.medium_count || 0)} ({summary?.total_analyzed ? ((summary.medium_count / summary.total_analyzed) * 100).toFixed(2) : 0}%)
                              </Typography>
                            </Box>
                            <div className="h-2.5 w-full rounded-full bg-amber-100 overflow-hidden">
                              <div
                                className="h-full bg-amber-500 rounded-full"
                                style={{
                                  width: `${summary?.total_analyzed ? (summary.medium_count / summary.total_analyzed) * 100 : 0}%`,
                                  minWidth: summary?.medium_count ? "4px" : "0px",
                                }}
                              />
                            </div>
                          </div>

                          <div>
                            <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#16A34A" }}>
                                Low Risk / Standard Activity
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#082f49" }}>
                                {formatAmount(summary?.low_count || 0)} ({summary?.total_analyzed ? ((summary.low_count / summary.total_analyzed) * 100).toFixed(2) : 0}%)
                              </Typography>
                            </Box>
                            <div className="h-2.5 w-full rounded-full bg-emerald-100 overflow-hidden">
                              <div
                                className="h-full bg-emerald-600 rounded-full"
                                style={{
                                  width: `${summary?.total_analyzed ? (summary.low_count / summary.total_analyzed) * 100 : 0}%`,
                                }}
                              />
                            </div>
                          </div>
                        </Stack>
                      </Paper>
                    </Grid>

                    <Grid item xs={12} md={6}>
                      <Paper sx={cardStyle}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 850, color: "#082f49", mb: 1.5 }}>
                          Navigation &amp; Quick Actions
                        </Typography>
                        <Typography variant="body2" sx={{ color: "#64748B", mb: 2 }}>
                          Quickly navigate across the anomaly intelligence tools:
                        </Typography>

                        <Stack spacing={1.5}>
                          <Button
                            variant="outlined"
                            fullWidth
                            onClick={() => setCurrentTab(1)}
                            endIcon={<ArrowForwardIcon />}
                            sx={{
                              justifyContent: "space-between",
                              p: 1.5,
                              textTransform: "none",
                              fontWeight: 800,
                              borderRadius: 1.5,
                              borderColor: "#CBD5E1",
                              color: "#082f49",
                              bgcolor: "#F8FAFC",
                              "&:hover": { bgcolor: "#F1F5F9", borderColor: "#94A3B8" },
                            }}
                          >
                            <span>Inspect Category &times; Month Matrix</span>
                            <span className="text-xs text-slate-500 font-semibold">Status indicators across all months &rarr;</span>
                          </Button>

                          <Button
                            variant="outlined"
                            fullWidth
                            onClick={() => {
                              setSelectedRisk("HIGH");
                              setCurrentTab(2);
                            }}
                            endIcon={<ArrowForwardIcon />}
                            sx={{
                              justifyContent: "space-between",
                              p: 1.5,
                              textTransform: "none",
                              fontWeight: 800,
                              borderRadius: 1.5,
                              borderColor: "#FECACA",
                              color: "#DC2626",
                              bgcolor: "#FFF5F5",
                              "&:hover": { bgcolor: "#FEE2E2", borderColor: "#FCA5A5" },
                            }}
                          >
                            <span>Review High Risk Transactions</span>
                            <span className="text-xs text-red-500 font-semibold">{formatAmount(summary?.high_count || 0)} flagged records &rarr;</span>
                          </Button>

                          <Button
                            variant="outlined"
                            fullWidth
                            onClick={() => setCurrentTab(3)}
                            endIcon={<ArrowForwardIcon />}
                            sx={{
                              justifyContent: "space-between",
                              p: 1.5,
                              textTransform: "none",
                              fontWeight: 800,
                              borderRadius: 1.5,
                              borderColor: "#CBD5E1",
                              color: "#082f49",
                              bgcolor: "#F8FAFC",
                              "&:hover": { bgcolor: "#F1F5F9", borderColor: "#94A3B8" },
                            }}
                          >
                            <span>Advanced Search &amp; Model Diagnostics</span>
                            <span className="text-xs text-slate-500 font-semibold">Filter parameters &amp; AI weights &rarr;</span>
                          </Button>
                        </Stack>
                      </Paper>
                    </Grid>
                  </Grid>
                </Box>
              )}

              {/* ══════════════════════════════════════════════════════════════ */}
              {/* TAB 1: CATEGORY × MONTH MATRIX                                 */}
              {/* ══════════════════════════════════════════════════════════════ */}
              {currentTab === 1 && (
                <Paper
                  sx={{
                    p: 2.5,
                    borderRadius: 2,
                    border: "1px solid #dce5ee",
                    boxShadow: "0 10px 24px rgba(15, 23, 42, 0.045)",
                    bgcolor: "#ffffff",
                  }}
                >
                  {/* Matrix Header */}
                  <Stack
                    direction={{ xs: "column", md: "row" }}
                    justifyContent="space-between"
                    alignItems={{ xs: "flex-start", md: "center" }}
                    spacing={2}
                    sx={{ mb: 2, pb: 1.5, borderBottom: "1px solid #F1F5F9" }}
                  >
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49", display: "flex", alignItems: "center", gap: 1 }}>
                        <CategoryIcon sx={{ color: "#1B6B93" }} />
                        Revenue Category &times; Month Anomaly Matrix (2026)
                      </Typography>
                      <Typography variant="caption" sx={{ color: "#64748B", fontWeight: 600 }}>
                        Click any cell to filter and view underlying transaction details in the Anomaly Details tab.
                      </Typography>
                    </Box>

                    <Stack direction="row" spacing={2} alignItems="center">
                      <Chip
                        label="OPERATING YEAR 2026"
                        size="small"
                        sx={{
                          bgcolor: "#e0f2fe",
                          color: "#0369a1",
                          fontWeight: 850,
                          fontSize: "0.72rem",
                        }}
                      />
                    </Stack>
                  </Stack>

                  {/* Matrix Legend */}
                  <Stack direction="row" spacing={2.5} flexWrap="wrap" alignItems="center" sx={{ mb: 2 }}>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.8 }}>
                      <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#DC2626", display: "inline-block" }} />
                      <Typography variant="caption" sx={{ fontWeight: 800, color: "#475569" }}>
                        🔴 High Risk Anomaly
                      </Typography>
                    </Box>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.8 }}>
                      <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#F59E0B", display: "inline-block" }} />
                      <Typography variant="caption" sx={{ fontWeight: 800, color: "#475569" }}>
                        🟡 Medium Risk Anomaly
                      </Typography>
                    </Box>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.8 }}>
                      <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#22C55E", display: "inline-block" }} />
                      <Typography variant="caption" sx={{ fontWeight: 800, color: "#475569" }}>
                        🟢 Normal Activity
                      </Typography>
                    </Box>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.8 }}>
                      <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#CBD5E1", display: "inline-block" }} />
                      <Typography variant="caption" sx={{ fontWeight: 800, color: "#94A3B8" }}>
                        ⚪ No Data
                      </Typography>
                    </Box>
                  </Stack>

                  {matrixLoading ? (
                    <Box sx={{ py: 6, display: "flex", justifyContent: "center", alignItems: "center" }}>
                      <CircularProgress size={32} />
                    </Box>
                  ) : (
                    <TableContainer sx={{ overflowX: "auto" }}>
                      <Table size="small" sx={{ minWidth: 700 }}>
                        <TableHead>
                          <TableRow sx={{ background: "#F8FAFC" }}>
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1.2, minWidth: 200 }}>
                              Revenue Category
                            </TableCell>
                            {matrixMonths.map((m) => (
                              <TableCell
                                key={m}
                                align="center"
                                sx={{
                                  fontWeight: 900,
                                  color: "#082f49",
                                  py: 1.2,
                                  px: 0.8,
                                  minWidth: 70,
                                }}
                              >
                                {m.slice(0, 3)}
                              </TableCell>
                            ))}
                            <TableCell align="center" sx={{ fontWeight: 900, color: "#082f49", py: 1.2, minWidth: 95 }}>
                              Status
                            </TableCell>
                          </TableRow>
                        </TableHead>

                        <TableBody>
                          {matrixCategories.map((category) => {
                            const catSummary = matrixData?.category_summaries?.[category] || {};
                            return (
                              <TableRow
                                key={category}
                                hover
                                sx={{
                                  "&:last-child td, &:last-child th": { border: 0 },
                                }}
                              >
                                <TableCell
                                  component="th"
                                  scope="row"
                                  sx={{
                                    fontWeight: 800,
                                    color: category === "Unmapped" ? "#E1251B" : "#0F172A",
                                    fontSize: 12.5,
                                    py: 1,
                                  }}
                                >
                                  {category}
                                </TableCell>

                                {matrixMonths.map((month) => {
                                  const cellKey = `${category}__${month}`;
                                  const cell = matrixGrid[cellKey] || {
                                    status: "NO_DATA",
                                    color: "gray",
                                    total_records: 0,
                                    high_risk_count: 0,
                                    medium_risk_count: 0,
                                  };

                                  const isSelected =
                                    selectedMatrixCell &&
                                    selectedMatrixCell.category === category &&
                                    selectedMatrixCell.month === month;

                                  let dotColor = "#CBD5E1";
                                  let dotBg = "#F8FAFC";
                                  let dotBorder = "#E2E8F0";
                                  let textColor = "#64748B";

                                  if (cell.status === "HIGH") {
                                    dotColor = "#DC2626";
                                    dotBg = "#FEF2F2";
                                    dotBorder = "#FCA5A5";
                                    textColor = "#DC2626";
                                  } else if (cell.status === "MEDIUM") {
                                    dotColor = "#D97706";
                                    dotBg = "#FFFBEB";
                                    dotBorder = "#FCD34D";
                                    textColor = "#D97706";
                                  } else if (cell.status === "NORMAL") {
                                    dotColor = "#16A34A";
                                    dotBg = "#F0FDF4";
                                    dotBorder = "#86EFAC";
                                    textColor = "#16A34A";
                                  }

                                  const tooltipContent = (
                                    <div style={{ padding: "4px 6px", maxWidth: 260 }}>
                                      <div style={{ fontWeight: 800, fontSize: 13, color: "#FFFFFF", marginBottom: 4 }}>
                                        {category} &bull; {month} {selectedYear}
                                      </div>
                                      <div style={{ fontSize: 12, marginBottom: 2 }}>
                                        <strong>Status:</strong> {cell.status}
                                      </div>
                                      <div style={{ fontSize: 12, marginBottom: 2 }}>
                                        <strong>Total Records:</strong> {formatAmount(cell.total_records)}
                                      </div>
                                      <div style={{ fontSize: 12, marginBottom: 2 }}>
                                        <strong>High Risk Anomalies:</strong> {cell.high_risk_count}
                                      </div>
                                      <div style={{ fontSize: 12, marginBottom: 2 }}>
                                        <strong>Medium Risk:</strong> {cell.medium_risk_count}
                                      </div>
                                      {cell.max_anomaly_score > 0 && (
                                        <div style={{ fontSize: 12, marginBottom: 4 }}>
                                          <strong>Max Score:</strong> {Math.round(cell.max_anomaly_score * 100)}%
                                        </div>
                                      )}
                                      <div style={{ fontSize: 11, fontStyle: "italic", color: "#CBD5E1", borderTop: "1px solid rgba(255,255,255,0.2)", paddingTop: 4 }}>
                                        {cell.primary_risk_reason}
                                      </div>
                                      <div style={{ fontSize: 10, marginTop: 4, color: "#93C5FD", fontWeight: 700 }}>
                                        Click to view details in Tab 3 &rarr;
                                      </div>
                                    </div>
                                  );

                                  return (
                                    <TableCell key={month} align="center" sx={{ py: 0.6, px: 0.4 }}>
                                      <Tooltip title={tooltipContent} arrow placement="top">
                                        <button
                                          type="button"
                                          onClick={() => handleCellClick(category, month, cell)}
                                          disabled={cell.status === "NO_DATA"}
                                          style={{
                                            display: "inline-flex",
                                            alignItems: "center",
                                            justifyContent: "center",
                                            gap: 4,
                                            width: "100%",
                                            maxWidth: 58,
                                            height: 32,
                                            borderRadius: 6,
                                            backgroundColor: isSelected ? "#082F49" : dotBg,
                                            border: `1.5px solid ${isSelected ? "#082F49" : dotBorder}`,
                                            color: isSelected ? "#FFFFFF" : textColor,
                                            cursor: cell.status === "NO_DATA" ? "default" : "pointer",
                                            transition: "all 0.15s ease",
                                          }}
                                        >
                                          <span
                                            style={{
                                              width: 8,
                                              height: 8,
                                              borderRadius: "50%",
                                              backgroundColor: isSelected ? "#38BDF8" : dotColor,
                                              display: "inline-block",
                                              flexShrink: 0,
                                            }}
                                          />
                                          <span style={{ fontSize: 10.5, fontWeight: 800 }}>
                                            {cell.high_risk_count > 0
                                              ? cell.high_risk_count
                                              : cell.medium_risk_count > 0
                                              ? cell.medium_risk_count
                                              : cell.status === "NORMAL"
                                              ? "OK"
                                              : "—"}
                                          </span>
                                        </button>
                                      </Tooltip>
                                    </TableCell>
                                  );
                                })}

                                <TableCell align="center" sx={{ py: 0.6 }}>
                                  <RiskBadge level={catSummary.overall_status || "LOW"} />
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                </Paper>
              )}

              {/* ══════════════════════════════════════════════════════════════ */}
              {/* TAB 2: ANOMALY DETAILS                                         */}
              {/* ══════════════════════════════════════════════════════════════ */}
              {currentTab === 2 && (
                <Paper
                  sx={{
                    p: 2.5,
                    borderRadius: 2,
                    border: "1px solid #dce5ee",
                    boxShadow: "0 10px 24px rgba(15, 23, 42, 0.045)",
                    bgcolor: "#ffffff",
                  }}
                >
                  {/* Top Bar with Filter Context */}
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    justifyContent="space-between"
                    alignItems={{ xs: "flex-start", sm: "center" }}
                    spacing={2}
                    sx={{ mb: 2 }}
                  >
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49" }}>
                        Anomaly Transaction Records ({formatAmount(totalResults)})
                      </Typography>
                      <Typography variant="caption" sx={{ color: "#64748B", fontWeight: 600 }}>
                        Filtered by active criteria. Click any row to expand diagnostic audit trail.
                      </Typography>
                    </Box>

                    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
                      {selectedMatrixCell && (
                        <Chip
                          icon={<FilterIcon sx={{ fontSize: 14 }} />}
                          label={`Matrix: ${selectedMatrixCell.category} (${selectedMatrixCell.month})`}
                          onDelete={() => {
                            setSelectedMatrixCell(null);
                            setSelectedCategory("");
                            setSelectedMonth("");
                          }}
                          color="primary"
                          size="small"
                          sx={{ fontWeight: 800, bgcolor: "#0B3041", color: "white" }}
                        />
                      )}
                      {selectedRisk && (
                        <Chip
                          label={`Risk: ${selectedRisk}`}
                          onDelete={() => setSelectedRisk("")}
                          size="small"
                          color={selectedRisk === "HIGH" ? "error" : selectedRisk === "MEDIUM" ? "warning" : "success"}
                          sx={{ fontWeight: 800 }}
                        />
                      )}
                      {(selectedCategory || selectedMonth || selectedRisk || searchTerm) && (
                        <Button
                          size="small"
                          onClick={handleClearFilters}
                          sx={{ textTransform: "none", fontWeight: 800, color: "#64748B" }}
                        >
                          Clear Filters
                        </Button>
                      )}
                    </Stack>
                  </Stack>

                  {/* Search Bar & Quick Filters */}
                  <Grid container spacing={1.5} sx={{ mb: 2 }}>
                    <Grid item xs={12} sm={6} md={5}>
                      <TextField
                        placeholder="Search by GL Code, Description, Account, Flexfield..."
                        value={searchTerm}
                        onChange={(e) => {
                          setSearchTerm(e.target.value);
                          setPage(0);
                        }}
                        size="small"
                        fullWidth
                        InputProps={{
                          startAdornment: (
                            <InputAdornment position="start">
                              <SearchIcon sx={{ color: "#94A3B8", fontSize: 18 }} />
                            </InputAdornment>
                          ),
                          endAdornment: searchTerm ? (
                            <InputAdornment position="end">
                              <IconButton size="small" onClick={() => { setSearchTerm(""); setPage(0); }}>
                                <ClearIcon fontSize="small" />
                              </IconButton>
                            </InputAdornment>
                          ) : null,
                        }}
                        sx={{ "& .MuiOutlinedInput-root": { borderRadius: 1.5, bgcolor: "#F8FAFC", height: 38 } }}
                      />
                    </Grid>

                    <Grid item xs={6} sm={3} md={2.3}>
                      <Select
                        size="small"
                        value={selectedCategory}
                        onChange={(e) => {
                          setSelectedCategory(e.target.value);
                          setSelectedMatrixCell(null);
                          setPage(0);
                        }}
                        fullWidth
                        displayEmpty
                        sx={{ borderRadius: 1.5, fontWeight: 700, bgcolor: "#F8FAFC", height: 38 }}
                      >
                        <MenuItem value="">All Categories</MenuItem>
                        {(filterOptions.categories || matrixCategories).map((c) => (
                          <MenuItem key={c} value={c}>
                            {c}
                          </MenuItem>
                        ))}
                      </Select>
                    </Grid>

                    <Grid item xs={6} sm={3} md={2.3}>
                      <Select
                        size="small"
                        value={selectedMonth}
                        onChange={(e) => {
                          setSelectedMonth(e.target.value);
                          setSelectedMatrixCell(null);
                          setPage(0);
                        }}
                        fullWidth
                        displayEmpty
                        sx={{ borderRadius: 1.5, fontWeight: 700, bgcolor: "#F8FAFC", height: 38 }}
                      >
                        <MenuItem value="">All Months</MenuItem>
                        {(filterOptions.months || matrixMonths).map((m) => (
                          <MenuItem key={m} value={m}>
                            {m}
                          </MenuItem>
                        ))}
                      </Select>
                    </Grid>

                    <Grid item xs={12} sm={6} md={2.4}>
                      <Select
                        size="small"
                        value={selectedRisk}
                        onChange={(e) => {
                          setSelectedRisk(e.target.value);
                          setPage(0);
                        }}
                        fullWidth
                        displayEmpty
                        sx={{ borderRadius: 1.5, fontWeight: 700, bgcolor: "#F8FAFC", height: 38 }}
                      >
                        <MenuItem value="">All Risk Levels</MenuItem>
                        <MenuItem value="HIGH">🔴 High Risk</MenuItem>
                        <MenuItem value="MEDIUM">🟡 Medium Risk</MenuItem>
                        <MenuItem value="LOW">🟢 Low Risk / Normal</MenuItem>
                      </Select>
                    </Grid>
                  </Grid>

                  {/* Results Table */}
                  {tableLoading ? (
                    <Box sx={{ py: 6, display: "flex", justifyContent: "center", alignItems: "center" }}>
                      <CircularProgress size={32} />
                    </Box>
                  ) : results.length === 0 ? (
                    <Box sx={{ py: 6, textAlign: "center" }}>
                      <ShieldIcon sx={{ fontSize: 42, color: "#94A3B8", mb: 1 }} />
                      <Typography variant="subtitle1" sx={{ fontWeight: 800, color: "#334155" }}>
                        No anomaly records matching criteria
                      </Typography>
                      <Button
                        onClick={handleClearFilters}
                        variant="outlined"
                        size="small"
                        sx={{ mt: 1.5, textTransform: "none", fontWeight: 800, borderRadius: 1.5 }}
                      >
                        Reset All Filters
                      </Button>
                    </Box>
                  ) : (
                    <TableContainer>
                      <Table size="small">
                        <TableHead>
                          <TableRow sx={{ background: "#F8FAFC" }}>
                            <TableCell sx={{ width: 32 }} />
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1 }}>Risk</TableCell>
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1 }}>Period</TableCell>
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1 }}>Revenue Category</TableCell>
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1 }}>GL Code</TableCell>
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1 }}>Description</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 900, color: "#082f49", py: 1 }}>
                              Period Activity (LKR)
                            </TableCell>
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1, minWidth: 110 }}>
                              Score
                            </TableCell>
                            <TableCell sx={{ fontWeight: 900, color: "#082f49", py: 1 }}>Reason</TableCell>
                          </TableRow>
                        </TableHead>

                        <TableBody>
                          {results.map((r) => {
                            const isExpanded = expandedRowId === r.id;
                            return (
                              <React.Fragment key={r.id}>
                                <TableRow
                                  hover
                                  onClick={() => setExpandedRowId(isExpanded ? null : r.id)}
                                  sx={{
                                    cursor: "pointer",
                                    bgcolor: isExpanded ? "#F8FAFC" : "transparent",
                                    "&:last-child td, &:last-child th": { border: 0 },
                                  }}
                                >
                                  <TableCell sx={{ py: 1 }}>
                                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); setExpandedRowId(isExpanded ? null : r.id); }}>
                                      {isExpanded ? <ArrowUpIcon fontSize="small" /> : <ArrowDownIcon fontSize="small" />}
                                    </IconButton>
                                  </TableCell>
                                  <TableCell sx={{ py: 1 }}>
                                    <RiskBadge level={r.risk_level} />
                                  </TableCell>
                                  <TableCell sx={{ fontWeight: 700, color: "#334155", py: 1, whiteSpace: "nowrap" }}>
                                    {r.period_month} {r.period_year}
                                  </TableCell>
                                  <TableCell sx={{ fontWeight: 700, color: "#0F172A", py: 1 }}>
                                    {r.revenue_category}
                                  </TableCell>
                                  <TableCell sx={{ fontFamily: "monospace", fontWeight: 700, color: "#1B6B93", py: 1 }}>
                                    {r.gl_code}
                                  </TableCell>
                                  <TableCell sx={{ color: "#334155", py: 1, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {r.description}
                                  </TableCell>
                                  <TableCell
                                    align="right"
                                    sx={{
                                      fontFamily: "monospace",
                                      fontWeight: 800,
                                      color: r.period_activity < 0 ? "#DC2626" : "#0F172A",
                                      py: 1,
                                      whiteSpace: "nowrap",
                                    }}
                                  >
                                    {formatAmount(r.period_activity)}
                                  </TableCell>
                                  <TableCell sx={{ py: 1 }}>
                                    <ScoreBar value={r.anomaly_score} />
                                  </TableCell>
                                  <TableCell sx={{ color: "#475569", fontSize: 11.5, py: 1, maxWidth: 260 }}>
                                    <span style={{ display: "-webkit-box", WebkitLineClamp: 1, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                                      {r.risk_reason}
                                    </span>
                                  </TableCell>
                                </TableRow>

                                {/* Expanded Drawer */}
                                <TableRow>
                                  <TableCell colSpan={9} sx={{ py: 0, px: 2.5, bgcolor: "#F8FAFC", borderBottom: isExpanded ? "1px solid #E2E8F0" : "none" }}>
                                    <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                                      <Box sx={{ py: 2, px: 2, my: 1, bgcolor: "white", borderRadius: 1.5, border: "1px solid #E2E8F0" }}>
                                        <Typography variant="caption" sx={{ fontWeight: 850, color: "#082f49", display: "block", mb: 1 }}>
                                          FLEXFIELD &amp; DIAGNOSTIC CONTEXT
                                        </Typography>

                                        <Grid container spacing={2}>
                                          <Grid item xs={12} md={6}>
                                            <Box sx={{ p: 1.2, bgcolor: "#F8FAFC", borderRadius: 1, mb: 1 }}>
                                              <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B" }}>
                                                Flexfield Code:
                                              </Typography>
                                              <Typography variant="body2" sx={{ fontFamily: "monospace", fontWeight: 700, mt: 0.2 }}>
                                                {r.flexfield || "—"}
                                              </Typography>
                                            </Box>
                                            <Grid container spacing={1}>
                                              <Grid item xs={6}>
                                                <Typography variant="caption" sx={{ color: "#64748B" }}>Cost Center:</Typography>
                                                <Typography variant="body2" sx={{ fontWeight: 750 }}>{r.cost_center || "—"}</Typography>
                                              </Grid>
                                              <Grid item xs={6}>
                                                <Typography variant="caption" sx={{ color: "#64748B" }}>Business Line:</Typography>
                                                <Typography variant="body2" sx={{ fontWeight: 750 }}>{r.business_line || "—"}</Typography>
                                              </Grid>
                                            </Grid>
                                          </Grid>

                                          <Grid item xs={12} md={6}>
                                            <Box sx={{ p: 1.2, bgcolor: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 1 }}>
                                              <Typography variant="caption" sx={{ fontWeight: 800, color: "#DC2626" }}>
                                                AI Anomaly Reasoning:
                                              </Typography>
                                              <Typography variant="body2" sx={{ color: "#991B1B", fontWeight: 600, mt: 0.2 }}>
                                                {r.risk_reason}
                                              </Typography>
                                              <Typography variant="caption" sx={{ color: "#B91C1C", display: "block", mt: 0.4 }}>
                                                Z-Score: {r.z_score} &bull; Isolation Score: {r.isolation_score} &bull; Method: {r.detection_method}
                                              </Typography>
                                            </Box>
                                          </Grid>
                                        </Grid>
                                      </Box>
                                    </Collapse>
                                  </TableCell>
                                </TableRow>
                              </React.Fragment>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}

                  {/* Pagination */}
                  {totalResults > PAGE_SIZE && (
                    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mt: 2, pt: 1.5, borderTop: "1px solid #F1F5F9" }}>
                      <Typography variant="caption" sx={{ fontWeight: 700, color: "#64748B" }}>
                        Showing {page * PAGE_SIZE + 1} &ndash; {Math.min((page + 1) * PAGE_SIZE, totalResults)} of {formatAmount(totalResults)} records
                      </Typography>

                      <Stack direction="row" spacing={1}>
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={page === 0 || tableLoading}
                          onClick={() => setPage((p) => p - 1)}
                          sx={{ textTransform: "none", fontWeight: 800, borderRadius: 1.5 }}
                        >
                          Previous
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={page >= totalPages - 1 || tableLoading}
                          onClick={() => setPage((p) => p + 1)}
                          sx={{ textTransform: "none", fontWeight: 800, borderRadius: 1.5 }}
                        >
                          Next ({page + 1} / {totalPages})
                        </Button>
                      </Stack>
                    </Box>
                  )}
                </Paper>
              )}

              {/* ══════════════════════════════════════════════════════════════ */}
              {/* TAB 3: FILTERS / ANALYSIS                                      */}
              {/* ══════════════════════════════════════════════════════════════ */}
              {currentTab === 3 && (
                <Grid container spacing={2.5}>
                  {/* Filter Configuration Card */}
                  <Grid item xs={12} md={7}>
                    <Paper sx={cardStyle}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 850, color: "#082f49", mb: 1.5 }}>
                        Dashboard Filter Controls
                      </Typography>
                      <Typography variant="body2" sx={{ color: "#64748B", mb: 2.5 }}>
                        Configure operating parameters to filter anomaly intelligence across all sections:
                      </Typography>

                      <Grid container spacing={2}>
                        <Grid item xs={12} sm={6}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", display: "block", mb: 0.5 }}>
                            OPERATING YEAR
                          </Typography>
                          <Box
                            sx={{
                              p: "8.5px 14px",
                              bgcolor: "#F8FAFC",
                              borderRadius: 1.5,
                              border: "1px solid #E2E8F0",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              height: 40,
                            }}
                          >
                            <Typography variant="body2" sx={{ fontWeight: 800, color: "#082F49" }}>
                              2026
                            </Typography>
                            <Chip label="Fixed Operating Year" size="small" sx={{ height: 20, fontSize: "0.65rem", fontWeight: 750, bgcolor: "#E0F2FE", color: "#0369A1" }} />
                          </Box>
                        </Grid>

                        <Grid item xs={12} sm={6}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", display: "block", mb: 0.5 }}>
                            PERIOD MONTH
                          </Typography>
                          <Select
                            value={selectedMonth}
                            onChange={(e) => {
                              setSelectedMonth(e.target.value);
                              setSelectedMatrixCell(null);
                              setPage(0);
                            }}
                            size="small"
                            fullWidth
                            displayEmpty
                            sx={{ borderRadius: 1.5, fontWeight: 700, bgcolor: "#F8FAFC" }}
                          >
                            <MenuItem value="">All Months</MenuItem>
                            {(filterOptions.months || matrixMonths).map((m) => (
                              <MenuItem key={m} value={m}>
                                {m}
                              </MenuItem>
                            ))}
                          </Select>
                        </Grid>

                        <Grid item xs={12} sm={6}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", display: "block", mb: 0.5 }}>
                            REVENUE CATEGORY
                          </Typography>
                          <Select
                            value={selectedCategory}
                            onChange={(e) => {
                              setSelectedCategory(e.target.value);
                              setSelectedMatrixCell(null);
                              setPage(0);
                            }}
                            size="small"
                            fullWidth
                            displayEmpty
                            sx={{ borderRadius: 1.5, fontWeight: 700, bgcolor: "#F8FAFC" }}
                          >
                            <MenuItem value="">All 14 Categories</MenuItem>
                            {(filterOptions.categories || matrixCategories).map((c) => (
                              <MenuItem key={c} value={c}>
                                {c}
                              </MenuItem>
                            ))}
                          </Select>
                        </Grid>

                        <Grid item xs={12} sm={6}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", display: "block", mb: 0.5 }}>
                            RISK LEVEL TIER
                          </Typography>
                          <Select
                            value={selectedRisk}
                            onChange={(e) => {
                              setSelectedRisk(e.target.value);
                              setPage(0);
                            }}
                            size="small"
                            fullWidth
                            displayEmpty
                            sx={{ borderRadius: 1.5, fontWeight: 700, bgcolor: "#F8FAFC" }}
                          >
                            <MenuItem value="">All Risk Levels</MenuItem>
                            <MenuItem value="HIGH">🔴 High Risk Only</MenuItem>
                            <MenuItem value="MEDIUM">🟡 Medium Risk Only</MenuItem>
                            <MenuItem value="LOW">🟢 Low Risk / Normal</MenuItem>
                          </Select>
                        </Grid>

                        <Grid item xs={12}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", display: "block", mb: 0.5 }}>
                            SEARCH TRANSACTION KEYWORDS
                          </Typography>
                          <TextField
                            placeholder="Search GL Code, Account Description, Flexfield..."
                            value={searchTerm}
                            onChange={(e) => {
                              setSearchTerm(e.target.value);
                              setPage(0);
                            }}
                            size="small"
                            fullWidth
                            sx={{ "& .MuiOutlinedInput-root": { borderRadius: 1.5, bgcolor: "#F8FAFC" } }}
                          />
                        </Grid>

                        <Grid item xs={12}>
                          <Button
                            onClick={handleClearFilters}
                            variant="outlined"
                            startIcon={<ClearIcon />}
                            sx={{
                              textTransform: "none",
                              fontWeight: 800,
                              borderRadius: 1.5,
                              borderColor: "#CBD5E1",
                              color: "#475569",
                              "&:hover": { borderColor: "#94A3B8", bgcolor: "#F1F5F9" },
                            }}
                          >
                            Reset Filter Parameters
                          </Button>
                        </Grid>
                      </Grid>
                    </Paper>
                  </Grid>

                  {/* Model Diagnostics Card */}
                  <Grid item xs={12} md={5}>
                    <Paper sx={cardStyle}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 850, color: "#082f49", mb: 1.5 }}>
                        AI Model Diagnostics
                      </Typography>

                      <Stack spacing={2}>
                        <Box sx={{ p: 1.5, bgcolor: "#F8FAFC", borderRadius: 1.5, border: "1px solid #E2E8F0" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", display: "block" }}>
                            DETECTION METHOD
                          </Typography>
                          <Typography variant="body2" sx={{ fontWeight: 800, color: "#082f49", mt: 0.2 }}>
                            Hybrid Isolation Forest + Group Z-Score
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#64748B", display: "block", mt: 0.3 }}>
                            Composite scoring: 60% Isolation Forest + 40% Z-Score
                          </Typography>
                        </Box>

                        <Box sx={{ p: 1.5, bgcolor: "#F8FAFC", borderRadius: 1.5, border: "1px solid #E2E8F0" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748B", display: "block" }}>
                            RISK LEVEL THRESHOLDS
                          </Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700, color: "#DC2626", mt: 0.3 }}>
                            &bull; High Risk: Composite Score &ge; 70%
                          </Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700, color: "#D97706" }}>
                            &bull; Medium Risk: Composite Score 40% &ndash; 69%
                          </Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700, color: "#16A34A" }}>
                            &bull; Low Risk: Composite Score &lt; 40%
                          </Typography>
                        </Box>

                        {isAdmin && (
                          <Box sx={{ p: 1.5, bgcolor: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 1.5 }}>
                            <Typography variant="caption" sx={{ fontWeight: 800, color: "#166534", display: "block" }}>
                              ADMIN RE-ANALYSIS TRIGGER
                            </Typography>
                            <Typography variant="body2" sx={{ color: "#14532d", mt: 0.3, mb: 1.5, fontSize: 13 }}>
                              Trigger an updated anomaly detection run across all stored Trial Balance files.
                            </Typography>
                            <Button
                              onClick={handleRunAnalysis}
                              disabled={analyzing}
                              variant="contained"
                              size="small"
                              startIcon={analyzing ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                              sx={{
                                textTransform: "none",
                                fontWeight: 800,
                                bgcolor: "#0B3041",
                                borderRadius: 1.5,
                                "&:hover": { bgcolor: "#1B6B93" },
                              }}
                            >
                              {analyzing ? "Running Detection..." : "Run AI Anomaly Detection"}
                            </Button>
                          </Box>
                        )}
                      </Stack>
                    </Paper>
                  </Grid>
                </Grid>
              )}
            </div>
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}

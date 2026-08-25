import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import {
  getAnomalySummary,
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
} from "@mui/material";
import {
  Dashboard as DashboardIcon,
  QueryStats as ForecastIcon,
  Person as PersonIcon,
  ExitToApp as LogoutIcon,
  Refresh as RefreshIcon,
  CheckCircle as CheckCircleIcon,
  WarningAmber as WarningIcon,
  BugReport as AnomalyIcon,
  Search as SearchIcon,
  FilterList as FilterIcon,
  Clear as ClearIcon,
  KeyboardArrowDown as ArrowDownIcon,
  KeyboardArrowUp as ArrowUpIcon,
  TrendingUp as TrendingUpIcon,
  AccountBalance as FinanceIcon,
  InfoOutlined as InfoIcon,
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
  { label: "Anomaly Detection", icon: AnomalyIcon, path: "/anomaly", active: true },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

// ── Semantic Risk Colors ──────────────────────────────────────────────────────
const RISK_STYLES = {
  high: {
    badgeColor: "#DC2626",
    badgeBg: "#FEE2E2",
    borderColor: "#FECACA",
    barColor: "#DC2626",
    label: "HIGH",
  },
  medium: {
    badgeColor: "#D97706",
    badgeBg: "#FEF3C7",
    borderColor: "#FDE68A",
    barColor: "#F59E0B",
    label: "MEDIUM",
  },
  low: {
    badgeColor: "#16A34A",
    badgeBg: "#DCFCE7",
    borderColor: "#BBF7D0",
    barColor: "#22C55E",
    label: "LOW",
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
  let bgTrack = "#DCFCE7";
  if (pct >= 70) {
    color = "#DC2626";
    bgTrack = "#FEE2E2";
  } else if (pct >= 40) {
    color = "#F59E0B";
    bgTrack = "#FEF3C7";
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 110 }}>
      <div
        style={{
          flex: 1,
          height: 7,
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
          fontSize: 12,
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

  const [summary, setSummary] = useState(null);
  const [results, setResults] = useState([]);
  const [totalResults, setTotalResults] = useState(0);
  const [filterOptions, setFilterOptions] = useState({ months: [], categories: [] });
  const [loading, setLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState(null);
  const [expandedRowId, setExpandedRowId] = useState(null);

  // Filters
  const [riskFilter, setRiskFilter] = useState("");
  const [monthFilter, setMonthFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 25;

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  // Load summary and filter options
  const loadInitialData = useCallback(async () => {
    try {
      const [sumRes, filtersRes] = await Promise.all([
        getAnomalySummary().catch(() => null),
        getAnomalyFilterOptions().catch(() => ({ months: [], categories: [] })),
      ]);
      setSummary(sumRes);
      setFilterOptions(filtersRes || { months: [], categories: [] });
    } catch (err) {
      console.error("Failed to load anomaly metadata:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInitialData();
  }, [loadInitialData]);

  // Query records when filters or page change
  const fetchRecords = useCallback(async () => {
    setTableLoading(true);
    try {
      const data = await getAnomalyResults({
        risk_level: riskFilter || undefined,
        period_month: monthFilter || undefined,
        revenue_category: categoryFilter || undefined,
        search: searchTerm.trim() || undefined,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
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
  }, [riskFilter, monthFilter, categoryFilter, searchTerm, page]);

  useEffect(() => {
    if (!loading) {
      fetchRecords();
    }
  }, [loading, fetchRecords]);

  // Handle manual analysis run (Admin only)
  const handleRunAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      await triggerAnomalyAnalysis();
      await loadInitialData();
      setPage(0);
      await fetchRecords();
    } catch (err) {
      setError(err.message || "Failed to trigger anomaly analysis");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleClearFilters = () => {
    setRiskFilter("");
    setMonthFilter("");
    setCategoryFilter("");
    setSearchTerm("");
    setPage(0);
  };

  const totalPages = Math.ceil(totalResults / PAGE_SIZE) || 1;
  const categoriesDistribution = summary?.category_distribution || [];
  const maxCategoryCount = categoriesDistribution.length > 0
    ? Math.max(...categoriesDistribution.map((d) => d.count))
    : 1;

  const formattedLastAnalyzed = useMemo(() => {
    if (!summary?.last_analyzed_at) return "N/A";
    try {
      const date = new Date(summary.last_analyzed_at);
      return date.toLocaleString("en-GB", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return summary.last_analyzed_at;
    }
  }, [summary]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
        <div className="flex min-h-screen">
          {/* ── Permanent Left Navigation Sidebar ────────────────────────────── */}
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
            {/* ── Application Top Header ─────────────────────────────────────── */}
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="relative flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src="/logo.png" alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">
                      Finance Revenue Automation
                    </h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      AI Risk Monitoring &amp; Financial Anomaly Detection
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

            {/* ── Page Body ──────────────────────────────────────────────────── */}
            <div className="flex-1 px-4 py-6 md:px-8 lg:px-10">
              {/* ── Page Title & Actions ─────────────────────────────────────── */}
              <Box sx={{ mb: 3 }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: { xs: "flex-start", sm: "center" }, flexDirection: { xs: "column", sm: "row" }, gap: 2, mb: 1.5 }}>
                  <Box>
                    <Typography variant="h4" sx={{ fontWeight: 900, color: "#082f49", display: "flex", alignItems: "center", gap: 1.5 }}>
                      <AnomalyIcon sx={{ fontSize: 32, color: "#1B6B93" }} />
                      Anomaly &amp; Fraud Detection
                    </Typography>
                    <Typography variant="body2" sx={{ color: "#64748B", fontWeight: 500, mt: 0.5 }}>
                      AI-driven analysis of Trial Balance data to surface potentially suspicious transactions for Finance Department review.
                    </Typography>
                  </Box>

                  {isAdmin && (
                    <Button
                      id="btn-run-analysis"
                      onClick={handleRunAnalysis}
                      disabled={analyzing}
                      variant="contained"
                      startIcon={analyzing ? <CircularProgress size={18} color="inherit" /> : <RefreshIcon />}
                      sx={{
                        height: 42,
                        backgroundColor: "#0B3041",
                        textTransform: "none",
                        fontWeight: 800,
                        borderRadius: 1.5,
                        px: 2.5,
                        boxShadow: "0 4px 14px rgba(11, 48, 65, 0.25)",
                        "&:hover": { backgroundColor: "#1B6B93" },
                      }}
                    >
                      {analyzing ? "Running Analysis…" : "Run Analysis"}
                    </Button>
                  )}
                </Box>

                {/* ── Compliance / Warning Notice Banner ──────────────────────── */}
                <Box
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 1.5,
                    p: 1.5,
                    px: 2,
                    borderRadius: 2,
                    backgroundColor: "#FFFBEB",
                    border: "1px solid #FDE68A",
                    color: "#92400E",
                    fontSize: "13px",
                    fontWeight: 600,
                  }}
                >
                  <WarningIcon sx={{ fontSize: 20, color: "#D97706", flexShrink: 0 }} />
                  <span>
                    <strong>Notice:</strong> All detections are potential anomalies for human review — not confirmed fraud classifications.
                  </span>
                </Box>

                {error && (
                  <Alert severity="error" sx={{ mt: 2, borderRadius: 2 }}>
                    {error}
                  </Alert>
                )}
              </Box>

              {loading ? (
                <Paper
                  elevation={0}
                  sx={{
                    p: 6,
                    textAlign: "center",
                    borderRadius: 2,
                    border: "1px solid #dce5ee",
                    backgroundColor: "#ffffff",
                  }}
                >
                  <CircularProgress size={40} sx={{ color: "#0B3041", mb: 2 }} />
                  <Typography variant="body1" sx={{ color: "#64748B", fontWeight: 600 }}>
                    Loading financial anomaly intelligence…
                  </Typography>
                </Paper>
              ) : (
                <Stack spacing={3}>
                  {/* ── KPI Summary Cards (4 Cards) ──────────────────────────── */}
                  <Grid container spacing={2.5}>
                    {/* Card 1: Total Analyzed */}
                    <Grid item xs={12} sm={6} md={3}>
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2.5,
                          borderRadius: 2,
                          border: "1px solid #dce5ee",
                          backgroundColor: "#ffffff",
                          boxShadow: "0 4px 18px rgba(15, 23, 42, 0.04)",
                          position: "relative",
                          overflow: "hidden",
                        }}
                      >
                        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                          <Typography variant="caption" sx={{ textTransform: "uppercase", fontWeight: 800, color: "#64748B", letterSpacing: "0.08em" }}>
                            Total Analyzed
                          </Typography>
                          <Box sx={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: "#1B6B93" }} />
                        </Box>
                        <Typography variant="h4" sx={{ fontWeight: 900, color: "#082f49", mb: 0.5 }}>
                          {summary?.total_analyzed?.toLocaleString() ?? "0"}
                        </Typography>
                        <Typography variant="caption" sx={{ color: "#94A3B8", fontWeight: 600, display: "block" }}>
                          Last run: {formattedLastAnalyzed}
                        </Typography>
                      </Paper>
                    </Grid>

                    {/* Card 2: High Risk */}
                    <Grid item xs={12} sm={6} md={3}>
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2.5,
                          borderRadius: 2,
                          border: "1px solid #FECACA",
                          backgroundColor: "#ffffff",
                          boxShadow: "0 4px 18px rgba(220, 38, 38, 0.05)",
                          position: "relative",
                        }}
                      >
                        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                          <Typography variant="caption" sx={{ textTransform: "uppercase", fontWeight: 800, color: "#DC2626", letterSpacing: "0.08em" }}>
                            🔴 High Risk
                          </Typography>
                          <Box sx={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: "#DC2626" }} />
                        </Box>
                        <Typography variant="h4" sx={{ fontWeight: 900, color: "#DC2626", mb: 0.5 }}>
                          {summary?.high_count?.toLocaleString() ?? "0"}
                        </Typography>
                        <Typography variant="caption" sx={{ color: "#94A3B8", fontWeight: 600, display: "block" }}>
                          Score &ge; 70% (Immediate Review)
                        </Typography>
                      </Paper>
                    </Grid>

                    {/* Card 3: Medium Risk */}
                    <Grid item xs={12} sm={6} md={3}>
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2.5,
                          borderRadius: 2,
                          border: "1px solid #FDE68A",
                          backgroundColor: "#ffffff",
                          boxShadow: "0 4px 18px rgba(217, 119, 6, 0.05)",
                          position: "relative",
                        }}
                      >
                        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                          <Typography variant="caption" sx={{ textTransform: "uppercase", fontWeight: 800, color: "#D97706", letterSpacing: "0.08em" }}>
                            🟡 Medium Risk
                          </Typography>
                          <Box sx={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: "#D97706" }} />
                        </Box>
                        <Typography variant="h4" sx={{ fontWeight: 900, color: "#D97706", mb: 0.5 }}>
                          {summary?.medium_count?.toLocaleString() ?? "0"}
                        </Typography>
                        <Typography variant="caption" sx={{ color: "#94A3B8", fontWeight: 600, display: "block" }}>
                          Score 40–70% (Flagged Movement)
                        </Typography>
                      </Paper>
                    </Grid>

                    {/* Card 4: Low Risk */}
                    <Grid item xs={12} sm={6} md={3}>
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2.5,
                          borderRadius: 2,
                          border: "1px solid #BBF7D0",
                          backgroundColor: "#ffffff",
                          boxShadow: "0 4px 18px rgba(22, 163, 74, 0.05)",
                          position: "relative",
                        }}
                      >
                        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                          <Typography variant="caption" sx={{ textTransform: "uppercase", fontWeight: 800, color: "#16A34A", letterSpacing: "0.08em" }}>
                            🟢 Low Risk
                          </Typography>
                          <Box sx={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: "#16A34A" }} />
                        </Box>
                        <Typography variant="h4" sx={{ fontWeight: 900, color: "#16A34A", mb: 0.5 }}>
                          {summary?.low_count?.toLocaleString() ?? "0"}
                        </Typography>
                        <Typography variant="caption" sx={{ color: "#94A3B8", fontWeight: 600, display: "block" }}>
                          Score &lt; 40% (Standard Range)
                        </Typography>
                      </Paper>
                    </Grid>
                  </Grid>

                  {/* ── Top Suspicious Categories ────────────────────────────── */}
                  {categoriesDistribution.length > 0 && (
                    <Paper
                      elevation={0}
                      sx={{
                        p: { xs: 2.5, md: 3 },
                        borderRadius: 2,
                        border: "1px solid #dce5ee",
                        backgroundColor: "#ffffff",
                        boxShadow: "0 18px 42px rgba(15, 23, 42, 0.04)",
                      }}
                    >
                      <Box sx={{ mb: 2.5 }}>
                        <Typography variant="h6" sx={{ fontWeight: 800, color: "#082f49" }}>
                          Top Suspicious Categories (HIGH &amp; MEDIUM)
                        </Typography>
                        <Typography variant="body2" sx={{ color: "#64748B" }}>
                          Revenue categories with highest volume of statistical outliers and structural anomalies
                        </Typography>
                      </Box>

                      <Stack spacing={1.5}>
                        {categoriesDistribution.map((item, index) => {
                          const barPct = Math.round((item.count / maxCategoryCount) * 100);
                          const isHigh = item.risk_level === "HIGH";
                          const barColor = isHigh ? "#DC2626" : "#F59E0B";

                          return (
                            <Box
                              key={index}
                              sx={{
                                display: "flex",
                                alignItems: "center",
                                gap: 2,
                                py: 0.5,
                              }}
                            >
                              <Typography
                                variant="body2"
                                sx={{
                                  width: { xs: 140, sm: 220 },
                                  fontWeight: 700,
                                  color: "#1E293B",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                }}
                                title={item.revenue_category}
                              >
                                {item.revenue_category || "Unmapped"}
                              </Typography>

                              <RiskBadge level={item.risk_level} />

                              <Box sx={{ flex: 1, height: 10, backgroundColor: "#F1F5F9", borderRadius: 9999, overflow: "hidden" }}>
                                <Box
                                  sx={{
                                    width: `${barPct}%`,
                                    height: "100%",
                                    backgroundColor: barColor,
                                    borderRadius: 9999,
                                    transition: "width 0.5s ease",
                                  }}
                                />
                              </Box>

                              <Typography
                                variant="body2"
                                sx={{
                                  width: 60,
                                  textAlign: "right",
                                  fontWeight: 800,
                                  color: "#082f49",
                                  fontFamily: "monospace",
                                }}
                              >
                                {item.count.toLocaleString()}
                              </Typography>
                            </Box>
                          );
                        })}
                      </Stack>
                    </Paper>
                  )}

                  {/* ── Suspicious Transaction Records Section ──────────────── */}
                  <Paper
                    elevation={0}
                    sx={{
                      p: { xs: 2.5, md: 3 },
                      borderRadius: 2,
                      border: "1px solid #dce5ee",
                      backgroundColor: "#ffffff",
                      boxShadow: "0 18px 42px rgba(15, 23, 42, 0.04)",
                    }}
                  >
                    <Box sx={{ mb: 2.5, display: "flex", justifyContent: "space-between", alignItems: { xs: "flex-start", sm: "center" }, flexDirection: { xs: "column", sm: "row" }, gap: 1 }}>
                      <Box>
                        <Typography variant="h6" sx={{ fontWeight: 800, color: "#082f49" }}>
                          Suspicious Transaction Records
                        </Typography>
                        <Typography variant="body2" sx={{ color: "#64748B" }}>
                          Detailed trial balance line-item anomaly scores and forensic explanations
                        </Typography>
                      </Box>
                      <Chip
                        label={`${totalResults.toLocaleString()} records found`}
                        size="small"
                        sx={{ fontWeight: 800, backgroundColor: "#E0F2FE", color: "#0369A1" }}
                      />
                    </Box>

                    {/* ── Filter Controls ──────────────────────────────────── */}
                    <Box
                      sx={{
                        p: 2,
                        mb: 2.5,
                        borderRadius: 1.5,
                        backgroundColor: "#F8FAFC",
                        border: "1px solid #E2E8F0",
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 1.5,
                        alignItems: "center",
                      }}
                    >
                      <TextField
                        size="small"
                        placeholder="Search GL code, description..."
                        value={searchTerm}
                        onChange={(e) => {
                          setSearchTerm(e.target.value);
                          setPage(0);
                        }}
                        InputProps={{
                          startAdornment: (
                            <InputAdornment position="start">
                              <SearchIcon fontSize="small" sx={{ color: "#94A3B8" }} />
                            </InputAdornment>
                          ),
                        }}
                        sx={{ minWidth: 240, backgroundColor: "#ffffff" }}
                      />

                      <Select
                        size="small"
                        value={riskFilter}
                        onChange={(e) => {
                          setRiskFilter(e.target.value);
                          setPage(0);
                        }}
                        displayEmpty
                        sx={{ minWidth: 160, backgroundColor: "#ffffff" }}
                      >
                        <MenuItem value="">All Risk Levels</MenuItem>
                        <MenuItem value="HIGH">🔴 High Risk</MenuItem>
                        <MenuItem value="MEDIUM">🟡 Medium Risk</MenuItem>
                        <MenuItem value="LOW">🟢 Low Risk</MenuItem>
                      </Select>

                      <Select
                        size="small"
                        value={monthFilter}
                        onChange={(e) => {
                          setMonthFilter(e.target.value);
                          setPage(0);
                        }}
                        displayEmpty
                        sx={{ minWidth: 150, backgroundColor: "#ffffff" }}
                      >
                        <MenuItem value="">All Months</MenuItem>
                        {filterOptions.months.map((m) => (
                          <MenuItem key={m} value={m}>
                            {m}
                          </MenuItem>
                        ))}
                      </Select>

                      <Select
                        size="small"
                        value={categoryFilter}
                        onChange={(e) => {
                          setCategoryFilter(e.target.value);
                          setPage(0);
                        }}
                        displayEmpty
                        sx={{ minWidth: 200, backgroundColor: "#ffffff" }}
                      >
                        <MenuItem value="">All Categories</MenuItem>
                        {filterOptions.categories.map((c) => (
                          <MenuItem key={c} value={c}>
                            {c}
                          </MenuItem>
                        ))}
                      </Select>

                      <Button
                        variant="outlined"
                        size="small"
                        onClick={handleClearFilters}
                        startIcon={<ClearIcon />}
                        sx={{
                          height: 40,
                          textTransform: "none",
                          fontWeight: 700,
                          borderColor: "#CBD5E1",
                          color: "#475569",
                          "&:hover": { borderColor: "#94A3B8", backgroundColor: "#F1F5F9" },
                        }}
                      >
                        Clear
                      </Button>
                    </Box>

                    {/* ── Data Table ────────────────────────────────────────── */}
                    <TableContainer sx={{ border: "1px solid #E2E8F0", borderRadius: 1.5 }}>
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow sx={{ "& th": { backgroundColor: "#F8FAFC", fontWeight: 800, color: "#475569", fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.05em", py: 1.5 } }}>
                            <TableCell width={90}>Risk</TableCell>
                            <TableCell width={140}>Score</TableCell>
                            <TableCell width={120}>Period</TableCell>
                            <TableCell width={110}>GL Code</TableCell>
                            <TableCell>Description</TableCell>
                            <TableCell width={110}>Account</TableCell>
                            <TableCell width={180}>Category</TableCell>
                            <TableCell align="right" width={140}>Period Activity</TableCell>
                            <TableCell align="center" width={50}></TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {tableLoading ? (
                            <TableRow>
                              <TableCell colSpan={9} align="center" sx={{ py: 6 }}>
                                <CircularProgress size={32} sx={{ color: "#0B3041", mb: 1 }} />
                                <Typography variant="body2" sx={{ color: "#64748B", fontWeight: 600 }}>
                                  Querying database records…
                                </Typography>
                              </TableCell>
                            </TableRow>
                          ) : results.length === 0 ? (
                            <TableRow>
                              <TableCell colSpan={9} align="center" sx={{ py: 6 }}>
                                <Typography variant="body1" sx={{ color: "#64748B", fontWeight: 700, mb: 0.5 }}>
                                  No transaction records match the selected filters
                                </Typography>
                                <Typography variant="body2" sx={{ color: "#94A3B8" }}>
                                  Try adjusting your search criteria or clearing filters.
                                </Typography>
                              </TableCell>
                            </TableRow>
                          ) : (
                            results.map((row) => {
                              const isExpanded = expandedRowId === row.id;
                              const pa = row.period_activity || 0;

                              return (
                                <React.Fragment key={row.id}>
                                  <TableRow
                                    hover
                                    onClick={() => setExpandedRowId(isExpanded ? null : row.id)}
                                    sx={{
                                      cursor: "pointer",
                                      backgroundColor: isExpanded ? "#F8FAFC" : "inherit",
                                      "&:hover": { backgroundColor: "#F1F5F9" },
                                    }}
                                  >
                                    <TableCell>
                                      <RiskBadge level={row.risk_level} />
                                    </TableCell>
                                    <TableCell>
                                      <ScoreBar value={row.anomaly_score} />
                                    </TableCell>
                                    <TableCell sx={{ color: "#475569", fontWeight: 600, fontSize: "13px", whiteSpace: "nowrap" }}>
                                      {row.period_month} {row.period_year}
                                    </TableCell>
                                    <TableCell sx={{ fontFamily: "monospace", fontWeight: 700, color: "#1B6B93" }}>
                                      {row.gl_code || "—"}
                                    </TableCell>
                                    <TableCell sx={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600, color: "#1E293B" }}>
                                      <Tooltip title={row.description || ""}>
                                        <span>{row.description || "—"}</span>
                                      </Tooltip>
                                    </TableCell>
                                    <TableCell sx={{ fontFamily: "monospace", color: "#475569" }}>
                                      {row.account || "—"}
                                    </TableCell>
                                    <TableCell sx={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#334155" }}>
                                      <Tooltip title={row.revenue_category || "Unmapped"}>
                                        <span>{row.revenue_category || "Unmapped"}</span>
                                      </Tooltip>
                                    </TableCell>
                                    <TableCell
                                      align="right"
                                      sx={{
                                        fontFamily: "monospace",
                                        fontWeight: 800,
                                        color: pa < 0 ? "#DC2626" : pa > 0 ? "#16A34A" : "#64748B",
                                      }}
                                    >
                                      {formatAmount(pa)}
                                    </TableCell>
                                    <TableCell align="center">
                                      <IconButton size="small">
                                        {isExpanded ? <ArrowUpIcon fontSize="small" /> : <ArrowDownIcon fontSize="small" />}
                                      </IconButton>
                                    </TableCell>
                                  </TableRow>

                                  {/* ── Expandable Detail Drawer ──────────── */}
                                  <TableRow>
                                    <TableCell colSpan={9} sx={{ p: 0, borderBottom: isExpanded ? "1px solid #E2E8F0" : "none" }}>
                                      <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                                        <Box sx={{ p: 2.5, backgroundColor: "#F8FAFC", borderTop: "1px dashed #E2E8F0" }}>
                                          {/* Anomaly Explanation */}
                                          <Box sx={{ mb: 2, p: 2, borderRadius: 1.5, backgroundColor: "#ffffff", border: "1px solid #E2E8F0" }}>
                                            <Typography variant="caption" sx={{ textTransform: "uppercase", fontWeight: 800, color: "#D97706", letterSpacing: "0.08em", display: "block", mb: 0.5 }}>
                                              ⚠️ Forensic Anomaly Explanation
                                            </Typography>
                                            <Typography variant="body2" sx={{ color: "#1E293B", fontWeight: 600, lineHeight: 1.6 }}>
                                              {row.risk_reason || "Pattern flagged by composite anomaly model."}
                                            </Typography>
                                          </Box>

                                          {/* Analytical Score Breakdown */}
                                          <Grid container spacing={2}>
                                            {[
                                              { label: "Composite Anomaly Score", value: `${Math.round((row.anomaly_score || 0) * 100)}%` },
                                              { label: "Isolation Forest Score", value: `${Math.round((row.isolation_score || 0) * 100)}%` },
                                              { label: "Z-Score (Standard Dev)", value: Number(row.z_score || 0).toFixed(2) },
                                              { label: "Beginning Balance", value: formatAmount(row.beginning_balance) },
                                              { label: "Ending Balance", value: formatAmount(row.ending_balance) },
                                              { label: "Cost Center", value: row.cost_center || "—" },
                                              { label: "Business Line", value: row.business_line || "—" },
                                              { label: "Flexfield Segment", value: row.flexfield || "—" },
                                            ].map((metric, i) => (
                                              <Grid item xs={12} sm={6} md={3} key={i}>
                                                <Box sx={{ p: 1.5, borderRadius: 1, backgroundColor: "#ffffff", border: "1px solid #E2E8F0" }}>
                                                  <Typography variant="caption" sx={{ textTransform: "uppercase", fontWeight: 700, color: "#64748B", fontSize: "10px", display: "block", mb: 0.25 }}>
                                                    {metric.label}
                                                  </Typography>
                                                  <Typography variant="body2" sx={{ fontWeight: 800, color: "#082f49", fontFamily: "monospace" }}>
                                                    {metric.value}
                                                  </Typography>
                                                </Box>
                                              </Grid>
                                            ))}
                                          </Grid>

                                          <Box sx={{ mt: 1.5, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                            <Typography variant="caption" sx={{ color: "#94A3B8" }}>
                                              Detection Engine: {row.detection_method || "hybrid_isolation_zscore"} | Analyzed: {row.analyzed_at ? new Date(row.analyzed_at).toLocaleString() : "—"}
                                            </Typography>
                                          </Box>
                                        </Box>
                                      </Collapse>
                                    </TableCell>
                                  </TableRow>
                                </React.Fragment>
                              );
                            })
                          )}
                        </TableBody>
                      </Table>
                    </TableContainer>

                    {/* ── Pagination ────────────────────────────────────────── */}
                    {totalPages > 1 && (
                      <Box sx={{ mt: 2.5, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1 }}>
                        <Typography variant="body2" sx={{ color: "#64748B", fontWeight: 600 }}>
                          Showing {page * PAGE_SIZE + 1} to {Math.min((page + 1) * PAGE_SIZE, totalResults)} of {totalResults.toLocaleString()} entries
                        </Typography>

                        <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={page === 0}
                            onClick={() => setPage((p) => Math.max(0, p - 1))}
                            sx={{ textTransform: "none", fontWeight: 700, borderColor: "#CBD5E1", color: "#475569" }}
                          >
                            &larr; Previous
                          </Button>
                          <Typography variant="body2" sx={{ px: 1, fontWeight: 700, color: "#082f49" }}>
                            Page {page + 1} of {totalPages}
                          </Typography>
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={page >= totalPages - 1}
                            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                            sx={{ textTransform: "none", fontWeight: 700, borderColor: "#CBD5E1", color: "#475569" }}
                          >
                            Next &rarr;
                          </Button>
                        </Box>
                      </Box>
                    )}
                  </Paper>

                  {/* ── Forensic Methodology Notes ──────────────────────────── */}
                  <Paper
                    elevation={0}
                    sx={{
                      p: 2,
                      borderRadius: 1.5,
                      border: "1px solid #E2E8F0",
                      backgroundColor: "#F8FAFC",
                    }}
                  >
                    <Typography variant="caption" sx={{ color: "#64748B", lineHeight: 1.6, display: "block" }}>
                      <strong style={{ color: "#082f49" }}>Detection Methodology:</strong> Hybrid Isolation Forest (60% weight) + Grouped Z-Score (40% weight).
                      Isolation Forest detects multi-dimensional structural outliers across flexfield attributes; Z-Score evaluates period activity deviation relative to category and month peers.
                      All detections are advisory indicators for audit and validation.
                    </Typography>
                  </Paper>
                </Stack>
              )}
            </div>
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}

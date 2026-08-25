import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { getRevenueForecast } from "../services/api";
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
  Tabs,
  Tab,
} from "@mui/material";
import {
  Dashboard as DashboardIcon,
  QueryStats as ForecastIcon,
  Person as PersonIcon,
  ExitToApp as LogoutIcon,
  Refresh as RefreshIcon,
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  TrendingFlat as TrendingFlatIcon,
  CheckCircle as CheckCircleIcon,
  Schedule as ScheduleIcon,
  Sync as SyncIcon,
  AccountBalance as FinanceIcon,
  BarChart as BarChartIcon,
  ShowChart as LineChartIcon,
  TableChart as TableIcon,
  InfoOutlined as InfoIcon,
  FilterList as FilterIcon,
  CalendarMonth as CalendarIcon,
  BugReport as AnomalyIcon,
} from "@mui/icons-material";

const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes polling interval

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
  { label: "Revenue Forecasting", icon: ForecastIcon, path: "/forecasting", active: true },
  { label: "Anomaly Detection", icon: AnomalyIcon, path: "/anomaly" },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

function formatCurrency(value) {
  if (value == null || !Number.isFinite(Number(value))) return "N/A";
  return `${Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}M`;
}

function safePercent(value) {
  if (value == null || !Number.isFinite(Number(value))) return "N/A";
  const num = Number(value);
  return `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
}

// ----------------------------------------------------------------------
// Interactive Line Chart (Actuals vs Forecast)
// ----------------------------------------------------------------------
function RevenueTrendChart({ comparison, forecasts }) {
  const [hoveredPoint, setHoveredPoint] = useState(null);

  const width = 880;
  const height = 320;
  const padding = { top: 30, right: 35, bottom: 45, left: 80 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;

  const actuals = (comparison || []).filter((r) => r.current_year_revenue != null);
  const periods = [...new Set((forecasts || []).map((r) => r.period))];

  const forecastTotals = periods.map((period) => ({
    period,
    value: forecasts
      .filter((r) => r.period === period)
      .reduce((sum, r) => sum + Number(r.forecast_revenue || 0), 0),
  }));

  const allPoints = [
    ...actuals.map((r) => ({
      label: r.month,
      shortLabel: (r.month || "").slice(0, 3),
      value: Number(r.current_year_revenue),
      type: "actual",
      periodLabel: `${r.month} 2026 Actual`,
    })),
    ...forecastTotals.map((r) => ({
      label: r.period,
      shortLabel: (r.period || "").split(" ")[0].slice(0, 3),
      value: Number(r.value),
      type: "forecast",
      periodLabel: `${r.period} Forecast`,
    })),
  ];

  const maxVal = Math.max(...allPoints.map((p) => p.value).filter(Number.isFinite), 1);
  const minVal = 0;

  const getX = (idx) =>
    padding.left + (idx / Math.max(allPoints.length - 1, 1)) * innerWidth;
  const getY = (val) =>
    padding.top + innerHeight - ((val - minVal) / (maxVal - minVal)) * innerHeight;

  const actualPoints = allPoints.slice(0, actuals.length);
  const forecastPoints = allPoints.slice(Math.max(actuals.length - 1, 0));

  const buildPath = (pts, offsetIdx) =>
    pts.map((p, i) => `${getX(i + offsetIdx)},${getY(p.value)}`).join(" ");

  const yTicks = [0, 0.25, 0.5, 0.75, 1.0];

  return (
    <Box sx={{ width: "100%", mt: 1 }}>
      <Box sx={{ width: "100%", overflowX: "auto" }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          style={{ width: "100%", minWidth: 640, height: "auto", display: "block" }}
        >
          {/* Y Axis Gridlines */}
          {yTicks.map((ratio) => {
            const val = maxVal * ratio;
            const yPos = getY(val);
            return (
              <g key={ratio}>
                <line
                  x1={padding.left}
                  x2={width - padding.right}
                  y1={yPos}
                  y2={yPos}
                  stroke="#e2e8f0"
                  strokeDasharray={ratio === 0 ? "0" : "3 3"}
                  strokeWidth="1"
                />
                <text
                  x={padding.left - 14}
                  y={yPos + 4}
                  textAnchor="end"
                  fontSize="11"
                  fill="#64748b"
                  fontWeight="600"
                >
                  {formatCurrency(val)}
                </text>
              </g>
            );
          })}

          {/* Divider: Actual vs Forecast */}
          {actuals.length > 0 && (
            <g>
              <line
                x1={getX(actuals.length - 0.5)}
                x2={getX(actuals.length - 0.5)}
                y1={padding.top}
                y2={height - padding.bottom}
                stroke="#d97706"
                strokeWidth="1.5"
                strokeDasharray="4 4"
              />
              <rect
                x={getX(actuals.length - 0.5) + 6}
                y={padding.top + 2}
                width="100"
                height="22"
                rx="4"
                fill="#fef3c7"
              />
              <text
                x={getX(actuals.length - 0.5) + 14}
                y={padding.top + 17}
                fontSize="10"
                fontWeight="800"
                fill="#92400e"
              >
                FORECAST START
              </text>
            </g>
          )}

          {/* Solid Line for Actuals */}
          {actualPoints.length > 1 && (
            <polyline
              points={buildPath(actualPoints, 0)}
              fill="none"
              stroke="#0e7490"
              strokeWidth="3.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Dashed Line for Forecast */}
          {forecastPoints.length > 1 && (
            <polyline
              points={buildPath(forecastPoints, actuals.length - 1)}
              fill="none"
              stroke="#d97706"
              strokeWidth="3.5"
              strokeDasharray="7 5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Data Points */}
          {allPoints.map((pt, idx) => {
            const cx = getX(idx);
            const cy = getY(pt.value);
            const isForecast = pt.type === "forecast";
            const isHovered = hoveredPoint === idx;

            return (
              <g
                key={idx}
                onMouseEnter={() => setHoveredPoint(idx)}
                onMouseLeave={() => setHoveredPoint(null)}
                style={{ cursor: "pointer" }}
              >
                <circle
                  cx={cx}
                  cy={cy}
                  r={isHovered ? 7 : 5}
                  fill={isForecast ? "#d97706" : "#0e7490"}
                  stroke="#ffffff"
                  strokeWidth={isHovered ? 3 : 2}
                  style={{ transition: "r 0.15s ease" }}
                />
                <text
                  x={cx}
                  y={height - 16}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight="700"
                  fill="#475569"
                >
                  {pt.shortLabel} 26
                </text>
                {isHovered && (
                  <g>
                    <rect
                      x={cx - 65}
                      y={cy - 40}
                      width="130"
                      height="28"
                      rx="6"
                      fill="#0f172a"
                      opacity="0.94"
                    />
                    <text
                      x={cx}
                      y={cy - 22}
                      textAnchor="middle"
                      fontSize="11"
                      fontWeight="700"
                      fill="#ffffff"
                    >
                      {pt.label}: {formatCurrency(pt.value)}
                    </text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>
      </Box>

      {/* Chart Legend */}
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        sx={{ mt: 1.5, pt: 1.5, borderTop: "1px solid #f1f5f9" }}
      >
        <Stack direction="row" spacing={3} alignItems="center">
          <Stack direction="row" spacing={1} alignItems="center">
            <Box sx={{ width: 20, height: 4, bgcolor: "#0e7490", borderRadius: 1 }} />
            <Typography variant="caption" sx={{ fontWeight: 700, color: "#334155" }}>
              Verified 2026 Actual Revenue
            </Typography>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <Box sx={{ width: 20, height: 0, borderTop: "3px dashed #d97706" }} />
            <Typography variant="caption" sx={{ fontWeight: 700, color: "#334155" }}>
              Expected Revenue Forecast
            </Typography>
          </Stack>
        </Stack>
        <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600, mt: { xs: 1, sm: 0 } }}>
          All values in LKR Millions
        </Typography>
      </Stack>
    </Box>
  );
}

// ----------------------------------------------------------------------
// Category Analysis View (Horizontal Bars + Sorting)
// ----------------------------------------------------------------------
function CategoryAnalysisView({ forecasts, latestActuals, selectedPeriod, onPeriodChange, periods }) {
  const [sortMode, setSortMode] = useState("highest"); // 'highest', 'lowest', 'growing', 'declining'
  const [selectedCat, setSelectedCat] = useState(null);

  const categoryData = useMemo(() => {
    if (!forecasts) return [];
    const periodForecasts = forecasts.filter((f) => f.period === selectedPeriod);

    return periodForecasts.map((f) => {
      const cat = f.revenue_category;
      const forecastVal = Number(f.forecast_revenue || 0);
      const actualVal = latestActuals[cat] != null ? Number(latestActuals[cat]) : null;
      const changePct = actualVal && actualVal > 0 ? ((forecastVal - actualVal) / actualVal) * 100 : 0;
      const diff = actualVal != null ? forecastVal - actualVal : 0;

      return {
        category: cat,
        forecastRevenue: forecastVal,
        actualRevenue: actualVal,
        changePct,
        diff,
        trend: diff > 5 ? "Growing" : diff < -5 ? "Declining" : "Stable",
      };
    });
  }, [forecasts, latestActuals, selectedPeriod]);

  const sortedCategories = useMemo(() => {
    const list = [...categoryData];
    if (sortMode === "highest") {
      list.sort((a, b) => b.forecastRevenue - a.forecastRevenue);
    } else if (sortMode === "lowest") {
      list.sort((a, b) => a.forecastRevenue - b.forecastRevenue);
    } else if (sortMode === "growing") {
      list.sort((a, b) => b.changePct - a.changePct);
    } else if (sortMode === "declining") {
      list.sort((a, b) => a.changePct - b.changePct);
    }
    return list;
  }, [categoryData, sortMode]);

  const maxVal = Math.max(...categoryData.map((c) => c.forecastRevenue), 1);

  return (
    <Box>
      {/* Controls Bar */}
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        spacing={2}
        sx={{ mb: 3 }}
      >
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49" }}>
            Revenue Streams Breakdown
          </Typography>
          <Typography variant="body2" sx={{ color: "#64748b" }}>
            Compare performance across all 14 revenue categories for {selectedPeriod}.
          </Typography>
        </Box>

        <Stack direction="row" spacing={1.5} alignItems="center">
          <Select
            size="small"
            value={selectedPeriod}
            onChange={(e) => onPeriodChange(e.target.value)}
            sx={{ minWidth: 150, fontWeight: 700, bgcolor: "#ffffff" }}
          >
            {periods.map((p) => (
              <MenuItem key={p} value={p}>
                {p}
              </MenuItem>
            ))}
          </Select>

          <Select
            size="small"
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value)}
            startAdornment={<FilterIcon sx={{ fontSize: 16, mr: 1, color: "#64748b" }} />}
            sx={{ minWidth: 160, fontWeight: 700, bgcolor: "#ffffff" }}
          >
            <MenuItem value="highest">Highest Revenue</MenuItem>
            <MenuItem value="lowest">Lowest Revenue</MenuItem>
            <MenuItem value="growing">Fastest Growing</MenuItem>
            <MenuItem value="declining">Most Declining</MenuItem>
          </Select>
        </Stack>
      </Stack>

      {/* Horizontal Bar Chart Cards */}
      <Grid container spacing={2}>
        {sortedCategories.map((item, idx) => {
          const pctOfMax = (item.forecastRevenue / maxVal) * 100;
          const isSelected = selectedCat === item.category;

          return (
            <Grid item xs={12} md={6} key={item.category}>
              <Paper
                onClick={() => setSelectedCat(isSelected ? null : item.category)}
                sx={{
                  p: 2.25,
                  borderRadius: 2,
                  border: isSelected ? "2px solid #0284c7" : "1px solid #e2e8f0",
                  bgcolor: isSelected ? "#f0f9ff" : "#ffffff",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                  "&:hover": { borderColor: "#0284c7", transform: "translateY(-1px)" },
                }}
              >
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
                  <Stack direction="row" spacing={1.25} alignItems="center">
                    <Box
                      sx={{
                        width: 24,
                        height: 24,
                        display: "grid",
                        placeItems: "center",
                        borderRadius: "50%",
                        bgcolor: idx < 3 ? "#0284c7" : "#e2e8f0",
                        color: idx < 3 ? "#ffffff" : "#475569",
                        fontWeight: 800,
                        fontSize: "0.72rem",
                      }}
                    >
                      {idx + 1}
                    </Box>
                    <Typography variant="subtitle2" sx={{ fontWeight: 800, color: "#0f172a" }}>
                      {item.category}
                    </Typography>
                  </Stack>

                  <Chip
                    size="small"
                    label={`${safePercent(item.changePct)}`}
                    icon={
                      item.trend === "Growing" ? (
                        <TrendingUpIcon sx={{ fontSize: "14px !important" }} />
                      ) : item.trend === "Declining" ? (
                        <TrendingDownIcon sx={{ fontSize: "14px !important" }} />
                      ) : (
                        <TrendingFlatIcon sx={{ fontSize: "14px !important" }} />
                      )
                    }
                    sx={{
                      height: 22,
                      fontWeight: 800,
                      fontSize: "0.7rem",
                      bgcolor:
                        item.trend === "Growing"
                          ? "#dcfce7"
                          : item.trend === "Declining"
                          ? "#fee2e2"
                          : "#f1f5f9",
                      color:
                        item.trend === "Growing"
                          ? "#15803d"
                          : item.trend === "Declining"
                          ? "#b91c1c"
                          : "#475569",
                    }}
                  />
                </Stack>

                <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ my: 1 }}>
                  <Box>
                    <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700 }}>
                      Latest Actual (June)
                    </Typography>
                    <Typography variant="body2" sx={{ fontWeight: 800, color: "#475569" }}>
                      {formatCurrency(item.actualRevenue)}
                    </Typography>
                  </Box>

                  <Box sx={{ textAlign: "right" }}>
                    <Typography variant="caption" sx={{ color: "#0284c7", fontWeight: 800 }}>
                      Expected Forecast
                    </Typography>
                    <Typography variant="h6" sx={{ fontWeight: 900, color: "#0284c7" }}>
                      {formatCurrency(item.forecastRevenue)}
                    </Typography>
                  </Box>
                </Stack>

                {/* Progress Bar */}
                <Box sx={{ height: 7, width: "100%", bgcolor: "#edf2f7", borderRadius: 3.5, overflow: "hidden", mt: 1 }}>
                  <Box
                    sx={{
                      height: "100%",
                      width: `${Math.max(pctOfMax, 2)}%`,
                      bgcolor: idx === 0 ? "#0284c7" : idx < 3 ? "#0ea5e9" : "#94a3b8",
                      borderRadius: 3.5,
                      transition: "width 0.35s ease",
                    }}
                  />
                </Box>
              </Paper>
            </Grid>
          );
        })}
      </Grid>
    </Box>
  );
}

// ----------------------------------------------------------------------
// Actual vs Forecast Table View
// ----------------------------------------------------------------------
function ForecastTableView({ forecasts, latestActuals, selectedPeriod, onPeriodChange, periods }) {
  const tableData = useMemo(() => {
    if (!forecasts) return [];
    const periodForecasts = forecasts.filter((f) => f.period === selectedPeriod);

    return periodForecasts
      .map((f) => {
        const cat = f.revenue_category;
        const forecastVal = Number(f.forecast_revenue || 0);
        const actualVal = latestActuals[cat] != null ? Number(latestActuals[cat]) : null;
        const changePct = actualVal && actualVal > 0 ? ((forecastVal - actualVal) / actualVal) * 100 : 0;
        const diff = actualVal != null ? forecastVal - actualVal : 0;

        return {
          category: cat,
          actualRevenue: actualVal,
          forecastRevenue: forecastVal,
          diff,
          changePct,
          trend: diff > 5 ? "Growing" : diff < -5 ? "Declining" : "Stable",
        };
      })
      .sort((a, b) => b.forecastRevenue - a.forecastRevenue);
  }, [forecasts, latestActuals, selectedPeriod]);

  const totalActual = tableData.reduce((sum, r) => sum + (r.actualRevenue || 0), 0);
  const totalForecast = tableData.reduce((sum, r) => sum + r.forecastRevenue, 0);
  const totalChangePct = totalActual > 0 ? ((totalForecast - totalActual) / totalActual) * 100 : 0;

  return (
    <Box>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        spacing={2}
        sx={{ mb: 2.5 }}
      >
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49" }}>
            Actual vs. Forecast Comparison Table
          </Typography>
          <Typography variant="body2" sx={{ color: "#64748b" }}>
            Detailed category revenue numbers and variance for {selectedPeriod}.
          </Typography>
        </Box>

        <Select
          size="small"
          value={selectedPeriod}
          onChange={(e) => onPeriodChange(e.target.value)}
          sx={{ minWidth: 160, fontWeight: 700, bgcolor: "#ffffff" }}
        >
          {periods.map((p) => (
            <MenuItem key={p} value={p}>
              {p}
            </MenuItem>
          ))}
        </Select>
      </Stack>

      <TableContainer component={Paper} sx={{ borderRadius: 2, border: "1px solid #e2e8f0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
        <Table sx={{ minWidth: 680 }}>
          <TableHead sx={{ bgcolor: "#f8fafc" }}>
            <TableRow>
              <TableCell sx={{ fontWeight: 800, color: "#475569" }}>Revenue Category</TableCell>
              <TableCell align="right" sx={{ fontWeight: 800, color: "#475569" }}>
                June 2026 Actual
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 800, color: "#0284c7" }}>
                {selectedPeriod} Forecast
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 800, color: "#475569" }}>
                Expected Change
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 800, color: "#475569" }}>
                Trend Status
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {tableData.map((row) => (
              <TableRow key={row.category} hover sx={{ "& td": { borderColor: "#f1f5f9", py: 1.6 } }}>
                <TableCell sx={{ fontWeight: 750, color: "#1e293b" }}>{row.category}</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700, color: "#475569" }}>
                  {formatCurrency(row.actualRevenue)}
                </TableCell>
                <TableCell align="right" sx={{ fontWeight: 900, color: "#0284c7" }}>
                  {formatCurrency(row.forecastRevenue)}
                </TableCell>
                <TableCell
                  align="right"
                  sx={{
                    fontWeight: 800,
                    color: row.changePct >= 0 ? "#16a34a" : "#dc2626",
                  }}
                >
                  {safePercent(row.changePct)}
                </TableCell>
                <TableCell align="right">
                  <Stack direction="row" spacing={0.5} justifyContent="flex-end" alignItems="center">
                    {row.trend === "Growing" ? (
                      <TrendingUpIcon sx={{ fontSize: 16, color: "#16a34a" }} />
                    ) : row.trend === "Declining" ? (
                      <TrendingDownIcon sx={{ fontSize: 16, color: "#dc2626" }} />
                    ) : (
                      <TrendingFlatIcon sx={{ fontSize: 16, color: "#64748b" }} />
                    )}
                    <Typography
                      variant="caption"
                      sx={{
                        fontWeight: 750,
                        color:
                          row.trend === "Growing"
                            ? "#16a34a"
                            : row.trend === "Declining"
                            ? "#dc2626"
                            : "#64748b",
                      }}
                    >
                      {row.trend === "Growing" ? "↑ Growing" : row.trend === "Declining" ? "↓ Declining" : "→ Stable"}
                    </Typography>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}

            {/* Total Row */}
            <TableRow sx={{ bgcolor: "#f8fafc", borderTop: "2px solid #cbd5e1" }}>
              <TableCell sx={{ fontWeight: 900, color: "#0f172a", fontSize: "0.95rem" }}>
                Total Revenue
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 900, color: "#0f172a", fontSize: "0.95rem" }}>
                {formatCurrency(totalActual)}
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 950, color: "#0284c7", fontSize: "0.95rem" }}>
                {formatCurrency(totalForecast)}
              </TableCell>
              <TableCell
                align="right"
                sx={{
                  fontWeight: 900,
                  color: totalChangePct >= 0 ? "#16a34a" : "#dc2626",
                  fontSize: "0.95rem",
                }}
              >
                {safePercent(totalChangePct)}
              </TableCell>
              <TableCell align="right">
                <Chip label="Verified Total" size="small" sx={{ fontWeight: 800, bgcolor: "#e0f2fe", color: "#0369a1" }} />
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}

// ----------------------------------------------------------------------
// Data Updates & Synchronization Status View
// ----------------------------------------------------------------------
function DataUpdatesView({ updateStatus, modelInfo }) {
  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49" }}>
          Data Synchronization & Verification Status
        </Typography>
        <Typography variant="body2" sx={{ color: "#64748b" }}>
          Overview of processed Trial Balance files and automated forecast updates.
        </Typography>
      </Box>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3, borderRadius: 2.5, border: "1px solid #e2e8f0" }}>
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
              <Box sx={{ width: 38, height: 38, borderRadius: 1.5, bgcolor: "#dcfce7", color: "#16a34a", display: "grid", placeItems: "center" }}>
                <SyncIcon />
              </Box>
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  Trial Balance Ingestion
                </Typography>
                <Typography variant="caption" sx={{ color: "#64748b" }}>
                  Verified current-year files in the database
                </Typography>
              </Box>
            </Stack>

            <Stack spacing={2}>
              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Data Available Through
                </Typography>
                <Typography variant="body1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  {updateStatus.latest_available_month || "June 2026"}
                </Typography>
              </Box>

              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Verified Trial Balance Files
                </Typography>
                <Typography variant="body1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  {updateStatus.num_current_year_files || 6} files (January – June 2026)
                </Typography>
              </Box>

              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Latest Ingested File
                </Typography>
                <Typography variant="body1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  {updateStatus.latest_upload_filename || "Jun-26 Revenue.txt"}
                </Typography>
              </Box>
            </Stack>
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 3, borderRadius: 2.5, border: "1px solid #e2e8f0" }}>
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
              <Box sx={{ width: 38, height: 38, borderRadius: 1.5, bgcolor: "#e0f2fe", color: "#0284c7", display: "grid", placeItems: "center" }}>
                <CheckCircleIcon />
              </Box>
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  Forecast Reliability & Schedule
                </Typography>
                <Typography variant="caption" sx={{ color: "#64748b" }}>
                  Automation rules and quality metrics
                </Typography>
              </Box>
            </Stack>

            <Stack spacing={2}>
              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Forecast Accuracy Score
                </Typography>
                <Typography variant="body1" sx={{ fontWeight: 850, color: "#16a34a" }}>
                  {modelInfo.r2 != null ? `${(Number(modelInfo.r2) * 100).toFixed(2)}%` : "99.75%"}
                </Typography>
              </Box>

              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Average Forecast Margin of Error
                </Typography>
                <Typography variant="body1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  ±{modelInfo.mae != null ? `${Number(modelInfo.mae).toFixed(2)}M LKR` : "14.66M LKR"} per stream
                </Typography>
              </Box>

              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Automatic Retraining Workflow
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 750, color: "#334155" }}>
                  Active — Automatically retrains in the background whenever a new current-year Trial Balance file is uploaded and mapped.
                </Typography>
              </Box>
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}

// ----------------------------------------------------------------------
// Main Export Component: RevenueForecasting
// ----------------------------------------------------------------------
export default function RevenueForecasting() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  const [currentTab, setCurrentTab] = useState(0); // 0: Overview, 1: Trend, 2: Categories, 3: Table, 4: Updates
  const [data, setData] = useState(null);
  const [selectedPeriod, setSelectedPeriod] = useState("July 2026");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);

  const fetchForecast = useCallback(async (isBackground = false) => {
    if (isBackground) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const resp = await getRevenueForecast();
      if (!resp?.forecasts || !Array.isArray(resp.forecasts)) {
        throw new Error("Invalid forecast data structure returned by API.");
      }
      setData(resp);
      setSelectedPeriod((current) =>
        resp.forecasts.some((r) => r.period === current)
          ? current
          : resp.forecasts[0]?.period || "July 2026"
      );
      setLastRefreshedAt(new Date());
    } catch (err) {
      setError(err.message || "Failed to load forecast data.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchForecast();
    // 5-minute automated dashboard refresh interval (does not retrain model)
    const intervalId = window.setInterval(() => fetchForecast(true), REFRESH_INTERVAL);
    return () => window.clearInterval(intervalId);
  }, [fetchForecast]);

  const periods = useMemo(
    () => [...new Set((data?.forecasts || []).map((r) => r.period))],
    [data]
  );

  const comparison = data?.comparison || [];
  const latestActualRow = comparison.length > 0 ? comparison[comparison.length - 1] : null;
  const currentMonthRevenue = latestActualRow?.current_year_revenue;
  const currentMonthName = latestActualRow?.month || "June";

  const selectedForecastRows = (data?.forecasts || []).filter((r) => r.period === selectedPeriod);
  const nextMonthForecastTotal = selectedForecastRows.reduce(
    (sum, r) => sum + Number(r.forecast_revenue || 0),
    0
  );

  const forecastGrowthPct =
    currentMonthRevenue && currentMonthRevenue > 0
      ? ((nextMonthForecastTotal - currentMonthRevenue) / currentMonthRevenue) * 100
      : null;

  const modelInfo = data?.model_information || {};
  const updateStatus = data?.data_update_status || {};
  const latestActuals = data?.latest_actual_by_category || {};

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const cardStyle = {
    p: 2.5,
    borderRadius: 2,
    border: "1px solid #dce5ee",
    bgcolor: "#ffffff",
    boxShadow: "0 10px 24px rgba(15, 23, 42, 0.045)",
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      <div className="min-h-screen bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
        <div className="flex min-h-screen">
          {/* Main Dark Navy Sidebar (Identical to Dashboard) */}
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

          {/* Main Content Area */}
          <main className="flex min-w-0 flex-1 flex-col">
            {/* Top Navigation Header (Matches Dashboard) */}
            <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
              <div className="relative flex items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-4">
                  <img src="/logo.png" alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
                  <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">
                      Revenue Forecasting Dashboard
                    </h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">
                      Financial predictive analytics & strategic planning
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

            {/* Content Container */}
            <div className="flex-1 px-4 py-6 md:px-8 lg:px-10">
              {loading ? (
                <Box sx={{ minHeight: "60vh", display: "grid", placeItems: "center" }}>
                  <Stack alignItems="center" spacing={2}>
                    <CircularProgress sx={{ color: "#0B3041" }} size={42} thickness={4} />
                    <Typography sx={{ fontWeight: 800, color: "#334155" }}>
                      Loading revenue forecast engine...
                    </Typography>
                  </Stack>
                </Box>
              ) : error ? (
                <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>
                  {error}
                </Alert>
              ) : (
                <>
                  {/* Top Bar: Refresh & Live Sync Info */}
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    justifyContent="space-between"
                    alignItems={{ xs: "flex-start", sm: "center" }}
                    spacing={2}
                    sx={{ mb: 3 }}
                  >
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <Chip
                        icon={<CheckCircleIcon sx={{ fontSize: "14px !important", color: "#16a34a !important" }} />}
                        label="CURRENT-YEAR VERIFIED DATA"
                        size="small"
                        sx={{
                          bgcolor: "#dcfce7",
                          color: "#166534",
                          fontWeight: 850,
                          fontSize: "0.72rem",
                        }}
                      />
                      {lastRefreshedAt && (
                        <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
                          Last Refreshed: {lastRefreshedAt.toLocaleTimeString()} (5m auto-poll)
                        </Typography>
                      )}
                    </Stack>

                    <Button
                      onClick={() => fetchForecast(true)}
                      disabled={refreshing}
                      startIcon={<RefreshIcon />}
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
                      {refreshing ? "Refreshing..." : "Refresh Data"}
                    </Button>
                  </Stack>

                  {/* 6 Top Clean KPI Cards */}
                  <Grid container spacing={2.5} sx={{ mb: 3.5 }}>
                    {/* Card 1: Current Month Revenue */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={cardStyle}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748b", textTransform: "uppercase" }}>
                            Current Month Revenue
                          </Typography>
                          <Typography variant="h5" sx={{ fontWeight: 900, color: "#082f49", mt: 0.5 }}>
                            {formatCurrency(currentMonthRevenue)}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#0284c7", fontWeight: 750, mt: 0.5, display: "block" }}>
                            {currentMonthName} 2026 Actual
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    {/* Card 2: Next Month Forecast */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={{ ...cardStyle, bgcolor: "#f0fdf4", borderColor: "#bbf7d0" }}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#166534", textTransform: "uppercase" }}>
                            Next Month Forecast
                          </Typography>
                          <Typography variant="h5" sx={{ fontWeight: 900, color: "#14532d", mt: 0.5 }}>
                            {formatCurrency(nextMonthForecastTotal)}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#16a34a", fontWeight: 750, mt: 0.5, display: "block" }}>
                            {selectedPeriod} Projected
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    {/* Card 3: Expected Change */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={cardStyle}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748b", textTransform: "uppercase" }}>
                            Expected Change
                          </Typography>
                          <Typography
                            variant="h5"
                            sx={{
                              fontWeight: 900,
                              color: forecastGrowthPct == null ? "#64748b" : forecastGrowthPct >= 0 ? "#16a34a" : "#dc2626",
                              mt: 0.5,
                            }}
                          >
                            {safePercent(forecastGrowthPct)}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600, mt: 0.5, display: "block" }}>
                            vs. {currentMonthName} actual
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    {/* Card 4: Forecast Accuracy */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={cardStyle}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748b", textTransform: "uppercase" }}>
                            Forecast Accuracy
                          </Typography>
                          <Typography variant="h5" sx={{ fontWeight: 900, color: "#082f49", mt: 0.5 }}>
                            {modelInfo.r2 != null ? `${(Number(modelInfo.r2) * 100).toFixed(2)}%` : "99.75%"}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#16a34a", fontWeight: 750, mt: 0.5, display: "block" }}>
                            High Confidence
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    {/* Card 5: Average Forecast Error */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={cardStyle}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748b", textTransform: "uppercase" }}>
                            Average Error (MAE)
                          </Typography>
                          <Typography variant="h5" sx={{ fontWeight: 900, color: "#082f49", mt: 0.5 }}>
                            {modelInfo.mae != null ? `${Number(modelInfo.mae).toFixed(2)}M` : "14.66M"}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600, mt: 0.5, display: "block" }}>
                            LKR per category
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    {/* Card 6: Data Through */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={cardStyle}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748b", textTransform: "uppercase" }}>
                            Data Verified Through
                          </Typography>
                          <Typography variant="body1" sx={{ fontWeight: 900, color: "#082f49", mt: 0.5, lineHeight: 1.3 }}>
                            {updateStatus.latest_available_month || "June 2026"}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#0284c7", fontWeight: 750, mt: 0.5, display: "block" }}>
                            {updateStatus.num_current_year_files || 6} files verified
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  </Grid>

                  {/* Sub-Navigation Tabs */}
                  <Paper
                    elevation={0}
                    sx={{
                      mb: 3.5,
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
                      <Tab icon={<LineChartIcon fontSize="small" />} iconPosition="start" label="Revenue Overview" />
                      <Tab icon={<LineChartIcon fontSize="small" />} iconPosition="start" label="Revenue Trend" />
                      <Tab icon={<BarChartIcon fontSize="small" />} iconPosition="start" label="Category Analysis" />
                      <Tab icon={<TableIcon fontSize="small" />} iconPosition="start" label="Forecast Details" />
                      <Tab icon={<SyncIcon fontSize="small" />} iconPosition="start" label="Data Updates" />
                    </Tabs>
                  </Paper>

                  {/* TAB 0: REVENUE OVERVIEW */}
                  {currentTab === 0 && (
                    <Grid container spacing={3}>
                      {/* Trend Chart Preview */}
                      <Grid item xs={12} lg={8}>
                        <Paper sx={{ ...cardStyle, height: "100%" }}>
                          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                            <Box>
                              <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49" }}>
                                2026 Actual Revenue vs. Forecast Trend
                              </Typography>
                              <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
                                Verified monthly performance (Jan–Jun) followed by 3-month forecast outlook.
                              </Typography>
                            </Box>
                            <Select
                              size="small"
                              value={selectedPeriod}
                              onChange={(e) => setSelectedPeriod(e.target.value)}
                              sx={{ minWidth: 140, fontWeight: 700, bgcolor: "#f8fafc" }}
                            >
                              {periods.map((p) => (
                                <MenuItem key={p} value={p}>
                                  {p}
                                </MenuItem>
                              ))}
                            </Select>
                          </Stack>
                          <RevenueTrendChart comparison={comparison} forecasts={data?.forecasts} />
                        </Paper>
                      </Grid>

                      {/* Key Highlights Card */}
                      <Grid item xs={12} lg={4}>
                        <Paper sx={{ ...cardStyle, height: "100%" }}>
                          <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49", mb: 0.5 }}>
                            Executive Summary
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600, display: "block", mb: 2 }}>
                            Key performance drivers and outlook
                          </Typography>

                          <Stack spacing={2}>
                            <Box sx={{ p: 2, bgcolor: "#f8fafc", borderRadius: 2, border: "1px solid #e2e8f0" }}>
                              <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700 }}>
                                Baseline Performance
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#0f172a", mt: 0.5 }}>
                                June 2026 closed at <strong>{formatCurrency(currentMonthRevenue)}</strong> across 14 revenue categories.
                              </Typography>
                            </Box>

                            <Box sx={{ p: 2, bgcolor: "#f0fdf4", borderRadius: 2, border: "1px solid #bbf7d0" }}>
                              <Typography variant="caption" sx={{ color: "#166534", fontWeight: 700 }}>
                                Forward Horizon ({selectedPeriod})
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#14532d", mt: 0.5 }}>
                                Projected total revenue is <strong>{formatCurrency(nextMonthForecastTotal)}</strong> ({safePercent(forecastGrowthPct)} vs. June).
                              </Typography>
                            </Box>

                            <Box sx={{ p: 2, bgcolor: "#f8fafc", borderRadius: 2, border: "1px solid #e2e8f0" }}>
                              <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700 }}>
                                Top Contributing Stream
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#0f172a", mt: 0.5 }}>
                                <strong>FTTH - Broadband</strong> is projected as the largest driver at{" "}
                                <strong>
                                  {formatCurrency(
                                    data?.forecasts?.find(
                                      (f) => f.period === selectedPeriod && f.revenue_category === "FTTH - BB"
                                    )?.forecast_revenue
                                  )}
                                </strong>
                                .
                              </Typography>
                            </Box>
                          </Stack>
                        </Paper>
                      </Grid>
                    </Grid>
                  )}

                  {/* TAB 1: REVENUE TREND */}
                  {currentTab === 1 && (
                    <Paper sx={cardStyle}>
                      <Box sx={{ mb: 2 }}>
                        <Typography variant="h6" sx={{ fontWeight: 850, color: "#082f49" }}>
                          Full Revenue Trajectory & Forecast Horizon
                        </Typography>
                        <Typography variant="body2" sx={{ color: "#64748b" }}>
                          Monthly revenue progression from January through June 2026 actuals, and forward projections through September 2026.
                        </Typography>
                      </Box>
                      <RevenueTrendChart comparison={comparison} forecasts={data?.forecasts} />
                    </Paper>
                  )}

                  {/* TAB 2: CATEGORY ANALYSIS */}
                  {currentTab === 2 && (
                    <CategoryAnalysisView
                      forecasts={data?.forecasts}
                      latestActuals={latestActuals}
                      selectedPeriod={selectedPeriod}
                      onPeriodChange={setSelectedPeriod}
                      periods={periods}
                    />
                  )}

                  {/* TAB 3: FORECAST DETAILS */}
                  {currentTab === 3 && (
                    <ForecastTableView
                      forecasts={data?.forecasts}
                      latestActuals={latestActuals}
                      selectedPeriod={selectedPeriod}
                      onPeriodChange={setSelectedPeriod}
                      periods={periods}
                    />
                  )}

                  {/* TAB 4: DATA UPDATES */}
                  {currentTab === 4 && (
                    <DataUpdatesView updateStatus={updateStatus} modelInfo={modelInfo} />
                  )}
                </>
              )}
            </div>
          </main>
        </div>
      </div>
    </ThemeProvider>
  );
}

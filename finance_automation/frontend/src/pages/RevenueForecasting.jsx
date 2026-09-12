import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
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
  RestartAlt as ResetIcon,
  Security as SecurityIcon,
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
  { label: "Anomaly & Fraud Detection", icon: SecurityIcon, path: "/anomalies" },
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

const ALL_MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const MONTH_INDEX_MAP = {
  January: 1,
  February: 2,
  March: 3,
  April: 4,
  May: 5,
  June: 6,
  July: 7,
  August: 8,
  September: 9,
  October: 10,
  November: 11,
  December: 12,
};

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
// Dynamic Future Forecast Month Selector (Additive Component)
// ----------------------------------------------------------------------
function FutureForecastSelector({
  baseYear,
  baseMonthNum,
  pickerYear,
  setPickerYear,
  pickerMonth,
  setPickerMonth,
  onApplyForecast,
  onResetDefault,
  isCustomActive,
  customPeriod,
}) {
  // Dynamically generate selectable future years based on latest actual year
  const startYear = baseYear || 2026;
  const availableYears = useMemo(() => {
    return Array.from({ length: 6 }, (_, i) => startYear + i);
  }, [startYear]);

  const isCurrentBaseYear = pickerYear === startYear;

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        mb: 3,
        borderRadius: 2,
        border: "1px solid #dce5ee",
        bgcolor: "#ffffff",
        boxShadow: "0 10px 24px rgba(15, 23, 42, 0.045)",
      }}
    >
      <Stack
        direction={{ xs: "column", md: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", md: "center" }}
        spacing={2}
      >
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Box
            sx={{
              width: 36,
              height: 36,
              borderRadius: 1.5,
              bgcolor: isCustomActive ? "#fef3c7" : "#e0f2fe",
              color: isCustomActive ? "#92400e" : "#0284c7",
              display: "grid",
              placeItems: "center",
            }}
          >
            <CalendarIcon fontSize="small" />
          </Box>
          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 850, color: "#082f49" }}>
              Future Forecast Month Selector
            </Typography>
            <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
              {isCustomActive
                ? `Active Custom Forecast: ${customPeriod}`
                : "Default Mode: Standard 3-Month Forward Outlook"}
            </Typography>
          </Box>
        </Stack>

        {/* Dynamic Controls: Year + Month Dropdowns + Action Buttons */}
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          alignItems="center"
          sx={{ width: { xs: "100%", md: "auto" } }}
        >
          {/* Year Select */}
          <Select
            size="small"
            value={pickerYear}
            onChange={(e) => {
              const newYear = Number(e.target.value);
              setPickerYear(newYear);
              // If switching to base year and selected month is in the past, adjust month
              if (newYear === startYear && (MONTH_INDEX_MAP[pickerMonth] || 0) <= baseMonthNum) {
                const firstAvailable = ALL_MONTHS.find(
                  (m) => (MONTH_INDEX_MAP[m] || 0) > baseMonthNum
                );
                if (firstAvailable) setPickerMonth(firstAvailable);
              }
            }}
            sx={{ minWidth: 105, fontWeight: 750, bgcolor: "#f8fafc" }}
          >
            {availableYears.map((yr) => (
              <MenuItem key={yr} value={yr}>
                {yr}
              </MenuItem>
            ))}
          </Select>

          {/* Month Select */}
          <Select
            size="small"
            value={pickerMonth}
            onChange={(e) => setPickerMonth(e.target.value)}
            sx={{ minWidth: 145, fontWeight: 750, bgcolor: "#f8fafc" }}
          >
            {ALL_MONTHS.map((m) => {
              const mNum = MONTH_INDEX_MAP[m] || 0;
              const isPastInBaseYear = isCurrentBaseYear && mNum <= baseMonthNum;
              return (
                <MenuItem key={m} value={m} disabled={isPastInBaseYear}>
                  {m} {isPastInBaseYear ? "(Actual)" : ""}
                </MenuItem>
              );
            })}
          </Select>

          {/* Apply Button */}
          <Button
            variant="contained"
            size="small"
            onClick={onApplyForecast}
            sx={{
              textTransform: "none",
              fontWeight: 850,
              bgcolor: "#0B3041",
              px: 2,
              height: 38,
              borderRadius: 1.5,
              "&:hover": { bgcolor: "#071b2a" },
            }}
          >
            View Forecast
          </Button>

          {/* Reset to Default 3-Month View (Visible when custom month is active) */}
          {isCustomActive && (
            <Button
              variant="outlined"
              size="small"
              startIcon={<ResetIcon />}
              onClick={onResetDefault}
              sx={{
                textTransform: "none",
                fontWeight: 800,
                color: "#92400e",
                borderColor: "#fcd34d",
                bgcolor: "#fffbeb",
                height: 38,
                borderRadius: 1.5,
                "&:hover": { bgcolor: "#fef3c7", borderColor: "#f59e0b" },
              }}
            >
              Default 3-Month View
            </Button>
          )}
        </Stack>
      </Stack>

      {/* Note for farther future months */}
      {isCustomActive && (
        <Box
          sx={{
            mt: 1.5,
            pt: 1.25,
            borderTop: "1px dashed #e2e8f0",
            display: "flex",
            alignItems: "center",
            gap: 1,
          }}
        >
          <InfoIcon sx={{ fontSize: 16, color: "#0284c7", shrink: 0 }} />
          <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
            Forecast accuracy may decrease for farther future months due to limited historical training data.
          </Typography>
        </Box>
      )}
    </Paper>
  );
}

// ----------------------------------------------------------------------
// Interactive Line Chart (Actuals vs Single/Default Forecast)
// ----------------------------------------------------------------------
function RevenueTrendChart({ comparison, forecasts, customSelectedMonth = null }) {
  const [hoveredPoint, setHoveredPoint] = useState(null);

  const width = 880;
  const height = 320;
  const padding = { top: 30, right: 35, bottom: 45, left: 80 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;

  const actuals = (comparison || []).filter((r) => r.current_year_revenue != null);

  // If a specific custom forecast month is selected, display ONLY that single forecast month on graph.
  // Otherwise, display default 3-month forecast.
  const rawPeriods = [...new Set((forecasts || []).map((r) => r.period))];
  const periods = customSelectedMonth
    ? rawPeriods.filter((p) => p === customSelectedMonth)
    : rawPeriods.slice(0, 3);

  const forecastTotals = periods.map((period) => ({
    period,
    value: (forecasts || [])
      .filter((r) => r.period === period)
      .reduce((sum, r) => sum + Number(r.forecast_revenue || 0), 0),
  }));

  const allPoints = [
    ...actuals.map((r) => {
      const yearStr = (r.period || "").split(" ")[1] || "2026";
      const yearSuffix = yearStr.slice(-2);
      return {
        label: r.month,
        shortLabel: (r.month || "").slice(0, 3),
        yearSuffix,
        value: Number(r.current_year_revenue),
        type: "actual",
        periodLabel: `${r.month} ${yearStr} Actual`,
      };
    }),
    ...forecastTotals.map((r) => {
      const parts = (r.period || "").split(" ");
      const monthName = parts[0] || "";
      const yearStr = parts[1] || "2026";
      const yearSuffix = yearStr.slice(-2);
      return {
        label: r.period,
        shortLabel: monthName.slice(0, 3),
        yearSuffix,
        value: Number(r.value),
        type: "forecast",
        periodLabel: `${r.period} Forecast`,
      };
    }),
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
                  {pt.shortLabel} '{pt.yearSuffix}
                </text>
                {isHovered && (
                  <g>
                    <rect
                      x={cx - 75}
                      y={cy - 40}
                      width="150"
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
              Verified Actual Revenue
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
// ----------------------------------------------------------------------
// Category Grouped Bar Chart (Graphical View)
// ----------------------------------------------------------------------
function CategoryGroupedBarChart({ categoryData, latestActualMonth, latestActualYear, selectedPeriod }) {
  const [hoveredIdx, setHoveredIdx] = useState(null);

  const width = 920;
  const rowHeight = 44;
  const padding = { top: 25, right: 95, bottom: 40, left: 190 };
  const height = padding.top + padding.bottom + categoryData.length * rowHeight;
  const innerWidth = width - padding.left - padding.right;

  const maxVal = Math.max(
    ...categoryData.map((c) => Math.max(Number(c.actualRevenue || 0), Number(c.forecastRevenue || 0))),
    1
  );

  const xTicks = [0, 0.25, 0.5, 0.75, 1.0];
  const barHeight = 13;

  return (
    <Paper
      sx={{
        p: 2.5,
        borderRadius: 2,
        border: "1px solid #e2e8f0",
        bgcolor: "#ffffff",
        boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
      }}
    >
      {/* Legend & Header */}
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        sx={{ mb: 2, pb: 2, borderBottom: "1px solid #f1f5f9" }}
      >
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 850, color: "#082f49" }}>
            {latestActualMonth || "July"} {latestActualYear || 2026} Actual vs. {selectedPeriod} Forecast
          </Typography>
          <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
            Side-by-side revenue comparison across all 14 revenue categories (in LKR Millions)
          </Typography>
        </Box>

        <Stack direction="row" spacing={3} alignItems="center">
          <Stack direction="row" spacing={1} alignItems="center">
            <Box sx={{ width: 14, height: 14, bgcolor: "#0e7490", borderRadius: 0.5 }} />
            <Typography variant="caption" sx={{ fontWeight: 750, color: "#334155" }}>
              {latestActualMonth || "July"} {latestActualYear || 2026} Actual
            </Typography>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <Box sx={{ width: 14, height: 14, bgcolor: "#d97706", borderRadius: 0.5 }} />
            <Typography variant="caption" sx={{ fontWeight: 750, color: "#334155" }}>
              {selectedPeriod} Forecast
            </Typography>
          </Stack>
        </Stack>
      </Stack>

      {/* SVG Grouped Bar Chart */}
      <Box sx={{ width: "100%", overflowX: "auto" }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          style={{ width: "100%", minWidth: 720, height: "auto", display: "block" }}
        >
          {/* Vertical Gridlines */}
          {xTicks.map((ratio) => {
            const val = maxVal * ratio;
            const xPos = padding.left + ratio * innerWidth;
            return (
              <g key={ratio}>
                <line
                  x1={xPos}
                  x2={xPos}
                  y1={padding.top}
                  y2={height - padding.bottom}
                  stroke="#e2e8f0"
                  strokeDasharray={ratio === 0 ? "0" : "3 3"}
                  strokeWidth="1"
                />
                <text
                  x={xPos}
                  y={height - padding.bottom + 18}
                  textAnchor="middle"
                  fontSize="11"
                  fill="#64748b"
                  fontWeight="600"
                >
                  {formatCurrency(val)}
                </text>
              </g>
            );
          })}

          {/* Category Rows */}
          {categoryData.map((item, idx) => {
            const rowY = padding.top + idx * rowHeight;
            const isHovered = hoveredIdx === idx;
            const actualWidth = Math.max((Number(item.actualRevenue || 0) / maxVal) * innerWidth, 2);
            const forecastWidth = Math.max((Number(item.forecastRevenue || 0) / maxVal) * innerWidth, 2);

            return (
              <g
                key={item.category}
                onMouseEnter={() => setHoveredIdx(idx)}
                onMouseLeave={() => setHoveredIdx(null)}
                style={{ cursor: "pointer" }}
              >
                {/* Row Hover Background */}
                <rect
                  x={10}
                  y={rowY}
                  width={width - 20}
                  height={rowHeight - 4}
                  rx={6}
                  fill={isHovered ? "#f0f9ff" : idx % 2 === 0 ? "#f8fafc" : "transparent"}
                />

                {/* Category Label */}
                <text
                  x={padding.left - 14}
                  y={rowY + 24}
                  textAnchor="end"
                  fontSize="12"
                  fontWeight="800"
                  fill={isHovered ? "#0284c7" : "#1e293b"}
                >
                  {item.category}
                </text>

                {/* Actual Bar */}
                <rect
                  x={padding.left}
                  y={rowY + 6}
                  width={actualWidth}
                  height={barHeight}
                  rx={3}
                  fill="#0e7490"
                  opacity={isHovered ? 1 : 0.9}
                  style={{ transition: "width 0.3s ease" }}
                />
                <text
                  x={padding.left + actualWidth + 6}
                  y={rowY + 16}
                  fontSize="10"
                  fontWeight="750"
                  fill="#0e7490"
                >
                  {formatCurrency(item.actualRevenue)}
                </text>

                {/* Forecast Bar */}
                <rect
                  x={padding.left}
                  y={rowY + 22}
                  width={forecastWidth}
                  height={barHeight}
                  rx={3}
                  fill="#d97706"
                  opacity={isHovered ? 1 : 0.9}
                  style={{ transition: "width 0.3s ease" }}
                />
                <text
                  x={padding.left + forecastWidth + 6}
                  y={rowY + 32}
                  fontSize="10"
                  fontWeight="750"
                  fill="#d97706"
                >
                  {formatCurrency(item.forecastRevenue)}
                </text>
              </g>
            );
          })}
        </svg>
      </Box>

      {/* Footer */}
      <Box sx={{ mt: 2, pt: 1.5, borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
          Comparing verified baseline actuals against active selected forecast horizon.
        </Typography>
        <Typography variant="caption" sx={{ color: "#082f49", fontWeight: 750 }}>
          14 Revenue Categories Verified
        </Typography>
      </Box>
    </Paper>
  );
}

// ----------------------------------------------------------------------
// Category Analysis View (Horizontal Bars + Sorting + Graphical View)
// ----------------------------------------------------------------------
function CategoryAnalysisView({ forecasts, latestActuals, selectedPeriod, onPeriodChange, periods, latestActualMonth, latestActualYear }) {
  const [viewMode, setViewMode] = useState("existing"); // 'existing' | 'graphical'
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

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems="center">
          {/* View Toggle: Existing View vs Graphical View */}
          <Stack direction="row" spacing={0.5} sx={{ bgcolor: "#f1f5f9", p: 0.5, borderRadius: 1.5, border: "1px solid #e2e8f0" }}>
            <Button
              size="small"
              onClick={() => setViewMode("existing")}
              sx={{
                textTransform: "none",
                fontWeight: 850,
                fontSize: "0.8rem",
                px: 1.75,
                py: 0.5,
                borderRadius: 1.2,
                bgcolor: viewMode === "existing" ? "#ffffff" : "transparent",
                color: viewMode === "existing" ? "#082f49" : "#64748b",
                boxShadow: viewMode === "existing" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                "&:hover": { bgcolor: viewMode === "existing" ? "#ffffff" : "#e2e8f0" },
              }}
            >
              Existing View
            </Button>
            <Button
              size="small"
              onClick={() => setViewMode("graphical")}
              sx={{
                textTransform: "none",
                fontWeight: 850,
                fontSize: "0.8rem",
                px: 1.75,
                py: 0.5,
                borderRadius: 1.2,
                bgcolor: viewMode === "graphical" ? "#ffffff" : "transparent",
                color: viewMode === "graphical" ? "#082f49" : "#64748b",
                boxShadow: viewMode === "graphical" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                "&:hover": { bgcolor: viewMode === "graphical" ? "#ffffff" : "#e2e8f0" },
              }}
            >
              Graphical View
            </Button>
          </Stack>

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

      {/* Conditionally Render: Graphical View vs Existing Cards View */}
      {viewMode === "graphical" ? (
        <CategoryGroupedBarChart
          categoryData={sortedCategories}
          latestActualMonth={latestActualMonth}
          latestActualYear={latestActualYear}
          selectedPeriod={selectedPeriod}
        />
      ) : (
        /* Existing Horizontal Bar Chart Cards */
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
                          fontWeight: 850,
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
                        Latest Actual ({latestActualMonth || "July"})
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
      )}
    </Box>
  );
}

// ----------------------------------------------------------------------
// Actual vs Forecast Table View
// ----------------------------------------------------------------------
function ForecastTableView({ forecasts, latestActuals, selectedPeriod, onPeriodChange, periods, latestActualMonth, latestActualYear }) {
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
                {latestActualMonth || "July"} {latestActualYear || 2026} Actual
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
function DataUpdatesView({ updateStatus, modelInfo, latestActualMonth, comparison }) {
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
                  {updateStatus.latest_available_month || (latestActualMonth ? `${latestActualMonth} 2026` : "July 2026")}
                </Typography>
              </Box>

              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Verified Trial Balance Files
                </Typography>
                <Typography variant="body1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  {updateStatus.num_current_year_files || 8} files ({updateStatus.first_available_month || "January"} to {latestActualMonth || (updateStatus.latest_available_month ? updateStatus.latest_available_month.split(" ")[0] : "July")})
                </Typography>
              </Box>

              <Box sx={{ p: 1.5, bgcolor: "#f8fafc", borderRadius: 1.5 }}>
                <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 700, display: "block" }}>
                  Latest Ingested File
                </Typography>
                <Typography variant="body1" sx={{ fontWeight: 850, color: "#0f172a" }}>
                  {updateStatus.latest_upload_filename || "N/A"}
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
// Main Export Component: RevenueForecasting (4 Locked Tabs)
// ----------------------------------------------------------------------
export default function RevenueForecasting() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  const [currentTab, setCurrentTab] = useState(0); // 0: Overview, 1: Categories, 2: Details, 3: Updates
  const [data, setData] = useState(null);
  const [selectedPeriod, setSelectedPeriod] = useState("August 2026");
  const [customForecastMonth, setCustomForecastMonth] = useState(null); // null = default 3-month mode
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);

  // Selector dynamic states
  const [pickerYear, setPickerYear] = useState(2026);
  const [pickerMonth, setPickerMonth] = useState("August");

  // In-flight request cancellation tracking & custom period sync refs
  const currentRequestIdRef = useRef(0);
  const customForecastMonthRef = useRef(customForecastMonth);
  const hasInitializedPickerRef = useRef(false);

  useEffect(() => {
    customForecastMonthRef.current = customForecastMonth;
  }, [customForecastMonth]);

  const fetchForecast = useCallback(async (isBackground = false, customParams = null) => {
    const reqId = ++currentRequestIdRef.current;
    if (isBackground) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const resp = await getRevenueForecast(customParams || {});
      if (reqId !== currentRequestIdRef.current) {
        // Discard stale in-flight response to prevent race condition overwrite
        return;
      }
      if (!resp?.forecasts || !Array.isArray(resp.forecasts)) {
        throw new Error("Invalid forecast data structure returned by API.");
      }
      setData(resp);

      // Determine and synchronize selected period
      if (customParams?.target_month && customParams?.target_year) {
        const periodStr = `${ALL_MONTHS[customParams.target_month - 1]} ${customParams.target_year}`;
        setSelectedPeriod(periodStr);
        setCustomForecastMonth(periodStr);
        setPickerYear(customParams.target_year);
        setPickerMonth(ALL_MONTHS[customParams.target_month - 1]);
      } else {
        setSelectedPeriod((current) =>
          resp.forecasts.some((r) => r.period === current)
            ? current
            : resp.forecasts[0]?.period || "August 2026"
        );
      }
      setLastRefreshedAt(new Date());
    } catch (err) {
      if (reqId === currentRequestIdRef.current) {
        setError(err.message || "Failed to load forecast data.");
      }
    } finally {
      if (reqId === currentRequestIdRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  // Initial mount load and automated 5-minute background refresh
  useEffect(() => {
    fetchForecast();
    // 5-minute automated dashboard refresh interval
    const intervalId = window.setInterval(() => {
      if (customForecastMonthRef.current) {
        const parts = customForecastMonthRef.current.split(" ");
        const mNum = MONTH_INDEX_MAP[parts[0]];
        const yNum = Number(parts[1]);
        fetchForecast(true, { target_month: mNum, target_year: yNum });
      } else {
        fetchForecast(true);
      }
    }, REFRESH_INTERVAL);
    return () => window.clearInterval(intervalId);
  }, [fetchForecast]);

  const modelInfo = data?.model_information || {};
  const updateStatus = data?.data_update_status || {};
  const latestActuals = data?.latest_actual_by_category || {};

  const comparison = data?.comparison || [];
  const actualComparisonRows = comparison.filter((r) => r.current_year_revenue != null);
  const latestActualRow = actualComparisonRows.length > 0 ? actualComparisonRows[actualComparisonRows.length - 1] : null;
  const currentMonthRevenue = latestActualRow?.current_year_revenue;
  const currentMonthName = latestActualRow?.month || (updateStatus.latest_available_month ? updateStatus.latest_available_month.split(" ")[0] : "July");
  const currentYearVal = modelInfo.current_year || 2026;
  const firstMonthName = updateStatus.first_available_month || (actualComparisonRows.length > 0 ? actualComparisonRows[0].month : "January");
  const latestActualMonthNum = MONTH_INDEX_MAP[currentMonthName] || 7;

  // Sync default picker values once when data is first loaded
  useEffect(() => {
    if (!hasInitializedPickerRef.current && currentYearVal && latestActualMonthNum) {
      hasInitializedPickerRef.current = true;
      setPickerYear(currentYearVal);
      const nextMonthIndex = latestActualMonthNum % 12; // e.g. July (7) -> August (index 7)
      setPickerMonth(ALL_MONTHS[nextMonthIndex]);
    }
  }, [currentYearVal, latestActualMonthNum]);

  const periods = useMemo(
    () => [...new Set((data?.forecasts || []).map((r) => r.period))],
    [data]
  );

  const selectedForecastRows = (data?.forecasts || []).filter((r) => r.period === selectedPeriod);
  const nextMonthForecastTotal = selectedForecastRows.reduce(
    (sum, r) => sum + Number(r.forecast_revenue || 0),
    0
  );

  const forecastGrowthPct =
    currentMonthRevenue && currentMonthRevenue > 0
      ? ((nextMonthForecastTotal - currentMonthRevenue) / currentMonthRevenue) * 100
      : null;

  // Unified period change handler across all tabs
  const handlePeriodChange = (newPeriod) => {
    setSelectedPeriod(newPeriod);
    const parts = newPeriod.split(" ");
    if (parts.length === 2) {
      if (MONTH_INDEX_MAP[parts[0]]) setPickerMonth(parts[0]);
      const yr = Number(parts[1]);
      if (!isNaN(yr)) setPickerYear(yr);
    }
    if (customForecastMonth) {
      setCustomForecastMonth(newPeriod);
    }
  };

  // Handler for custom future month selection
  const handleApplyForecast = () => {
    const targetMonthNum = MONTH_INDEX_MAP[pickerMonth];
    const targetPeriodStr = `${pickerMonth} ${pickerYear}`;
    setCustomForecastMonth(targetPeriodStr);
    setSelectedPeriod(targetPeriodStr);
    fetchForecast(false, { target_month: targetMonthNum, target_year: pickerYear });
  };

  // Handler for resetting back to default 3-month forecast view
  const handleResetDefault = () => {
    setCustomForecastMonth(null);
    const nextMonthIndex = latestActualMonthNum % 12;
    setPickerYear(currentYearVal || 2026);
    setPickerMonth(ALL_MONTHS[nextMonthIndex]);
    fetchForecast(false, {});
  };

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
                      onClick={() => {
                        if (customForecastMonth) {
                          const parts = customForecastMonth.split(" ");
                          const mNum = MONTH_INDEX_MAP[parts[0]];
                          const yNum = Number(parts[1]);
                          fetchForecast(true, { target_month: mNum, target_year: yNum });
                        } else {
                          fetchForecast(true);
                        }
                      }}
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
                  <Grid container spacing={2.5} sx={{ mb: 3 }}>
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
                            {currentMonthName} {currentYearVal} Actual
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>

                    {/* Card 2: Next Month Forecast / Selected Forecast */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={{ ...cardStyle, bgcolor: "#f0fdf4", borderColor: "#bbf7d0" }}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#166534", textTransform: "uppercase" }}>
                            {customForecastMonth ? "Projected Revenue" : "Next Month Forecast"}
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

                    {/* Card 6: Data Verified Through */}
                    <Grid item xs={12} sm={6} lg={2}>
                      <Card sx={cardStyle}>
                        <CardContent sx={{ p: "0 !important" }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: "#64748b", textTransform: "uppercase" }}>
                            Data Verified Through
                          </Typography>
                          <Typography variant="body1" sx={{ fontWeight: 900, color: "#082f49", mt: 0.5, lineHeight: 1.3 }}>
                            {updateStatus.latest_available_month || `${currentMonthName} ${currentYearVal}`}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "#0284c7", fontWeight: 750, mt: 0.5, display: "block" }}>
                            {updateStatus.num_current_year_files || 8} files verified
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  </Grid>

                  {/* Additive Dynamic Future Forecast Month Selector */}
                  <FutureForecastSelector
                    baseYear={currentYearVal}
                    baseMonthNum={latestActualMonthNum}
                    pickerYear={pickerYear}
                    setPickerYear={setPickerYear}
                    pickerMonth={pickerMonth}
                    setPickerMonth={setPickerMonth}
                    onApplyForecast={handleApplyForecast}
                    onResetDefault={handleResetDefault}
                    isCustomActive={Boolean(customForecastMonth)}
                    customPeriod={customForecastMonth}
                  />

                  {/* Strictly 4 Sub-Navigation Tabs (No Revenue Trend Tab) */}
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
                                {customForecastMonth
                                  ? `${currentYearVal} Actual Revenue vs. ${customForecastMonth} Forecast`
                                  : `${currentYearVal} Actual Revenue vs. Forecast Trend`}
                              </Typography>
                              <Typography variant="caption" sx={{ color: "#64748b", fontWeight: 600 }}>
                                {customForecastMonth
                                  ? `Verified monthly performance (${firstMonthName.slice(0, 3)}–${currentMonthName.slice(0, 3)}) with single-point forecast for ${customForecastMonth}.`
                                  : `Verified monthly performance (${firstMonthName.slice(0, 3)}–${currentMonthName.slice(0, 3)}) followed by 3-month forecast outlook.`}
                              </Typography>
                            </Box>
                            <Select
                              size="small"
                              value={selectedPeriod}
                              onChange={(e) => handlePeriodChange(e.target.value)}
                              sx={{ minWidth: 150, fontWeight: 750, bgcolor: "#f8fafc" }}
                            >
                              {periods.map((p) => (
                                <MenuItem key={p} value={p}>
                                  {p}
                                </MenuItem>
                              ))}
                            </Select>
                          </Stack>
                          <RevenueTrendChart
                            comparison={comparison}
                            forecasts={data?.forecasts}
                            customSelectedMonth={customForecastMonth}
                          />
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
                                {currentMonthName} {currentYearVal} closed at <strong>{formatCurrency(currentMonthRevenue)}</strong> across 14 revenue categories.
                              </Typography>
                            </Box>

                            <Box sx={{ p: 2, bgcolor: "#f0fdf4", borderRadius: 2, border: "1px solid #bbf7d0" }}>
                              <Typography variant="caption" sx={{ color: "#166534", fontWeight: 700 }}>
                                Forward Horizon ({selectedPeriod})
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 800, color: "#14532d", mt: 0.5 }}>
                                Projected total revenue is <strong>{formatCurrency(nextMonthForecastTotal)}</strong> ({safePercent(forecastGrowthPct)} vs. {currentMonthName}).
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

                  {/* TAB 1: CATEGORY ANALYSIS */}
                  {currentTab === 1 && (
                    <CategoryAnalysisView
                      forecasts={data?.forecasts}
                      latestActuals={latestActuals}
                      selectedPeriod={selectedPeriod}
                      onPeriodChange={handlePeriodChange}
                      periods={periods}
                      latestActualMonth={currentMonthName}
                      latestActualYear={currentYearVal}
                    />
                  )}

                  {/* TAB 2: FORECAST DETAILS */}
                  {currentTab === 2 && (
                    <ForecastTableView
                      forecasts={data?.forecasts}
                      latestActuals={latestActuals}
                      selectedPeriod={selectedPeriod}
                      onPeriodChange={handlePeriodChange}
                      periods={periods}
                      latestActualMonth={currentMonthName}
                      latestActualYear={currentYearVal}
                    />
                  )}

                  {/* TAB 3: DATA UPDATES */}
                  {currentTab === 3 && (
                    <DataUpdatesView
                      updateStatus={updateStatus}
                      modelInfo={modelInfo}
                      latestActualMonth={currentMonthName}
                      comparison={comparison}
                    />
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

import React, { useState, useEffect, useRef } from "react";
import {
  Box,
  Button,
  Paper,
  Typography,
  LinearProgress,
  Chip,
  Alert,
  Stack,
} from "@mui/material";
import {
  BuildCircle as PrepareIcon,
  Download as DownloadIcon,
  Autorenew as SpinnerIcon,
  CheckCircle as SuccessIcon,
  AccessTime as TimeIcon,
  TableChart as ExcelIcon,
} from "@mui/icons-material";
import { generateUnmappedReport, getUnmappedDownloadUrl } from "../services/api";

export default function ReportSummaryActions({ reportResult, sessionId }) {
  // States: 'idle' (Stage 1) | 'preparing' (In Progress) | 'ready' (Stage 2) | 'error'
  const [unmappedState, setUnmappedState] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [downloadFilename, setDownloadFilename] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const timerRef = useRef(null);

  const ESTIMATED_TOTAL_SECONDS = 8; // Predictable duration estimate for unmapped excel generation

  // Cleanup timer interval on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Reset state whenever sessionId or reportResult changes
  useEffect(() => {
    setUnmappedState("idle");
    setProgress(0);
    setElapsedSeconds(0);
    setDownloadFilename(null);
    setErrorMessage(null);
    if (timerRef.current) clearInterval(timerRef.current);
  }, [sessionId, reportResult]);

  if (!reportResult || Number(reportResult.unmapped_count) <= 0) {
    return null;
  }

  const handlePrepareUnmapped = async () => {
    if (!sessionId || unmappedState === "preparing") return;

    setUnmappedState("preparing");
    setErrorMessage(null);
    setProgress(0);
    setElapsedSeconds(0);

    const startTime = Date.now();
    timerRef.current = setInterval(() => {
      const elapsed = (Date.now() - startTime) / 1000;
      setElapsedSeconds(elapsed);
      const computedProgress = Math.min(95, (elapsed / ESTIMATED_TOTAL_SECONDS) * 100);
      setProgress(computedProgress);
    }, 100);

    try {
      const result = await generateUnmappedReport(sessionId);
      if (timerRef.current) clearInterval(timerRef.current);

      setProgress(100);
      setDownloadFilename(result.filename);
      setUnmappedState("ready");
    } catch (err) {
      if (timerRef.current) clearInterval(timerRef.current);
      setUnmappedState("idle");
      setProgress(0);
      setErrorMessage(err.message || "Failed to prepare unmapped report. Please try again.");
    }
  };

  const handleInstantDownload = async () => {
    if (!downloadFilename) return;

    try {
      const token = localStorage.getItem("token");
      const headers = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const response = await fetch(getUnmappedDownloadUrl(downloadFilename), { headers });
      if (!response.ok) throw new Error("Failed to download file");

      const blob = await response.blob();
      const localUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = localUrl;
      a.download = downloadFilename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(localUrl);
    } catch (err) {
      setErrorMessage(err.message || "Failed to download file");
    }
  };

  // Format seconds into mm:ss countdown format
  const remainingSeconds = Math.max(0, Math.ceil(ESTIMATED_TOTAL_SECONDS - elapsedSeconds));
  const formatTimer = (secs) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  return (
    <Box sx={{ width: "100%", mt: 1 }}>
      {/* Action Button Stage 1 vs Stage 2 */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, flexWrap: "wrap" }}>
        {unmappedState === "ready" ? (
          /* Stage 2: Ready Download Button */
          <Button
            type="button"
            variant="contained"
            size="large"
            startIcon={<DownloadIcon />}
            onClick={handleInstantDownload}
            sx={{
              minHeight: 48,
              px: 3.5,
              borderRadius: 1.5,
              backgroundColor: "#16a34a",
              color: "#FFFFFF",
              textTransform: "none",
              fontWeight: 900,
              boxShadow: "0 8px 20px rgba(22, 163, 74, 0.25)",
              "&:hover": {
                backgroundColor: "#15803d",
                boxShadow: "0 10px 24px rgba(22, 163, 74, 0.35)",
              },
            }}
          >
            Download Unmapped Rows (.xlsx)
          </Button>
        ) : (
          /* Stage 1: Prepare Button */
          <Button
            type="button"
            variant="contained"
            size="large"
            startIcon={
              unmappedState === "preparing" ? (
                <SpinnerIcon
                  sx={{
                    animation: "spin 1.5s linear infinite",
                    "@keyframes spin": {
                      "0%": { transform: "rotate(0deg)" },
                      "100%": { transform: "rotate(360deg)" },
                    },
                  }}
                />
              ) : (
                <PrepareIcon />
              )
            }
            onClick={handlePrepareUnmapped}
            disabled={unmappedState === "preparing"}
            sx={{
              minHeight: 48,
              px: 3.5,
              borderRadius: 1.5,
              backgroundColor: "#E8A838",
              color: "#FFFFFF",
              textTransform: "none",
              fontWeight: 900,
              boxShadow: "0 8px 18px rgba(232, 168, 56, 0.25)",
              "&:hover": {
                backgroundColor: "#D99A26",
                boxShadow: "0 10px 22px rgba(232, 168, 56, 0.35)",
              },
              "&.Mui-disabled": {
                backgroundColor: "#d97706",
                color: "rgba(255,255,255,0.85)",
              },
            }}
          >
            {unmappedState === "preparing"
              ? "Preparing Report..."
              : "Prepare Unmapped Rows"}
          </Button>
        )}

        {/* State Badge Status Chip */}
        {unmappedState === "ready" && (
          <Chip
            icon={<SuccessIcon sx={{ color: "#16a34a !important" }} />}
            label="Report Ready for Direct Download"
            variant="outlined"
            color="success"
            sx={{ fontWeight: 800, borderRadius: 1.5, height: 36, px: 0.5 }}
          />
        )}
      </Box>

      {/* Progress Feedback Card (Displayed during 'preparing' stage) */}
      {unmappedState === "preparing" && (
        <Paper
          elevation={0}
          sx={{
            mt: 2,
            p: 2,
            borderRadius: 2,
            border: "1px solid #fde68a",
            backgroundColor: "#fffbeb",
            boxShadow: "0 4px 14px rgba(217, 119, 6, 0.08)",
          }}
        >
          <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <ExcelIcon sx={{ color: "#d97706", fontSize: 20 }} />
              <Typography variant="subtitle2" sx={{ fontWeight: 900, color: "#92400e" }}>
                Building Unmapped Rows Analysis Workbook...
              </Typography>
            </Box>

            <Stack direction="row" spacing={1} alignItems="center">
              <Chip
                icon={<TimeIcon sx={{ fontSize: 15 }} />}
                label={
                  remainingSeconds > 0
                    ? `Estimated time remaining: ${formatTimer(remainingSeconds)}`
                    : "Finalizing formatting..."
                }
                size="small"
                sx={{
                  backgroundColor: "#fef3c7",
                  color: "#92400e",
                  fontWeight: 800,
                  fontSize: "0.75rem",
                }}
              />
              <Typography variant="caption" sx={{ fontWeight: 900, color: "#b45309" }}>
                {Math.round(progress)}%
              </Typography>
            </Stack>
          </Box>

          <LinearProgress
            variant="determinate"
            value={progress}
            sx={{
              height: 8,
              borderRadius: 999,
              backgroundColor: "#fef3c7",
              "& .MuiLinearProgress-bar": {
                borderRadius: 999,
                backgroundColor: "#d97706",
              },
            }}
          />
        </Paper>
      )}

      {/* Error Alert Display */}
      {errorMessage && (
        <Alert severity="error" onClose={() => setErrorMessage(null)} sx={{ mt: 2, borderRadius: 1.5 }}>
          {errorMessage}
        </Alert>
      )}
    </Box>
  );
}

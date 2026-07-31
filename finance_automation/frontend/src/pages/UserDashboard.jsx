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
} from "@mui/icons-material";
import {
  uploadFiles,
  generateReport,
  getDownloadUrl,
  generateUnmappedReport,
  getUnmappedDownloadUrl,
  getAdminConfig,
} from "../services/api";
import StatusPanel from "../components/StatusPanel";
import ReportSummaryActions from "../components/ReportSummaryActions";

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
  { label: "Profile", icon: PersonIcon, path: "/profile" },
];

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
  const [activeStep, setActiveStep] = useState(0);
  const [uploadResult, setUploadResult] = useState(null);
  const [reportResult, setReportResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [unmappedLoading, setUnmappedLoading] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      const cfg = await getAdminConfig();
      setAdminConfig(cfg);
    } catch (err) {
      console.error("Failed to load admin config:", err);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const allFilesUploaded =
    files.tb_current &&
    files.tb_previous &&
    (files.budget || adminConfig.default_budget_active) &&
    (files.mapping || adminConfig.default_mapping_active);

  const currentYear = new Date().getFullYear();
  const getDefaultLabel = (key) => {
    const filename =
      key === "budget"
        ? adminConfig.default_budget_filename
        : adminConfig.default_mapping_filename;
    return filename || "system global template";
  };

  const handleFileChange = useCallback((key, event) => {
    const file = event.target.files[0];
    if (file) {
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

  const handleUnmappedDownload = async () => {
    if (!uploadResult?.session_id) return;
    setUnmappedLoading(true);
    try {
      const result = await generateUnmappedReport(uploadResult.session_id);
      const token = localStorage.getItem("token");
      const headers = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const response = await fetch(getUnmappedDownloadUrl(result.filename), { headers });
      if (!response.ok) throw new Error("Failed to download unmapped file");

      const blob = await response.blob();
      const localUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = localUrl;
      a.download = result.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(localUrl);
    } catch (err) {
      const msg = err.message || "Failed to generate unmapped report";
      setError(msg);
    } finally {
      setUnmappedLoading(false);
    }
  };

  const handleReset = () => {
    setFiles({});
    setUploadResult(null);
    setReportResult(null);
    setActiveStep(0);
    setError(null);
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
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

              <Paper elevation={0} sx={{ p: { xs: 2.5, md: 3.5 }, borderRadius: 2, border: "1px solid #dce5ee", boxShadow: "0 18px 42px rgba(15, 23, 42, 0.08)", background: "linear-gradient(180deg, #ffffff 0%, #fbfdff 100%)" }}>
                <Box sx={{ mb: 3, display: "flex", alignItems: { xs: "flex-start", md: "center" }, justifyContent: "space-between", gap: 2, flexDirection: { xs: "column", md: "row" } }}>
                  <Box>
                    <Typography variant="h5" sx={{ fontWeight: 900, color: "#082f49" }}>
                      Source Workbooks
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.75, color: "#64748b", fontWeight: 600 }}>
                      Current and previous trial balances are required. Admin defaults can cover budget and mapping.
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
              onDownloadUnmapped={handleUnmappedDownload}
              unmappedLoading={unmappedLoading}
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
    </ThemeProvider>
  );
}

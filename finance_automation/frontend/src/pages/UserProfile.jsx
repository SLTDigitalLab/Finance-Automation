import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import {
  ThemeProvider,
  createTheme,
  CssBaseline,
  Box,
  Button,
  Chip,
  Paper,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  Dashboard as DashboardIcon,
  Email as EmailIcon,
  ExitToApp as LogoutIcon,
  Person as PersonIcon,
  VerifiedUser as VerifiedUserIcon,
} from "@mui/icons-material";

const theme = createTheme({
  palette: {
    primary: { main: "#0B3041" },
    background: { default: "#F5F7FA" },
  },
  typography: {
    fontFamily: "'Inter', 'Roboto', 'Arial', sans-serif",
  },
});

const NAV_ITEMS = [
  { label: "Dashboard", icon: DashboardIcon, path: "/dashboard" },
  { label: "Profile", icon: PersonIcon, path: "/profile", active: true },
];

export default function UserProfile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const currentYear = new Date().getFullYear();

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
                    <h2 className="truncate text-lg font-black text-[#082f49] md:text-2xl">User Profile</h2>
                    <p className="hidden text-sm font-bold text-slate-500 sm:block">Finance Revenue Automation account details</p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
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

            <div className="flex flex-1 items-center justify-center px-4 py-8 md:px-8 lg:px-10">
              <Paper
                elevation={0}
                sx={{
                  width: "100%",
                  maxWidth: 560,
                  overflow: "hidden",
                  borderRadius: 4,
                  border: "1px solid #dce5ee",
                  boxShadow: "0 26px 62px rgba(8, 47, 73, 0.16)",
                  backgroundColor: "#ffffff",
                }}
              >
                <div className="relative h-44 overflow-hidden bg-[linear-gradient(135deg,#082f49_0%,#0f5368_58%,#0f766e_100%)]">
                  <div className="absolute -left-16 -top-20 h-56 w-56 rounded-full bg-cyan-300/18" />
                  <div className="absolute -right-20 top-4 h-64 w-64 rounded-full bg-emerald-300/14" />
                  <div className="absolute left-1/2 top-12 grid h-40 w-40 -translate-x-1/2 place-items-center rounded-full border-[12px] border-white bg-[#dff6fb] shadow-[0_18px_35px_rgba(8,47,73,0.24)]">
                    <PersonIcon sx={{ fontSize: 72, color: "#082f49" }} />
                  </div>
                </div>

                <div className="px-6 pb-8 pt-20 text-center md:px-9">
                  <Typography
                    variant="h4"
                    sx={{
                      color: "#082f49",
                      fontWeight: 900,
                      textTransform: "uppercase",
                      letterSpacing: 0,
                      lineHeight: 1.15,
                    }}
                  >
                    {user?.full_name || "Finance User"}
                  </Typography>

                  <div className="mt-3 flex items-center justify-center gap-2 text-slate-500">
                    <EmailIcon fontSize="small" />
                    <span className="break-all text-sm font-bold">{user?.email || "No email available"}</span>
                  </div>

                  <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                    <Chip
                      icon={<VerifiedUserIcon />}
                      label={user?.status || "Approved"}
                      sx={{ fontWeight: 900, color: "#047857", backgroundColor: "#d1fae5" }}
                    />
                    <Chip
                      label={user?.role || "User"}
                      sx={{ fontWeight: 900, color: "#0f766e", backgroundColor: "#ccfbf1" }}
                    />
                  </div>

                  <Typography sx={{ mx: "auto", mt: 5, maxWidth: 390, color: "#64748b", fontWeight: 700, lineHeight: 1.7 }}>
                    Account details for Finance Revenue Automation. Use this profile to confirm your registered name and email address.
                  </Typography>

                  <Button
                    variant="outlined"
                    onClick={() => navigate("/dashboard")}
                    sx={{
                      mt: 4,
                      minWidth: 190,
                      borderRadius: 999,
                      borderColor: "#082f49",
                      color: "#082f49",
                      textTransform: "none",
                      fontWeight: 900,
                      px: 4,
                      py: 1.1,
                      "&:hover": {
                        borderColor: "#0f5368",
                        backgroundColor: "#e0f2fe",
                      },
                    }}
                  >
                    View Dashboard
                  </Button>
                </div>
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

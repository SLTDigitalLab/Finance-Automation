import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { ThemeProvider, createTheme, CssBaseline, Alert, Button, Tooltip } from "@mui/material";
import {
  AdminPanelSettings as AdminIcon,
  ExitToApp as LogoutIcon,
  Lock as LockIcon,
  Person as PersonIcon,
  VerifiedUser as VerifiedUserIcon,
} from "@mui/icons-material";
import { USE_CASES, getAllowedUseCaseIds } from "../config/useCases";
// Full-colour logo for light backgrounds (public/logo.png has white "SLT" for the dark sidebar)
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

function AppIcon({ useCase, allowed, onOpen }) {
  const Icon = useCase.icon;
  const comingSoon = !useCase.path;
  const enabled = allowed && !comingSoon;

  const tooltip = !allowed
    ? "Assigned to another finance team member"
    : comingSoon
      ? "Coming soon"
      : useCase.description || useCase.name;

  return (
    <Tooltip title={tooltip} arrow>
      <span className="flex justify-center">
        <button
          type="button"
          disabled={!enabled}
          onClick={() => onOpen(useCase)}
          aria-label={`${useCase.name}${enabled ? "" : " (locked)"}`}
          className={`group flex w-[104px] flex-col items-center gap-2.5 rounded-2xl p-2 outline-none transition focus-visible:ring-2 focus-visible:ring-[#1B6B93] ${
            enabled ? "cursor-pointer" : "cursor-not-allowed"
          }`}
        >
          <span
            className={`relative grid h-[76px] w-[76px] place-items-center rounded-[22px] transition ${
              enabled
                ? "shadow-[0_12px_24px_rgba(8,47,73,0.22)] group-hover:-translate-y-1 group-hover:shadow-[0_18px_30px_rgba(8,47,73,0.28)]"
                : "bg-slate-200"
            }`}
            style={enabled ? { background: `linear-gradient(145deg, ${useCase.color} 0%, #082f49 140%)` } : undefined}
          >
            <Icon sx={{ fontSize: 38, color: enabled ? "#ffffff" : "#94a3b8" }} />
            {!enabled && (
              <span className="absolute -right-1.5 -top-1.5 grid h-6 w-6 place-items-center rounded-full border-2 border-white bg-slate-500 text-white shadow">
                <LockIcon sx={{ fontSize: 13 }} />
              </span>
            )}
          </span>
          <span
            className={`line-clamp-2 text-center text-xs font-extrabold leading-tight ${
              enabled ? "text-[#082f49]" : "text-slate-400"
            }`}
          >
            {useCase.name}
          </span>
          {allowed && comingSoon && (
            <span className="-mt-1 text-[10px] font-bold uppercase tracking-wide text-slate-400">Coming soon</span>
          )}
        </button>
      </span>
    </Tooltip>
  );
}

export default function UseCaseLauncher() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const currentYear = new Date().getFullYear();

  const allowedIds = getAllowedUseCaseIds(user);
  const isAdmin = user?.role === "Admin";
  const openable = USE_CASES.filter((u) => allowedIds.includes(u.id) && u.path);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      <div className="flex min-h-screen flex-col bg-[linear-gradient(180deg,#edf4fb_0%,#f8fafc_46%,#eef3f8_100%)] font-sans text-slate-900">
        <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
          <div className="relative flex items-center justify-between gap-4">
            <img src={lightLogo} alt="SLT Mobitel Logo" className="h-10 object-contain" />
            <div className="hidden min-w-0 text-center md:absolute md:left-1/2 md:top-1/2 md:block md:-translate-x-1/2 md:-translate-y-1/2">
              <h2 className="truncate text-2xl font-black text-[#082f49]">Finance Automation</h2>
              <p className="text-sm font-bold text-slate-500">Welcome, {user?.full_name}</p>
            </div>

            <div className="flex items-center gap-3">
              {isAdmin && (
                <Button
                  onClick={() => navigate("/admin")}
                  variant="outlined"
                  startIcon={<AdminIcon />}
                  sx={{
                    height: 42,
                    borderColor: "#082f49",
                    color: "#082f49",
                    textTransform: "none",
                    fontWeight: 900,
                    borderRadius: 1.5,
                  }}
                >
                  <span className="hidden sm:inline">Admin Panel</span>
                </Button>
              )}
              <Tooltip title="Profile">
                <button
                  type="button"
                  onClick={() => navigate(isAdmin ? "/admin" : "/profile")}
                  className="flex items-center rounded-lg border border-slate-200 bg-white p-1.5 shadow-[0_8px_20px_rgba(15,23,42,0.06)]"
                  aria-label="Profile"
                >
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#082f49] text-white">
                    <PersonIcon sx={{ fontSize: 20 }} />
                  </span>
                </button>
              </Tooltip>
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
            </div>
          </div>
        </header>

        <main className="flex-1 px-4 py-10 md:px-8">
          <div className="mx-auto max-w-4xl">
            <div className="text-center">
              <h1 className="text-2xl font-black text-[#082f49] md:text-3xl">Your Finance Use Cases</h1>
              <p className="mt-2 text-sm font-semibold text-slate-500">
                {isAdmin
                  ? "As an administrator you can open every use case."
                  : "Open the use case assigned to you. Other use cases belong to other finance team members."}
              </p>
            </div>

            {!isAdmin && allowedIds.length === 0 && (
              <Alert severity="info" sx={{ mt: 4, fontWeight: 600 }}>
                Your account ({user?.email}) has not been assigned a use case yet. Please contact the system
                administrator.
              </Alert>
            )}

            <div className="mt-8 rounded-[28px] border border-white bg-white/70 px-4 py-8 shadow-[0_26px_62px_rgba(8,47,73,0.12)] backdrop-blur sm:px-8">
              <div className="grid grid-cols-3 gap-y-6 sm:grid-cols-4 md:grid-cols-5">
                {USE_CASES.map((useCase) => (
                  <AppIcon
                    key={useCase.id}
                    useCase={useCase}
                    allowed={allowedIds.includes(useCase.id)}
                    onOpen={(u) => navigate(u.path)}
                  />
                ))}
              </div>
            </div>

            <p className="mt-5 text-center text-xs font-bold text-slate-400">
              {openable.length} of {USE_CASES.length} use cases available to you
            </p>
          </div>
        </main>

        <footer className="border-t border-slate-200 bg-white px-4 py-5 md:px-8 lg:px-10">
          <div className="mx-auto flex max-w-5xl flex-col items-center justify-center gap-2 text-center">
            <div className="flex items-center gap-2 text-[#082f49]">
              <VerifiedUserIcon fontSize="small" />
              <span className="text-sm font-black">Finance Revenue Automation</span>
            </div>
            <p className="text-xs font-semibold text-slate-500">© {currentYear} SLT-MOBITEL</p>
          </div>
        </footer>
      </div>
    </ThemeProvider>
  );
}

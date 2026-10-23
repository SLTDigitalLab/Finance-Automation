import React from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import UseCaseRoute from "./components/UseCaseRoute";
import UseCaseLauncher from "./pages/UseCaseLauncher";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import Unauthorized from "./pages/Unauthorized";
import AdminLayout from "./layouts/AdminLayout";
import UserDashboard from "./pages/UserDashboard";
import UserProfile from "./pages/UserProfile";
import AuthCallback from "./pages/AuthCallback";
import RevenueForecasting from "./pages/RevenueForecasting";
import AnomalyDetection from "./pages/AnomalyDetection";
import FinanceBoardPack from "./pages/FinanceBoardPack";
import FinancialAnalysis from "./pages/FinancialAnalysis";

/**
 * RootHandler — handles the root "/" route.
 *
 * When Microsoft redirects back to http://localhost:3000 after login,
 * it appends ?code=xxx&state=xxx to the URL.
 * This component detects those params and renders AuthCallback.
 * Otherwise it redirects to /login as normal.
 */
function RootHandler() {
  const { user, loading } = useAuth();
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const hasOAuthCallback = params.has("code") && params.has("state");

  if (hasOAuthCallback) {
    return <AuthCallback />;
  }
  if (!loading && user) {
    return <Navigate to={user.role === "Admin" ? "/admin" : "/home"} replace />;
  }
  return <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          {/* Root: handles Microsoft OAuth redirect (?code=&state=) or goes to /login */}
          <Route path="/" element={<RootHandler />} />

          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/unauthorized" element={<Unauthorized />} />
          {/* Kept for backward compat if redirect URI is changed to /auth/callback later */}
          <Route path="/auth/callback" element={<AuthCallback />} />

          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRoles={["Admin"]}>
                <AdminLayout />
              </ProtectedRoute>
            }
          />

          <Route
            path="/home"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <UseCaseLauncher />
              </ProtectedRoute>
            }
          />

          <Route
            path="/dashboard"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <UseCaseRoute useCase="revenue">
                  <UserDashboard />
                </UseCaseRoute>
              </ProtectedRoute>
            }
          />

          <Route
            path="/profile"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <UserProfile />
              </ProtectedRoute>
            }
          />

          <Route
            path="/forecasting"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <UseCaseRoute useCase="revenue">
                  <RevenueForecasting />
                </UseCaseRoute>
              </ProtectedRoute>
            }
          />

          <Route
            path="/anomalies"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <UseCaseRoute useCase="revenue">
                  <AnomalyDetection />
                </UseCaseRoute>
              </ProtectedRoute>
            }
          />

          <Route
            path="/board-pack"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <UseCaseRoute useCase="board_pack">
                  <FinanceBoardPack />
                </UseCaseRoute>
              </ProtectedRoute>
            }
          />

          <Route
            path="/financial-analysis"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <UseCaseRoute useCase="financial_analysis">
                  <FinancialAnalysis />
                </UseCaseRoute>
              </ProtectedRoute>
            }
          />

          <Route
            path="/anomaly"
            element={
              <ProtectedRoute allowedRoles={["User", "Admin"]}>
                <AnomalyDetection />
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

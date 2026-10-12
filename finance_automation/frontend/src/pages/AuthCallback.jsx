import React, { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { authMicrosoftFinish, authMicrosoftRegister } from "../services/api";

/**
 * AuthCallback — /auth/callback
 *
 * Microsoft redirects here after login with:
 *   ?code=<authorization_code>&state=<encrypted_state>
 *
 * This page:
 *   1. Reads code + state from URL params
 *   2. POSTs them to /api/auth/microsoft/finish
 *   3. If the user is new, displays a screen to choose a role.
 *   4. Calls /api/auth/microsoft/register after role is selected.
 *   5. Handles approved / pending / rejected responses
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const { finalizeLogin } = useAuth();
  const [status, setStatus] = useState("loading"); // "loading" | "new_user" | "pending" | "rejected" | "error"
  const [errorMessage, setErrorMessage] = useState("");
  const [newUserData, setNewUserData] = useState(null);
  const [selectedRole, setSelectedRole] = useState("User");
  const [submittingRole, setSubmittingRole] = useState(false);
  const calledRef = useRef(false); // prevent double-call in React StrictMode

  useEffect(() => {
    if (calledRef.current) return;
    calledRef.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const errorParam = params.get("error");
    const errorDesc = params.get("error_description");

    if (errorParam) {
      setErrorMessage(errorDesc || errorParam);
      setStatus("error");
      return;
    }

    if (!code || !state) {
      setErrorMessage("Missing authorization code or state. Please try signing in again.");
      setStatus("error");
      return;
    }

    (async () => {
      try {
        const data = await authMicrosoftFinish(code, state);

        console.log("SSO Finish response:", { sso_status: data.sso_status, user: data.user });

        if (data.sso_status === "approved" && data.access_token) {
          await finalizeLogin(data.access_token, data.user);
          console.log("Navigating after SSO approval. User role:", data.user?.role);
          navigate("/home", { replace: true });
        } else if (data.sso_status === "new_user") {
          setNewUserData(data.user);
          setStatus("new_user");
        } else if (data.sso_status === "pending") {
          setStatus("pending");
        } else if (data.sso_status === "rejected") {
          setStatus("rejected");
        } else {
          setErrorMessage("Unexpected response from server.");
          setStatus("error");
        }
      } catch (err) {
        setErrorMessage(err.message || "Sign-in failed. Please try again.");
        setStatus("error");
      }
    })();
  }, []);

  const handleRoleSubmit = async (e) => {
    e.preventDefault();
    if (!newUserData) return;

    setSubmittingRole(true);
    try {
      await authMicrosoftRegister(
        newUserData.microsoft_id,
        newUserData.email,
        newUserData.full_name,
        newUserData.service_number,
        selectedRole
      );
      setStatus("pending");
    } catch (err) {
      setErrorMessage(err.message || "Registration failed. Please try again.");
      setStatus("error");
    } finally {
      setSubmittingRole(false);
    }
  };

  // ── Screens ────────────────────────────────────────────────────────────

  if (status === "loading") {
    return (
      <div className="auth-shell min-h-screen flex items-center justify-center font-sans">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-sky-100 mb-6 animate-pulse">
            <svg className="w-8 h-8 text-sky-600" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
              <rect x="1" y="1" width="9" height="9" fill="#f25022" />
              <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
              <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
              <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
            </svg>
          </div>
          <h2 className="text-xl font-extrabold text-slate-800 mb-2">Completing sign-in…</h2>
          <p className="text-sm text-slate-500 font-semibold">
            Verifying your Microsoft account, please wait.
          </p>
        </div>
      </div>
    );
  }

  if (status === "new_user") {
    return (
      <div className="auth-shell min-h-screen flex items-center justify-center font-sans px-4">
        <div className="w-full max-w-[440px] bg-white rounded-[22px] shadow-[0_24px_70px_rgba(77,112,148,0.18)] overflow-hidden">
          <div className="px-8 pt-8 pb-7 text-center border-b border-slate-200">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-sky-50 border border-sky-100 mb-4">
              <svg className="w-7 h-7 text-sky-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </div>
            <h1 className="text-[22px] font-extrabold text-[#070b1f] mb-1">Select Access Role</h1>
            <p className="text-sm font-semibold text-slate-500 leading-relaxed">
              Welcome, <span className="text-[#0787d8]">{newUserData?.full_name}</span>.
              Please select a role to request access.
            </p>
          </div>

          <form onSubmit={handleRoleSubmit} className="px-8 py-7 space-y-6">
            <div className="grid grid-cols-2 gap-4">
              {/* User Card */}
              <label className={`relative flex flex-col items-center justify-center p-5 rounded-2xl border-2 cursor-pointer transition-all ${
                selectedRole === "User"
                  ? "border-[#0787d8] bg-sky-50/50 shadow-[0_4px_16px_rgba(7,135,216,0.08)]"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}>
                <input
                  type="radio"
                  name="role"
                  value="User"
                  checked={selectedRole === "User"}
                  onChange={() => setSelectedRole("User")}
                  className="sr-only"
                />
                <svg className={`w-8 h-8 mb-3 ${selectedRole === "User" ? "text-[#0787d8]" : "text-slate-400"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span className="text-sm font-extrabold text-slate-800">User</span>
                <span className="text-[10px] font-bold text-slate-400 mt-1">General access</span>
              </label>

              {/* Admin Card */}
              <label className={`relative flex flex-col items-center justify-center p-5 rounded-2xl border-2 cursor-pointer transition-all ${
                selectedRole === "Admin"
                  ? "border-[#0787d8] bg-sky-50/50 shadow-[0_4px_16px_rgba(7,135,216,0.08)]"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}>
                <input
                  type="radio"
                  name="role"
                  value="Admin"
                  checked={selectedRole === "Admin"}
                  onChange={() => setSelectedRole("Admin")}
                  className="sr-only"
                />
                <svg className={`w-8 h-8 mb-3 ${selectedRole === "Admin" ? "text-[#0787d8]" : "text-slate-400"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
                <span className="text-sm font-extrabold text-slate-800">Admin</span>
                <span className="text-[10px] font-bold text-slate-400 mt-1">Full management</span>
              </label>
            </div>

            <button
              type="submit"
              disabled={submittingRole}
              className="w-full h-[50px] rounded-xl bg-gradient-to-r from-sky-500 via-blue-600 to-emerald-500 text-white text-sm font-extrabold shadow-[0_12px_22px_rgba(14,126,216,0.24)] transition-all hover:brightness-105 active:scale-[0.99] disabled:opacity-60"
            >
              {submittingRole ? "Submitting request..." : "Submit Request"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  if (status === "pending") {
    return (
      <div className="auth-shell min-h-screen flex items-center justify-center font-sans px-4">
        <div className="w-full max-w-[420px] bg-white rounded-[22px] shadow-[0_24px_70px_rgba(77,112,148,0.18)] overflow-hidden">
          <div className="px-8 pt-8 pb-7 text-center border-b border-slate-200">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-amber-100 mb-4">
              <svg className="w-7 h-7 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h1 className="text-[22px] font-extrabold text-[#070b1f] mb-2">Pending Approval</h1>
            <p className="text-sm font-semibold text-slate-500 leading-relaxed">
              Your account has been created and is awaiting administrator approval.
              You'll be notified once access is granted.
            </p>
          </div>
          <div className="px-8 py-6 text-center">
            <button
              onClick={() => navigate("/login", { replace: true })}
              className="w-full h-[46px] rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 text-white text-sm font-extrabold shadow-[0_8px_20px_rgba(14,126,216,0.22)] hover:brightness-105 transition-all active:scale-[0.99]"
            >
              Back to Login
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (status === "rejected") {
    return (
      <div className="auth-shell min-h-screen flex items-center justify-center font-sans px-4">
        <div className="w-full max-w-[420px] bg-white rounded-[22px] shadow-[0_24px_70px_rgba(77,112,148,0.18)] overflow-hidden">
          <div className="px-8 pt-8 pb-7 text-center border-b border-slate-200">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-red-100 mb-4">
              <svg className="w-7 h-7 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h1 className="text-[22px] font-extrabold text-[#070b1f] mb-2">Access Denied</h1>
            <p className="text-sm font-semibold text-slate-500 leading-relaxed">
              Your account registration has been rejected by an administrator.
              Please contact your system administrator if you believe this is an error.
            </p>
          </div>
          <div className="px-8 py-6 text-center">
            <button
              onClick={() => navigate("/login", { replace: true })}
              className="w-full h-[46px] rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 text-white text-sm font-extrabold shadow-[0_8px_20px_rgba(14,126,216,0.22)] hover:brightness-105 transition-all active:scale-[0.99]"
            >
              Back to Login
            </button>
          </div>
        </div>
      </div>
    );
  }

  // status === "error"
  return (
    <div className="auth-shell min-h-screen flex items-center justify-center font-sans px-4">
      <div className="w-full max-w-[420px] bg-white rounded-[22px] shadow-[0_24px_70px_rgba(77,112,148,0.18)] overflow-hidden">
        <div className="px-8 pt-8 pb-7 text-center border-b border-slate-200">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-red-100 mb-4">
            <svg className="w-7 h-7 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h1 className="text-[22px] font-extrabold text-[#070b1f] mb-2">Sign-in Failed</h1>
          <p className="text-sm font-semibold text-slate-500 leading-relaxed">
            {errorMessage || "Something went wrong during sign-in. Please try again."}
          </p>
        </div>
        <div className="px-8 py-6 text-center">
          <button
            onClick={() => navigate("/login", { replace: true })}
            className="w-full h-[46px] rounded-xl bg-gradient-to-r from-sky-500 to-blue-600 text-white text-sm font-extrabold shadow-[0_8px_20px_rgba(14,126,216,0.22)] hover:brightness-105 transition-all active:scale-[0.99]"
          >
            Try Again
          </button>
        </div>
      </div>
    </div>
  );
}

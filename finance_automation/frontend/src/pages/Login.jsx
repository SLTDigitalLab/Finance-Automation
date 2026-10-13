import React, { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function Login() {
  const { login, loginWithMicrosoft, isAzureAdConfigured, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [localLoading, setLocalLoading] = useState(false);
  const [microsoftLoading, setMicrosoftLoading] = useState(false);
  const [error, setError] = useState(null);

  // If already logged in, redirect based on role
  useEffect(() => {
    if (user) {
      if (user.role === "Admin") {
        navigate("/admin", { replace: true });
      } else {
        navigate("/home", { replace: true });
      }
    }
  }, [user, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLocalLoading(true);
    setError(null);
    try {
      const loggedIn = await login(email, password);
      if (loggedIn?.role === "Admin") {
        navigate("/admin");
      } else {
        navigate("/home");
      }
    } catch (err) {
      setError(err.message || "Invalid credentials");
    } finally {
      setLocalLoading(false);
    }
  };

  const handleMicrosoftLogin = async () => {
    setError(null);
    setMicrosoftLoading(true);
    try {
      await loginWithMicrosoft();
    } catch (err) {
      setError(err.message || "Microsoft sign-in failed. Please try again.");
      setMicrosoftLoading(false);
    }
  };

  return (
    <div className="auth-shell min-h-screen relative overflow-hidden px-4 py-8 font-sans text-slate-900">
      <div className="relative z-10 min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="w-full max-w-[420px] bg-white rounded-[22px] shadow-[0_24px_70px_rgba(77,112,148,0.18)] overflow-hidden">
          <div className="px-6 sm:px-8 pt-8 pb-7 text-center border-b border-slate-200">
            <h1 className="text-[26px] sm:text-[30px] leading-tight font-extrabold text-[#070b1f] tracking-normal">
              Sign In
            </h1>
            <p className="mt-2.5 text-sm font-semibold text-slate-500">
              Finance Portal Access
            </p>
          </div>

          <div className="px-6 sm:px-8 py-7">
            {error && (
              <div className="mb-6 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                {error}
              </div>
            )}

            {isAzureAdConfigured && (
              <>
                <button
                  type="button"
                  onClick={handleMicrosoftLogin}
                  disabled={microsoftLoading || localLoading}
                  className="w-full h-[50px] rounded-xl border-2 border-slate-200 bg-white text-slate-700 text-sm font-extrabold flex items-center justify-center gap-3 transition-all hover:bg-slate-50 hover:border-slate-300 active:scale-[0.99] disabled:opacity-60"
                >
                  <svg className="w-5 h-5" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                    <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                    <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                    <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                    <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
                  </svg>
                  {microsoftLoading ? "Redirecting..." : "Sign in with Microsoft"}
                </button>

                <div className="flex items-center gap-4 my-6">
                  <div className="flex-1 h-px bg-slate-200" />
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">or</span>
                  <div className="flex-1 h-px bg-slate-200" />
                </div>
              </>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <label className="block text-xs font-extrabold text-slate-500 uppercase tracking-[0.08em]">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  className="w-full h-[46px] px-4 bg-slate-50 text-slate-900 border border-slate-200 rounded-xl focus:outline-none focus:ring-4 focus:ring-sky-100 focus:border-sky-400 text-sm font-semibold placeholder:text-slate-400 transition-all"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <label className="block text-xs font-extrabold text-slate-500 uppercase tracking-[0.08em]">
                  Password
                </label>
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  className="w-full h-[46px] px-4 bg-slate-50 text-slate-900 border border-slate-200 rounded-xl focus:outline-none focus:ring-4 focus:ring-sky-100 focus:border-sky-400 text-sm font-semibold placeholder:text-slate-400 transition-all"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>

              <div className="flex items-center justify-between gap-4 -mt-1">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-500 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={showPassword}
                    onChange={() => setShowPassword(!showPassword)}
                    className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  />
                  Show password
                </label>
                <Link to="/forgot-password" className="text-xs font-extrabold text-[#0787d8] hover:text-[#056da8] transition-all">
                  Forgot password?
                </Link>
              </div>

              <button
                type="submit"
                disabled={localLoading || microsoftLoading}
                className="w-full h-[50px] rounded-xl bg-gradient-to-r from-sky-500 via-blue-600 to-emerald-500 text-white text-sm font-extrabold shadow-[0_12px_22px_rgba(14,126,216,0.24)] transition-all hover:brightness-105 active:scale-[0.99] disabled:opacity-60"
              >
                {localLoading ? "Signing in..." : "Sign In"}
              </button>
            </form>

            <div className="mt-6 pt-5 border-t border-slate-200 text-center">
              <p className="text-xs font-semibold text-slate-500">
                Don't have an account?{" "}
                <Link to="/register" className="text-[#0787d8] font-extrabold hover:text-[#056da8] transition-all">
                  Request Access
                </Link>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

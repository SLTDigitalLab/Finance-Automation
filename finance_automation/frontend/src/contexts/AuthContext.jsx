import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import {
  authLogin,
  authRegister,
  authLogout,
  authMe,
  getMicrosoftLoginUrl,
  getMyUseCases,
} from "../services/api";

/** Adds the use cases this user may open (from the server) to the user object. */
async function withUseCases(userData) {
  if (!userData) return userData;
  try {
    const { use_cases } = await getMyUseCases();
    return { ...userData, use_cases };
  } catch (err) {
    console.error("Failed to load use case access:", err);
    return { ...userData, use_cases: [] };
  }
}

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("token"));
  const [loading, setLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    try {
      if (token) {
        const userData = await authMe();
        setUser(await withUseCases(userData));
      } else {
        setUser(null);
      }
    } catch (err) {
      console.error("Session expired or invalid token:", err);
      localStorage.removeItem("token");
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchUser();
  }, []);

  const login = async (email, password) => {
    setLoading(true);
    try {
      const data = await authLogin(email, password);
      localStorage.setItem("token", data.access_token);
      setToken(data.access_token);
      const userData = await withUseCases(data.user);
      setUser(userData);
      return userData;
    } catch (err) {
      throw err;
    } finally {
      setLoading(false);
    }
  };

  /**
   * Microsoft PKCE SSO — Option B
   * Fetches the auth URL from the backend and redirects the browser.
   * Microsoft will redirect back to http://localhost:3000/auth/callback?code=&state=
   * which is handled by <AuthCallback />.
   */
  const loginWithMicrosoft = async () => {
    const { auth_url } = await getMicrosoftLoginUrl();
    window.location.href = auth_url;
  };

  /**
   * Called by AuthCallback after the backend returns the local JWT.
   * Stores the token and user in context/localStorage.
   */
  const finalizeLogin = async (accessToken, userData) => {
    localStorage.setItem("token", accessToken);
    setToken(accessToken);
    setUser(await withUseCases(userData));
  };

  const register = async (fullName, email, password, confirmPassword, role) => {
    setLoading(true);
    try {
      return await authRegister(fullName, email, password, confirmPassword, role);
    } catch (err) {
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    setLoading(true);
    try {
      await authLogout();
    } catch (err) {
      console.error("Failed to call logout api:", err);
    } finally {
      localStorage.removeItem("token");
      setToken(null);
      setUser(null);
      setLoading(false);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        loginWithMicrosoft,
        finalizeLogin,
        register,
        logout,
        refreshUser: fetchUser,
        // Always true — SSO is now server-driven, no frontend config needed
        isAzureAdConfigured: true,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

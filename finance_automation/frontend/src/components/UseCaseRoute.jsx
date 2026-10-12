import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { canAccessUseCase } from "../config/useCases";

/**
 * Sends the user back to the launcher if the page belongs to a use case
 * they are not assigned to. Use inside ProtectedRoute (which handles login).
 */
export default function UseCaseRoute({ useCase, children }) {
  const { user } = useAuth();

  if (!canAccessUseCase(user, useCase)) {
    return <Navigate to="/home" replace />;
  }

  return children;
}

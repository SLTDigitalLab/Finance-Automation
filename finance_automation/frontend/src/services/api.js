const API_BASE = process.env.REACT_APP_API_BASE_URL || "/api";
const EMPTY_ADMIN_CONFIG = {
  default_mapping_active: false,
  default_budget_active: false,
  default_mapping_filename: null,
  default_budget_filename: null,
};

async function readApiError(response, fallback) {
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    const error = await response.json();
    const detail = error.detail;
    if (detail?.errors) {
      return detail.errors.join(", ");
    }
    return detail || error.message || fallback;
  }

  const text = await response.text();
  if (response.status === 502) {
    return "The backend gateway timed out or is unavailable. Please try again; if it continues, restart/check the backend server.";
  }

  return text ? `${fallback}: ${text.slice(0, 180)}` : fallback;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getAuthHeaders(headers = {}) {
  const token = localStorage.getItem("token");
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function parseResponseError(response, defaultMessage = "Request failed") {
  let errorMsg = `${defaultMessage} (${response.status})`;
  try {
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
      const errorData = await response.json();
      errorMsg = errorData.detail?.errors?.join(", ") || errorData.detail || errorData.message || errorMsg;
    } else {
      const text = await response.text();
      if (response.status === 502) {
        errorMsg = "502 Bad Gateway: The backend server is down or unreachable.";
      } else if (response.status === 504) {
        errorMsg = "504 Gateway Timeout: Request timed out on backend server.";
      } else if (response.status === 413) {
        errorMsg = "File is too large. Server file size limit exceeded.";
      } else if (text && text.length < 200 && !text.includes("<html")) {
        errorMsg = text;
      }
    }
  } catch (e) {
    if (response.status === 502) {
      errorMsg = "502 Bad Gateway: Backend server unreachable.";
    }
  }
  return new Error(errorMsg);
}

async function safeJsonResponse(response, defaultMsg = "Invalid response from server") {
  if (!response.ok) {
    throw await parseResponseError(response, defaultMsg);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const text = await response.text();
    if (text.trim().startsWith("<") || text.includes("<html")) {
      throw new Error(`Server returned HTML instead of JSON (${response.status}). Check backend service URL & proxy routing.`);
    }
    try {
      return JSON.parse(text);
    } catch (e) {
      throw new Error(text || `${defaultMsg} (${response.status})`);
    }
  }
  return response.json();
}

// Upload & Report Generation
export async function uploadFiles(files) {
  const formData = new FormData();
  formData.append("tb_current", files.tb_current);
  formData.append("tb_previous", files.tb_previous);
  if (files.budget) {
    formData.append("budget", files.budget);
  }
  if (files.mapping) {
    formData.append("mapping", files.mapping);
  }

  const response = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Upload failed"));
  }

  return response.json();
}

export async function generateReport(sessionId) {
  const response = await fetch(`${API_BASE}/generate?session_id=${sessionId}`, {
    method: "POST",
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Report generation failed"));
  }

  const result = await response.json();
  if (result.status !== "processing") {
    return result;
  }

  return pollReportStatus(sessionId);
}

export async function pollReportStatus(sessionId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await wait(2000);

    const response = await fetch(`${API_BASE}/report-status/${sessionId}`, {
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(await readApiError(response, "Failed to fetch report status"));
    }

    const result = await response.json();
    if (result.status === "success") {
      return result;
    }
    if (result.status === "error") {
      throw new Error(result.message || "Report generation failed");
    }
  }

  throw new Error("Report generation is taking longer than expected. Please try again later.");
}

export function getDownloadUrl(filename) {
  return `${API_BASE}/download/${filename}`;
}

export async function generateUnmappedReport(sessionId) {
  const response = await fetch(`${API_BASE}/generate-unmapped?session_id=${sessionId}`, {
    method: "POST",
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Unmapped report generation failed"));
  }

  return response.json();
}

export function getUnmappedDownloadUrl(filename) {
  return `${API_BASE}/download-unmapped/${filename}`;
}

// Admin Services (Templates & Flexfields)
export async function getAdminConfig() {
  const response = await fetch(`${API_BASE}/admin/config`, {
    headers: getAuthHeaders(),
  });
  if (response.status === 404) {
    return EMPTY_ADMIN_CONFIG;
  }
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to fetch admin config"));
  }
  return response.json();
}

export async function uploadDefaultFile(fileType, file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/admin/upload-default?file_type=${fileType}`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Default upload failed"));
  }
  return response.json();
}

export async function getSessions() {
  const response = await fetch(`${API_BASE}/admin/sessions`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to fetch sessions history"));
  }
  return response.json();
}

export async function getFlexfields() {
  const response = await fetch(`${API_BASE}/admin/flexfields`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to fetch flexfields configuration"));
  }
  return response.json();
}

export async function updateFlexfields(flexfields) {
  const response = await fetch(`${API_BASE}/admin/flexfields`, {
    method: "POST",
    headers: getAuthHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(flexfields),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to update flexfields"));
  }
  return response.json();
}

// AUTH SERVICES
export async function authRegister(fullName, email, password, confirmPassword, role) {
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      full_name: fullName,
      email,
      password,
      confirm_password: confirmPassword,
      role,
    }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Registration failed"));
  }
  return response.json();
}

export async function authLogin(email, password) {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Login failed"));
  }
  return response.json();
}

export async function requestPasswordResetOtp(email) {
  const response = await fetch(`${API_BASE}/auth/forgot-password/request-otp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to send OTP"));
  }
  return response.json();
}

export async function verifyPasswordResetOtp(email, otp) {
  const response = await fetch(`${API_BASE}/auth/forgot-password/verify-otp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, otp }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Invalid OTP"));
  }
  return response.json();
}

export async function resetForgottenPassword(email, otp, newPassword, confirmPassword) {
  const response = await fetch(`${API_BASE}/auth/forgot-password/reset`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email,
      otp,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to reset password"));
  }
  return response.json();
}

export async function authAzureLogin(idToken) {
  const response = await fetch(`${API_BASE}/auth/azure-login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ id_token: idToken }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Azure login failed"));
  }
  return response.json();
}

// ── Microsoft PKCE SSO ────────────────────────────────────────────────────

/**
 * Step 1 — Ask backend for the Microsoft authorization URL (with PKCE + encrypted state).
 * Returns { auth_url: "https://login.microsoftonline.com/..." }
 */
export async function getMicrosoftLoginUrl() {
  const response = await fetch(`${API_BASE}/auth/microsoft/login`);
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to get Microsoft login URL"));
  }
  return response.json();
}

/**
 * Step 2 — After Microsoft redirects back to /auth/callback?code=&state=,
 * send code + state to backend to complete the PKCE exchange.
 * Returns { access_token, token_type, sso_status, user }
 */
export async function authMicrosoftFinish(code, state) {
  const response = await fetch(`${API_BASE}/auth/microsoft/finish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Microsoft SSO login failed"));
  }
  return response.json();
}

/**
 * Step 3 — Registers new SSO user with the role selected in the UI.
 * Returns { status, message }
 */
export async function authMicrosoftRegister(microsoftId, email, fullName, serviceNumber, role) {
  const response = await fetch(`${API_BASE}/auth/microsoft/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      microsoft_id: microsoftId,
      email,
      full_name: fullName,
      service_number: serviceNumber,
      role,
    }),
  });

  if (!response.ok) {
    throw new Error(await readApiError(response, "Microsoft SSO registration failed"));
  }
  return response.json();
}

export async function authLogout() {
  const response = await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Logout failed"));
  }
  return response.json();
}

export async function authMe() {
  const response = await fetch(`${API_BASE}/auth/me`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to fetch current user profile"));
  }
  return response.json();
}

// USER MANAGEMENT SERVICES
export async function getUsers() {
  const response = await fetch(`${API_BASE}/users`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to fetch users"));
  }
  return response.json();
}

export async function getUser(id) {
  const response = await fetch(`${API_BASE}/users/${id}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, `Failed to fetch user with ID ${id}`));
  }
  return response.json();
}

export async function createUser(user) {
  const response = await fetch(`${API_BASE}/users`, {
    method: "POST",
    headers: getAuthHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(user),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to create user"));
  }
  return response.json();
}

export async function updateUser(id, userData) {
  const response = await fetch(`${API_BASE}/users/${id}`, {
    method: "PUT",
    headers: getAuthHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(userData),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to update user"));
  }
  return response.json();
}

export async function deleteUser(id) {
  const response = await fetch(`${API_BASE}/users/${id}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to delete user"));
  }
  return response.json();
}

export async function approveUser(id) {
  const response = await fetch(`${API_BASE}/users/${id}/approve`, {
    method: "PATCH",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to approve user"));
  }
  return response.json();
}

export async function rejectUser(id) {
  const response = await fetch(`${API_BASE}/users/${id}/reject`, {
    method: "PATCH",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to reject user"));
  }
  return response.json();
}

export async function activateUser(id) {
  const response = await fetch(`${API_BASE}/users/${id}/activate`, {
    method: "PATCH",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to activate user"));
  }
  return response.json();
}

export async function deactivateUser(id) {
  const response = await fetch(`${API_BASE}/users/${id}/deactivate`, {
    method: "PATCH",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to deactivate user"));
  }
  return response.json();
}

export async function changeUserRole(id, role) {
  const response = await fetch(`${API_BASE}/users/${id}/role`, {
    method: "PATCH",
    headers: getAuthHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify({ role }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to change role"));
  }
  return response.json();
}

export async function resetUserPassword(id, newPassword) {
  const response = await fetch(`${API_BASE}/users/${id}/reset-password`, {
    method: "PATCH",
    headers: getAuthHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify({ new_password: newPassword }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to reset password"));
  }
  return response.json();
}

// AUDIT LOG SERVICES
export async function getSystemAuditLogs(params = {}) {
  const queryParts = [];
  if (params.skip !== undefined) queryParts.push(`skip=${params.skip}`);
  if (params.limit !== undefined) queryParts.push(`limit=${params.limit}`);
  if (params.search) queryParts.push(`search=${encodeURIComponent(params.search)}`);
  if (params.user_id) queryParts.push(`user_id=${params.user_id}`);
  if (params.action) queryParts.push(`action=${encodeURIComponent(params.action)}`);
  if (params.start_date) queryParts.push(`start_date=${params.start_date}`);
  if (params.end_date) queryParts.push(`end_date=${params.end_date}`);

  const queryString = queryParts.length > 0 ? `?${queryParts.join("&")}` : "";
  const response = await fetch(`${API_BASE}/audit-logs${queryString}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Failed to fetch audit logs"));
  }
  return response.json();
}

import React, { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import { Button, Tooltip } from "@mui/material";
import {
  ExitToApp as LogoutIcon,
  Person as PersonIcon,
} from "@mui/icons-material";
import {
  getUsers,
  createUser,
  updateUser,
  deleteUser,
  approveUser,
  rejectUser,
  activateUser,
  deactivateUser,
  changeUserRole,
  resetUserPassword,
  getSystemAuditLogs,
} from "../services/api";
import UseCaseAccessManager from "../components/UseCaseAccessManager";
import { USE_CASES } from "../config/useCases";

export default function AdminLayout() {
  const { user: currentUser, logout } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("dashboard"); // dashboard, users, pending, audits, profile

  // API states
  const [users, setUsers] = useState([]);
  const [auditResponse, setAuditResponse] = useState({ total: 0, logs: [] });
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);

  // Filter and pagination states
  const [userSearch, setUserSearch] = useState("");
  const [userFilterRole, setUserFilterRole] = useState("All");
  const [userFilterStatus, setUserFilterStatus] = useState("All");

  const [auditSearch, setAuditSearch] = useState("");
  const [auditAction, setAuditAction] = useState("");
  const [auditModule, setAuditModule] = useState("");
  const [auditUserId, setAuditUserId] = useState("");
  const [auditStartDate, setAuditStartDate] = useState("");
  const [auditEndDate, setAuditEndDate] = useState("");
  const [auditPage, setAuditPage] = useState(1);
  const [auditLimit] = useState(15);

  // Modals state
  const [editUser, setEditUser] = useState(null); // User object being edited
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [resetPasswordUser, setResetPasswordUser] = useState(null);

  // New user form state
  const [newUserForm, setNewUserForm] = useState({ full_name: "", email: "", password: "", role: "User", status: "Approved" });
  const [resetPasswordVal, setResetPasswordVal] = useState("");

  const showToast = (message, type = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 5000);
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const usersData = await getUsers();
      setUsers(usersData);
    } catch (err) {
      showToast(err.message || "Failed to load users data", "error");
    } finally {
      setLoading(false);
    }
  };

  const loadAudits = async () => {
    try {
      const skip = (auditPage - 1) * auditLimit;
      const data = await getSystemAuditLogs({
        skip,
        limit: auditLimit,
        search: auditSearch,
        action: auditAction,
        module: auditModule || undefined,
        user_id: auditUserId || undefined,
        start_date: auditStartDate || undefined,
        end_date: auditEndDate || undefined,
      });
      setAuditResponse(data);
    } catch (err) {
      showToast(err.message || "Failed to load audit logs", "error");
    }
  };

  useEffect(() => {
    if (activeTab === "users" || activeTab === "pending" || activeTab === "dashboard" || activeTab === "audits") {
      loadData();
    }
    if (activeTab === "audits") {
      loadAudits();
    }
  }, [activeTab, auditPage, auditSearch, auditAction, auditModule, auditUserId, auditStartDate, auditEndDate]);

  const handleCreateUserSubmit = async (e) => {
    e.preventDefault();
    try {
      await createUser(newUserForm);
      showToast("User created successfully!");
      setCreateUserOpen(false);
      setNewUserForm({ full_name: "", email: "", password: "", role: "User", status: "Approved" });
      loadData();
    } catch (err) {
      showToast(err.message || "Failed to create user", "error");
    }
  };

  const handleUpdateUserSubmit = async (e) => {
    e.preventDefault();
    try {
      await updateUser(editUser.id, {
        full_name: editUser.full_name,
        email: editUser.email,
        role: editUser.role,
        status: editUser.status,
      });
      showToast("User updated successfully!");
      setEditUser(null);
      loadData();
    } catch (err) {
      showToast(err.message || "Failed to update user", "error");
    }
  };

  const handleResetPasswordSubmit = async (e) => {
    e.preventDefault();
    try {
      await resetUserPassword(resetPasswordUser.id, resetPasswordVal);
      showToast("Password reset successfully!");
      setResetPasswordUser(null);
      setResetPasswordVal("");
    } catch (err) {
      showToast(err.message || "Failed to reset password", "error");
    }
  };

  // Quick actions
  const handleApprove = async (id) => {
    try {
      await approveUser(id);
      showToast("User approved successfully!");
      loadData();
    } catch (err) {
      showToast(err.message || "Approval failed", "error");
    }
  };

  const handleReject = async (id) => {
    try {
      await rejectUser(id);
      showToast("User rejected.");
      loadData();
    } catch (err) {
      showToast(err.message || "Rejection failed", "error");
    }
  };

  const handleToggleActive = async (user) => {
    try {
      if (user.is_active) {
        await deactivateUser(user.id);
        showToast("User deactivated.");
      } else {
        await activateUser(user.id);
        showToast("User activated.");
      }
      loadData();
    } catch (err) {
      showToast(err.message || "Action failed", "error");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this user?")) return;
    try {
      await deleteUser(id);
      showToast("User deleted successfully!");
      loadData();
    } catch (err) {
      showToast(err.message || "Deletion failed", "error");
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  // Calculations for dashboard counters
  const totalUsers = users.length;
  const pendingUsers = users.filter((u) => u.status === "Pending").length;
  const approvedUsers = users.filter((u) => u.status === "Approved").length;
  const adminUsers = users.filter((u) => u.role === "Admin").length;
  const activeUsers = users.filter((u) => u.is_active).length;

  // Filtered Users List
  const filteredUsers = users.filter((u) => {
    const matchesSearch =
      u.full_name.toLowerCase().includes(userSearch.toLowerCase()) ||
      u.email.toLowerCase().includes(userSearch.toLowerCase());
    const matchesRole = userFilterRole === "All" || u.role === userFilterRole;
    const matchesStatus = userFilterStatus === "All" || u.status === userFilterStatus;
    return matchesSearch && matchesRole && matchesStatus;
  });

  const pendingList = users.filter((u) => u.status === "Pending");

  return (
    <div className="flex h-screen bg-gray-100 font-sans overflow-hidden">
      {/* Toast Notification */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 p-4 rounded-lg shadow-lg text-white font-semibold transition-all ${toast.type === "error" ? "bg-red-600" : "bg-green-600"}`}>
          {toast.message}
        </div>
      )}

      {/* Sidebar */}
      <aside className="w-64 bg-[#061826] text-white flex flex-col shadow-xl border-r border-white/5">
        <div className="p-6 border-b border-white/5 flex flex-col items-center">
          <img src="/logo.png" alt="SLT Mobitel Logo" className="h-14 object-contain mb-3" />
          <span className="font-bold text-sm tracking-wide uppercase text-blue-400">Admin Workspace</span>
          <span className="text-xs text-gray-400 mt-1">{currentUser?.email}</span>
        </div>

        <nav className="flex-1 px-4 py-6 space-y-2 overflow-y-auto">

          {[
            { id: "dashboard", label: "Dashboard", icon: "📊" },
            { id: "users", label: "User Directory", icon: "👥" },
            { id: "pending", label: "Pending Approvals", count: pendingList.length, icon: "⏳" },
            { id: "use-cases", label: "Use Case Access", icon: "🔐" },
            { id: "audits", label: "Audit Logs", icon: "📜" },
            { id: "profile", label: "Admin Profile", icon: "👤" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm font-semibold transition-all ${activeTab === tab.id ? "bg-blue-600 text-white shadow-lg" : "text-gray-300 hover:bg-white/5 hover:text-white"}`}
            >
              <div className="flex items-center space-x-3">
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
              </div>
              {tab.count > 0 && (
                <span className="bg-red-500 text-white text-xs px-2 py-0.5 rounded-full font-bold">
                  {tab.count}
                </span>
              )}
            </button>
          ))}

          <div className="pt-3 border-t border-white/10 mt-3">
            <button
              onClick={() => navigate("/home")}
              className="w-full flex items-center justify-between px-4 py-2.5 rounded-lg text-xs font-bold text-sky-300 hover:bg-white/10 hover:text-white transition-all border border-sky-400/20"
              title="Open Finance Use Cases Launcher"
            >
              <div className="flex items-center space-x-2.5">
                <span className="text-sm">🚀</span>
                <span>Finance Use Cases</span>
              </div>
              <span className="text-[10px] bg-sky-900/80 text-sky-200 px-1.5 py-0.5 rounded font-mono">Launcher</span>
            </button>
          </div>
        </nav>

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

      {/* Main Content Area */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-gray-50">
        <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 py-3 shadow-sm backdrop-blur md:px-8">
          <div className="relative flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-4">
              <img src="/logo.png" alt="SLT Mobitel Logo" className="h-9 object-contain lg:hidden" />
              <div className="min-w-0 text-left md:absolute md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:text-center">
                <h2 className="truncate text-lg font-black capitalize text-[#082f49] md:text-2xl">
                  {activeTab.replace("-", " ")} Panel
                </h2>
                <p className="hidden text-sm font-bold text-slate-500 sm:block">
                  Welcome, {currentUser?.full_name}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                className="flex items-center rounded-lg border border-slate-200 bg-white p-2 shadow-[0_8px_20px_rgba(15,23,42,0.06)]"
                aria-label="Admin profile"
                onClick={() => setActiveTab("profile")}
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

        {/* Content body */}
        <div className="flex-1 overflow-y-auto p-8">
          {/* DASHBOARD TAB */}
          {activeTab === "dashboard" && (
            <div className="space-y-8">
              {/* Counters Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-6">
                {[
                  { label: "Total Users", val: totalUsers, bg: "from-blue-500 to-blue-600", icon: "👥" },
                  { label: "Pending Approvals", val: pendingUsers, bg: "from-orange-500 to-orange-600", icon: "⏳" },
                  { label: "Approved Users", val: approvedUsers, bg: "from-green-500 to-green-600", icon: "✅" },
                  { label: "Admin Accounts", val: adminUsers, bg: "from-[#0B3041] to-[#154D66]", icon: "🛡️" },
                  { label: "Active Sessions", val: activeUsers, bg: "from-teal-500 to-teal-600", icon: "🟢" },
                ].map((card, idx) => (
                  <div key={idx} className={`bg-gradient-to-tr ${card.bg} text-white p-6 rounded-xl shadow-md flex justify-between items-center`}>
                    <div>
                      <span className="text-xs uppercase tracking-wider opacity-80">{card.label}</span>
                      <h3 className="text-3xl font-extrabold mt-1">{card.val}</h3>
                    </div>
                    <span className="text-3xl opacity-50">{card.icon}</span>
                  </div>
                ))}
              </div>

              {/* Quick Settings & Navigation Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
                  <h3 className="text-lg font-bold text-gray-900 mb-4">Quick User Actions</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <button
                      onClick={() => setActiveTab("users")}
                      className="p-4 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-lg text-left transition-all"
                    >
                      <span className="text-2xl block mb-1">👥</span>
                      <span className="font-semibold text-gray-800 text-sm">Manage Directory</span>
                      <p className="text-xs text-gray-500 mt-1">Edit accounts, reset passwords, change roles.</p>
                    </button>
                    <button
                      onClick={() => setActiveTab("pending")}
                      className="p-4 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-lg text-left transition-all relative"
                    >
                      {pendingUsers > 0 && (
                        <span className="absolute top-2 right-2 bg-red-500 text-white text-xs px-2 py-0.5 rounded-full font-bold">
                          {pendingUsers}
                        </span>
                      )}
                      <span className="text-2xl block mb-1">⏳</span>
                      <span className="font-semibold text-gray-800 text-sm">Review Pending</span>
                      <p className="text-xs text-gray-500 mt-1">Approve or reject new registrations.</p>
                    </button>
                  </div>
                </div>

                <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
                  <h3 className="text-lg font-bold text-gray-900 mb-4">Audits & System Logs</h3>
                  <p className="text-sm text-gray-600 mb-4">
                    Review trace records for all registrations, approvals, logins, security resets, role changes, and data uploads.
                  </p>
                  <button
                    onClick={() => setActiveTab("audits")}
                    className="inline-flex items-center space-x-2 px-4 py-2 bg-[#0B3041] hover:bg-[#1B6B93] text-white text-sm font-semibold rounded-lg transition-all"
                  >
                    <span>📜</span>
                    <span>View Audit Logs</span>
                  </button>
                </div>
              </div>

            </div>
          )}

          {/* USER MANAGEMENT TAB */}
          {activeTab === "users" && (
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 space-y-6">
              {/* Toolbar */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div className="flex flex-1 items-center space-x-3">
                  <input
                    type="text"
                    placeholder="Search name or email..."
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] text-sm w-full sm:max-w-xs"
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                  />
                  <select
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] text-sm bg-white"
                    value={userFilterRole}
                    onChange={(e) => setUserFilterRole(e.target.value)}
                  >
                    <option value="All">All Roles</option>
                    <option value="Admin">Admin</option>
                    <option value="User">User</option>
                  </select>
                  <select
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] text-sm bg-white"
                    value={userFilterStatus}
                    onChange={(e) => setUserFilterStatus(e.target.value)}
                  >
                    <option value="All">All Status</option>
                    <option value="Pending">Pending</option>
                    <option value="Approved">Approved</option>
                    <option value="Rejected">Rejected</option>
                  </select>
                </div>
                <button
                  onClick={() => setCreateUserOpen(true)}
                  className="px-4 py-2 bg-[#7AB648] hover:bg-[#6AA038] text-white text-sm font-bold rounded-lg transition-all shadow-sm"
                >
                  + Add User
                </button>
              </div>

              {/* Table */}
              <div className="overflow-x-auto border border-gray-200 rounded-lg">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50 text-gray-700 uppercase font-semibold text-xs">
                    <tr>
                      <th className="px-6 py-3 text-left">Name</th>
                      <th className="px-6 py-3 text-left">Email</th>
                      <th className="px-6 py-3 text-left">Role</th>
                      <th className="px-6 py-3 text-left">Status</th>
                      <th className="px-6 py-3 text-left">Active</th>
                      <th className="px-6 py-3 text-left">Created Date</th>
                      <th className="px-6 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 text-gray-600 bg-white">
                    {filteredUsers.length === 0 ? (
                      <tr>
                        <td colSpan="7" className="text-center py-8 text-gray-400">
                          No users matching search filters.
                        </td>
                      </tr>
                    ) : (
                      filteredUsers.map((u) => (
                        <tr key={u.id} className="hover:bg-gray-50">
                          <td className="px-6 py-4 font-semibold text-gray-800">{u.full_name}</td>
                          <td className="px-6 py-4">{u.email}</td>
                          <td className="px-6 py-4">
                            <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${u.role === "Admin" ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"}`}>
                              {u.role}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${u.status === "Approved" ? "bg-green-100 text-green-700" : u.status === "Pending" ? "bg-orange-100 text-orange-700" : "bg-red-100 text-red-700"}`}>
                              {u.status}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <button
                              onClick={() => handleToggleActive(u)}
                              disabled={u.id === currentUser.id}
                              className={`px-2 py-0.5 rounded-full text-xs font-bold border transition-all ${u.is_active ? "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100" : "bg-gray-100 text-gray-600 border-gray-300 hover:bg-gray-200"}`}
                            >
                              {u.is_active ? "Active" : "Inactive"}
                            </button>
                          </td>
                          <td className="px-6 py-4 text-xs">
                            {new Date(u.created_at).toLocaleDateString()}
                          </td>
                          <td className="px-6 py-4 text-right space-x-1.5 whitespace-nowrap">
                            {u.status === "Pending" && (
                              <>
                                <button
                                  onClick={() => handleApprove(u.id)}
                                  className="text-xs bg-green-500 hover:bg-green-600 text-white px-2 py-1 rounded"
                                >
                                  Approve
                                </button>
                                <button
                                  onClick={() => handleReject(u.id)}
                                  className="text-xs bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded"
                                >
                                  Reject
                                </button>
                              </>
                            )}
                            <button
                              onClick={() => setEditUser(u)}
                              className="text-xs bg-blue-500 hover:bg-blue-600 text-white px-2 py-1 rounded"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => setResetPasswordUser(u)}
                              className="text-xs bg-orange-500 hover:bg-orange-600 text-white px-2 py-1 rounded"
                            >
                              Reset Pass
                            </button>
                            <button
                              onClick={() => handleDelete(u.id)}
                              disabled={u.id === currentUser.id}
                              className="text-xs bg-red-600 hover:bg-red-700 text-white px-2 py-1 rounded disabled:opacity-50"
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* PENDING APPROVALS TAB */}
          {activeTab === "pending" && (
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 space-y-6">
              <div className="overflow-x-auto border border-gray-200 rounded-lg">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50 text-gray-700 uppercase font-semibold text-xs">
                    <tr>
                      <th className="px-6 py-3 text-left">Name</th>
                      <th className="px-6 py-3 text-left">Email</th>
                      <th className="px-6 py-3 text-left">Registration Date</th>
                      <th className="px-6 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 text-gray-600 bg-white">
                    {pendingList.length === 0 ? (
                      <tr>
                        <td colSpan="4" className="text-center py-8 text-gray-400">
                          No registrations pending administrator approval.
                        </td>
                      </tr>
                    ) : (
                      pendingList.map((u) => (
                        <tr key={u.id} className="hover:bg-gray-50">
                          <td className="px-6 py-4 font-semibold text-gray-800">{u.full_name}</td>
                          <td className="px-6 py-4">{u.email}</td>
                          <td className="px-6 py-4">
                            {new Date(u.created_at).toLocaleString()}
                          </td>
                          <td className="px-6 py-4 text-right space-x-2">
                            <button
                              onClick={() => handleApprove(u.id)}
                              className="px-3 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-xs font-bold transition-all shadow-sm"
                            >
                              Approve
                            </button>
                            <button
                              onClick={() => handleReject(u.id)}
                              className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded text-xs font-bold transition-all shadow-sm"
                            >
                              Reject
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* USE CASE ACCESS TAB */}
          {activeTab === "use-cases" && <UseCaseAccessManager showToast={showToast} />}

          {/* AUDIT LOGS TAB */}
          {activeTab === "audits" && (() => {
            // Action colour map — covers all real backend actions
            const actionStyle = (action) => {
              if (!action) return "bg-gray-100 text-gray-600";
              if (action.includes("Failed")) return "bg-red-100 text-red-700";
              if (action === "Login" || action === "Azure AD Login" || action === "Microsoft SSO Login") return "bg-emerald-100 text-emerald-700";
              if (action === "Logout") return "bg-slate-100 text-slate-600";
              if (action.includes("Registration") || action.includes("SSO Registration")) return "bg-blue-100 text-blue-700";
              if (action === "User Approval" || action === "User Activation") return "bg-green-100 text-green-700";
              if (action === "User Rejection" || action === "User Deactivation" || action === "User Deletion") return "bg-red-100 text-red-700";
              if (action === "Role Change" || action === "User Creation" || action === "User Update") return "bg-purple-100 text-purple-700";
              if (action === "Password Reset" || action === "Forgot Password Reset" || action === "Password Reset OTP Request") return "bg-orange-100 text-orange-700";
              if (action === "Report Generation" || action === "Download Report") return "bg-teal-100 text-teal-700";
              if (action.includes("Upload")) return "bg-cyan-100 text-cyan-700";
              if (action.includes("Forecast")) return "bg-violet-100 text-violet-700";
              if (action === "Use Case Assignment") return "bg-indigo-100 text-indigo-700";
              if (action.includes("Pending")) return "bg-amber-100 text-amber-700";
              return "bg-gray-100 text-gray-600";
            };

            const totalPages = Math.ceil(auditResponse.total / auditLimit) || 1;

            // Summary counts from current page (approximate for display)
            const logins = auditResponse.logs.filter(l => l.action === "Login" || l.action === "Azure AD Login" || l.action === "Microsoft SSO Login").length;
            const failures = auditResponse.logs.filter(l => l.action === "Failed Login").length;
            const registrations = auditResponse.logs.filter(l => l.action?.includes("Registration")).length;
            const adminActions = auditResponse.logs.filter(l =>
              ["User Approval","User Rejection","User Creation","User Deletion","Role Change","User Activation","User Deactivation","Password Reset","Use Case Assignment"].includes(l.action)
            ).length;

            const clearFilters = () => {
              setAuditSearch("");
              setAuditAction("");
              setAuditModule("");
              setAuditUserId("");
              setAuditStartDate("");
              setAuditEndDate("");
              setAuditPage(1);
            };

            return (
              <div className="space-y-5">

                {/* ── Summary stat pills ── */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  {[
                    { label: "Total Events", value: auditResponse.total, colour: "bg-[#0B3552] text-white", icon: "📋" },
                    { label: "Successful Logins", value: logins, colour: "bg-emerald-600 text-white", icon: "✅" },
                    { label: "Failed Logins", value: failures, colour: "bg-red-600 text-white", icon: "⚠️" },
                    { label: "Admin Actions", value: adminActions, colour: "bg-purple-600 text-white", icon: "🛡️" },
                  ].map((s) => (
                    <div key={s.label} className={`${s.colour} rounded-xl px-5 py-4 flex items-center gap-3 shadow-sm`}>
                      <span className="text-2xl opacity-80">{s.icon}</span>
                      <div>
                        <p className="text-xs font-semibold opacity-80 uppercase tracking-wide">{s.label}</p>
                        <p className="text-2xl font-black">{s.value}</p>
                      </div>
                    </div>
                  ))}
                </div>

                {/* ── Filter toolbar ── */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 space-y-4">
                  <div className="flex flex-col sm:flex-row gap-3 flex-wrap">
                    {/* Search */}
                    <div className="relative flex-1 min-w-[180px]">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
                      <input
                        type="text"
                        placeholder="Search user, action, description, IP…"
                        className="w-full pl-8 pr-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                        value={auditSearch}
                        onChange={(e) => { setAuditSearch(e.target.value); setAuditPage(1); }}
                      />
                    </div>

                    {/* Action filter */}
                    <select
                      className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1B6B93] min-w-[180px]"
                      value={auditAction}
                      onChange={(e) => { setAuditAction(e.target.value); setAuditPage(1); }}
                    >
                      <option value="">All Actions</option>
                      <optgroup label="Authentication">
                        <option value="Login">Login</option>
                        <option value="Logout">Logout</option>
                        <option value="Failed Login">Failed Login</option>
                        <option value="Registration">Registration</option>
                        <option value="Password Reset OTP Request">Password Reset OTP Request</option>
                        <option value="Forgot Password Reset">Forgot Password Reset</option>
                      </optgroup>
                      <optgroup label="Microsoft / Azure SSO">
                        <option value="Azure AD Login">Azure AD Login</option>
                        <option value="Azure AD Registration">Azure AD Registration</option>
                        <option value="Microsoft SSO Login">Microsoft SSO Login</option>
                        <option value="Microsoft SSO Login — Pending">Microsoft SSO Login — Pending</option>
                        <option value="Microsoft SSO Registration">Microsoft SSO Registration</option>
                      </optgroup>
                      <optgroup label="User Management">
                        <option value="User Creation">User Creation</option>
                        <option value="User Approval">User Approval</option>
                        <option value="User Rejection">User Rejection</option>
                        <option value="User Activation">User Activation</option>
                        <option value="User Deactivation">User Deactivation</option>
                        <option value="User Deletion">User Deletion</option>
                        <option value="Role Change">Role Change</option>
                        <option value="Password Reset">Password Reset</option>
                      </optgroup>
                      <optgroup label="Use Cases">
                        <option value="Use Case Assignment">Use Case Assignment</option>
                      </optgroup>
                      <optgroup label="Revenue Analysis">
                        <option value="File Upload">File Upload</option>
                        <option value="Report Generation">Report Generation</option>
                        <option value="PL File Upload">PL File Upload</option>
                        <option value="Actual Revenue File Upload">Actual Revenue File Upload</option>
                        <option value="Daily Revenue File Upload">Daily Revenue File Upload</option>
                        <option value="Forecast Generation">Forecast Generation</option>
                      </optgroup>
                      <optgroup label="Finance Board Pack">
                        <option value="Report Generation">Report Generation</option>
                        <option value="Download Report">Download Report</option>
                      </optgroup>
                    </select>

                    {/* User filter */}
                    <select
                      className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1B6B93] min-w-[160px]"
                      value={auditUserId}
                      onChange={(e) => { setAuditUserId(e.target.value); setAuditPage(1); }}
                    >
                      <option value="">All Users</option>
                      {users.map((u) => (
                        <option key={u.id} value={u.id}>{u.full_name} ({u.email})</option>
                      ))}
                    </select>

                    {/* Module / Use Case filter */}
                    <select
                      className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1B6B93] min-w-[180px]"
                      value={auditModule}
                      onChange={(e) => { setAuditModule(e.target.value); setAuditPage(1); }}
                    >
                      <option value="">All Use Cases / Modules</option>
                      <option value="Revenue Analysis">📈 Revenue Analysis</option>
                      <option value="Finance Board Pack">📊 Finance Board Pack</option>
                      <option value="Petty Cash Manager">💵 Petty Cash Manager</option>
                      <option value="Auth">🔐 Auth</option>
                      <option value="User Management">👥 User Management</option>
                    </select>
                  </div>

                  {/* Date range row */}
                  <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
                    <div className="flex items-center gap-2">
                      <label className="text-xs font-semibold text-gray-500 whitespace-nowrap">From</label>
                      <input
                        type="date"
                        className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                        value={auditStartDate}
                        onChange={(e) => { setAuditStartDate(e.target.value); setAuditPage(1); }}
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-xs font-semibold text-gray-500 whitespace-nowrap">To</label>
                      <input
                        type="date"
                        className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                        value={auditEndDate}
                        onChange={(e) => { setAuditEndDate(e.target.value); setAuditPage(1); }}
                      />
                    </div>
                    {(auditSearch || auditAction || auditModule || auditUserId || auditStartDate || auditEndDate) && (
                      <button
                        onClick={clearFilters}
                        className="px-3 py-2 text-xs font-bold text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-all"
                      >
                        ✕ Clear Filters
                      </button>
                    )}
                    <span className="ml-auto text-xs text-gray-400 font-semibold">
                      {auditResponse.total} record{auditResponse.total !== 1 ? "s" : ""} found
                    </span>
                  </div>
                </div>

                {/* ── Audit table ── */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-100 text-sm">
                      <thead className="bg-[#0B3552] text-white">
                        <tr>
                          <th className="px-5 py-3 text-left text-xs font-bold uppercase tracking-wider whitespace-nowrap">Date / Time (SLST)</th>
                          <th className="px-5 py-3 text-left text-xs font-bold uppercase tracking-wider">User</th>
                          <th className="px-5 py-3 text-left text-xs font-bold uppercase tracking-wider">Action</th>
                          <th className="px-5 py-3 text-left text-xs font-bold uppercase tracking-wider">Module</th>
                          <th className="px-5 py-3 text-left text-xs font-bold uppercase tracking-wider">Description</th>
                          <th className="px-5 py-3 text-left text-xs font-bold uppercase tracking-wider">IP Address</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 bg-white">
                        {auditResponse.logs.length === 0 ? (
                          <tr>
                            <td colSpan="6" className="text-center py-12">
                              <div className="flex flex-col items-center gap-2 text-gray-400">
                                <span className="text-4xl">📋</span>
                                <p className="font-semibold text-sm">No audit records matched your filters.</p>
                                <button onClick={clearFilters} className="text-xs text-blue-600 underline mt-1">Clear all filters</button>
                              </div>
                            </td>
                          </tr>
                        ) : (
                          auditResponse.logs.map((log, idx) => (
                            <tr key={log.id} className={`hover:bg-blue-50/40 transition-colors ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/50"}`}>
                              {/* Timestamp */}
                              <td className="px-5 py-3 whitespace-nowrap">
                                <p className="text-xs font-semibold text-gray-700">
                                  {new Date(log.created_at + "Z").toLocaleDateString("en-GB", { timeZone: "Asia/Colombo", day: "2-digit", month: "short", year: "numeric" })}
                                </p>
                                <p className="text-[11px] text-gray-400 font-medium">
                                  {new Date(log.created_at + "Z").toLocaleTimeString("en-US", { timeZone: "Asia/Colombo", hour: "2-digit", minute: "2-digit", second: "2-digit" })} SLST
                                </p>
                              </td>

                              {/* User */}
                              <td className="px-5 py-3">
                                <div className="flex items-center gap-2">
                                  <div className="h-7 w-7 rounded-full bg-[#0B3552]/10 flex items-center justify-center text-[10px] font-black text-[#0B3552] shrink-0">
                                    {(log.user_name || "S")[0].toUpperCase()}
                                  </div>
                                  <div>
                                    <p className="font-semibold text-gray-800 text-xs leading-tight">{log.user_name || "System"}</p>
                                    {log.user_id && <p className="text-[10px] text-gray-400">ID: {log.user_id}</p>}
                                  </div>
                                </div>
                              </td>

                              {/* Action badge */}
                              <td className="px-5 py-3">
                                <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-bold whitespace-nowrap ${actionStyle(log.action)}`}>
                                  {log.action}
                                </span>
                              </td>

                              {/* Module */}
                              <td className="px-5 py-3">
                                <span className={`text-xs font-semibold px-2 py-0.5 rounded-md ${
                                  log.module === "Finance" || log.module === "Revenue Analysis" || log.module === "Revenue Analytics"
                                    ? "bg-blue-50 text-blue-700 border border-blue-200"
                                    : log.module === "Finance Board Pack"
                                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                    : log.module === "Auth"
                                    ? "bg-purple-50 text-purple-700 border border-purple-200"
                                    : "bg-gray-100 text-gray-700"
                                }`}>
                                  {log.module === "Finance" ? "Revenue Analysis" : log.module}
                                </span>
                              </td>

                              {/* Description */}
                              <td className="px-5 py-3 max-w-[260px]">
                                <Tooltip title={log.description || ""} placement="top">
                                  <p className="text-xs text-gray-600 truncate" style={{ maxWidth: 240 }}>
                                    {log.description || <span className="text-gray-300 italic">—</span>}
                                  </p>
                                </Tooltip>
                              </td>

                              {/* IP */}
                              <td className="px-5 py-3">
                                <Tooltip title={log.user_agent || ""} placement="top">
                                  <span className="text-xs font-mono text-gray-500 cursor-default">
                                    {log.ip_address || "—"}
                                  </span>
                                </Tooltip>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>

                  {/* Pagination footer */}
                  <div className="flex items-center justify-between border-t border-gray-100 px-5 py-3 bg-gray-50">
                    <p className="text-xs text-gray-500">
                      Showing {Math.min((auditPage - 1) * auditLimit + 1, auditResponse.total)}–{Math.min(auditPage * auditLimit, auditResponse.total)} of {auditResponse.total}
                    </p>
                    <div className="flex items-center gap-1">
                      <button
                        disabled={auditPage <= 1}
                        onClick={() => setAuditPage(1)}
                        className="px-2.5 py-1.5 border border-gray-300 rounded-lg disabled:opacity-40 text-xs font-bold hover:bg-gray-100 transition-all"
                        title="First page"
                      >«</button>
                      <button
                        disabled={auditPage <= 1}
                        onClick={() => setAuditPage((p) => Math.max(1, p - 1))}
                        className="px-3 py-1.5 border border-gray-300 rounded-lg disabled:opacity-40 text-xs font-bold hover:bg-gray-100 transition-all"
                      >Previous</button>
                      <span className="px-4 py-1.5 text-xs font-semibold text-gray-600">
                        Page {auditPage} of {totalPages}
                      </span>
                      <button
                        disabled={auditPage >= totalPages}
                        onClick={() => setAuditPage((p) => p + 1)}
                        className="px-3 py-1.5 border border-gray-300 rounded-lg disabled:opacity-40 text-xs font-bold hover:bg-gray-100 transition-all"
                      >Next</button>
                      <button
                        disabled={auditPage >= totalPages}
                        onClick={() => setAuditPage(totalPages)}
                        className="px-2.5 py-1.5 border border-gray-300 rounded-lg disabled:opacity-40 text-xs font-bold hover:bg-gray-100 transition-all"
                        title="Last page"
                      >»</button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* ADMIN PROFILE TAB */}
          {activeTab === "profile" && (
            <div className="flex min-h-[calc(100vh-9rem)] items-center justify-center px-4 py-8">
              <div className="w-full max-w-[560px] overflow-hidden rounded-[32px] border border-[#dce5ee] bg-white shadow-[0_26px_62px_rgba(8,47,73,0.16)]">
                <div className="relative h-44 overflow-hidden bg-[linear-gradient(135deg,#082f49_0%,#0f5368_58%,#0f766e_100%)]">
                  <div className="absolute -left-16 -top-20 h-56 w-56 rounded-full bg-cyan-300/20" />
                  <div className="absolute -right-20 top-4 h-64 w-64 rounded-full bg-emerald-300/16" />
                  <div className="absolute left-1/2 top-12 grid h-40 w-40 -translate-x-1/2 place-items-center rounded-full border-[12px] border-white bg-[#dff6fb] shadow-[0_18px_35px_rgba(8,47,73,0.24)]">
                    <PersonIcon sx={{ fontSize: 72, color: "#082f49" }} />
                  </div>
                </div>

                <div className="px-6 pb-8 pt-20 text-center md:px-9">
                  <h3 className="text-3xl font-black uppercase leading-tight text-[#082f49] md:text-4xl">
                    {currentUser?.full_name || "System Administrator"}
                  </h3>

                  <div className="mt-3 flex items-center justify-center gap-2 text-slate-500">
                    <span className="text-lg" aria-hidden="true">✉</span>
                    <span className="break-all text-sm font-bold">
                      {currentUser?.email || "No email available"}
                    </span>
                  </div>

                  <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                    <span className="rounded-full bg-emerald-100 px-3 py-1 text-sm font-black text-emerald-700">
                      {currentUser?.status || "Approved"}
                    </span>
                    <span className="rounded-full bg-teal-100 px-3 py-1 text-sm font-black text-teal-700">
                      {currentUser?.role || "Admin"}
                    </span>
                  </div>

                  <p className="mx-auto mt-5 max-w-[390px] text-sm font-bold leading-7 text-slate-500">
                    Account details for Finance Revenue Automation. Use this profile to confirm your administrator account and access status.
                  </p>

                  <button
                    type="button"
                    onClick={() => setActiveTab("dashboard")}
                    className="mt-8 min-w-[190px] rounded-full border border-[#082f49] px-6 py-2.5 text-sm font-black text-[#082f49] transition hover:border-[#0f5368] hover:bg-sky-100"
                  >
                    View Dashboard
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* CREATE USER MODAL */}
      {createUserOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md">
            <h3 className="text-lg font-bold text-gray-900 mb-4">Add New User</h3>
            <form onSubmit={handleCreateUserSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                  value={newUserForm.full_name}
                  onChange={(e) => setNewUserForm({ ...newUserForm, full_name: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Email Address</label>
                <input
                  type="email"
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                  value={newUserForm.email}
                  onChange={(e) => setNewUserForm({ ...newUserForm, email: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Password</label>
                <input
                  type="password"
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                  value={newUserForm.password}
                  onChange={(e) => setNewUserForm({ ...newUserForm, password: e.target.value })}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Role</label>
                  <select
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] bg-white"
                    value={newUserForm.role}
                    onChange={(e) => setNewUserForm({ ...newUserForm, role: e.target.value })}
                  >
                    <option value="User">User</option>
                    <option value="Admin">Admin</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Approval Status</label>
                  <select
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] bg-white"
                    value={newUserForm.status}
                    onChange={(e) => setNewUserForm({ ...newUserForm, status: e.target.value })}
                  >
                    <option value="Approved">Approved</option>
                    <option value="Pending">Pending</option>
                    <option value="Rejected">Rejected</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end space-x-2 pt-4 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setCreateUserOpen(false)}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-[#0B3041] hover:bg-[#1B6B93] text-white rounded-lg text-sm font-semibold"
                >
                  Create User
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EDIT USER MODAL */}
      {editUser && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md">
            <h3 className="text-lg font-bold text-gray-900 mb-4">Edit User Account</h3>
            <form onSubmit={handleUpdateUserSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                  value={editUser.full_name}
                  onChange={(e) => setEditUser({ ...editUser, full_name: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Email Address</label>
                <input
                  type="email"
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                  value={editUser.email}
                  onChange={(e) => setEditUser({ ...editUser, email: e.target.value })}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Role</label>
                  <select
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] bg-white"
                    value={editUser.role}
                    onChange={(e) => setEditUser({ ...editUser, role: e.target.value })}
                    disabled={editUser.id === currentUser.id}
                  >
                    <option value="User">User</option>
                    <option value="Admin">Admin</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">Approval Status</label>
                  <select
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] bg-white"
                    value={editUser.status}
                    onChange={(e) => setEditUser({ ...editUser, status: e.target.value })}
                    disabled={editUser.id === currentUser.id}
                  >
                    <option value="Approved">Approved</option>
                    <option value="Pending">Pending</option>
                    <option value="Rejected">Rejected</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end space-x-2 pt-4 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setEditUser(null)}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-[#0B3041] hover:bg-[#1B6B93] text-white rounded-lg text-sm font-semibold"
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* RESET PASSWORD MODAL */}
      {resetPasswordUser && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Reset User Password</h3>
            <p className="text-xs text-gray-500 mb-4">
              Resetting password for: <span className="font-semibold">{resetPasswordUser.email}</span>
            </p>
            <form onSubmit={handleResetPasswordSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">New Password</label>
                <input
                  type="password"
                  required
                  placeholder="At least 6 characters"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                  value={resetPasswordVal}
                  onChange={(e) => setResetPasswordVal(e.target.value)}
                />
              </div>
              <div className="flex justify-end space-x-2 pt-4 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => {
                    setResetPasswordUser(null);
                    setResetPasswordVal("");
                  }}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white rounded-lg text-sm font-semibold"
                >
                  Reset Password
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

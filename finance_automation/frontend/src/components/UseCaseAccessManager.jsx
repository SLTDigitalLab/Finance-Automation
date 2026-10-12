import React, { useEffect, useMemo, useState } from "react";
import { Check as CheckIcon } from "@mui/icons-material";
import { USE_CASES } from "../config/useCases";
import { getUseCaseAssignments, updateUseCaseAssignment } from "../services/api";

const USE_CASE_BY_ID = Object.fromEntries(USE_CASES.map((u) => [u.id, u]));

function UseCaseChip({ id }) {
  const useCase = USE_CASE_BY_ID[id];
  if (!useCase) return null;
  const Icon = useCase.icon;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold text-white"
      style={{ backgroundColor: useCase.color }}
    >
      <Icon sx={{ fontSize: 13 }} />
      {useCase.name}
    </span>
  );
}

function AssignModal({ initial, onClose, onSaved, showToast }) {
  const isNew = !initial;
  const [email, setEmail] = useState(initial?.email || "");
  const [selected, setSelected] = useState(new Set(initial?.use_cases || []));
  const [saving, setSaving] = useState(false);

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const ordered = USE_CASES.map((u) => u.id).filter((id) => selected.has(id));
      const result = await updateUseCaseAssignment(email, ordered);
      showToast(
        result.use_cases.length
          ? `Use cases saved for ${result.email}`
          : `All use case access removed for ${result.email}`
      );
      onSaved();
    } catch (err) {
      showToast(err.message || "Failed to save use cases", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-bold text-gray-900">{isNew ? "Assign Use Cases by Email" : "Edit Use Cases"}</h3>
        <p className="text-xs text-gray-500 mt-1 mb-4">
          {isNew
            ? "Use the person's SLT email. Access applies as soon as they sign in, even if they have not registered yet."
            : `${initial.full_name ? `${initial.full_name} · ` : ""}${initial.email}`}
        </p>

        <form onSubmit={handleSubmit} className="space-y-5">
          {isNew && (
            <div>
              <label htmlFor="assign-email" className="block text-xs font-semibold text-gray-500 uppercase mb-1">
                Email Address
              </label>
              <input
                id="assign-email"
                type="email"
                required
                placeholder="name@slt.com.lk"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93]"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          )}

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="block text-xs font-semibold text-gray-500 uppercase">Use Cases</span>
              <span className="text-xs text-gray-500">{selected.size} selected</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {USE_CASES.map((useCase) => {
                const Icon = useCase.icon;
                const checked = selected.has(useCase.id);
                return (
                  <button
                    key={useCase.id}
                    type="button"
                    onClick={() => toggle(useCase.id)}
                    aria-pressed={checked}
                    className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-all ${
                      checked ? "border-[#1B6B93] bg-sky-50 ring-1 ring-[#1B6B93]" : "border-gray-200 hover:bg-gray-50"
                    }`}
                  >
                    <span
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-lg"
                      style={{ backgroundColor: useCase.color }}
                    >
                      <Icon sx={{ fontSize: 20, color: "#fff" }} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold text-gray-800 truncate">{useCase.name}</span>
                      {!useCase.path && <span className="block text-[11px] text-gray-400">Coming soon</span>}
                    </span>
                    <span
                      className={`grid h-5 w-5 shrink-0 place-items-center rounded border ${
                        checked ? "border-[#1B6B93] bg-[#1B6B93] text-white" : "border-gray-300 bg-white"
                      }`}
                    >
                      {checked && <CheckIcon sx={{ fontSize: 14 }} />}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex justify-end space-x-2 pt-4 border-t border-gray-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 bg-[#0B3041] hover:bg-[#1B6B93] text-white rounded-lg text-sm font-semibold disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save Use Cases"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function UseCaseAccessManager({ showToast }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All");
  const [useCaseFilter, setUseCaseFilter] = useState("All");
  const [editing, setEditing] = useState(null); // row object, or "new"

  const load = async () => {
    setLoading(true);
    try {
      setRows(await getUseCaseAssignments());
    } catch (err) {
      showToast(err.message || "Failed to load use case assignments", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      const matchesSearch = !q || r.email.includes(q) || (r.full_name || "").toLowerCase().includes(q);
      const matchesFilter =
        filter === "All" || (filter === "Assigned" ? r.use_cases.length > 0 : r.use_cases.length === 0);
      const matchesUseCase = useCaseFilter === "All" || r.use_cases.includes(useCaseFilter);
      return matchesSearch && matchesFilter && matchesUseCase;
    });
  }, [rows, search, filter, useCaseFilter]);

  const unassignedCount = rows.filter((r) => r.use_cases.length === 0).length;

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 space-y-6">
      <div>
        <h3 className="text-lg font-bold text-gray-900">Use Case Access</h3>
        <p className="text-sm text-gray-500 mt-1">
          Assign each finance user to the use case(s) they own. Users see all 13 use cases on their home screen but can
          only open the ones assigned here. Admins can open every use case.
        </p>
      </div>

      {unassignedCount > 0 && (
        <div className="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-800">
          <span className="font-bold">{unassignedCount}</span> user{unassignedCount === 1 ? " has" : "s have"} no use
          case assigned and cannot open anything yet.
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex flex-1 flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="Search name or email..."
            className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] text-sm w-full sm:max-w-xs"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] text-sm bg-white"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="All">All Users</option>
            <option value="Assigned">With Use Cases</option>
            <option value="Unassigned">No Use Case</option>
          </select>
          <select
            className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1B6B93] text-sm bg-white"
            value={useCaseFilter}
            onChange={(e) => setUseCaseFilter(e.target.value)}
          >
            <option value="All">All Use Cases</option>
            {USE_CASES.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={() => setEditing("new")}
          className="px-4 py-2 bg-[#7AB648] hover:bg-[#6AA038] text-white text-sm font-bold rounded-lg transition-all shadow-sm"
        >
          + Assign by Email
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto border border-gray-200 rounded-lg">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50 text-gray-700 uppercase font-semibold text-xs">
            <tr>
              <th className="px-6 py-3 text-left">User</th>
              <th className="px-6 py-3 text-left">Account</th>
              <th className="px-6 py-3 text-left">Assigned Use Cases</th>
              <th className="px-6 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-600 bg-white">
            {loading ? (
              <tr>
                <td colSpan="4" className="text-center py-8 text-gray-400">
                  Loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan="4" className="text-center py-8 text-gray-400">
                  No users match the filters.
                </td>
              </tr>
            ) : (
              filtered.map((r) => (
                <tr key={r.email} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="font-semibold text-gray-800">{r.full_name || "—"}</div>
                    <div className="text-xs text-gray-500">{r.email}</div>
                  </td>
                  <td className="px-6 py-4">
                    {r.registered ? (
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                          r.status === "Approved"
                            ? "bg-green-100 text-green-700"
                            : r.status === "Pending"
                              ? "bg-orange-100 text-orange-700"
                              : "bg-red-100 text-red-700"
                        }`}
                      >
                        {r.status}
                      </span>
                    ) : (
                      <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-gray-100 text-gray-600">
                        Not signed in yet
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    {r.use_cases.length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {r.use_cases.map((id) => (
                          <UseCaseChip key={id} id={id} />
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-gray-400">None — all use cases locked</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right whitespace-nowrap">
                    <button
                      onClick={() => setEditing(r)}
                      className="text-xs bg-blue-500 hover:bg-blue-600 text-white px-3 py-1 rounded"
                    >
                      {r.use_cases.length ? "Edit" : "Assign"}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {editing && (
        <AssignModal
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
          showToast={showToast}
        />
      )}
    </div>
  );
}

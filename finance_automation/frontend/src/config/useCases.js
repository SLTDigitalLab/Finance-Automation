import {
  Apps as AppsIcon,
  AccountBalance as AccountBalanceIcon,
  Assessment as AssessmentIcon,
  BarChart as BarChartIcon,
  Calculate as CalculateIcon,
  Insights as InsightsIcon,
  Inventory as InventoryIcon,
  Paid as PaidIcon,
  PieChart as PieChartIcon,
  Receipt as ReceiptIcon,
  RequestQuote as RequestQuoteIcon,
  Savings as SavingsIcon,
  Slideshow as SlideshowIcon,
  TrendingUp as TrendingUpIcon,
} from "@mui/icons-material";

/**
 * The 13 finance automation use cases shown on the launcher (/home).
 *
 * - `path`: where the icon navigates. `null` = not built yet ("Coming soon").
 * - `paths`: every route that belongs to the use case (used to guard direct URL access).
 */
export const USE_CASES = [
  {
    id: "revenue",
    name: "Revenue Analytics",
    description: "Revenue dashboard, forecasting and anomaly detection",
    icon: TrendingUpIcon,
    color: "#1B6B93",
    path: "/dashboard",
    paths: ["/dashboard", "/forecasting", "/anomalies"],
  },
  {
    id: "board_pack",
    name: "Finance Board Pack",
    description: "Monthly board pack PowerPoint from the Sub workings file",
    icon: SlideshowIcon,
    color: "#7AB648",
    path: "/board-pack",
    paths: ["/board-pack"],
  },
  { id: "use_case_3", name: "Use Case 3", icon: AssessmentIcon, color: "#E8A838", path: null, paths: [] },
  { id: "use_case_4", name: "Use Case 4", icon: AccountBalanceIcon, color: "#0F766E", path: null, paths: [] },
  { id: "use_case_5", name: "Use Case 5", icon: ReceiptIcon, color: "#7C3AED", path: null, paths: [] },
  { id: "use_case_6", name: "Use Case 6", icon: PaidIcon, color: "#DB2777", path: null, paths: [] },
  { id: "use_case_7", name: "Use Case 7", icon: PieChartIcon, color: "#2563EB", path: null, paths: [] },
  { id: "use_case_8", name: "Use Case 8", icon: CalculateIcon, color: "#EA580C", path: null, paths: [] },
  { id: "use_case_9", name: "Use Case 9", icon: SavingsIcon, color: "#059669", path: null, paths: [] },
  { id: "use_case_10", name: "Use Case 10", icon: RequestQuoteIcon, color: "#9333EA", path: null, paths: [] },
  { id: "use_case_11", name: "Use Case 11", icon: BarChartIcon, color: "#0891B2", path: null, paths: [] },
  { id: "use_case_12", name: "Use Case 12", icon: InventoryIcon, color: "#B45309", path: null, paths: [] },
  { id: "use_case_13", name: "Use Case 13", icon: InsightsIcon, color: "#4F46E5", path: null, paths: [] },
];

/**
 * Use cases the signed-in user may open. Admins assign them per email in the
 * Admin panel (Use Case Access tab); AuthContext loads them into `user.use_cases`.
 * Users with no assignment see every use case locked. Admins can open all of them.
 */
export function getAllowedUseCaseIds(user) {
  if (!user) return [];
  if (user.role === "Admin") return USE_CASES.map((u) => u.id);
  return user.use_cases || [];
}

export function canAccessUseCase(user, useCaseId) {
  return getAllowedUseCaseIds(user).includes(useCaseId);
}

export function useCaseForPath(pathname) {
  return USE_CASES.find((u) => u.paths.includes(pathname)) || null;
}

/** Sidebar items for a page: adds the launcher link and hides links to other users' use cases. */
export function visibleNavItems(items, user) {
  const allowed = items.filter((item) => {
    const useCase = useCaseForPath(item.path);
    return !useCase || canAccessUseCase(user, useCase.id);
  });
  return [{ label: "All Use Cases", icon: AppsIcon, path: "/home" }, ...allowed];
}

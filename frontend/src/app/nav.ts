import {
  Activity,
  BellRing,
  Building2,
  Car,
  Cctv,
  GraduationCap,
  History,
  LayoutDashboard,
  PackageCheck,
  Radio,
  ScrollText,
  Settings,
  ShieldAlert,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "../api/types";

export interface NavItem {
  to: string;
  label: string;
  short?: string;
  icon: LucideIcon;
  group: "Operations" | "Registry" | "Configuration" | "System";
  roles?: Role[];
  /** Shown in primary tab navigation bars */
  tab?: boolean;
  end?: boolean;
}

/**
 * Primary Guard & Security Operations Tabs:
 * 1. Live Gate Feed (`feed`)
 * 2. Security Review Queue (`reviews`)
 * 3. Delivery Verification (`deliveries`)
 * 4. Vehicles Inside (`inside`)
 * 5. Movement Logs (`logs`)
 * 6. Vehicle History (`history`)
 */
export const NAV: NavItem[] = [
  { to: "/feed", label: "Live Gate Feed", short: "Live Feed", icon: Radio, group: "Operations", tab: true },
  { to: "/reviews", label: "Security Review Queue", short: "Review Queue", icon: ShieldAlert, group: "Operations", tab: true },
  { to: "/deliveries", label: "Delivery Verification", short: "Deliveries", icon: PackageCheck, group: "Operations", tab: true },
  { to: "/inside", label: "Vehicles Inside", short: "Inside", icon: Building2, group: "Operations", tab: true },
  { to: "/logs", label: "Movement Logs", short: "Movement Logs", icon: ScrollText, group: "Operations", tab: true },
  { to: "/history", label: "Vehicle History", short: "History", icon: History, group: "Operations", tab: true },
  { to: "/", label: "Overview", icon: LayoutDashboard, group: "Operations", end: true },
  { to: "/alerts", label: "Alerts", icon: BellRing, group: "Operations" },
  { to: "/vehicles", label: "Vehicles", icon: Car, group: "Registry" },
  { to: "/owners", label: "Owners", icon: Users, group: "Registry" },
  { to: "/gates", label: "Gates & cameras", icon: Cctv, group: "Configuration" },
  { to: "/users", label: "Accounts", icon: UserCog, group: "Configuration", roles: ["ADMIN"] },
  { to: "/system", label: "System status", icon: Activity, group: "System" },
  { to: "/members", label: "College Members", short: "Members", icon: GraduationCap, group: "System" },
  { to: "/settings", label: "Settings", icon: Settings, group: "System" },
];

export function visibleNav(role: Role): NavItem[] {
  return NAV.filter((n) => !n.roles || n.roles.includes(role));
}

/** "pb 65-ab 1234" -> "PB65AB1234" (same rule as the backend's normalize_plate). */
export function normalizePlate(input: string): string {
  return input.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
}

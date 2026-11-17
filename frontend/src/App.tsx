import { QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { RouterProvider } from "react-router";
import { createQueryClient } from "./api/queries";
import { router } from "./app/router";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ToastProvider } from "./components/ui/Toast";
import { LiveFeedProvider } from "./feed/LiveFeedContext";
import { installBackButton } from "./lib/backButton";
import { ThemeProvider } from "./lib/theme";
import { LoginPage } from "./pages/LoginPage";

/**
 * Core Operational Navigation Tabs for CVS-ACS Guard & Security Console:
 * - Live Gate Feed (`feed`)
 * - Security Review Queue (`reviews`)
 * - Delivery Verification (`deliveries`)
 * - Vehicles Inside (`inside`)
 * - Movement Logs (`logs`)
 * - Vehicle History (`history`)
 */
export const NAVIGATION_TABS = [
  { id: "feed", path: "/feed", label: "Live Gate Feed" },
  { id: "reviews", path: "/reviews", label: "Security Review Queue" },
  { id: "deliveries", path: "/deliveries", label: "Delivery Verification" },
  { id: "inside", path: "/inside", label: "Vehicles Inside" },
  { id: "logs", path: "/logs", label: "Movement Logs" },
  { id: "history", path: "/history", label: "Vehicle History" },
] as const;

export type NavigationTab = (typeof NAVIGATION_TABS)[number];

function Shell() {
  const { session } = useAuth();
  const queryClient = useQueryClient();

  // Nothing cached for one account is shown to the next one.
  useEffect(() => {
    if (!session) queryClient.clear();
  }, [session, queryClient]);

  if (!session) return <LoginPage />;
  // Remount per session so a new login starts a fresh live stream.
  return (
    <LiveFeedProvider key={session.token} token={session.token}>
      <RouterProvider router={router} />
    </LiveFeedProvider>
  );
}

export default function App() {
  const [queryClient] = useState(createQueryClient);
  useEffect(installBackButton, []);
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AuthProvider>
            <Shell />
          </AuthProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

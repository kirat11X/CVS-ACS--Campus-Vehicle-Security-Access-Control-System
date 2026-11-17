import type { ReactNode } from "react";
import { createHashRouter, Navigate, useParams } from "react-router";
import type { Role } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { ErrorState } from "../components/ui/Feedback";
import { ApiError } from "../api/client";
import { AlertsPage } from "../pages/AlertsPage";
import { CollegeMembersPage } from "../pages/CollegeMembersPage";
import { DashboardPage } from "../pages/DashboardPage";
import { DeliveryDetailPage } from "../pages/DeliveryDetailPage";
import { DeliveryVerificationPage } from "../pages/DeliveryVerificationPage";
import { FeedPage } from "../pages/FeedPage";
import { GatesPage } from "../pages/GatesPage";
import { InsidePage } from "../pages/InsidePage";
import { MorePage } from "../pages/MorePage";
import { MovementLogPage } from "../pages/MovementLogPage";
import { NotFoundPage, RouteErrorPage } from "../pages/NotFoundPage";
import { OwnerDetailPage } from "../pages/OwnerDetailPage";
import { OwnersPage } from "../pages/OwnersPage";
import { SecurityReviewPage } from "../pages/SecurityReviewPage";
import { SettingsPage } from "../pages/SettingsPage";
import { SystemPage } from "../pages/SystemPage";
import { UsersPage } from "../pages/UsersPage";
import { VehicleDetailPage } from "../pages/VehicleDetailPage";
import { VehiclesPage } from "../pages/VehiclesPage";
import { AppShell } from "./AppShell";

/** UI gate only; the backend enforces every role on every request. */
function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useSession();
  if (roles.includes(user.role)) return children;
  return (
    <div className="card">
      <ErrorState error={new ApiError(403, "Your role does not include this page.")} />
    </div>
  );
}

/** Links from the previous console (#/history/<plate>) keep working. */
function LegacyHistory() {
  const { plate } = useParams();
  return <Navigate to={plate ? `/vehicles/${plate}` : "/vehicles/lookup"} replace />;
}

// Hash routing works unchanged from a static web host, the Vite proxy and the Capacitor app.
export const router = createHashRouter([
  {
    element: <AppShell />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <DashboardPage /> },
      // Core Guard & Security Operations Tabs:
      { path: "feed", element: <FeedPage /> },
      { path: "reviews", element: <SecurityReviewPage /> },
      { path: "deliveries", element: <DeliveryVerificationPage /> },
      { path: "deliveries/:orderId", element: <DeliveryDetailPage /> },
      { path: "inside", element: <InsidePage /> },
      { path: "logs", element: <MovementLogPage /> },
      { path: "history", element: <VehicleDetailPage /> },
      { path: "history/:plate?", element: <LegacyHistory /> },

      // Registry, Admin & Diagnostics:
      { path: "alerts", element: <AlertsPage /> },
      { path: "vehicles", element: <VehiclesPage /> },
      { path: "vehicles/lookup", element: <VehicleDetailPage /> },
      { path: "vehicles/:plate", element: <VehicleDetailPage /> },
      { path: "owners", element: <OwnersPage /> },
      { path: "owners/:id", element: <OwnerDetailPage /> },
      { path: "gates", element: <GatesPage /> },
      {
        path: "users",
        element: (
          <RequireRole roles={["ADMIN"]}>
            <UsersPage />
          </RequireRole>
        ),
      },
      { path: "system", element: <SystemPage /> },
      { path: "members", element: <CollegeMembersPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "more", element: <MorePage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

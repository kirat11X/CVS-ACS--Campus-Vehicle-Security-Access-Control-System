import { Compass } from "lucide-react";
import { isRouteErrorResponse, useRouteError } from "react-router";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState } from "../components/ui/Feedback";

export function NotFoundPage() {
  return (
    <div className="card">
      <EmptyState
        icon={<Compass className="h-5 w-5" />}
        title="Page not found"
        description="That address is not part of the console."
        action={
          <ButtonLink to="/" variant="primary" size="sm">
            Go to the overview
          </ButtonLink>
        }
      />
    </div>
  );
}

/** Shown when a page throws while rendering; the rest of the shell keeps working. */
export function RouteErrorPage() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "Unknown error";
  return (
    <div className="card">
      <EmptyState
        title="This page hit a problem"
        description={message}
        action={
          <ButtonLink to="/" variant="primary" size="sm">
            Go to the overview
          </ButtonLink>
        }
      />
    </div>
  );
}

import { useEffect, useState } from "react";

export type Page = "feed" | "inside" | "logs" | "history";

export interface Route {
  page: Page;
  param: string | null;
}

const PAGES: Page[] = ["feed", "inside", "logs", "history"];

function parse(hash: string): Route {
  const [, page, ...rest] = hash.replace(/^#/, "").split("/");
  const known = PAGES.includes(page as Page) ? (page as Page) : "feed";
  return { page: known, param: rest.length ? decodeURIComponent(rest.join("/")) : null };
}

export function navigate(page: Page, param?: string | null): void {
  window.location.hash = param ? `/${page}/${encodeURIComponent(param)}` : `/${page}`;
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

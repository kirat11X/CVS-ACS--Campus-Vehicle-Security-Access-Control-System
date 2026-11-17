import { App } from "@capacitor/app";
import { isNativeApp } from "./platform";

type Handler = () => void;
const handlers: Handler[] = [];

/** While registered, the Android back button calls `handler` (e.g. to close a dialog). */
export function pushBackHandler(handler: Handler): () => void {
  handlers.push(handler);
  return () => {
    const i = handlers.lastIndexOf(handler);
    if (i >= 0) handlers.splice(i, 1);
  };
}

let installed = false;

/** Android back: close the top dialog, else go back a page, else send the app to the background. */
export function installBackButton(): void {
  if (!isNativeApp || installed) return;
  installed = true;
  void App.addListener("backButton", ({ canGoBack }) => {
    const top = handlers[handlers.length - 1];
    if (top) top();
    else if (canGoBack) window.history.back();
    else void App.minimizeApp();
  });
}

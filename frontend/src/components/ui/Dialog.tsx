import { X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { pushBackHandler } from "../../lib/backButton";
import { cx } from "../../lib/cx";
import { Button } from "./Button";
import { ErrorNote } from "./Feedback";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

// Open dialogs, innermost last: Escape and the Android back button close only the top one.
const stack: string[] = [];
let savedOverflow = "";

const SIZE = { sm: "sm:max-w-md", md: "sm:max-w-lg", lg: "sm:max-w-2xl", xl: "sm:max-w-4xl" } as const;

interface DialogProps {
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: keyof typeof SIZE;
}

/** Centred modal on wide screens, bottom sheet on phones. */
export function Dialog({ title, description, onClose, children, footer, size = "md" }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  const key = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const node = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    stack.push(key);
    if (stack.length === 1) {
      savedOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    const focusables = () => (node ? [...node.querySelectorAll<HTMLElement>(FOCUSABLE)] : []);
    const initial =
      node?.querySelector<HTMLElement>("[data-autofocus]") ??
      focusables().find((el) => el.matches("input,select,textarea")) ??
      focusables()[0];
    initial?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== key) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
      } else if (e.key === "Tab") {
        const els = focusables();
        if (els.length === 0) return;
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const popBack = pushBackHandler(() => onCloseRef.current());
    return () => {
      document.removeEventListener("keydown", onKey);
      popBack();
      const i = stack.lastIndexOf(key);
      if (i >= 0) stack.splice(i, 1);
      if (stack.length === 0) document.body.style.overflow = savedOverflow;
      previous?.focus?.();
    };
  }, [key]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6" role="presentation">
      <div className="absolute inset-0 animate-fade-in bg-slate-950/50 backdrop-blur-[2px]" onClick={() => onCloseRef.current()} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        className={cx(
          "relative flex max-h-[92dvh] w-full animate-sheet-up flex-col rounded-t-2xl bg-white shadow-2xl ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800 sm:rounded-2xl",
          SIZE[size],
        )}
      >
        <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-slate-300 dark:bg-slate-700 sm:hidden" aria-hidden />
        <header className="flex shrink-0 items-start gap-3 px-5 pb-3 pt-3 sm:pt-5">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-base font-semibold text-slate-900 dark:text-white">
              {title}
            </h2>
            {description && (
              <div id={descId} className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                {description}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() => onCloseRef.current()}
            className="-mr-1 rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5">{children}</div>
        {footer && (
          <footer className="flex shrink-0 flex-col-reverse gap-2 border-t border-slate-200 px-5 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] dark:border-slate-800 sm:flex-row sm:justify-end sm:pb-3">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** Confirmation for consequential (but never destructive) actions such as deactivation. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The action failed.");
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={title}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={() => void run()} data-autofocus>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm text-slate-700 dark:text-slate-300">{message}</div>
      <div className="mt-3">
        <ErrorNote message={error} />
      </div>
    </Dialog>
  );
}

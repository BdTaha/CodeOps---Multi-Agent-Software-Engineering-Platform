import { useEffect } from "react";

// The existing domain dialogs keep their own submit/close handlers. This adds
// consistent focus containment without changing approval or dismissal behavior.
export default function DialogFocusManager() {
  useEffect(() => {
    let current: HTMLElement | null = null;
    let restore: HTMLElement | null = null;
    let lastOutside =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const controls = () =>
      current
        ? Array.from(
            current.querySelectorAll<HTMLElement>(
              'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
            ),
          ).filter((element) => element.getClientRects().length > 0)
        : [];
    function sync() {
      const dialogs = document.querySelectorAll<HTMLElement>(
        '[role="dialog"][aria-modal="true"]',
      );
      const next =
        Array.from(dialogs)
          .filter((dialog) => dialog.getClientRects().length > 0)
          .at(-1) ?? null;
      if (next === current) return;
      if (!next) {
        current = null;
        if (restore?.isConnected) restore.focus();
        restore = null;
        return;
      }
      if (!current) restore = lastOutside;
      current = next;
      if (!current.contains(document.activeElement)) controls()[0]?.focus();
    }
    function key(event: KeyboardEvent) {
      if (event.key !== "Tab" || !current) return;
      const items = controls();
      if (!items.length) return;
      const first = items[0],
        last = items[items.length - 1];
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !current.contains(document.activeElement))
      ) {
        event.preventDefault();
        event.stopPropagation();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !current.contains(document.activeElement))
      ) {
        event.preventDefault();
        event.stopPropagation();
        first.focus();
      }
    }
    const observer = new MutationObserver(sync);
    const focus = (event: FocusEvent) => {
      if (
        event.target instanceof HTMLElement &&
        !event.target.closest('[role="dialog"], dialog')
      )
        lastOutside = event.target;
    };
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("keydown", key, true);
    document.addEventListener("focusin", focus, true);
    sync();
    return () => {
      observer.disconnect();
      document.removeEventListener("keydown", key, true);
      document.removeEventListener("focusin", focus, true);
    };
  }, []);
  return null;
}

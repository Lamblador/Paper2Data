const BASE_TITLE = "Paper2Data";

let busyLabel: string | null = null;
let pinnedTitle: string | null = null;
let watching = false;

function tabIsAway(): boolean {
  return document.hidden || !document.hasFocus();
}

function applyTitle(): void {
  if (tabIsAway()) {
    const label = busyLabel ?? pinnedTitle;
    document.title = label ? `${label} — ${BASE_TITLE}` : BASE_TITLE;
    return;
  }
  pinnedTitle = null;
  document.title = BASE_TITLE;
}

function watchFocus(): void {
  if (watching) return;
  watching = true;
  const schedule = () => window.setTimeout(applyTitle, 0);
  document.addEventListener("visibilitychange", schedule);
  window.addEventListener("focus", schedule);
  window.addEventListener("blur", schedule);
}

function clip(text: string | undefined): string | undefined {
  const value = text?.replace(/\s+/g, " ").trim();
  if (!value) return undefined;
  return value.length > 240 ? `${value.slice(0, 237)}…` : value;
}

/** Запрос разрешения в обработчике клика, пока жест пользователя ещё действует. */
export function armRunNotification(): void {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "default") return;
  void Notification.requestPermission().catch(() => undefined);
}

export function markRunBusy(label = "Прогон выполняется…"): void {
  watchFocus();
  busyLabel = label;
  pinnedTitle = null;
  applyTitle();
}

export function notifyRunFinished(title: string, body?: string): void {
  watchFocus();
  busyLabel = null;
  pinnedTitle = title;
  applyTitle();
  if (!tabIsAway()) return;
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  try {
    const note = new Notification(title, {
      body: clip(body),
      lang: "ru",
      tag: `paper2data-${Date.now()}`,
    });
    note.onclick = () => {
      window.focus();
      note.close();
    };
  } catch {
    // вне secure context или если браузер запретил конструктор
  }
}

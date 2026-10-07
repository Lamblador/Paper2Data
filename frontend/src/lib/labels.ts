export const SECTION_LABELS: Record<string, string> = {
  abstract: "Аннотация",
  introduction: "Введение",
  experimental: "Эксперимент",
  results: "Результаты",
  conclusion: "Заключение",
  acknowledgments: "Благодарности",
  references: "Список литературы",
  esi: "ESI",
  other: "Прочее",
};

export const RUN_STATUS_LABELS: Record<string, string> = {
  pending: "создан, не запускался",
  running: "выполняется…",
  awaiting_review: "ждёт проверки",
  completed: "завершён",
  failed: "ошибка",
  cancelled: "отменён",
};

export function runStatusLabel(status: string | null | undefined): string {
  if (!status) return "";
  return RUN_STATUS_LABELS[status] || status;
}

export function runStatusBadgeClass(status: string | null | undefined): string {
  switch (status) {
    case "completed":
      return "badge ok";
    case "failed":
    case "cancelled":
      return "badge danger";
    case "awaiting_review":
      return "badge warn";
    case "running":
    case "pending":
      return "badge info";
    default:
      return "badge";
  }
}

export const STRATEGY_LABELS: Record<string, string> = {
  iterative: "итеративная",
  entities_first: "сначала сущности",
  one_shot: "один проход",
};

export function strategyLabel(strategy: string | null | undefined): string {
  if (!strategy) return "—";
  return STRATEGY_LABELS[strategy] || strategy;
}

/** Склонение: 1 карточка, 2 карточки, 5 карточек. */
export function ruCount(n: number, one: string, few: string, many: string): string {
  const abs = Math.abs(Math.trunc(n));
  const n10 = abs % 10;
  const n100 = abs % 100;
  const word =
    n10 === 1 && n100 !== 11
      ? one
      : n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)
        ? few
        : many;
  return `${n} ${word}`;
}

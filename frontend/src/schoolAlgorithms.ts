/** School-facing checkboxes → node trigger types. Only algorithms the node actually runs. */

export const NODE_TRIGGERS = [
  "presence",
  "convergence",
  "vif",
  "stream_silent",
  "fall",
  "smoke",
] as const;

export type NodeTrigger = (typeof NODE_TRIGGERS)[number];

export const TRIGGER_LABELS: Record<string, string> = {
  presence: "Присутствие",
  convergence: "Сходка",
  vif: "Драка (пересечение)",
  stream_silent: "Камера молчит",
  fall: "Падение",
  smoke: "Курение",
};

export function triggerLabel(type: string): string {
  return TRIGGER_LABELS[type] || type;
}

export const SCHOOL_ALGORITHMS = [
  {
    id: "fight",
    category: "Поведение",
    label: "Драка / сходка",
    hint: "Двое сблизились или боксы пересеклись. Клип уходит в Campus.",
    triggers: ["convergence", "vif"] as const,
    ready: true,
  },
  {
    id: "fall",
    category: "Поведение",
    label: "Падение",
    hint: "Модель ещё не подключена. Галочка сохранится, сработок пока не будет.",
    triggers: ["fall"] as const,
    ready: false,
  },
  {
    id: "smoke",
    category: "Поведение",
    label: "Курение",
    hint: "Модель ещё не подключена. Галочка сохранится, сработок пока не будет.",
    triggers: ["smoke"] as const,
    ready: false,
  },
  {
    id: "presence",
    category: "Общее",
    label: "Присутствие",
    hint: "В кадре есть движущийся человек дольше порога. Один прохожий тоже попадёт.",
    triggers: ["presence"] as const,
    ready: true,
  },
  {
    id: "stream_silent",
    category: "Техника",
    label: "Камера молчит",
    hint: "Нет кадров дольше порога. Клип в MinIO не пишется.",
    triggers: ["stream_silent"] as const,
    ready: true,
  },
] as const;

export type SchoolAlgorithmId = (typeof SCHOOL_ALGORITHMS)[number]["id"];

export const PRESETS = [
  {
    id: "safe_school",
    label: "Safe School",
    hint: "Коридоры днём: только сходка/драка, без одиночного прохожего.",
    algorithms: ["fight"] as SchoolAlgorithmId[],
  },
  {
    id: "night_corridor",
    label: "Ночной коридор",
    hint: "Сходка/драка и человек в кадре.",
    algorithms: ["fight", "presence"] as SchoolAlgorithmId[],
  },
] as const;

export function algorithmIsOn(triggers: readonly string[], algoId: string): boolean {
  const algo = SCHOOL_ALGORITHMS.find((item) => item.id === algoId);
  if (!algo) return false;
  return algo.triggers.some((t) => triggers.includes(t));
}

export function setAlgorithm(
  triggers: readonly string[],
  algoId: string,
  on: boolean,
): string[] {
  const algo = SCHOOL_ALGORITHMS.find((item) => item.id === algoId);
  const next = new Set(triggers);
  if (!algo) return NODE_TRIGGERS.filter((t) => next.has(t));
  if (on) {
    for (const t of algo.triggers) next.add(t);
  } else {
    for (const t of algo.triggers) next.delete(t);
  }
  return NODE_TRIGGERS.filter((t) => next.has(t));
}

export function triggersFromAlgorithms(algoIds: readonly string[]): string[] {
  const next = new Set<string>();
  for (const algo of SCHOOL_ALGORITHMS) {
    if (algoIds.includes(algo.id)) {
      for (const t of algo.triggers) next.add(t);
    }
  }
  return NODE_TRIGGERS.filter((t) => next.has(t));
}

export function sameTriggerSet(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const left = new Set(a);
  return b.every((item) => left.has(item));
}

export function presetIsActive(
  triggers: readonly string[],
  presetId: string,
): boolean {
  const preset = PRESETS.find((item) => item.id === presetId);
  if (!preset) return false;
  return sameTriggerSet(triggers, triggersFromAlgorithms(preset.algorithms));
}

export function selectedAlgorithmCount(triggers: readonly string[]): number {
  return SCHOOL_ALGORITHMS.filter((algo) => algorithmIsOn(triggers, algo.id)).length;
}

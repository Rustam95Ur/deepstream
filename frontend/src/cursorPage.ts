import { computed, ref } from "vue";

export const PAGE_SIZE = 10;
export const HISTORY_PAGE_SIZE = 10;

export function useCursorPage() {
  const cursor = ref("");
  const prevCursors = ref<string[]>([]);
  const nextCursor = ref("");

  const canPrev = computed(() => prevCursors.value.length > 0);
  const canNext = computed(() => Boolean(nextCursor.value));

  function resetPage() {
    cursor.value = "";
    prevCursors.value = [];
    nextCursor.value = "";
  }

  function setNext(value: string | null | undefined) {
    nextCursor.value = value || "";
  }

  function goNext() {
    if (!nextCursor.value) return false;
    prevCursors.value.push(cursor.value);
    cursor.value = nextCursor.value;
    return true;
  }

  function goPrev() {
    if (!prevCursors.value.length) return false;
    cursor.value = prevCursors.value.pop() || "";
    return true;
  }

  return { cursor, canPrev, canNext, resetPage, setNext, goNext, goPrev };
}

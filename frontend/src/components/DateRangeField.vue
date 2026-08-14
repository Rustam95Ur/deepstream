<script setup lang="ts">
import flatpickr from "flatpickr";
import { Russian } from "flatpickr/dist/l10n/ru.js";
import "flatpickr/dist/flatpickr.min.css";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Instance } from "flatpickr/dist/types/instance";

const props = withDefaults(
  defineProps<{
    id: string;
    label: string;
    from: string;
    to: string;
    placeholder?: string;
  }>(),
  { placeholder: "Выберите период" },
);

const emit = defineEmits<{
  "update:from": [value: string];
  "update:to": [value: string];
}>();

const input = ref<HTMLInputElement | null>(null);
let picker: Instance | null = null;

function formatYmd(date: Date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function currentValue() {
  return picker?.selectedDates.map(formatYmd) ?? [];
}

function applyDates(from: string, to: string) {
  if (!picker) return;
  const selected = currentValue();
  if (!from && !to) {
    if (selected.length) picker.clear();
    return;
  }
  if (from && to) {
    if (selected[0] === from && selected[1] === to) return;
    picker.setDate([from, to], false);
    return;
  }
  if (from && selected[0] !== from) picker.setDate([from], false);
}

function emitRange(dates: Date[]) {
  if (!dates.length) {
    emit("update:from", "");
    emit("update:to", "");
    return;
  }
  if (dates.length === 1) {
    const day = formatYmd(dates[0]);
    emit("update:from", day);
    emit("update:to", day);
    return;
  }
  emit("update:from", formatYmd(dates[0]));
  emit("update:to", formatYmd(dates[1]));
}

onMounted(() => {
  if (!input.value) return;
  picker = flatpickr(input.value, {
    locale: Russian,
    altInput: true,
    altFormat: "j F Y",
    dateFormat: "Y-m-d",
    mode: "range",
    disableMobile: true,
    allowInput: false,
    altInputClass: "date-range-alt",
    defaultDate: props.from && props.to ? [props.from, props.to] : undefined,
    onChange(selectedDates) {
      if (selectedDates.length === 2 || selectedDates.length === 0) {
        emitRange(selectedDates);
      }
    },
    onClose(selectedDates) {
      if (selectedDates.length === 1) {
        picker?.setDate([selectedDates[0], selectedDates[0]], false);
        emitRange([selectedDates[0], selectedDates[0]]);
      }
    },
  });
  if (picker.altInput) {
    picker.input.removeAttribute("id");
    picker.altInput.id = props.id;
  }
});

watch(
  () => [props.from, props.to] as const,
  ([from, to]) => applyDates(from, to),
);

onBeforeUnmount(() => {
  picker?.destroy();
  picker = null;
});
</script>

<template>
  <div class="ig date-range-field">
    <label class="form-label" :for="id">{{ label }}</label>
    <div class="date-range-control">
      <input
        :id="id"
        ref="input"
        type="text"
        :placeholder="placeholder"
        autocomplete="off"
        readonly
      />
      <span class="date-range-icon" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <rect x="3.5" y="5" width="17" height="16" rx="3" stroke="currentColor" stroke-width="1.7" />
          <path d="M8 3.5v3.5M16 3.5v3.5M3.5 10h17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
        </svg>
      </span>
    </div>
  </div>
</template>

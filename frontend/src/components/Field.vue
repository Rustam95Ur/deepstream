<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    id: string;
    label: string;
    type?: string;
    modelValue: string | number;
    required?: boolean;
    step?: string | number;
    autocomplete?: string;
    addon?: string;
    invalid?: boolean;
    readonly?: boolean;
    minlength?: number;
    maxlength?: number;
    hint?: string;
  }>(),
  { type: "text" },
);

const emit = defineEmits<{
  "update:modelValue": [value: string | number];
}>();

function onInput(event: Event) {
  if (props.readonly) return;
  const el = event.target as HTMLInputElement;
  if (props.type === "number") {
    emit("update:modelValue", el.value === "" ? 0 : Number(el.value));
    return;
  }
  emit("update:modelValue", el.value);
}
</script>

<template>
  <div class="ig" :class="{ 'has-addon': !!addon }">
    <label class="form-label" :for="id">{{ label }}</label>
    <p v-if="hint" class="field-hint">{{ hint }}</p>
    <span v-if="addon" class="ig-addon">{{ addon }}</span>
    <div class="form-floating">
      <input
        :id="id"
        :type="type"
        :value="modelValue"
        :required="required"
        :step="step"
        :autocomplete="autocomplete"
        :aria-invalid="invalid ? true : undefined"
        :placeholder="label"
        :readonly="readonly"
        :minlength="minlength"
        :maxlength="maxlength"
        @input="onInput"
      />
    </div>
  </div>
</template>

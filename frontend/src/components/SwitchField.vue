<script setup lang="ts">
defineProps<{
  id: string;
  label: string;
  modelValue: boolean;
  compact?: boolean;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
}>();
</script>

<template>
  <label class="switch" :class="{ compact }" :for="id">
    <input
      :id="id"
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      :aria-label="label"
      @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
    />
    <span class="switch-ui" aria-hidden="true"></span>
    <span v-if="!compact">{{ label }}</span>
  </label>
</template>

<script setup lang="ts">
defineProps<{
  id: string;
  label: string;
  modelValue: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
}>();
</script>

<template>
  <label class="switch" :for="id">
    <input
      :id="id"
      type="checkbox"
      :checked="modelValue"
      @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
    />
    <span class="switch-ui" aria-hidden="true"></span>
    {{ label }}
  </label>
</template>

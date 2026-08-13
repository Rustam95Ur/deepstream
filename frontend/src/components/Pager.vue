<script setup lang="ts">
defineProps<{
  canPrev: boolean;
  canNext: boolean;
  disabled?: boolean;
}>();

defineEmits<{
  prev: [];
  next: [];
}>();
</script>

<template>
  <div v-if="canPrev || canNext" class="pager">
    <button type="button" class="ghost" :disabled="disabled || !canPrev" @click="$emit('prev')">Назад</button>
    <button type="button" class="ghost" :disabled="disabled || !canNext" @click="$emit('next')">Далее</button>
  </div>
</template>

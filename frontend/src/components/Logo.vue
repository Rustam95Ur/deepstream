<script setup lang="ts">
withDefaults(
  defineProps<{
    height?: number;
    inverse?: boolean;
  }>(),
  { height: 40 },
);
</script>

<template>
  <svg
    :height="height"
    viewBox="0 0 40 40"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <rect x="2" y="10" width="10" height="22" rx="3" :fill="inverse ? '#fff' : 'currentColor'" />
    <rect x="15" y="4" width="10" height="32" rx="3" :fill="inverse ? 'rgb(255 255 255 / 0.55)' : '#E8E9ED'" />
    <rect x="28" y="14" width="10" height="18" rx="3" :fill="inverse ? '#fff' : 'currentColor'" />
  </svg>
</template>

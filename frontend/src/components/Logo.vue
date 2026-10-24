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
  <img
    class="nexus-logo"
    src="/logo.png"
    alt=""
    :height="height"
    :style="inverse ? { filter: 'brightness(0) invert(1)' } : undefined"
  />
</template>

<style scoped>
.nexus-logo {
  display: block;
  width: auto;
}
</style>

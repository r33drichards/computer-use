<script setup lang="ts">
import { useColorMode } from '@vueuse/core'

// Share VitePress's storage key and automatic device-theme tracking.
const { store } = useColorMode({ storageKey: 'vitepress-theme-appearance' })
</script>

<template>
  <label class="theme-settings">
    Theme
    <select v-model="store" aria-label="Theme">
      <option value="light">Light</option>
      <option value="dark">Dark</option>
      <option value="auto">System</option>
    </select>
  </label>
</template>

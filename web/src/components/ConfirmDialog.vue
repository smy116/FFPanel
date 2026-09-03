<script setup lang="ts">
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'

defineProps<{ open: boolean; title: string; description: string; confirmLabel: string; danger?: boolean; busy?: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean]; confirm: [] }>()
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="dialog-overlay" />
      <DialogContent class="dialog-content">
        <DialogTitle class="dialog-title">{{ title }}</DialogTitle>
        <DialogDescription class="dialog-description">{{ description }}</DialogDescription>
        <div class="dialog-actions">
          <DialogClose class="secondary-button">取消</DialogClose>
          <button :class="danger ? 'danger-button' : 'primary-button'" :disabled="busy" @click="emit('confirm')">
            {{ busy ? '处理中…' : confirmLabel }}
          </button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>


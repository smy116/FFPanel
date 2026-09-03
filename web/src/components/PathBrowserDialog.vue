<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronLeft, FileVideo2, Folder, LoaderCircle, X } from 'lucide-vue-next'
import { DialogContent, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import { api } from '../api'
import type { BrowseEntry, StorageLocation } from '../types'

const props = defineProps<{ open: boolean; location: StorageLocation }>()
const emit = defineEmits<{ 'update:open': [value: boolean]; select: [value: StorageLocation] }>()
const current = ref('')
const entries = ref<BrowseEntry[]>([])
const loading = ref(false)
const error = ref('')
const normalized = computed<StorageLocation>(() => ({ ...props.location, path: current.value }))

watch(() => props.open, (value) => {
  if (value) { current.value = props.location.path; void load() }
})

async function load() {
  loading.value = true; error.value = ''
  try { entries.value = await api.browse(normalized.value) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '目录读取失败'; entries.value = [] }
  finally { loading.value = false }
}
function openEntry(entry: BrowseEntry) { if (entry.isDir) { current.value = entry.path; void load() } }
function parent() {
  const parts = current.value.replace(/\\/g, '/').replace(/\/$/, '').split('/')
  if (props.location.kind === 'rclone') current.value = parts.slice(0, -1).join('/')
  else current.value = parts.length <= 2 ? current.value : parts.slice(0, -1).join('/') || '/'
  void load()
}
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal><DialogOverlay class="dialog-overlay" />
      <DialogContent class="dialog-content browser-dialog">
        <div class="dialog-heading"><DialogTitle class="dialog-title">选择目录</DialogTitle><button class="icon-button" @click="emit('update:open', false)"><X :size="18" /></button></div>
        <div class="browser-toolbar"><button class="icon-button" title="上级目录" @click="parent"><ChevronLeft :size="18" /></button><code>{{ current || '/' }}</code></div>
        <div class="browser-list">
          <div v-if="loading" class="browser-state"><LoaderCircle class="spin" :size="22" />正在读取目录</div>
          <div v-else-if="error" class="browser-state error-text">{{ error }}</div>
          <button v-for="entry in entries" v-else :key="entry.path" :disabled="!entry.isDir" @dblclick="openEntry(entry)" @click="entry.isDir && openEntry(entry)">
            <Folder v-if="entry.isDir" :size="19" /><FileVideo2 v-else :size="19" /><span>{{ entry.name }}</span><small>{{ entry.isDir ? '目录' : '文件' }}</small>
          </button>
          <div v-if="!loading && !error && !entries.length" class="browser-state">空目录</div>
        </div>
        <div class="dialog-actions"><button class="secondary-button" @click="emit('update:open', false)">取消</button><button class="primary-button" @click="emit('select', normalized); emit('update:open', false)">选择当前目录</button></div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>


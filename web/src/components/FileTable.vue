<script setup lang="ts">
import { computed, ref, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import type { CompanionFile, TaskFile } from '../types'
import FileDetailDialog from './FileDetailDialog.vue'

const props = defineProps<{ files: TaskFile[]; companions: CompanionFile[] }>()
const parentRef = ref<HTMLElement | null>(null)
type FileRow = (TaskFile & { kind: 'video' }) | (CompanionFile & { kind: 'companion' })
const rows = computed<FileRow[]>(() => [
  ...props.files.map((item) => ({ ...item, kind: 'video' as const })),
  ...props.companions.map((item) => ({ ...item, kind: 'companion' as const })),
])
const virtualizer = useVirtualizer(computed(() => ({
  count: rows.value.length,
  getScrollElement: () => parentRef.value,
  estimateSize: () => 47,
  getItemKey: (index) => rows.value[index]?.id ?? index,
  overscan: 8,
})))
const selectedId = ref<string | null>(null)
const selectedFile = computed(() => rows.value.find((row) => row.id === selectedId.value) ?? null)
const stageLabel: Record<string, string> = { pending: '等待', downloading: '下载', probing: '预检', transcoding: '转码', upload_queued: '待上传', uploading: '上传', copying: '复制', completed: '完成', failed: '失败', interrupted: '中断', skipped: '跳过' }
function measureRow(node: Element | ComponentPublicInstance | null) {
  if (node instanceof Element) virtualizer.value.measureElement(node)
}
function openDetails(row: FileRow) { selectedId.value = row.id }
function closeDetails(open: boolean) { if (!open) selectedId.value = null }
</script>

<template>
  <div class="file-table">
    <div class="file-table-head"><span>文件</span><span>类型</span><span>状态</span><span>尝试</span></div>
    <div ref="parentRef" class="file-table-scroll">
      <div class="virtual-space" :style="{ height: `${virtualizer.getTotalSize()}px` }">
        <div v-for="virtualRow in virtualizer.getVirtualItems()" :key="rows[virtualRow.index]!.id" :data-index="virtualRow.index" :ref="measureRow" class="file-row-wrap" :style="{ transform: `translateY(${virtualRow.start}px)` }">
          <button class="file-row" @click="openDetails(rows[virtualRow.index]!)">
            <span :title="rows[virtualRow.index]!.relativePath">{{ rows[virtualRow.index]!.relativePath }}</span>
            <span>{{ rows[virtualRow.index]!.kind === 'video' ? '视频' : '伴随文件' }}</span>
            <span><i :class="`stage-dot ${rows[virtualRow.index]!.stage}`"></i>{{ stageLabel[rows[virtualRow.index]!.stage] }}</span>
            <span>#{{ rows[virtualRow.index]!.attempt }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
  <FileDetailDialog :open="selectedFile !== null" :file="selectedFile" @update:open="closeDetails" />
</template>


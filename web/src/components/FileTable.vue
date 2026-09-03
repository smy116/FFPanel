<script setup lang="ts">
import { computed, ref } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import type { CompanionFile, TaskFile } from '../types'
import ParameterDecisionPanel from './ParameterDecisionPanel.vue'

const props = defineProps<{ files: TaskFile[]; companions: CompanionFile[] }>()
const parentRef = ref<HTMLElement | null>(null)
const rows = computed(() => [
  ...props.files.map((item) => ({ ...item, kind: 'video' as const })),
  ...props.companions.map((item) => ({ ...item, kind: 'companion' as const })),
])
const virtualizer = useVirtualizer(computed(() => ({
  count: rows.value.length,
  getScrollElement: () => parentRef.value,
  estimateSize: () => 47,
  overscan: 8,
})))
const expanded = ref<string | null>(null)
const stageLabel: Record<string, string> = { pending: '等待', downloading: '下载', probing: '预检', transcoding: '转码', upload_queued: '待上传', uploading: '上传', copying: '复制', completed: '完成', failed: '失败', interrupted: '中断', skipped: '跳过' }
</script>

<template>
  <div ref="parentRef" class="file-table-scroll">
    <div class="file-table-head"><span>文件</span><span>类型</span><span>状态</span><span>尝试</span></div>
    <div class="virtual-space" :style="{ height: `${virtualizer.getTotalSize()}px` }">
      <div v-for="virtualRow in virtualizer.getVirtualItems()" :key="rows[virtualRow.index]!.id" class="file-row-wrap" :style="{ transform: `translateY(${virtualRow.start}px)` }">
        <button class="file-row" @click="expanded = expanded === rows[virtualRow.index]!.id ? null : rows[virtualRow.index]!.id">
          <span :title="rows[virtualRow.index]!.relativePath">{{ rows[virtualRow.index]!.relativePath }}</span>
          <span>{{ rows[virtualRow.index]!.kind === 'video' ? '视频' : '伴随文件' }}</span>
          <span><i :class="`stage-dot ${rows[virtualRow.index]!.stage}`"></i>{{ stageLabel[rows[virtualRow.index]!.stage] }}</span>
          <span>#{{ rows[virtualRow.index]!.attempt }}</span>
        </button>
        <div v-if="expanded === rows[virtualRow.index]!.id" class="file-expanded">
          <p v-if="rows[virtualRow.index]!.lastError" class="error-text">{{ rows[virtualRow.index]!.lastError }}</p>
          <ParameterDecisionPanel v-if="rows[virtualRow.index]!.kind === 'video' && (rows[virtualRow.index] as TaskFile).parameterDecision" :decision="(rows[virtualRow.index] as TaskFile).parameterDecision!" />
        </div>
      </div>
    </div>
  </div>
</template>


<script setup lang="ts">
import { computed } from 'vue'
import { DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import { X } from 'lucide-vue-next'
import type { CompanionFile, TaskFile } from '../types'
import ParameterDecisionPanel from './ParameterDecisionPanel.vue'

type FileDetail = (TaskFile & { kind: 'video' }) | (CompanionFile & { kind: 'companion' })

const props = defineProps<{ open: boolean; file: FileDetail | null }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const selectedVideo = computed(() => props.file?.kind === 'video' ? props.file : null)
const stageLabel: Record<string, string> = { pending: '等待', downloading: '下载', probing: '预检', transcoding: '转码', upload_queued: '待上传', uploading: '上传', copying: '复制', completed: '完成', failed: '失败', interrupted: '中断', skipped: '跳过' }

function close() { emit('update:open', false) }
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="dialog-overlay" />
      <DialogContent class="dialog-content file-detail-dialog">
        <div class="dialog-heading">
          <DialogTitle class="dialog-title">文件详情</DialogTitle>
          <button class="icon-button" aria-label="关闭文件详情" @click="close"><X :size="18" /></button>
        </div>
        <DialogDescription class="file-detail-path" :title="file?.relativePath">{{ file?.relativePath }}</DialogDescription>
        <div v-if="file" class="file-detail-meta">
          <div><small>类型</small><b>{{ file.kind === 'video' ? '视频' : '伴随文件' }}</b></div>
          <div><small>状态</small><b><i :class="`stage-dot ${file.stage}`"></i>{{ stageLabel[file.stage] }}</b></div>
          <div><small>尝试</small><b>#{{ file.attempt }}</b></div>
          <div><small>大小</small><b>{{ file.sourceSize == null ? '—' : `${file.sourceSize.toLocaleString()} B` }}</b></div>
        </div>
        <p v-if="file?.lastError" class="file-detail-error">{{ file.lastError }}</p>
        <ParameterDecisionPanel v-if="selectedVideo?.parameterDecision" :decision="selectedVideo.parameterDecision" />
        <div v-else class="file-detail-empty">{{ file?.kind === 'companion' ? '伴随文件没有参数决策记录。' : '暂无参数决策记录。' }}</div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

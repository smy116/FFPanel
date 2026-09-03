<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ParameterDecision } from '../types'

const props = defineProps<{ decision: ParameterDecision }>()
const changedOnly = ref(true)
const hasFallback = computed(() => props.decision.reasons.some((reason) => reason.code === 'transcode_auto_fallback'))
const keys = computed(() => {
  const values = new Set([...Object.keys(props.decision.source || {}), ...Object.keys(props.decision.requested || {}), ...Object.keys(props.decision.effective || {})])
  return [...values].filter((key) => !changedOnly.value || JSON.stringify(props.decision.requested?.[key]) !== JSON.stringify(props.decision.effective?.[key]))
})
function value(record: Record<string, unknown> | null, key: string): string {
  const item = record?.[key]
  if (key === 'hardwareMode' && typeof item === 'string') return ({ mpp_mpp: 'MPP 硬件编解码', cpu_mpp: 'CPU 软解 + MPP 编码', cpu_cpu: 'CPU 软件编解码' } as Record<string, string>)[item] || item
  if (key === 'autoFallback' && typeof item === 'boolean') return item ? '开启' : '关闭'
  return item == null ? '—' : typeof item === 'object' ? JSON.stringify(item) : String(item)
}
</script>

<template>
  <div class="decision-panel">
    <div class="decision-toolbar"><b>{{ hasFallback ? '参数决策 · 已自动退回' : '参数决策' }}</b><label><input v-model="changedOnly" type="checkbox" />只看变化项</label></div>
    <div class="decision-table">
      <div class="decision-head"><span>字段</span><span>源参数 Source</span><span>用户参数 Requested</span><span>实际参数 Effective</span></div>
      <div v-for="key in keys" :key="key" class="decision-row"><b>{{ key }}</b><span>{{ value(decision.source, key) }}</span><span>{{ value(decision.requested, key) }}</span><span class="effective">{{ value(decision.effective, key) }}</span></div>
      <p v-if="!keys.length" class="muted-copy">没有自动调整的参数。</p>
    </div>
    <div v-if="decision.reasons.length" class="reason-list"><span v-for="(reason, index) in decision.reasons" :key="reason.code + reason.field + index">{{ reason.message }}</span></div>
    <details v-if="decision.ffmpegArgv?.length" class="argv"><summary>实际 FFmpeg 参数</summary><code>{{ decision.ffmpegArgv.join(' ') }}</code></details>
  </div>
</template>


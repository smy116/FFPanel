<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ParameterDecision } from '../types'

const props = defineProps<{ decision: ParameterDecision }>()
const changedOnly = ref(true)
const keys = computed(() => {
  const values = new Set([...Object.keys(props.decision.source || {}), ...Object.keys(props.decision.requested || {}), ...Object.keys(props.decision.effective || {})])
  return [...values].filter((key) => !changedOnly.value || JSON.stringify(props.decision.requested?.[key]) !== JSON.stringify(props.decision.effective?.[key]))
})
function value(record: Record<string, unknown> | null, key: string): string {
  const item = record?.[key]
  return item == null ? '—' : typeof item === 'object' ? JSON.stringify(item) : String(item)
}
</script>

<template>
  <div class="decision-panel">
    <div class="decision-toolbar"><b>参数决策</b><label><input v-model="changedOnly" type="checkbox" />只看变化项</label></div>
    <div class="decision-table">
      <div class="decision-head"><span>字段</span><span>源参数 Source</span><span>用户参数 Requested</span><span>实际参数 Effective</span></div>
      <div v-for="key in keys" :key="key" class="decision-row"><b>{{ key }}</b><span>{{ value(decision.source, key) }}</span><span>{{ value(decision.requested, key) }}</span><span class="effective">{{ value(decision.effective, key) }}</span></div>
      <p v-if="!keys.length" class="muted-copy">没有自动调整的参数。</p>
    </div>
    <div v-if="decision.reasons.length" class="reason-list"><span v-for="reason in decision.reasons" :key="reason.code + reason.field">{{ reason.message }}</span></div>
    <details v-if="decision.ffmpegArgv?.length" class="argv"><summary>实际 FFmpeg 参数</summary><code>{{ decision.ffmpegArgv.join(' ') }}</code></details>
  </div>
</template>


<script setup lang="ts">
import { computed, onMounted } from "vue";
import { Cpu, Plus, RadioTower, Rows3 } from "lucide-vue-next";
import { RouterLink, RouterView } from "vue-router";
import { useTasksStore } from "./stores/tasks";
import { hardwareGroups, statusLabel } from "./hardware";

const store = useTasksStore();
const groups = computed(() => hardwareGroups(store.system));
const hardwareBrand = computed(() => groups.value.map(group => group.label).join(' · '));
onMounted(() => {
  void Promise.all([store.loadSnapshot(), store.loadRemotes()]);
  store.connectEvents();
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-inner">
        <RouterLink to="/new" class="brand" aria-label="FFPanel 首页">
          <span class="brand-mark"><Cpu :size="21" /></span>
          <span>FFPanel</span>
          <span class="hardware-badge">{{ hardwareBrand }}</span>
        </RouterLink>
        <nav class="nav-tabs" aria-label="主导航">
          <RouterLink to="/new"><Plus :size="17" />新建转码任务</RouterLink>
          <RouterLink to="/tasks"
            ><Rows3 :size="17" />任务清单
            <span class="nav-count">{{ store.pendingCount }}</span></RouterLink
          >
        </nav>
        <div class="heartbeat" :class="{ online: store.connected }">
          <RadioTower :size="16" /><span>{{
            store.connected
              ? `CPU ${store.system.cpuPercent?.toFixed(0) || 0}% · RAM ${store.system.memoryPercent?.toFixed(0) || 0}%`
              : "正在连接"
          }}</span>
        </div>
      </div>
    </header>
    <main class="main-container"><RouterView /></main>
    <footer class="statusbar">
      <details v-for="group in groups" :key="group.id" class="hardware-status">
        <summary><span class="status-dot" :class="{ muted: group.status !== 'ready' }"></span>{{ group.label }} · {{ statusLabel(group.status) }}</summary>
        <div class="hardware-status-details"><p v-for="(detail, index) in group.details" :key="index">{{ detail }}</p></div>
      </details>
      <div class="status-remotes">Rclone · {{ store.remotes.length }} Remotes</div>
      <div class="status-version">FFPanel v1.0.0</div>
    </footer>
  </div>
</template>

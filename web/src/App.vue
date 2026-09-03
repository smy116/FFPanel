<script setup lang="ts">
import { computed, onMounted } from "vue";
import { Cpu, Plus, RadioTower, Rows3 } from "lucide-vue-next";
import { RouterLink, RouterView } from "vue-router";
import { useTasksStore } from "./stores/tasks";

const store = useTasksStore();
const hardwareState = computed(() =>
  store.system.mppAvailable
    ? "Ready"
    : store.system.error
      ? "Unavailable"
      : "Detecting",
);
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
          <span class="hardware-badge">Rockchip Accelerated</span>
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
      <div>
        <span
          class="status-dot"
          :class="{ muted: !store.system.mppAvailable }"
        ></span
        >MPP · {{ hardwareState }}
      </div>
      <div>
        <span
          class="status-dot"
          :class="{ muted: !store.system.rgaAvailable }"
        ></span
        >RGA · {{ store.system.rgaAvailable ? "Ready" : "Unavailable" }}
      </div>
      <div>Rclone · {{ store.remotes.length }} Remotes</div>
      <div class="status-version">FFPanel v1.0.0</div>
    </footer>
  </div>
</template>

<template>
  <div id="app" :class="{ 'theme-dark': isDarkTheme }">
    <Sidebar />
    <div class="main-content" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
      <router-view />
    </div>
  </div>
</template>

<script>
import Sidebar from '@/components/Layout/Sidebar'

export default {
  name: 'App',
  components: {
    Sidebar
  },
  computed: {
    isDarkTheme() {
      return true
    },
    sidebarCollapsed() {
      return this.$store.state.sidebarCollapsed
    }
  }
}
</script>

<style>
#app {
  min-height: 100vh;
  background: #141414;
  display: flex;
}

.theme-dark {
  background: #141414;
  color: #d1d4dc;
}

.main-content {
  flex: 1;
  margin-left: 200px;
  min-height: 100vh;
  transition: margin-left 0.3s;
}

.main-content.sidebar-collapsed {
  margin-left: 64px;
}
</style>

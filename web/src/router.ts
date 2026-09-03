import { createRouter, createWebHistory } from 'vue-router'
import NewTaskView from './views/NewTaskView.vue'
import TasksView from './views/TasksView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/new' },
    { path: '/new', component: NewTaskView },
    { path: '/tasks', component: TasksView },
  ],
})

import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import JobDetailView from './views/JobDetailView.vue'
import VoucherView from './views/VoucherView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/vouchers', name: 'vouchers', component: VoucherView },
    { path: '/jobs/:id', name: 'job-detail', component: JobDetailView, props: true },
  ],
})

export default router

import { createApp } from 'vue';
import { createPinia } from 'pinia';
import DashboardView from './views/DashboardView.vue';

createApp(DashboardView).use(createPinia()).mount('#app');

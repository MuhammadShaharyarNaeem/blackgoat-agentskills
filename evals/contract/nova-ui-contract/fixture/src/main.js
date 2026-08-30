import { createApp } from 'vue';
import SupplierDetail from './views/SupplierDetail.vue';

const app = createApp(SupplierDetail, { supplierId: 1 });
app.mount('#app');

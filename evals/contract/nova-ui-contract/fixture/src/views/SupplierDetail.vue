<script setup>
import { ref, onMounted } from 'vue';
import { getSupplier } from '../api/client.js';

const props = defineProps({
  supplierId: { type: Number, required: true }
});

const supplier = ref(null);

onMounted(async () => {
  supplier.value = await getSupplier(props.supplierId);
});
</script>

<template>
  <main class="supplier-detail" data-test="supplier-detail">
    <header class="supplier-detail__header">
      <h1 data-test="supplier-name">{{ supplier ? supplier.name : '…' }}</h1>
    </header>

    <!-- Task 1 (Milestone 1): the ContactsPanel mounts here. -->
  </main>
</template>

<style scoped>
.supplier-detail {
  max-width: 64rem;
  margin: 0 auto;
  padding: var(--space-6, 2.5rem) var(--space-4, 1.5rem);
}

.supplier-detail__header {
  border-bottom: 2px solid var(--color-ink, #16211c);
  padding-bottom: var(--space-3, 1rem);
}
</style>

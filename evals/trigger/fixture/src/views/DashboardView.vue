<template>
  <section data-test="dashboard">
    <input v-model="q" data-test="account-search" placeholder="Search accounts" />
    <ul><li v-for="a in results" :key="a.id">{{ a.name }}</li></ul>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue';
import { searchAccounts } from '../api/client.js';

const q = ref('');
const results = ref([]);

// No debounce, no server-side paging: every keystroke round-trips the full account set.
watch(q, async (value) => {
  const { data } = await searchAccounts(value);
  results.value = data.items;
});
</script>

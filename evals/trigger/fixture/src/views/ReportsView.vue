<template>
  <section data-test="reports">
    <input v-model="from" type="date" data-test="range-from" />
    <input v-model="to" type="date" data-test="range-to" />
    <button data-test="export-btn" @click="onExport">Export CSV</button>
  </section>
</template>

<script setup>
import { ref } from 'vue';
import { exportReport } from '../api/client.js';

const from = ref('');
const to = ref('');

// Sends whatever is in the inputs, empty strings included.
const onExport = () => exportReport(from.value, to.value);
</script>

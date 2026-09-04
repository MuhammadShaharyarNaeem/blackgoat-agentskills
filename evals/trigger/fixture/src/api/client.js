import axios from 'axios';
import { config } from '../config.js';

export const api = axios.create({
  baseURL: config.apiBaseUrl,
  timeout: config.requestTimeoutMs,
});

export const searchAccounts = (q) => api.get('/accounts/search', { params: { q } });
export const exportReport = (from, to) => api.get('/reports/export', { params: { from, to } });

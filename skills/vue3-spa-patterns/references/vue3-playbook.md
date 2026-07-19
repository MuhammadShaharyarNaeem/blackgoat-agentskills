# Vue 3 Playbook — Code Patterns

GOOD/BAD examples for each contract rule. TypeScript throughout.

## 1. State Mutation Boundary — Pinia Actions Only

```ts
// stores/cart.ts
export const useCartStore = defineStore('cart', {
  state: () => ({ items: [] as CartItem[] }),
  getters: {
    total: (s) => s.items.reduce((sum, i) => sum + i.price * i.qty, 0),
  },
  actions: {
    addItem(item: CartItem) {
      const existing = this.items.find((i) => i.sku === item.sku)
      existing ? existing.qty++ : this.items.push(item)
    },
  },
})
```

```vue
<!-- GOOD: component calls the action -->
<script setup lang="ts">
const cart = useCartStore()
const { items, total } = storeToRefs(cart)
function onAdd(item: CartItem) { cart.addItem(item) }
</script>
```

```ts
// BAD: component mutates store state directly — violates the state-mutation boundary
cart.items.push(item)          // NO
cart.$patch({ items: [...] })  // NO (from a component)
```

## 2. Typed Props / Emits

```vue
<script setup lang="ts">
// GOOD
interface Props { order: Order; readonly?: boolean }
const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'confirm', id: string): void }>()
</script>
```

```js
// BAD: untyped runtime declarations in new code
const props = defineProps(['order', 'readonly'])
```

## 3. Composable Extraction (Rule of Three)

Third component needing paginated fetching → extract:

```ts
// composables/usePagedQuery.ts
export function usePagedQuery<T>(fetcher: (page: number) => Promise<Paged<T>>) {
  const page = ref(1)
  const rows = shallowRef<T[]>([])       // large list: shallowRef
  const loading = ref(false)
  async function load() {
    loading.value = true
    try { rows.value = (await fetcher(page.value)).items }
    finally { loading.value = false }
  }
  watch(page, load, { immediate: true }) // side effect: legitimate watch
  return { page, rows, loading, reload: load }
}
```

Do NOT extract on first use — inline logic in one component stays in that component.

## 4. The Shared Axios Instance — Response Pattern + Refresh Queueing

```ts
// api/http.ts — the ONE instance
import axios from 'axios'

// Backend's standardized envelope — mirrors the WIRE shape of BaseResponse<T> in
// BG.Infrastructure.Core: C# PascalCase records serialize to camelCase under ASP.NET Core's
// default JsonSerializerDefaults.Web (see dotnet-backend-patterns/references/response-and-errors.md)
interface ApiNotification { code: string; message: string; propertyName?: string; actionHint?: string }
interface BaseResponse<T> {
  statusCode: number
  isSuccess: boolean
  data: T
  dataContext?: Record<string, unknown>   // e.g. pagination
  notifications: ApiNotification[]
}

export const http = axios.create({ baseURL: import.meta.env.VITE_API_URL })

// Auth header centralized
http.interceptors.request.use((config) => {
  const token = useAuthStore().accessToken
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Refresh-token queueing state
let refreshing: Promise<string> | null = null

http.interceptors.response.use(
  // Unwrap the Response Pattern: callers get `Data`, never the envelope
  (res) => {
    const body = res.data as BaseResponse<unknown>
    if (body.isSuccess === false) return Promise.reject(new ApiError(body.notifications))
    res.data = body.data
    return res
  },
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retried) {
      original._retried = true
      // All concurrent 401s await the SAME refresh — no refresh stampede
      refreshing ??= useAuthStore().refreshTokens().finally(() => { refreshing = null })
      const newToken = await refreshing
      original.headers.Authorization = `Bearer ${newToken}`
      return http(original) // replay
    }
    return Promise.reject(error)
  },
)
```

Each notification's `code` is a 6-digit ErrorCode whose TT segment (ErrorTypeCodes 01-05) tells the UI
how to surface it — inline field error (01), popup (02), toast (03), redirect (04), or silent (05) —
per `dotnet-backend-patterns/references/response-and-errors.md`.

```ts
// BAD: ad-hoc clients scattered through components
const res = await fetch('/api/orders')            // NO
const client = axios.create({ ... })              // NO — second instance
const { data } = await axios.get('/api/orders')   // NO — bypasses interceptors
```

## 5. data-test IDs on Every Interactive Element

```vue
<!-- GOOD: Playwright selectors survive any restyle -->
<button data-test="order-submit" @click="onSubmit">Submit</button>
<input data-test="order-search" v-model="query" />
<select data-test="order-status-filter" v-model="status">...</select>
```

```ts
// Playwright side
await page.getByTestId('order-submit').click()
```

```vue
<!-- BAD: selector coupled to styling/text — breaks on redesign -->
<button class="btn btn-primary mt-2">Submit</button>
<!-- page.locator('.btn-primary') / getByText('Submit')  → fragile -->
```

## 6. Route-Level Lazy Loading

```ts
// router/index.ts
const routes = [
  { path: '/', component: HomeView },                                   // critical: eager
  { path: '/reports', component: () => import('@/views/ReportsView.vue') }, // GOOD: lazy
  { path: '/admin', component: () => import('@/views/AdminView.vue') },
]
```

```ts
// BAD: everything eagerly imported — one giant entry bundle
import ReportsView from '@/views/ReportsView.vue'
import AdminView from '@/views/AdminView.vue'
```

## 7. Computed vs Watch Anti-Pattern

```ts
// BAD: watcher manually maintaining derived state
const fullName = ref('')
watch([first, last], () => { fullName.value = `${first.value} ${last.value}` })

// GOOD: derived state is computed — cached, lazy, always consistent
const fullName = computed(() => `${first.value} ${last.value}`)
```

Legitimate `watch`: genuine side effects only (fetch on param change, persist to storage, imperative library calls).

```ts
// v-memo: ONLY with profiling evidence of a render hotspot
<tr v-for="row in rows" :key="row.id" v-memo="[row.updatedAt]">
```

If you cannot point at a profiler flame chart, do not add `v-memo`.

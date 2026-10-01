<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const boosts = ref<any[]>([])
onMounted(async () => {
  const data = await api('/allocate/latest?segment_id=1')
  rows.value = data.rejected || []
  boosts.value = data.boosts || []
})
</script>
<template>
  <h1>放不下</h1>
  <p class="sub">无法在连续空档内安置且不跨越挡柱的摊位 · 排队次序按本轮生效优先</p>
  <p v-if="boosts.length" class="sub">
    本轮临时抬优先：{{ boosts.map(b => `#${b.vendor_id} → ${b.priority}`).join('，') }}
  </p>
  <div class="card">
    <table>
      <thead><tr><th>摊主</th><th>需求宽度</th><th>登记优先</th><th>本轮临时</th><th>生效优先</th><th>原因</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.vendor_id">
          <td>{{ r.vendor_name }}</td><td>{{ r.width_m }}</td>
          <td>{{ r.priority }}</td>
          <td>{{ r.temp_priority ?? '—' }}</td>
          <td>{{ r.effective_priority }}</td>
          <td>{{ r.reason }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">全部放下</p>
  </div>
</template>

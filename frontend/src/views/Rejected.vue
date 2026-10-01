<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errDetail, isNotFound } from '../api'
const rows = ref<any[]>([])
const loaded = ref(false)
const notConfirmed = ref(false)
const errorMsg = ref('')
onMounted(async () => {
  try {
    const data = await api('/allocate/latest?segment_id=1')
    rows.value = data.rejected || []
    loaded.value = true
  } catch (e) {
    if (isNotFound(e)) { notConfirmed.value = true; loaded.value = true }
    else errorMsg.value = errDetail(e)
  }
})
</script>
<template>
  <h1>放不下</h1>
  <p class="sub">最近一次<b>已确认入库</b>轮次里，无法在连续空档内安置且不跨越挡柱的摊位（现算预览不计入）</p>
  <div v-if="errorMsg" class="ss-banner ss-banner-bad">{{ errorMsg }}</div>
  <div v-if="notConfirmed" class="card"><p class="muted">尚未确认入库，暂无放不下名单。请先到「分配带」确认一轮。</p></div>
  <div class="card" v-else-if="loaded">
    <table>
      <thead><tr><th>摊主</th><th>需求宽度</th><th>登记</th><th>临时</th><th>本轮生效</th><th>原因</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.vendor_id">
          <td>{{ r.vendor_name }}</td><td>{{ r.width_m }}</td>
          <td>{{ r.registered_priority ?? '—' }}</td>
          <td><span v-if="r.temp_priority != null" class="badge badge-warn">{{ r.temp_priority }}</span><span v-else class="muted">—</span></td>
          <td>{{ r.effective_priority ?? '—' }}</td>
          <td>{{ r.reason }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">全部放下</p>
  </div>
</template>

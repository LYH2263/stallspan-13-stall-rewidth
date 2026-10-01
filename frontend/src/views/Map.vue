<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const data = ref<any>(null)
const vendors = ref<any[]>([])
const drawerOpen = ref(false)
const errorMsg = ref('')
// 本轮临时优先表：vendor_id -> 1..9；只影响本轮现算或确认，不写回登记
const boostDraft = ref<Record<number, number | null>>({})

function boostList() {
  return Object.entries(boostDraft.value)
    .filter(([, p]) => p !== null && p !== undefined)
    .map(([id, p]) => ({ vendor_id: Number(id), priority: Number(p) }))
}

async function run(commit = true) {
  errorMsg.value = ''
  try {
    data.value = await api('/allocate/run?segment_id=1', {
      method: 'POST',
      body: JSON.stringify({ boosts: boostList(), commit }),
    })
  } catch (e: any) {
    // 整次拒绝：后端未做任何写入，页面保留上一次结果，只提示原因
    errorMsg.value = e?.message || '分配请求被拒绝'
  }
}

// 清除临时：清空本轮临时表并立即按登记优先重分入库，禁止继续吃临时缓存
async function clearBoosts() {
  boostDraft.value = {}
  await run(true)
}

onMounted(async () => {
  vendors.value = await api('/vendors')
  await run()
})

const boostedCount = computed(() => boostList().length)
const runBoosts = computed<Record<number, number>>(() => {
  const m: Record<number, number> = {}
  for (const b of data.value?.boosts || []) m[b.vendor_id] = b.priority
  return m
})

const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
const cells = computed(() => {
  if (!data.value) return []
  const width = data.value.segment.width_m
  const out: any[] = []
  for (const p of data.value.pillars || []) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m/2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const [i, p] of (data.value.placements || []).entries()) {
    out.push({ type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name, color: colors[i % colors.length] })
  }
  return out.sort((a,b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})
</script>
<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">沿街一维开间 · 挡柱为竖直阻断 · 底部为摊主排队</p>
    <div class="ss-toolbar">
      <button class="btn" @click="run(true)">重新分配</button>
      <button class="btn ss-btn-ghost" @click="drawerOpen = true">本轮临时优先</button>
      <span v-if="data && !data.committed" class="badge badge-warn">预览未入库</span>
      <span v-else-if="data && data.boosts?.length" class="badge badge-warn">本轮已抬 {{ data.boosts.length }} 摊</span>
      <span v-else-if="data" class="badge badge-ok">登记优先</span>
    </div>
    <p v-if="errorMsg" class="ss-error">{{ errorMsg }}</p>
    <div class="ss-band-ruler" v-if="data">
      <span>0 m</span>
      <span>{{ data.segment.name }} · {{ data.segment.width_m }} m</span>
      <span>{{ data.segment.width_m }} m</span>
    </div>
    <div class="ss-street-band" v-if="data">
      <div class="ss-street-inner">
        <div
          v-for="(c,i) in cells" :key="i"
          class="ss-band-cell"
          :class="{ 'ss-pillar': c.type === 'pillar' }"
          :style="{ width: c.pct + '%', background: c.type === 'pillar' ? undefined : c.color, flex: '0 0 ' + c.pct + '%' }"
        >{{ c.label }}</div>
      </div>
    </div>
    <div class="ss-vendor-queue">
      <div v-for="v in vendors" :key="v.id" class="ss-vendor-chip">
        <strong>{{ v.name }}</strong>
        <span>需 {{ v.stall_width_m }} m · 登记 {{ v.priority }}<template v-if="runBoosts[v.id]"> · 本轮 {{ runBoosts[v.id] }}</template></span>
      </div>
    </div>
    <div class="card" v-if="data">
      <table>
        <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th><th>登记优先</th><th>本轮临时</th><th>生效优先</th></tr></thead>
        <tbody>
          <tr v-for="p in data.placements" :key="p.vendor_id">
            <td>{{ p.vendor_name }}</td><td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
            <td>{{ p.priority }}</td>
            <td>{{ p.temp_priority ?? '—' }}</td>
            <td>{{ p.effective_priority }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card" v-if="data && data.rejected?.length">
      <h2 class="ss-card-title">本轮放不下</h2>
      <table>
        <thead><tr><th>摊主</th><th>需求宽度</th><th>登记优先</th><th>本轮临时</th><th>生效优先</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="r in data.rejected" :key="r.vendor_id">
            <td>{{ r.vendor_name }}</td><td>{{ r.width_m }}</td>
            <td>{{ r.priority }}</td>
            <td>{{ r.temp_priority ?? '—' }}</td>
            <td>{{ r.effective_priority }}</td>
            <td>{{ r.reason }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="drawerOpen" class="ss-drawer-mask" @click.self="drawerOpen = false">
      <aside class="ss-drawer">
        <h2>本轮临时优先</h2>
        <p class="sub">只对这一次现算或确认生效，不写回登记优先；留空表示不抬。临时与登记冲突时本轮只认临时。</p>
        <table>
          <thead><tr><th>摊主</th><th>登记优先</th><th>本轮临时</th></tr></thead>
          <tbody>
            <tr v-for="v in vendors" :key="v.id">
              <td>{{ v.name }}</td>
              <td>{{ v.priority }}</td>
              <td>
                <select v-model="boostDraft[v.id]" class="ss-boost-select">
                  <option :value="null">不抬</option>
                  <option v-for="n in 9" :key="n" :value="n">{{ n }}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="ss-drawer-actions">
          <button class="btn ss-btn-ghost" @click="run(false)">现算预览</button>
          <button class="btn" @click="run(true)">确认入库</button>
          <button class="btn ss-btn-danger" :disabled="!boostedCount" @click="clearBoosts">清除临时</button>
          <button class="btn ss-btn-ghost" @click="drawerOpen = false">关闭</button>
        </div>
        <p class="muted ss-drawer-note" v-if="boostedCount">本轮将抬 {{ boostedCount }} 摊；确认后占位次序与放不下排队按临时优先。</p>
        <p class="muted ss-drawer-note" v-else>未抬任何摊：与登记优先口径一致。</p>
      </aside>
    </div>
  </div>
</template>

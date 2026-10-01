<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errDetail, isNotFound } from '../api'

interface VendorRow {
  vendor_id: number
  vendor_name: string
  width_m: number
  registered_priority: number
  temp_priority: number | null
  effective_priority: number
  status: 'placed' | 'rejected'
}
interface Round {
  id: number | null
  confirmed: boolean
  created_at: string | null
  round_token: string
  placements: any[]
  rejected: any[]
  free_spans: any[]
  vendors: VendorRow[]
  segment: { id: number; name: string; width_m: number }
  pillars: { position_m: number; thickness_m: number; label?: string }[]
}

const round = ref<Round | null>(null)
const drawerOpen = ref(false)
const tempInputs = ref<Record<string, string>>({})
const invalid = ref<Set<number>>(new Set())
const busy = ref(false)
const errorMsg = ref('')
const hint = ref('')

const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
const colorOf = (id: number) => colors[(id - 1) % colors.length]

onMounted(async () => {
  try {
    round.value = await api('/allocate/latest?segment_id=1')
  } catch (e) {
    // 尚无确认记录：发一次空 boosts 的现算，仅为取得同源摊主/优先数，不入库
    if (isNotFound(e)) {
      try { round.value = await api('/allocate/preview', { method: 'POST', body: JSON.stringify({ segment_id: 1, boosts: [] }) }) }
      catch (e2) { errorMsg.value = errDetail(e2) }
    } else {
      errorMsg.value = errDetail(e)
    }
  }
})

const cells = computed(() => {
  if (!round.value) return []
  const width = round.value.segment.width_m
  const out: any[] = []
  for (const p of round.value.pillars || []) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m / 2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const p of round.value.placements || []) {
    out.push({ type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name,
      color: colorOf(p.vendor_id), boosted: p.temp_priority != null })
  }
  return out.sort((a, b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})

/** 抽屉里实时的本轮生效值：临时合法用临时，否则回登记优先。 */
function effOf(v: VendorRow): number {
  const t = (tempInputs.value[String(v.vendor_id)] || '').trim()
  return /^[1-9]$/.test(t) ? Number(t) : v.registered_priority
}
function rawTemp(v: VendorRow): string {
  return tempInputs.value[String(v.vendor_id)] || ''
}
function onTempInput(v: VendorRow, val: string) {
  tempInputs.value[String(v.vendor_id)] = val
  invalid.value.delete(v.vendor_id)
  invalid.value = new Set(invalid.value)
  hint.value = ''
}

function gatherBoosts(): { ok: boolean; boosts: { vendor_id: number; temp_priority: number }[] } {
  const bad = new Set<number>()
  const boosts: { vendor_id: number; temp_priority: number }[] = []
  for (const v of round.value?.vendors || []) {
    const t = (tempInputs.value[String(v.vendor_id)] || '').trim()
    if (t === '') continue
    if (!/^[1-9]$/.test(t)) { bad.add(v.vendor_id); continue }
    boosts.push({ vendor_id: v.vendor_id, temp_priority: Number(t) })
  }
  invalid.value = bad
  return { ok: bad.size === 0, boosts }
}

async function callOnce(path: string, boosts: any[]) {
  return api(path, { method: 'POST', body: JSON.stringify({ segment_id: 1, boosts }) })
}

async function preview() {
  if (busy.value || !round.value) return
  const { ok, boosts } = gatherBoosts()
  if (!ok) { errorMsg.value = '本轮临时优先必须留空或填 1–9 的整数；已标红，请改后再算（整次抬升未执行）。'; return }
  busy.value = true; errorMsg.value = ''
  try {
    round.value = await callOnce('/allocate/preview', boosts)
    hint.value = boosts.length ? `本轮已对 ${boosts.length} 个摊主临时抬优先，仅预览、未入库。` : '本轮按登记优先现算，未入库。'
  } catch (e) {
    errorMsg.value = errDetail(e) // 旧 round 保留不动
  } finally { busy.value = false }
}

async function confirmRun() {
  if (busy.value || !round.value) return
  const { ok, boosts } = gatherBoosts()
  if (!ok) { errorMsg.value = '本轮临时优先必须留空或填 1–9 的整数；已标红，请改后再确认（整次抬升未执行）。'; return }
  busy.value = true; errorMsg.value = ''
  try {
    round.value = await callOnce('/allocate/run', boosts)
    // 本轮结束：清空临时输入，下轮换将回到登记优先；服务端也从不保存临时表
    tempInputs.value = {}
    invalid.value = new Set()
    hint.value = boosts.length
      ? `已按本轮临时优先确认入库；临时表已清除，下一轮自动回到登记优先。`
      : '已按登记优先确认入库。'
  } catch (e) {
    errorMsg.value = errDetail(e) // 400：登记、图、放不下均不变
  } finally { busy.value = false }
}

async function clearTemp() {
  if (busy.value || !round.value) return
  tempInputs.value = {}
  invalid.value = new Set()
  busy.value = true; errorMsg.value = ''
  try {
    round.value = await callOnce('/allocate/preview', [])
    hint.value = '临时已清除，已按登记优先重新现算（未入库）。'
  } catch (e) {
    errorMsg.value = errDetail(e)
  } finally { busy.value = false }
}

const banner = computed(() => {
  if (!round.value) return null
  if (round.value.confirmed) {
    const t = (round.value.created_at || '').replace('T', ' ').slice(0, 19)
    return { cls: 'ok', text: `已入库 #${round.value.id}${t ? ' · ' + t : ''} · 本轮结果已正式落库` }
  }
  return { cls: 'preview', text: '现算预览 · 尚未入库（登记优先与正式占位均未改变）' }
})
const fmtTime = (s: string | null) => (s || '').replace('T', ' ').slice(0, 19)
</script>

<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">沿街一维开间 · 挡柱为竖直阻断 · 可在「本轮抬优先」抽屉里临时指定 1–9，只影响这一次现算/确认</p>
    <div class="ss-actions">
      <button class="btn" :disabled="busy || !round" @click="drawerOpen = true">本轮抬优先</button>
    </div>

    <div v-if="banner" class="ss-banner" :class="'ss-banner-' + banner.cls">{{ banner.text }}</div>
    <div v-if="hint" class="ss-banner ss-banner-hint">{{ hint }}</div>
    <div v-if="errorMsg" class="ss-banner ss-banner-bad">抬升被拒绝：{{ errorMsg }}</div>

    <div class="ss-band-ruler" v-if="round">
      <span>0 m</span>
      <span>{{ round.segment.name }} · {{ round.segment.width_m }} m</span>
      <span>{{ round.segment.width_m }} m</span>
    </div>
    <div class="ss-street-band" v-if="round">
      <div class="ss-street-inner">
        <div
          v-for="(c, i) in cells" :key="i"
          class="ss-band-cell"
          :class="{ 'ss-pillar': c.type === 'pillar', 'ss-boosted': c.type === 'stall' && c.boosted }"
          :style="{ width: c.pct + '%', background: c.type === 'pillar' ? undefined : c.color, flex: '0 0 ' + c.pct + '%' }"
        >
          <span v-if="c.type === 'stall' && c.boosted" class="ss-cell-tag" :title="'本轮临时抬优先'">▲</span>{{ c.label }}
        </div>
      </div>
    </div>

    <!-- 摊主两套数：全部只来自当前这一个轮次载荷，杜绝串口径 -->
    <div class="ss-vendor-queue" v-if="round">
      <div v-for="v in round.vendors" :key="v.vendor_id" class="ss-vendor-chip"
           :class="{ 'ss-chip-rejected': v.status === 'rejected' }">
        <strong>{{ v.vendor_name }}</strong>
        <span>需 {{ v.width_m }} m</span>
        <span class="ss-prio-line">
          登记 <b>{{ v.registered_priority }}</b>
          <template v-if="v.temp_priority != null"> · 临时 <b class="ss-temp-num">{{ v.temp_priority }}</b></template>
          · 生效 <b>{{ v.effective_priority }}</b>
        </span>
        <span class="badge" :class="v.status === 'placed' ? 'badge-ok' : 'badge-bad'">
          {{ v.status === 'placed' ? '已落位' : '放不下' }}
        </span>
      </div>
    </div>

    <div class="card" v-if="round">
      <h2 class="ss-card-title">本轮占位次序<span class="muted">（按本轮生效优先）</span></h2>
      <table>
        <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th><th>登记</th><th>临时</th><th>本轮生效</th></tr></thead>
        <tbody>
          <tr v-for="p in round.placements" :key="p.vendor_id">
            <td>{{ p.vendor_name }}</td>
            <td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
            <td>{{ p.registered_priority }}</td>
            <td><span v-if="p.temp_priority != null" class="badge badge-warn">{{ p.temp_priority }}</span><span v-else class="muted">—</span></td>
            <td>{{ p.effective_priority }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card" v-if="round">
      <h2 class="ss-card-title">本轮放不下
        <span class="badge" :class="round.confirmed ? 'badge-ok' : 'badge-warn'">{{ round.confirmed ? '已入库' : '仅预览' }}</span>
      </h2>
      <table v-if="round.rejected.length">
        <thead><tr><th>摊主</th><th>需求宽度</th><th>登记</th><th>临时</th><th>本轮生效</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="r in round.rejected" :key="r.vendor_id">
            <td>{{ r.vendor_name }}</td><td>{{ r.width_m }}</td>
            <td>{{ r.registered_priority }}</td>
            <td><span v-if="r.temp_priority != null" class="badge badge-warn">{{ r.temp_priority }}</span><span v-else class="muted">—</span></td>
            <td>{{ r.effective_priority }}</td>
            <td>{{ r.reason }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">全部放下</p>
    </div>

    <!-- 运行抽屉 -->
    <div v-if="drawerOpen" class="ss-drawer-backdrop" @click.self="drawerOpen = false"></div>
    <aside class="ss-run-drawer" :class="{ 'ss-drawer-open': drawerOpen }">
      <header class="ss-drawer-head">
        <strong>本轮临时抬优先</strong>
        <button class="ss-drawer-x" @click="drawerOpen = false">×</button>
      </header>
      <p class="ss-drawer-note">
        临时值只在 1–9，<b>留空=不抬</b>；只影响这一次，绝不写回登记优先。本轮结束或「清临时」后回到登记优先。
      </p>
      <div class="ss-drawer-list">
        <div v-for="v in round?.vendors || []" :key="v.vendor_id" class="ss-drawer-row"
             :class="{ 'ss-row-invalid': invalid.has(v.vendor_id) }">
          <div class="ss-drawer-name">
            {{ v.vendor_name }}
            <span class="muted">需 {{ v.width_m }}m</span>
          </div>
          <div class="ss-drawer-prios">
            <label>登记 <b>{{ v.registered_priority }}</b></label>
            <input class="ss-temp-input" type="number" min="1" max="9" step="1"
                   :value="rawTemp(v)" @input="onTempInput(v, ($event.target as HTMLInputElement).value)"
                   placeholder="—" />
            <label>生效 <b :class="rawTemp(v).trim() ? 'ss-temp-num' : ''">{{ effOf(v) }}</b></label>
          </div>
          <p v-if="invalid.has(v.vendor_id)" class="ss-row-err">临时优先须为 1–9 的整数</p>
        </div>
      </div>
      <footer class="ss-drawer-actions">
        <button class="btn" :disabled="busy" @click="preview">现算（不入库）</button>
        <button class="btn btn-primary" :disabled="busy" @click="confirmRun">确认入库</button>
        <button class="btn btn-ghost" :disabled="busy" @click="clearTemp">清临时</button>
      </footer>
    </aside>
  </div>
</template>

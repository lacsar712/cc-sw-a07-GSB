<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const role = ref(localStorage.getItem('role') || '')
const jobs = ref([])
const coupons = ref([])
const err = ref('')
const form = ref({
  lamp: '',
  nominal_nm: 0.15,
  measured_nm: 0.15,
  coupon_code: localStorage.getItem('coupon_code') || '',
})
let timer

const todayStr = computed(() => {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
})

const attachedCoupon = computed(() => {
  const code = (form.value.coupon_code || '').trim()
  if (!code) return null
  return coupons.value.find((c) => c.code === code) || null
})

const couponState = computed(() => {
  const code = (form.value.coupon_code || '').trim()
  if (!code) return { key: 'empty', text: '未挂券：提交校准必须挂一张当日有效券', ok: false }
  const c = attachedCoupon.value
  if (!c) return { key: 'unknown', text: '错券：查无此口令券，投单将被拒收', ok: false }
  if (c.status === 'void') {
    return { key: 'void', text: '该券已记入作废簿，不得再次挂用', ok: false }
  }
  if (c.valid_date !== todayStr.value) {
    return { key: 'expired', text: `隔日旧券（券面日期 ${c.valid_date}），一律拒收`, ok: false }
  }
  return { key: 'valid', text: '当日有效券，可以挂单提交', ok: true }
})

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [jobRows, couponRows] = await Promise.all([
      api('/api/jobs'),
      api('/api/coupons'),
    ])
    jobs.value = jobRows
    coupons.value = couponRows
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function submit() {
  err.value = ''
  if (!couponState.value.ok) {
    err.value = couponState.value.text
    return
  }
  try {
    await api('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({
        lamp: form.value.lamp,
        nominal_nm: form.value.nominal_nm,
        measured_nm: form.value.measured_nm,
        coupon_code: form.value.coupon_code.trim(),
      }),
    })
    // 一次性券已随入队核销：清掉挂用，避免作废券再投第二单
    form.value.coupon_code = ''
    localStorage.removeItem('coupon_code')
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
    await refresh()
  }
}

function goDetail(id) {
  router.push(`/jobs/${id}`)
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <section v-if="role === 'writer'" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>提交校准</h3>
      <div style="margin-bottom:8px;">
        <label>
          口令券
          <input
            v-model="form.coupon_code"
            placeholder="粘贴/输入当日券号，或去口令台挂用"
            style="width:300px; font-family:monospace;"
          />
        </label>
        <router-link to="/coupons" style="margin-left:10px; font-size:13px;">去口令台领券 →</router-link>
        <span
          class="coupon-badge"
          :class="couponState.ok ? 'badge-ok' : 'badge-bad'"
          style="margin-left:10px;"
        >{{ couponState.text }}</span>
      </div>
      <label>灯种 <input v-model="form.lamp" /></label>
      <label>标称 nm <input type="number" step="0.01" v-model.number="form.nominal_nm" /></label>
      <label>实测 nm <input type="number" step="0.01" v-model.number="form.measured_nm" /></label>
      <button :disabled="!couponState.ok" @click="submit">挂券入队</button>
    </section>
    <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
      <thead>
        <tr>
          <th>编号</th><th>灯种</th><th>标称</th><th>实测</th><th>状态</th><th>结论</th><th>理由</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="j in jobs"
          :key="j.id"
          style="cursor:pointer"
          @click="goDetail(j.id)"
        >
          <td>{{ j.id }}</td>
          <td>{{ j.lamp }}</td>
          <td>{{ j.nominal_nm }}</td>
          <td>{{ j.measured_nm }}</td>
          <td>{{ j.status }}</td>
          <td>{{ j.verdict }}</td>
          <td>{{ j.reason }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.coupon-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
}
.badge-ok {
  background: #e3f4e8;
  color: #1e6b36;
}
.badge-bad {
  background: #fbe4e8;
  color: #b00020;
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
</style>

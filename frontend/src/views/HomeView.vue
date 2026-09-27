<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const role = ref(localStorage.getItem('role') || '')
const jobs = ref([])
const vouchers = ref([])
const err = ref('')
const form = ref({ lamp: '', nominal_nm: 0.15, measured_nm: 0.15, voucher_code: '' })
let timer

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [j, v] = await Promise.all([api('/api/jobs'), api('/api/vouchers')])
    jobs.value = j
    vouchers.value = v.valid || []
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function submit() {
  err.value = ''
  if (!form.value.voucher_code) {
    err.value = '请先挂一张当日有效口令券'
    return
  }
  try {
    await api('/api/jobs', { method: 'POST', body: JSON.stringify(form.value) })
    form.value.voucher_code = ''
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
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
      <label>灯种 <input v-model="form.lamp" /></label>
      <label>标称 nm <input type="number" step="0.01" v-model.number="form.nominal_nm" /></label>
      <label>实测 nm <input type="number" step="0.01" v-model.number="form.measured_nm" /></label>
      <label>口令券
        <select v-model="form.voucher_code">
          <option value="" disabled>请选择当日有效券</option>
          <option v-for="v in vouchers" :key="v.id" :value="v.code">{{ v.code }}（{{ v.day }}）</option>
        </select>
      </label>
      <button @click="submit">入队</button>
      <p v-if="!vouchers.length" style="color:#8a6d3b; font-size:13px;">
        暂无有效券，先到<router-link to="/vouchers">口令台</router-link>生成当日券。
      </p>
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

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const valid = ref([])
const voided = ref([])
const fresh = ref(null)
const err = ref('')
const todayUtc = new Date().toISOString().slice(0, 10)
let timer

function fmt(ts) {
  return ts ? String(ts).slice(0, 19).replace('T', ' ') : ''
}

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const data = await api('/api/vouchers')
    valid.value = data.valid || []
    voided.value = data.void || []
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function generate() {
  err.value = ''
  try {
    fresh.value = await api('/api/vouchers', { method: 'POST', body: '{}' })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="voucher-cols">
      <section class="col">
        <h3>生成区</h3>
        <template v-if="role === 'writer'">
          <p class="desc">当日校准口令为一次性券：提交校准时挂一张，入队成功即作废。</p>
          <button type="button" @click="generate">生成当日口令券</button>
          <div v-if="fresh" class="fresh-card">
            <div class="code">{{ fresh.code }}</div>
            <div class="meta">日期 {{ fresh.day }} · 已入有效券</div>
          </div>
        </template>
        <p v-else class="desc">观察账号只读：可翻有效券与作废簿，不可发券也不可作废。</p>
      </section>

      <section class="col">
        <h3>有效券（{{ valid.length }}）</h3>
        <p v-if="!valid.length" class="empty">暂无有效券</p>
        <div v-for="v in valid" :key="v.id" class="card">
          <div class="code">{{ v.code }}</div>
          <div class="meta">
            日期 {{ v.day }}
            <span v-if="v.day !== todayUtc" class="stale">隔日</span>
          </div>
          <div class="meta">{{ v.created_by }} · {{ fmt(v.created_at) }}</div>
        </div>
      </section>

      <section class="col">
        <h3>作废簿（{{ voided.length }}）</h3>
        <p v-if="!voided.length" class="empty">暂无作废券</p>
        <div v-for="v in voided" :key="v.id" class="card void">
          <div class="code">{{ v.code }}</div>
          <div class="meta">日期 {{ v.day }} · 任务 #{{ v.job_id }}</div>
          <div class="meta">作废于 {{ fmt(v.used_at) }}</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.voucher-cols {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
  margin-top: 16px;
}
.col {
  flex: 1 1 240px;
  min-width: 220px;
  border: 1px solid #ccc;
  border-radius: 6px;
  padding: 12px;
  background: #fafbfc;
}
.desc {
  color: #555;
  font-size: 13px;
}
.empty {
  color: #999;
  font-size: 13px;
}
.err {
  color: #b00020;
}
.card {
  border: 1px solid #d8dee4;
  border-radius: 6px;
  padding: 8px 10px;
  margin: 8px 0;
  background: #fff;
}
.card.void {
  background: #f3f4f6;
  color: #666;
}
.card.void .code {
  text-decoration: line-through;
}
.code {
  font-family: monospace;
  font-weight: 700;
}
.meta {
  font-size: 12px;
  color: #777;
  margin-top: 2px;
}
.stale {
  color: #b00020;
  border: 1px solid #b00020;
  border-radius: 4px;
  padding: 0 4px;
  font-size: 11px;
  margin-left: 4px;
}
.fresh-card {
  border: 1px dashed #2a7;
  border-radius: 6px;
  padding: 8px 10px;
  margin-top: 10px;
  background: #f2fbf6;
}
button {
  cursor: pointer;
}
</style>

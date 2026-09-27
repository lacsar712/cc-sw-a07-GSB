<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const role = ref(localStorage.getItem('role') || '')
const coupons = ref([])
const err = ref('')
const busy = ref(false)

const isWriter = computed(() => role.value === 'writer')
const today = computed(() => {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
})

// 有效券：未核销且券面日期就是今日
const validCoupons = computed(() =>
  coupons.value.filter((c) => c.status === 'valid' && c.valid_date === today.value),
)
// 作废簿：已核销/手动作废
const voidedCoupons = computed(() => coupons.value.filter((c) => c.status === 'void'))
// 隔日旧券：尚未核销但日期已过，自动失效不能再挂
const expiredCoupons = computed(() =>
  coupons.value.filter((c) => c.status === 'valid' && c.valid_date !== today.value),
)

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    coupons.value = await api('/api/coupons')
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function generate() {
  err.value = ''
  busy.value = true
  try {
    await api('/api/coupons', { method: 'POST' })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function revoke(c) {
  if (!window.confirm(`确认手动作废券 ${c.code}？作废后不可恢复。`)) return
  err.value = ''
  try {
    await api(`/api/coupons/${c.id}/void`, { method: 'POST' })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function useNow(c) {
  localStorage.setItem('coupon_code', c.code)
  router.push('/')
}

let timer
onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="coupon-desk">
    <p v-if="err" class="err">{{ err }}</p>

    <!-- 生成区 -->
    <section class="gen-area">
      <div class="gen-text">
        <h3>当日校准口令券</h3>
        <p class="hint">
          一次性券：当日有效，挂券提交成功后立即记入作废簿，不得再次挂用；
          错券、隔日旧券一律拒收。今日（{{ today }}）
        </p>
      </div>
      <div class="gen-action">
        <button v-if="isWriter" type="button" :disabled="busy" @click="generate">
          {{ busy ? '生成中…' : '生成当日券' }}
        </button>
        <span v-else class="reader-notice">观察账号：只许翻阅，不许发券</span>
      </div>
    </section>

    <!-- 有效券 / 作废簿 分栏 -->
    <div class="columns">
      <section class="col col-valid">
        <h4 class="col-head">有效券（{{ validCoupons.length }}）</h4>
        <p v-if="!validCoupons.length" class="empty">暂无当日有效券</p>
        <div
          v-for="c in validCoupons"
          :key="c.id"
          class="card card-valid"
        >
          <div class="card-code">{{ c.code }}</div>
          <div class="card-meta">
            <span>券面日期：{{ c.valid_date }}</span>
            <span>生成：{{ c.created_by }}</span>
          </div>
          <div v-if="isWriter" class="card-actions">
            <button type="button" class="primary" @click="useNow(c)">挂用并去提交</button>
            <button type="button" class="danger" @click="revoke(c)">作废</button>
          </div>
        </div>
      </section>

      <section class="col col-void">
        <h4 class="col-head">作废簿（{{ voidedCoupons.length + expiredCoupons.length }}）</h4>
        <p
          v-if="!voidedCoupons.length && !expiredCoupons.length"
          class="empty"
        >尚无作废记录</p>

        <div v-for="c in voidedCoupons" :key="'v' + c.id" class="card card-void">
          <div class="card-code">
            {{ c.code }}
            <span class="tag tag-used">已核销</span>
          </div>
          <div class="card-meta">
            <span>券面日期：{{ c.valid_date }}</span>
            <span v-if="c.used_by_job">用于任务：#{{ c.used_by_job }}</span>
          </div>
          <div class="card-reason">{{ c.void_reason || '已作废' }}</div>
          <div class="card-meta">
            <span>经办：{{ c.voided_by || '-' }}</span>
            <span>{{ c.voided_at ? c.voided_at.replace('T', ' ').slice(0, 19) : '' }}</span>
          </div>
        </div>

        <div v-for="c in expiredCoupons" :key="'e' + c.id" class="card card-expired">
          <div class="card-code">
            {{ c.code }}
            <span class="tag tag-expired">隔日旧券</span>
          </div>
          <div class="card-meta">
            <span>券面日期：{{ c.valid_date }}</span>
            <span>生成：{{ c.created_by }}</span>
          </div>
          <div class="card-reason">已过当日有效期，挂单一律拒收</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.coupon-desk {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.err {
  color: #b00020;
}
.gen-area {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid #2c4a6e;
  border-radius: 8px;
  background: #f4f8fc;
}
.gen-text h3 {
  margin: 0 0 4px;
}
.gen-text .hint {
  margin: 0;
  color: #55606c;
  font-size: 13px;
}
.gen-action button {
  cursor: pointer;
  padding: 8px 18px;
  font-size: 14px;
}
.reader-notice {
  color: #8a6d1a;
  font-size: 13px;
  white-space: nowrap;
}
.columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.col {
  border: 1px solid #d4dde7;
  border-radius: 8px;
  padding: 12px;
  min-height: 200px;
  background: #fff;
}
.col-valid {
  border-color: #2e7d46;
}
.col-void {
  border-color: #8a8f98;
  background: #f6f7f9;
}
.col-head {
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #c4ccd6;
}
.empty {
  color: #8a93a0;
  font-size: 13px;
}
.card {
  border: 1px solid #cfd8e3;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fff;
}
.card-valid {
  border-left: 4px solid #2e7d46;
}
.card-void {
  border-left: 4px solid #7a828c;
  opacity: 0.92;
}
.card-expired {
  border-left: 4px solid #b06a00;
  background: #fff8ec;
}
.card-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 700;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: #5a6470;
  font-size: 12px;
  margin-top: 6px;
}
.card-reason {
  margin-top: 6px;
  font-size: 12px;
  color: #444c56;
}
.card-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.card-actions button {
  cursor: pointer;
  padding: 4px 12px;
  font-size: 13px;
}
.card-actions .primary {
  background: #2e7d46;
  color: #fff;
  border: 1px solid #2e7d46;
  border-radius: 4px;
}
.card-actions .danger {
  background: #fff;
  color: #b00020;
  border: 1px solid #b00020;
  border-radius: 4px;
}
.tag {
  font-size: 11px;
  font-weight: 400;
  padding: 1px 7px;
  border-radius: 10px;
}
.tag-used {
  background: #e6e8eb;
  color: #555d68;
}
.tag-expired {
  background: #fdecd2;
  color: #8a5200;
}
@media (max-width: 720px) {
  .columns {
    grid-template-columns: 1fr;
  }
}
</style>

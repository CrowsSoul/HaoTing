<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import Viewer from './Viewer.vue'
import { api, post } from './api'
import type { Task, Finding, CheckRun, ModelBundle, RuleBook, Rule, DisplayMesh } from './generated/contracts'
interface RuleVersion { id: string; created_at: string; book: RuleBook }
interface CatalogRow { check_item_id: string; name_cn: string; implemented: boolean; owner_module: string }
const page = ref<'tasks' | 'rules'>('tasks')
const tasks = ref<Task[]>([])
const books = ref<RuleVersion[]>([])
const samples = ref<string[]>([])
const catalog = ref<CatalogRow[]>([])
const health = ref({ nx_available: false, workers: 0, nx_slots: 0, m8_available: false })
const rulebookId = ref('')
const sampleName = ref('board_a.model.json')
const file = ref<File | null>(null)
const inputMode = ref('sample')
const selectedIds = ref<string[]>([])
const busy = ref(false)
const reportBusy = ref(false)
const error = ref('')
const notice = ref('')
const activeId = ref('')
const result = ref<CheckRun | null>(null)
const model = ref<ModelBundle | null>(null)
const mesh = ref<DisplayMesh | null>(null)
const selectedFinding = ref<Finding | null>(null)
const severity = ref('all')
const query = ref('')
const draft = ref<RuleBook | null>(null)
const ruleSearch = ref('')
const active = computed(() => tasks.value.find(t => t.id === activeId.value))
const terminal = (t?: Task) => !!t && ['completed','failed'].includes(t.state)
const findings = computed(() => (result.value?.findings ?? []).filter(f => (severity.value === 'all' || f.severity === severity.value) && `${f.check_item_id} ${f.message}`.toLowerCase().includes(query.value.toLowerCase())))
const draftRules = computed(() => draft.value?.rules.filter(r => `${r.check_item_id} ${r.name}`.toLowerCase().includes(ruleSearch.value.toLowerCase())) ?? [])
const unavailable = computed(() => catalog.value.filter(c => !c.implemented && (!active.value?.only.length || active.value.only.includes(c.check_item_id))))
const statusNames: Record<string,string> = {queued:'排队中',waiting_nx:'等待 NX',extracting:'解析模型',checking:'检查中',completed:'已完成',failed:'失败',ok:'已执行',skipped:'已跳过',filtered:'未选择',missing_data:'缺少数据',error:'执行失败'}
const paramNames: Record<string,string> = {min_clearance_mm:'最小间隙（mm）',standard_diameters:'标准刀具直径（mm）',tolerance_mm:'匹配公差（mm）',max_distinct_radii:'最大圆角种类数',pull_direction:'拔模方向（X / Y / Z）'}
const value = (v: number | null | undefined) => v == null ? '—' : Number(v.toFixed(4)).toString()
const date = (s: string | null) => s ? new Date(s).toLocaleString('zh-CN', {hour12:false}) : '—'
const running = computed(() => tasks.value.filter(t => !terminal(t)).length)
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false
let loadingResult = ''
async function loadResult(id: string) {
  if (loadingResult === id) return
  loadingResult = id
  try {
    const [r,m,geometry] = await Promise.all([api<CheckRun>(`/tasks/${id}/result`), api<ModelBundle>(`/tasks/${id}/model`),api<DisplayMesh>(`/tasks/${id}/mesh`).catch(()=>null)])
    if (activeId.value === id) { result.value=r; model.value=m; mesh.value=geometry; selectedFinding.value=r.findings[0] ?? null }
  } finally { if (loadingResult === id) loadingResult = '' }
}
async function refresh() {
  tasks.value = await api<Task[]>('/tasks')
  if (active.value?.state === 'completed' && !result.value) await loadResult(active.value.id)
}
async function poll() {
  try { await refresh() } catch (e) { error.value = `连接失败：${(e as Error).message}` }
  if (!stopped) timer=setTimeout(poll, 1500)
}
async function selectTask(t: Task) {
  activeId.value=t.id; result.value=null; model.value=null; mesh.value=null; selectedFinding.value=null
  severity.value='all'; query.value=''
  if (t.state === 'completed') {
    try { await loadResult(t.id) } catch (e) { error.value=(e as Error).message }
  }
}
function resetDraft(id: string) {
  const book=books.value.find(b=>b.id===id)
  if (book) draft.value=JSON.parse(JSON.stringify(book.book))
}
watch(page, p => { if(p==='rules') resetDraft(rulebookId.value) })
async function submit() {
  busy.value=true; error.value=''; notice.value=''
  try {
    let uploaded: {id:string}
    if (inputMode.value==='sample') uploaded=await post(`/samples/${encodeURIComponent(sampleName.value)}`)
    else {
      if (!file.value) throw new Error('请先选择模型文件')
      const form=new FormData(); form.append('file', file.value)
      uploaded=await api('/models', {method:'POST',body:form})
    }
    const task=await post<Task>('/tasks',{model_id:uploaded.id,rulebook_id:rulebookId.value,only:selectedIds.value})
    await refresh(); await selectTask(task); notice.value='任务已提交，可在下方查看执行情况。'
  } catch(e) { error.value=(e as Error).message }
  finally { busy.value=false }
}
async function saveRules() {
  if (!draft.value) return
  busy.value=true; error.value=''; notice.value=''
  try {
    const saved=await post<RuleVersion>('/rulebooks',draft.value)
    books.value.unshift(saved); rulebookId.value=saved.id; resetDraft(saved.id)
    notice.value='已保存新规则版本。新任务将使用此版本，历史任务保持原快照。'
  } catch(e) { error.value=(e as Error).message }
  finally { busy.value=false }
}
function setNumber(rule: Rule, key: string, event: Event, index?: number) {
  const input=event.target as HTMLInputElement
  input.setCustomValidity('')
  if (!input.value.trim() || !Number.isFinite(Number(input.value))) { input.setCustomValidity('请输入有效数字'); input.reportValidity(); return }
  const n=Number(input.value)
  if (index != null) (rule.params[key] as number[])[index]=n
  else rule.params[key]=n
}
function addArray(rule: Rule, key: string) { (rule.params[key] as unknown[]).push(0) }
function removeArray(rule: Rule, key: string, index: number) { (rule.params[key] as unknown[]).splice(index,1) }
async function generateReport(fmt: string) {
  reportBusy.value=true; error.value=''
  try {
    const r=await post<{download_url:string}>(`/tasks/${activeId.value}/reports/${fmt}`)
    const link=document.createElement('a'); link.href=r.download_url; link.download=''; link.click()
    await refresh()
  } catch(e) { error.value=(e as Error).message }
  finally { reportBusy.value=false }
}
async function attachMesh(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]; if(!file) return
  const id=activeId.value
  try {
    if(file.size>30*1024*1024) throw new Error('显示网格最大 30 MB')
    const payload=JSON.parse(await file.text())
    const saved=await post<DisplayMesh>(`/tasks/${id}/mesh`,payload)
    if(activeId.value===id) mesh.value=saved
    notice.value='显示网格已保存，可按面 ID 高亮缺陷。'
  } catch(e) { error.value=(e as Error).message }
  finally { input.value='' }
}
onMounted(async () => {
  try {
    const [b,s,c,h] = await Promise.all([api<RuleVersion[]>('/rulebooks'),api<string[]>('/samples'),api<{rows:CatalogRow[]}>('/catalog'),api<typeof health.value>('/health')])
    books.value=b; samples.value=s; catalog.value=c.rows; health.value=h
    rulebookId.value=b[0]?.id ?? ''; resetDraft(rulebookId.value)
    await refresh(); if(tasks.value[0]) await selectTask(tasks.value[0]); void poll()
  } catch(e) { error.value=(e as Error).message }
})
onBeforeUnmount(()=>{ stopped=true; clearTimeout(timer) })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="/">HARTING<span>DESIGN REVIEW PLATFORM</span></a>
      <div class="workspace-label">工程工作台 <span>01</span></div>
      <nav aria-label="主导航"><button :class="{selected:page==='tasks'}" @click="page='tasks'">▦ <span>模型检查</span></button><button :class="{selected:page==='rules'}" @click="page='rules'">⚙ <span>规则配置</span></button></nav>
      <div class="side-bottom"><span class="connection-dot"></span> 本地检查服务 <p>NX {{ health.nx_available ? '已就绪' : '未连接 · 可使用 JSON 模型' }}</p><p>M7 · v0.1.0</p></div>
    </aside>
    <main>
      <header class="topbar"><span>连接器智能设计检查</span><span class="top-meta">M7 工程平台 <i></i> {{ health.workers }} 个任务槽位 / {{ health.nx_slots }} 个 NX 槽位</span></header>
      <div class="content">
        <div class="page-heading"><div><div class="eyebrow">{{ page==='tasks'?'DESIGN VALIDATION':'RULE MANAGEMENT' }}</div><h1>{{ page==='tasks'?'模型检查':'规则配置' }}</h1><p>{{ page==='tasks'?'从模型到问题，让每一次设计评审都有据可循。':'编辑工程阈值，保存独立版本；每次检查保留完整规则快照。' }}</p></div><span class="outline-badge">{{ catalog.filter(c=>c.implemented).length }} / {{ catalog.length }} 检查项已接入</span></div>
        <div v-if="error" class="alert error" role="alert">{{ error }}<button @click="error=''" aria-label="关闭错误">×</button></div>
        <div v-if="notice" class="alert success" role="status">{{ notice }}<button @click="notice=''" aria-label="关闭通知">×</button></div>
        <template v-if="page==='tasks'">
          <div class="stats"><div><span>全部任务</span><strong>{{ tasks.length.toString().padStart(2,'0') }}</strong></div><div><span>正在处理</span><strong>{{ running.toString().padStart(2,'0') }}</strong></div><div><span>已完成</span><strong>{{ tasks.filter(t=>t.state==='completed').length.toString().padStart(2,'0') }}</strong></div><div><span>检查覆盖</span><strong>{{ catalog.filter(c=>c.implemented).length }}<small> / {{ catalog.length }}</small></strong></div></div>
          <section class="panel new-check"><div class="panel-title"><div><h2>新建检查</h2><p>选择模型与规则，检查将在后台执行。</p></div><span class="step-label">01 / 提交模型</span></div>
            <form @submit.prevent="submit"><div class="upload-grid"><div class="upload-area"><div class="segmented"><button type="button" :class="{on:inputMode==='sample'}" @click="inputMode='sample'">示例模型</button><button type="button" :class="{on:inputMode==='file'}" @click="inputMode='file'">本地上传</button></div>
              <div v-if="inputMode==='sample'" class="upload-inner"><div class="model-icon">⬡</div><label for="sample">用示例开始一次检查</label><select id="sample" v-model="sampleName"><option v-for="s in samples" :key="s">{{ s }}</option></select><p>board_a：2 个零件 · 预期 4 条示例缺陷</p></div>
              <div v-else class="upload-inner"><div class="model-icon">↑</div><label for="model-file">选择模型文件</label><input id="model-file" type="file" accept=".json,.prt" @change="file=($event.target as HTMLInputElement).files?.[0]??null"><p>支持 .model.json / 单零件 .prt，最大 100 MB</p></div>
            </div><div class="check-config"><label for="rulebook">规则版本</label><select id="rulebook" v-model="rulebookId"><option v-for="b in books" :value="b.id" :key="b.id">{{ b.book.name }} · v{{ b.book.version }} · {{ b.id.slice(0,6) }}</option></select><label class="check-label">检查范围 <span>不勾选时运行全部已接入项目</span></label><div class="checker-options"><label v-for="c in catalog.filter(c=>c.implemented)" :key="c.check_item_id"><input type="checkbox" v-model="selectedIds" :value="c.check_item_id"><span><b>{{ c.check_item_id }}</b> {{ c.name_cn }}</span></label></div><button class="primary submit" :disabled="busy||!rulebookId">{{ busy?'提交中…':'开始检查' }} <span>→</span></button></div></div></form>
          </section>
          <section class="panel"><div class="panel-title"><div><h2>任务记录 <span class="count">{{ tasks.length }}</span></h2><p>任务独立保存，检查失败不会影响其他任务。</p></div><span class="live"><i></i> 自动更新</span></div><div class="table-scroll"><table class="task-table"><thead><tr><th>模型 / 任务</th><th>创建时间</th><th>状态</th><th>进度 / 耗时</th><th>缺陷</th><th></th></tr></thead><tbody><tr v-for="t in tasks" :key="t.id" :class="{active:t.id===activeId}"><td><strong>{{ t.filename }}</strong><small>{{ t.id.slice(0,12) }}</small></td><td>{{ date(t.created_at) }}</td><td><span class="status" :class="t.state">{{ statusNames[t.state] }}</span></td><td><template v-if="t.state==='queued'">排队第 {{ t.queue_position }} 位</template><template v-else-if="t.state==='waiting_nx'">等待 NX 许可槽位</template><template v-else>{{ t.current_item || t.stage }}<small>{{ (t.elapsed_ms/1000).toFixed(1) }} 秒<span v-if="t.total_items"> · {{ t.completed_items }}/{{ t.total_items }} 项</span></small></template></td><td>{{ t.summary?.findings ?? '—' }}</td><td><button class="text-button" @click="selectTask(t)">查看 →</button></td></tr><tr v-if="!tasks.length"><td colspan="6" class="empty">还没有检查任务。选择上方示例，开始第一次检查。</td></tr></tbody></table></div></section>
          <section v-if="active" class="panel detail"><div class="panel-title"><div><h2>检查详情 <span class="mono">{{ active.id.slice(0,8) }}</span></h2><p>{{ active.filename }} · 规则快照 {{ active.rulebook_id.slice(0,8) }}</p></div><div class="actions" v-if="result"><a :href="`/api/tasks/${active.id}/download`" class="quiet">结果 JSON</a><a :href="`/api/tasks/${active.id}/rules`" class="quiet">规则快照</a><a :href="`/api/tasks/${active.id}/reports/html`" class="primary">下载报告</a><template v-if="health.m8_available"><button class="quiet" :disabled="reportBusy" @click="generateReport('pdf')">{{ reportBusy?'生成中…':'生成 PDF' }}</button><button class="quiet" :disabled="reportBusy" @click="generateReport('docx')">生成 Word</button></template></div></div>
            <div v-if="active.state==='failed'" class="inline-error">{{ active.error }}</div><div v-else-if="!result" class="empty">{{ active.stage }}{{ active.current_item?' · '+active.current_item:'' }}，页面将自动更新。</div>
            <template v-if="result"><div class="result-notice">本次实际执行 {{ result.results.filter(r=>r.status==='ok').length }} 项，发现 {{ result.findings.length }} 条缺陷。其余跳过、失败及未实现项目见下方执行明细。</div>
              <div class="result-grid"><div class="finding-list"><div class="filters"><input v-model="query" placeholder="搜索检查项或问题" aria-label="搜索缺陷"><select v-model="severity" aria-label="严重程度"><option value="all">全部级别</option><option v-for="s in ['P0','P1','P2','P3']" :key="s">{{ s }}</option></select></div><button v-for="f in findings" :key="f.finding_id" class="finding-card" :class="{chosen:selectedFinding?.finding_id===f.finding_id}" @click="selectedFinding=f"><div><span class="severity" :class="f.severity">{{ f.severity }}</span><span class="mono">{{ f.check_item_id }}</span></div><strong>{{ f.check_item_name }}</strong><p>{{ f.message }}</p><span class="finding-values">实测 {{ value(f.measured_value) }} / 阈值 {{ value(f.threshold_value) }} {{ f.unit }}</span></button><div v-if="!findings.length" class="empty">{{ result.findings.length?'没有符合筛选条件的缺陷':'本次已执行项目未发现缺陷' }}</div></div><div><Viewer :model="model" :finding="selectedFinding" :mesh="mesh"/><div class="geometry-note">{{ mesh ? '已加载装配坐标网格，按 evidence.face_ids 高亮对应面。' : '当前显示包围盒区域；附加 NX 显示网格后启用面高亮。' }}<label class="mesh-upload">附加显示网格<input type="file" accept=".json" @change="attachMesh"></label></div><div v-if="selectedFinding" class="finding-detail"><div class="detail-heading"><span class="severity" :class="selectedFinding.severity">{{ selectedFinding.severity }}</span><h3>{{ selectedFinding.check_item_name }}</h3></div><div class="measurements"><div><span>实测值</span><b>{{ value(selectedFinding.measured_value) }} <small>{{ selectedFinding.unit }}</small></b></div><div><span>阈值</span><b>{{ value(selectedFinding.threshold_value) }}</b></div><div><span>偏差</span><b>{{ value(selectedFinding.deviation) }}</b></div></div><div class="suggestion"><b>修改建议</b><p>{{ selectedFinding.suggestion.text || '检查器尚未提供修改建议' }}</p></div><dl><dt>零件</dt><dd>{{ selectedFinding.part_refs.join(', ')||'—' }}</dd><dt>面 ID</dt><dd>{{ selectedFinding.evidence.face_ids.join(', ')||'未提供' }}</dd><dt>坐标</dt><dd>{{ selectedFinding.location?.map(v=>value(v)).join(', ')||'未提供' }}</dd><dt>证据说明</dt><dd>{{ selectedFinding.evidence.note||'—' }}</dd><dt>置信度</dt><dd>{{ (selectedFinding.confidence*100).toFixed(0) }}%</dd></dl></div></div></div>
              <details class="execution"><summary>检查项执行明细 · {{ result.results.length }} 项记录 / {{ unavailable.length }} 项尚未实现</summary><table><thead><tr><th>检查项</th><th>状态</th><th>说明</th></tr></thead><tbody><tr v-for="r in result.results" :key="r.check_item_id"><td>{{ r.check_item_id }} {{ r.name }}</td><td>{{ statusNames[r.status]||r.status }}</td><td>{{ r.reason || `${r.finding_count} 条缺陷` }}</td></tr><tr v-for="c in unavailable" :key="c.check_item_id"><td>{{ c.check_item_id }} {{ c.name_cn }}</td><td>尚未实现</td><td>负责人模块 {{ c.owner_module }}</td></tr></tbody></table><p v-if="result.load_errors.length">插件加载异常：{{ result.load_errors }}</p></details>
            </template>
          </section>
        </template>
        <template v-else><section class="panel" v-if="draft"><div class="panel-title"><div><h2>规则版本管理</h2><p>修改阈值后保存为新版本，不覆盖历史任务。</p></div><span class="step-label">{{ draft.rules.length }} 条规则</span></div><div class="rule-toolbar"><label>来源版本<select :value="rulebookId" @change="rulebookId=($event.target as HTMLSelectElement).value;resetDraft(rulebookId)"><option v-for="b in books" :key="b.id" :value="b.id">{{ b.book.name }} · v{{ b.book.version }} · {{ b.id.slice(0,6) }}</option></select></label></div><form @submit.prevent="saveRules"><div class="rule-toolbar"><label>规则库名称<input v-model="draft.name" required></label><label>版本名称<input v-model="draft.version" required></label><label>搜索检查项<input v-model="ruleSearch" placeholder="例如 DFM-02、最小间隙"></label><button class="primary" :disabled="busy">{{ busy?'保存中…':'保存为新版本' }}</button></div><div class="rule-list"><article v-for="r in draftRules" :key="r.check_item_id" class="rule-card"><div class="rule-heading"><div><span class="mono">{{ r.check_item_id }}</span><h3>{{ r.name }}</h3></div><label class="toggle"><input type="checkbox" v-model="r.enabled">启用</label><select v-model="r.severity" :aria-label="r.check_item_id+' 严重程度'"><option v-for="s in ['P0','P1','P2','P3']" :key="s">{{ s }}</option></select></div><div class="param-grid"><label v-for="(v,k) in r.params" :key="k"><span>{{ paramNames[k] || k }}</span><input v-if="typeof v==='number'" :value="v" type="number" step="any" required @input="setNumber(r,k,$event)"><input v-else-if="typeof v==='boolean'" type="checkbox" :checked="v" @change="r.params[k]=($event.target as HTMLInputElement).checked"><div v-else-if="Array.isArray(v)" class="array-editor"><div v-for="(item,i) in v" :key="i"><input :value="item" type="number" step="any" required :aria-label="`${k} 第 ${i+1} 项`" @input="setNumber(r,k,$event,i)"><button type="button" class="text-button" @click="removeArray(r,k,i)" :aria-label="'移除第 '+(i+1)+' 项'">×</button></div><button type="button" class="quiet" @click="addArray(r,k)">＋ 添加值</button></div><input v-else-if="typeof v==='string'" :value="v" @input="r.params[k]=($event.target as HTMLInputElement).value"><span v-else>当前为复杂参数，请与检查项负责人确认表单。</span></label></div><p v-if="!Object.keys(r.params).length" class="muted">此检查项暂无可配置参数。</p><p class="rule-notes">{{ r.notes }}<span v-if="r.source_standard"> · 依据：{{ r.source_standard }}</span></p></article></div></form></section></template>
        <footer>浩亭 · 连接器智能设计检查平台 <span>数据保存在当前服务，检查结论以实际执行范围为准。</span></footer>
      </div>
    </main>
  </div>
</template>

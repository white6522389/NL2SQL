<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'
import { analyze } from './api'
import type { StageEvent, WorkflowResult } from './types'

const question=ref('查询2025年华东地区销售额最高的商品，并生成柱状图')
const loading=ref(false),error=ref(''),result=ref<WorkflowResult|null>(null),events=ref<StageEvent[]>([])
const conversationId=crypto.randomUUID()
echarts.use([BarChart, LineChart, PieChart, GridComponent, TitleComponent, TooltipComponent, CanvasRenderer])
const chartEl=ref<HTMLElement|null>(null);let chart:EChartsType|null=null
const stages=[['planner','任务规划'],['schema_rag','Schema RAG'],['sql_agent','SQL 生成'],['validator','安全校验'],['executor','查询执行'],['reflection','错误反思'],['analysis','数据分析']]
const stageState=(key:string)=>[...events.value].reverse().find(e=>e.stage===key)?.status||'pending'
const timelineEvents=computed(()=>stages
  .map(([key])=>[...events.value].reverse().find(event=>event.stage===key))
  .filter((event):event is StageEvent=>Boolean(event)))
const columns=computed(()=>result.value?.execution?.columns||[])
async function submit(){if(!question.value.trim()||loading.value)return;loading.value=true;error.value='';events.value=[];result.value=null
  try{result.value=await analyze(question.value,conversationId,event=>events.value.push(event))}catch(e){error.value=e instanceof Error?e.message:String(e)}finally{loading.value=false}}
function copySql(){if(result.value?.sql)navigator.clipboard.writeText(result.value.sql)}
function renderChart(){chart?.dispose();const config=result.value?.analysis?.chart;if(!chartEl.value||!config)return;chart=echarts.init(chartEl.value)
  if(config.type==='pie'){chart.setOption({title:{text:config.title},tooltip:{trigger:'item'},series:[{type:'pie',radius:['42%','70%'],data:config.data.map(r=>({name:r[config.name_field||'name'],value:r[config.value_field||'value']}))}]})}
  else{chart.setOption({title:{text:config.title,textStyle:{fontSize:16}},tooltip:{trigger:'axis'},grid:{left:44,right:20,top:54,bottom:36},xAxis:{type:'category',data:config.data.map(r=>r[config.x_field||'name']),axisLine:{lineStyle:{color:'#cbd5e1'}}},yAxis:{type:'value',splitLine:{lineStyle:{color:'#e8edf3'}}},series:[{type:config.type,data:config.data.map(r=>r[config.y_field||'value']),itemStyle:{color:'#0f8b8d'},lineStyle:{color:'#0f8b8d',width:3},smooth:true,barMaxWidth:38}]})}}
watch(()=>result.value?.analysis?.chart,async()=>{await nextTick();renderChart()},{deep:true});onBeforeUnmount(()=>chart?.dispose())
</script>

<template>
  <div class="shell">
    <aside class="rail">
      <div class="brand"><span class="brand-mark">智</span><strong>智析 SQL</strong></div>
      <nav aria-label="Agent 工作流">
        <div v-for="([key,label],i) in stages" :key="key" class="nav-step" :class="stageState(key)">
          <span class="step-index">{{ String(i+1).padStart(2,'0') }}</span><span>{{ label }}</span><i></i>
        </div>
      </nav>
      <div class="rail-note">五 Agent 协作<br><small>安全、可解释、可追踪</small></div>
    </aside>
    <main>
      <header><div><h1>智能数据分析工作台</h1><p>用自然语言查询业务数据，获得可靠 SQL、洞察与图表</p></div><div class="connection"><span></span>MySQL 5.7 · Qwen</div></header>
      <section class="composer"><label for="question">分析问题</label><textarea id="question" v-model="question" rows="3" @keydown.ctrl.enter="submit"></textarea><div class="composer-foot"><span>Ctrl + Enter 发送</span><button :disabled="loading" @click="submit">{{ loading?'正在分析…':'开始分析' }}</button></div></section>
      <div v-if="timelineEvents.length" class="timeline" aria-live="polite"><div v-for="event in timelineEvents" :key="event.stage" :class="event.status"><b>{{ event.stage }}</b><span>{{ event.message }}<template v-if="event.elapsed_ms"> · {{ Math.round(event.elapsed_ms) }} ms</template></span></div></div>
      <div v-if="result?.metrics" class="trace-summary"><span>Trace: {{ result.metrics.trace_id.slice(0,8) }}</span><span>　·　总耗时: {{ Math.round(result.metrics.total_elapsed_ms) }} ms</span><span>　·　LLM: {{ result.metrics.llm_call_count }} 次</span><span>　·　Token: {{ result.metrics.total_tokens }}</span><span>　·　重试: {{ result.metrics.retry_count }} 次</span></div>
      <div v-if="error" class="error">{{ error }}</div>
      <section v-if="result" class="workspace">
        <div class="left-stack">
          <article class="panel sql-panel"><div class="panel-head"><div><span>生成 SQL</span><h2>{{ result.plan.objective }}</h2></div><button class="ghost" @click="copySql">复制 SQL</button></div><pre><code>{{ result.sql }}</code></pre></article>
          <article class="panel table-panel"><div class="panel-head"><h2>查询结果</h2><span>{{ result.execution?.row_count||0 }} 行</span></div><div class="table-wrap"><table><thead><tr><th v-for="col in columns" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row,i) in result.execution?.rows" :key="i"><td v-for="col in columns" :key="col">{{ row[col] }}</td></tr></tbody></table></div></article>
        </div>
        <div class="right-stack">
          <article class="panel chart-panel"><div v-if="result.analysis?.chart" ref="chartEl" class="chart"></div><div v-else class="empty">本次分析无需图表</div></article>
          <article class="analysis"><h2>分析结论</h2><p>{{ result.analysis?.summary }}</p><ul><li v-for="item in result.analysis?.insights" :key="item">{{ item }}</li></ul></article>
        </div>
      </section>
      <section v-else-if="!loading" class="welcome"><div><h2>从一个业务问题开始</h2><p>系统将依次完成任务规划、Schema 检索、SQL 生成、安全校验、执行与数据分析。</p></div><span>结果将在这里展开</span></section>
    </main>
  </div>
</template>

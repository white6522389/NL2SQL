import type { StageEvent, WorkflowResult } from './types'
export async function analyze(question:string,conversationId:string,onStage:(event:StageEvent)=>void):Promise<WorkflowResult>{
  const response=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,conversation_id:conversationId})})
  if(!response.ok||!response.body) throw new Error(`请求失败：${response.status}`)
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer=''
  while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const blocks=buffer.split('\n\n');buffer=blocks.pop()||''
    for(const block of blocks){if(!block.startsWith('data: '))continue;const raw=block.slice(6);if(raw==='[DONE]')continue;const item=JSON.parse(raw);if(item.type==='stage')onStage(item.data);if(item.type==='error')throw new Error(item.data.message);if(item.type==='result')return item.data}}
  throw new Error('服务未返回分析结果')
}

// Pure scheduling: no native objects, video, system clock calls or display API.
// Times are injected so the exact shipped policy can be tested deterministically.
function captionSeconds(value){
 if(!value)return null;
 const seconds=value.start?value.start.seconds:value.seconds;
 return typeof seconds==='number'&&Number.isFinite(seconds)?seconds:null;
}
function makeCaptionPacer(report=()=>{}){
 const policy={minimum_ms:1200,maximum_ms:6000,base_ms:650,characters_per_second:6,
  catchup_start_ms:3000,catchup_full_ms:5000,catchup_minimum_ms:700,maximum_queue:12};
 let queue=[],active=null,held=null,seen=new Set(),playhead=null,lastStarted=-Infinity;
 const counters={offered:0,drawn:0,ended:0,dropped:0};
 function characters(text){return Array.from(text).filter(c=>{
  const code=c.codePointAt(0);
  return /[0-9A-Za-z\u00c0-\u024f\u0370-\u052f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(c)||(code>=0x20000&&code<=0x3134f);
 }).length;}
 function reading(text){return Math.max(policy.minimum_ms,Math.min(policy.maximum_ms,
  policy.base_ms+characters(text)*1000/policy.characters_per_second));}
 function lag(item,now){
  return Math.max(0,playhead!==null&&item.source_seconds!==null?
   (playhead-item.source_seconds)*1000:now-item.source_at);
 }
 function duration(item,now){
  const behind=lag(item,now),fraction=Math.max(0,Math.min(1,
   (behind-policy.catchup_start_ms)/(policy.catchup_full_ms-policy.catchup_start_ms)));
  if(fraction===0)return item.read_ms;
  return Math.max(policy.catchup_minimum_ms,Math.min(item.read_ms*(1-.65*fraction),
   fraction===1?1000:item.read_ms));
 }
 function details(item,now){return {presentation_id:item.id,source_epoch:item.source_epoch,
  source_stream_id:item.source_stream_id,characters:item.characters,base_duration_ms:Math.round(item.read_ms),
  duration_ms:Math.round(duration(item,now)),lag_ms:Math.round(lag(item,now)),
  mode:lag(item,now)>policy.catchup_start_ms?'catchup':'normal'};}
 function drop(item,reason,now){counters.dropped++;report({kind:'subtitle_pacing',event:'dropped',
  ...details(item,now),reason});}
 function finish(item,reason,now){
  if(!item)return;
  if(item.shown_at===null)drop(item,reason,now);
  else{counters.ended++;report({kind:'subtitle_pacing',event:'ended',...details(item,now),reason,
   shown_ms:Math.max(0,Math.round(now-item.shown_at))});}
 }
 function tick(now,clock){
  if(typeof clock==='number'&&Number.isFinite(clock))playhead=clock;
  else playhead=null;
  const previous=active&&active.id;
  // Bound overload explicitly; ordinary 3-5s lag is handled by faster reading,
  // not by discarding every late fragment.
  while(queue.length>1&&lag(queue[0],now)>10000)drop(queue.shift(),'over_10_seconds_behind',now);
  if(active){
   if(active.shown_at===null){if(now-active.selected_at>=1500){
    finish(active,'no_native_draw',now);active=held;held=null;
   }}
   else{
    const elapsed=now-active.shown_at;
    // A reading deadline permits a replacement. It must NEVER clear a drawn
    // translation while there is no ready successor (the 0.1.9 ~3s flicker).
    if(queue.length&&elapsed>=duration(active,now)){held=active;active=null;}
   }
  }
  if(!active&&queue.length){
   active=queue.shift();active.selected_at=now;active.shown_at=null;lastStarted=active.source_at;
   report({kind:'subtitle_pacing',event:'selected',...details(active,now),queue_depth:queue.length});
  }
  return previous!==(active&&active.id);
 }
 return {policy,characters,reading,
  offer(entry,source,now){
   const id=String(source.stream_id)+':'+String(source.epoch);
   if(seen.has(id))return false;
   const at=Number.isFinite(source.requested_ms)?source.requested_ms:now;
   const text=entry.texts.filter(Boolean).join('\n');
   const item={id,entry,source_epoch:source.epoch,source_stream_id:source.stream_id,
    source_at:at,source_seconds:captionSeconds(source.caption_time),characters:characters(text),
    read_ms:reading(text),ready_at:now,selected_at:null,shown_at:null};
   seen.add(id);if(seen.size>2000)seen.delete(seen.values().next().value);
   if(at<lastStarted){drop(item,'out_of_order',now);return false;}
   counters.offered++;queue.push(item);queue.sort((a,b)=>a.source_at-b.source_at||a.source_epoch-b.source_epoch);
   while(queue.length>policy.maximum_queue)drop(queue.shift(),'queue_limit',now);
   report({kind:'subtitle_pacing',event:'queued',...details(item,now),queue_depth:queue.length});
   return true;
  },tick,
  markDrawn(id,now){
   if(!active||active.id!==id||active.shown_at!==null)return false;
   // Keep the previous frame eligible until its replacement REALLY draws.
   finish(held,'reading_complete',now);held=null;
   active.shown_at=now;counters.drawn++;
   report({kind:'subtitle_pacing',event:'drawn',...details(active,now),
    request_to_draw_ms:Math.round(now-active.source_at),queue_depth:queue.length});
   return true;
  },
  current(){return active;},
  fallback(){return held;},
  displayable(id){return !!(active&&active.id===id||held&&held.id===id);},
  status(now){return {policy,...counters,queue_depth:queue.length,
   active:active?{...details(active,now),shown_ms:active.shown_at===null?null:Math.max(0,now-active.shown_at),
    holding_for_next:active.shown_at!==null&&!queue.length&&now-active.shown_at>=duration(active,now)}:null,
   displayed:held?details(held,now):active&&active.shown_at!==null?details(active,now):null};},
  reset(reason,now){finish(active,reason,now);finish(held,reason,now);active=null;held=null;
   for(const item of queue)drop(item,reason,now);
   queue=[];seen.clear();playhead=null;lastStarted=-Infinity;}
 };
}
if(typeof module!=='undefined'&&module.exports)module.exports={makeCaptionPacer,captionSeconds};

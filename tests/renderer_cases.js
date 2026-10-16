// Execute the actual renderer with controlled native geometry and CoreText calls.
// No Apple TV process, compositor or screen automation is involved.
function rendererFixture(source){
 const objects=new Map(),keep=[],hooks=new Map(),calls={frames:0,bounds:0,positions:0,draws:[],commits:[],receipts:[],messages:[],parent_layouts:0,flushes:0};
 const hold=value=>{const p=Memory.alloc(256);keep.push(p);objects.set(p.toString(),value);return p;};
 const refs=new Map();let fault=null,detachFault=false;
 const owned=p=>{const key=p.toString();refs.set(key,(refs.get(key)||0)+1);return p;};
 const drop=p=>{if(!p||p.isNull())return;const key=p.toString(),n=refs.get(key)||0;if(n<1)throw Error('Unowned/double CF release '+key);refs.set(key,n-1);};
 const live=()=>Array.from(refs.values()).reduce((a,b)=>a+b,0);
 const object=p=>objects.get(p.toString());
 const numbers=(p,n)=>Array.from({length:n},(_,i)=>p.add(i*8).readDouble());
 const write=(p,values)=>{values.forEach((v,i)=>p.add(i*8).writeDouble(v));return p;};
 const child=hold({bounds:[0,0,156,32],position:[288,93],contents:hold({backing:true})});
 const parent=hold({bounds:[0,0,720,405],position:[0,0]});
 const children=hold({values:[child]}),user=Memory.alloc(64);keep.push(user);user.add(0x30).writePointer(children);
 const library={getExportByName(name){return {toString(){return name;},readPointer(){return ptr(1);}};}};
 let drawHook=null,failFrame=false;
 const env={Memory,ptr,int64,Process:{getModuleByName(){return library;},getCurrentThreadId(){return 7;}},
  Interceptor:{attach(address,hook){const key=address.toString();hooks.set(key,hook);if(key===ptr(0xa54210).toString())drawHook=hook;return {detach(){hooks.delete(key);if(detachFault){detachFault=false;throw Error('Injected detach failure');}}};}},
  cf:library,ct:library,qc:library,cm:{base:ptr(0x100000)},PROFILE:{},
  enabled:true,layer:parent,layerUser:user,currentKey:'source-1',currentSources:['First source.'],epoch:1,streamId:1,
  stats:{errors:0,translated_groups:0},requestMs:Date.now(),types:{Array:1},textKey:ptr(1),
  entry:{texts:['这是第一条译文。'],mode:'Translated',paragraph:true,source_text:'First source.',presentation:{id:'1:1',source_stream_id:1,source_epoch:1}},
  pacer:{displayable(id){return id==='1:1'||id==='1:2';}},
  retain(p){return owned(p);},release:drop,caLock(){},caUnlock(){},
  send(value){calls.messages.push(value);},completedCue(value){calls.receipts.push(value);},
  displayEntry(){return env.entry;},
  type(p){return uint64(object(p).values?1:2);},
  arrayCount(p){return int64(object(p).values.length);},arrayAt(p,i){return object(p).values[i];},
  dictGet(p){if(fault==='template'){fault=null;throw Error('Injected template failure');}return object(p).attribute||ptr(0);},readAttr(p){return object(p).text;},
  getString(p){return p;},getLength(p){return int64(object(p).text.length);},
  cs(text){if(fault==='string'){fault=null;throw Error('Injected string failure');}return owned(hold({text}));},attrCopy(_a,_n,p){return owned(hold({...object(p)}));},
  replaceString(a,_range,s){object(a).text=object(s).text;},
  arrayCopy(_a,_n,p){return owned(hold({values:object(p).values.slice()}));},
  needsDisplay(){},needsLayout(){calls.parent_layouts++;},flush(){calls.flushes++;},context(){return ptr(0x200);},user(){return user;},
 };
 const apis={
  CACFLayerGetBounds(out,p){return write(out,object(p).bounds);},
  CACFLayerGetPosition(out,p){return write(out,object(p).position);},
  CACFLayerGetContents(p){return object(p).contents;},
  CACFLayerSetContents(p,value){object(p).contents=value;},
  CACFLayerSetBounds(p,value){calls.bounds++;object(p).bounds=numbers(value,4);},
  CACFLayerSetPosition(p,value){calls.positions++;object(p).position=numbers(value,2);},
  CACFLayerIsGeometryFlipped(){return 0;},
  CTFramesetterCreateWithAttributedString(p){return owned(hold({...object(p)}));},
  CTFramesetterCreateFrame(setter){calls.frames++;const text=object(setter).text;
   const count=Math.max(text.includes('\n')?2:1,Math.ceil(text.length/20));
   return owned(hold({text,lines:hold({values:Array.from({length:count},()=>hold({text}))})}));},
  CTFrameGetVisibleStringRange(out,p){out.writeS64(0);out.add(8).writeS64(object(p).text.length-(failFrame?1:0));return out;},
  CTFrameGetLines(p){return object(p).lines;},
  CTFrameGetLineOrigins(p,_range,out){object(object(p).lines).values.forEach((_,i)=>write(out.add(i*16),[8,2000-i*16]));},
  CTLineGetTypographicBounds(_p,a,d,l){if(!a.isNull())a.writeDouble(10);if(!d.isNull())d.writeDouble(4);if(!l.isNull())l.writeDouble(0);return 100;},
  CTLineCreateWithAttributedString(p){return owned(hold({...object(p)}));},
  CTFrameDraw(p){calls.draws.push(p.toString());},
  CGPathCreateMutable(){return owned(hold({}));},CGPathAddRect(){},
  CGContextGetClipBoundingBox(out){return write(out,[0,0,4096,4096]);},
  CGContextGetCTM(out){return write(out,[1,0,0,1,0,0]);},
  CFArrayRemoveAllValues(p){object(p).values=[];},
 };
 env.api=(_module,name)=>apis[name]||(()=>{});
 const renderer=new Function('env','with(env){'+source+';return makeBilingualRenderer();}')(env);
 function observe(key='source-1'){
  env.currentKey=key;const attribute=hold({text:'A native font template.'}),row=hold({attribute});renderer.observe(hold({values:[row]}),key);
 }
 function native(bounds,position){object(child).bounds=bounds.slice();object(child).position=position.slice();}
 function draw(notify=true){if(object(child).bounds[2]<1||object(child).bounds[3]<1)return false;
  const count=calls.draws.length,invocation={};drawHook.onEnter.call(invocation,[child,ptr(0x100)]);
  const rows=hold({values:[hold({text:'English source'})]}),args=[ptr(0),rows,ptr(0x100)];
  const suppressed=renderer.suppress(args);
  if(notify){const h=hooks.get('CFNotificationCenterPostNotification');if(h)h.onEnter.call({returnAddress:env.cm.base.add(0x954416)},[ptr(0),ptr(0),ptr(0x200)]);
   calls.commits.push(calls.draws.length>count?calls.draws[calls.draws.length-1]:'empty');}
  drawHook.onLeave.call(invocation);if(suppressed)drop(suppressed);return !!suppressed;
 }
 function setter(name,args,rva){const h=hooks.get(name),invocation={returnAddress:env.cm.base.add(rva)};if(h&&h.onEnter)h.onEnter.call(invocation,args);apis[name](...args);if(h&&h.onLeave)h.onLeave.call(invocation);}
 function clear(layout=true){const zero=Memory.alloc(32);write(zero,[0,0,0,0]);setter('CACFLayerSetBounds',[child,zero],0x954177);setter('CACFLayerSetContents',[child,ptr(0)],0x954182);env.currentKey='';env.currentSources=[];env.epoch++;if(layout)renderer.layout();}
 function refresh(bridge,presentation){parent.add(0x98).writePointer(env.cm.base.add(0x953e20));child.add(0x90).writePointer(env.cm.base.add(0x954210));
  env.bilingual=renderer;env.PROFILE.disable_redraw=false;env.stats.redraws=0;
  const code=bridge.slice(bridge.indexOf('function redrawCEA('),bridge.indexOf('function redraw('));
  new Function('env','with(env){'+code+';redrawCEA('+presentation+');}')(env);
 }
 observe();
 function nativeBounds(bounds,position){object(child).position=position.slice();const buffer=Memory.alloc(32);write(buffer,bounds);setter('CACFLayerSetBounds',[child,buffer],0x95414f);renderer.layout();}
 return {env,calls,renderer,child,parent,object,native,nativeBounds,observe,draw,clear,refresh,live,fault(value){fault=value;},detachFault(){detachFault=true;},fail(value){failFrame=value;}};
}

function captionRendererCases(source,bridge=''){
 const cases={};
 const assert=(v,message)=>{if(!v)throw Error(message);};
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 cases.complete_native_frame_and_suppression=()=>{
  const f=rendererFixture(source);f.renderer.layout();assert(f.draw(),'English not suppressed');
  assert(f.calls.draws.length===1&&f.calls.receipts.length===1,'Missing native draw receipt');assert(!f.env.stats.errors,'Draw error');
 };
 cases.unchanged_presentation_does_not_rebuild_or_rewrite=()=>{
  const f=rendererFixture(source);f.renderer.layout();const before=[f.calls.frames,f.calls.bounds,f.calls.positions];
  f.renderer.layout();assert(same(before,[f.calls.frames,f.calls.bounds,f.calls.positions]),'Unchanged presentation rebuilt or rewrote geometry');
 };
 cases.new_source_keeps_held_frame_and_position=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();const frame=f.calls.draws[0],position=f.object(f.child).position.slice(),bounds=f.object(f.child).bounds.slice(),count=f.calls.frames;
  f.native([0,0,120,32],[266.5,93]);f.env.epoch=2;f.env.currentSources=['Different source.'];f.observe('source-2');f.renderer.layout();f.draw();
  assert(same(f.object(f.child).position,position)&&same(f.object(f.child).bounds,bounds),'Held subtitle moved with raw English');
  assert(f.calls.frames===count&&f.calls.draws[1]===frame,'Held frame rebuilt');
 };
 cases.stop_restores_latest_native_geometry_after_holding=()=>{
  const f=rendererFixture(source);f.renderer.layout();const bounds=[0,0,120,32],position=[266.5,93];
  f.native(bounds,position);f.env.epoch=2;f.observe('source-2');f.renderer.layout();f.renderer.restoreGeometry();
  assert(same(f.object(f.child).bounds,bounds)&&same(f.object(f.child).position,position),'Latest native restoration lost');
 };
 cases.parent_resize_reflows_instead_of_pinning_stale_layout=()=>{
  const f=rendererFixture(source);f.renderer.layout();const count=f.calls.frames;
  f.object(f.parent).bounds=[0,0,1280,720];f.native([0,0,280,48],[420,120]);f.renderer.layout();
  assert(f.calls.frames>count,'Resize did not rebuild');assert(f.draw(),'Resized translation not drawn');
 };
 cases.new_translation_is_a_direct_complete_replacement=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();const old=f.calls.draws[0];
  f.env.entry={...f.env.entry,texts:['这是下一条较长的译文。'],presentation:{id:'1:2',source_stream_id:1,source_epoch:2}};
  f.renderer.layout();assert(f.draw(),'Replacement leaked English');assert(f.calls.draws[1]!==old,'New translation not installed');
 };
 cases.failed_successor_preparation_keeps_old_drawable=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();const old=f.calls.draws[0];
  f.env.entry={...f.env.entry,texts:['下一条'],presentation:{id:'1:2',source_stream_id:1,source_epoch:2}};
  f.fail(true);let failed=false;try{f.renderer.layout();}catch(e){failed=true;}
  assert(failed,'Failure fixture did not fail');assert(f.draw()&&f.calls.draws[1]===old,'Failed preparation removed held frame');
 };
 cases.blank_source_does_not_clear_drawn_translation=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();const old=f.calls.draws[0];
  f.env.currentKey='';f.env.currentSources=[];f.env.epoch++;f.renderer.layout();
  assert(f.draw()&&f.calls.draws[1]===old,'Blank source exposed English');
 };
 cases.stop_clears_translation_and_restores_original=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.env.enabled=false;f.renderer.layout();
  assert(!f.draw()&&f.calls.draws.length===0,'Stopped renderer still draws');assert(same(f.object(f.child).bounds,[0,0,156,32]),'Stop did not restore bounds');
 };
 cases.stream_change_rejects_previous_frame=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.env.streamId++;
  f.draw();assert(f.calls.draws.length===0,'Old stream frame drawn');
 };
 cases.paint_precedes_native_completion_notification=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();
  assert(f.calls.commits[0]!=='empty','Native completion observed an empty frame before Chinese paint');
  assert(f.calls.draws.length===1&&f.calls.receipts.length===1,'Paint/receipt duplicated');
 };
 cases.missing_notification_still_paints_once_at_callback_end=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw(false);
  assert(f.calls.draws.length===1&&f.calls.receipts.length===1,'Fallback callback did not paint once');
 };
 cases.native_empty_cue_preserves_caption_bounds_and_contents=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();const b=f.object(f.child).bounds.slice(),content=f.object(f.child).contents;
  f.clear();assert(same(f.object(f.child).bounds,b),'Native empty cue collapsed translated layer');
  assert(f.object(f.child).contents.equals(content),'Native empty cue erased the backing store');assert(f.draw(),'Held Chinese lost after native clear');
 };
 cases.ready_translation_replaces_held_caption_during_source_gap=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();const old=f.calls.draws[0];f.clear();
  f.env.entry={...f.env.entry,texts:['后续译文已经就绪。'],presentation:{id:'1:2',source_stream_id:1,source_epoch:2}};
  f.renderer.layout();assert(f.draw()&&f.calls.draws[1]!==old,'Ready translation waited for another English cue');
  assert(f.calls.commits[1]!=='empty','Source-gap replacement committed empty');
 };
 cases.empty_caption_window_keeps_frame_and_restores_exact_native_bounds=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.draw();const b=f.object(f.child).bounds.slice(),p=f.object(f.child).position.slice();
  f.nativeBounds([0,0,0,32],[0,93]);
  assert(same(f.object(f.child).bounds,b)&&same(f.object(f.child).position,p),'Zero-width native window blanked the held subtitle');
  f.env.enabled=false;f.renderer.restoreGeometry();
  assert(same(f.object(f.child).bounds,[0,0,0,32])&&same(f.object(f.child).position,[0,93]),'Native zero-width restoration lost');
 };
 cases.stop_allows_native_empty_cue_clear=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.env.enabled=false;f.clear(false);
  assert(same(f.object(f.child).bounds,[0,0,0,0])&&f.object(f.child).contents.isNull(),'Stop blocked native clearing');
 };
 cases.new_stream_allows_native_empty_cue_clear=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.env.streamId++;f.clear();
  assert(f.object(f.child).contents.isNull(),'Old stream blocked native clearing');
 };
 if(bridge)cases.translation_refresh_does_not_run_original_parent_layout=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.refresh(bridge,true);
  assert(f.calls.parent_layouts===0&&f.calls.flushes===1,'Translation refresh reran English parent layout');
 };
 if(bridge)cases.stop_refresh_runs_original_parent_layout=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.env.enabled=false;f.refresh(bridge,false);
  assert(f.calls.parent_layouts===1,'Native restoration did not request parent layout');
 };
 cases.cf_ownership_plateaus_and_closes=()=>{
  const f=rendererFixture(source);f.renderer.layout();const plateau=f.live();
  for(let i=0;i<200;i++){f.env.entry={...f.env.entry,texts:['字幕 '+i],presentation:{id:'1:2',source_stream_id:1,source_epoch:i+2}};f.observe('source-'+(i+2));f.renderer.layout();f.draw();assert(f.live()===plateau,'CF ownership grows at '+i);}
  f.renderer.close();f.renderer.close();assert(f.live()===0,'CF ownership remains after close');
 };
 cases.template_failure_preserves_owned_old_template=()=>{
  const f=rendererFixture(source);f.renderer.layout();const before=f.live();f.fault('template');let failed=false;try{f.observe('next');}catch(e){failed=true;}
  assert(failed&&f.live()===before,'Failed template acquisition released active template');f.renderer.close();assert(f.live()===0,'Template failure leaked or double-freed');
 };
 cases.string_allocation_failure_releases_partial_frame=()=>{
  const f=rendererFixture(source);f.renderer.layout();const before=f.live();f.env.entry={...f.env.entry,texts:['next']};f.fault('string');let failed=false;try{f.renderer.layout();}catch(e){failed=true;}
  assert(failed&&f.live()===before,'Partial string allocation leaked');assert(f.draw(),'Old frame removed by allocation failure');f.renderer.close();assert(f.live()===0,'Close after failed replacement leaked');
 };
 cases.failed_hook_cleanup_still_releases_frames_and_template=()=>{
  const f=rendererFixture(source);f.renderer.layout();f.detachFault();f.renderer.close();assert(f.live()===0,'Hook detach error skipped CF cleanup');
 };
 if(bridge)cases.native_cache_limits_text_bytes_and_entries=()=>{
  const begin=bridge.indexOf('class CaptionCache'),end=bridge.indexOf('let layer=null',begin);
  assert(begin>=0,'Native cache has no text-byte budget');
  const cache=new Function(bridge.slice(begin,end)+';return new CaptionCache();')();
  for(let i=0;i<2000;i++){cache.set('source '+i,{texts:['中文'.repeat(1000)]});assert(cache.size<=128&&cache.bytes<=1048576,'Native text cache exceeded budget');}
  cache.set('oversize',{texts:['x'.repeat(40000)]});assert(!cache.has('oversize'),'Oversize native entry retained');
  cache.clear();assert(cache.size===0&&cache.bytes===0,'Native cache clear left accounting/data');
 };
 return {names(){return Object.keys(cases);},run(name){cases[name]();return true;}};
}

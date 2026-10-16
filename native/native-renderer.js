'use strict';
// Caption-only CF object copies; Apple retains timing, CEA-608 geometry and rendering.
const cf=Process.getModuleByName('CoreFoundation.dll'),cm=Process.getModuleByName('CoreMedia.dll'),qc=Process.getModuleByName('QuartzCore.dll'),ct=Process.getModuleByName('CoreText.dll');
for(const name of ['AMPLibraryAgent.exe','CoreMedia.dll','CoreText.dll','CoreFoundation.dll','QuartzCore.dll','CoreGraphics.dll']){
 if(Process.getModuleByName(name).path.toLowerCase()!==(PROFILE.package_root+'\\'+name).toLowerCase())throw new Error('Unexpected module path: '+name);
}
// Check the running code before installing any interceptor.
for(const check of PROFILE.hooks){
 const bytes=new Uint8Array(Process.getModuleByName(check.module).base.add(check.rva).readByteArray(check.bytes.length/2));
 const actual=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
 if(actual!==check.bytes)throw new Error('Unsupported running code: '+check.module+' '+check.rva.toString(16));
}
const api=(m,n,r,a)=>new NativeFunction(m.getExportByName(n),r,a);
const type=api(cf,'CFGetTypeID','uint64',['pointer']);
const types={};for(const n of ['Array','Dictionary','AttributedString'])types[n]=api(cf,'CF'+n+'GetTypeID','uint64',[])().toNumber();
types.String=api(cf,'CFStringGetTypeID','uint64',[])().toNumber();
const retain=api(cf,'CFRetain','pointer',['pointer']),release=api(cf,'CFRelease','void',['pointer']);
const arrayCount=api(cf,'CFArrayGetCount','int64',['pointer']),arrayAt=api(cf,'CFArrayGetValueAtIndex','pointer',['pointer','int64']);
const arrayCopy=api(cf,'CFArrayCreateMutableCopy','pointer',['pointer','int64','pointer']),arraySet=api(cf,'CFArraySetValueAtIndex','void',['pointer','int64','pointer']);
const dictGet=api(cf,'CFDictionaryGetValue','pointer',['pointer','pointer']),dictCopy=api(cf,'CFDictionaryCreateMutableCopy','pointer',['pointer','int64','pointer']);
const dictSet=api(cf,'CFDictionarySetValue','void',['pointer','pointer','pointer']);
const getString=api(cf,'CFAttributedStringGetString','pointer',['pointer']);
const getLength=api(cf,'CFStringGetLength','int64',['pointer']);
const getCString=api(cf,'CFStringGetCString','uchar',['pointer','pointer','int64','uint']);
const attrCopy=api(cf,'CFAttributedStringCreateMutableCopy','pointer',['pointer','int64','pointer']);
const replaceString=api(cf,'CFAttributedStringReplaceString','void',['pointer',['int64','int64'],'pointer']);
const makeString=api(cf,'CFStringCreateWithCharacters','pointer',['pointer','pointer','int64']);
function cs(text){return makeString(ptr(0),Memory.allocUtf16String(text),text.length);}
const textKey=cs('QuickTimeClosedCaptionStringKey');
const caLock=api(qc,'CACFLock','void',[]),caUnlock=api(qc,'CACFUnlock','void',[]);
const needsLayout=api(qc,'CACFLayerSetNeedsLayout','void',['pointer']);
const needsDisplay=api(qc,'CACFLayerSetNeedsDisplay','void',['pointer','pointer']);
const context=api(qc,'CACFLayerGetContext','pointer',['pointer']);
const flush=api(qc,'CACFContextFlush','void',['pointer']);
const user=api(qc,'CACFLayerGetUserData','pointer',['pointer']);
// UTF-16 accounting is a conservative text-storage budget, independent of item count.
class CaptionCache extends Map{
 constructor(){super();this.bytes=0;this.costs=new Map();}
 delete(key){if(this.has(key)){this.bytes-=this.costs.get(key);this.costs.delete(key);}return super.delete(key);}
 clear(){super.clear();this.costs.clear();this.bytes=0;}
 set(key,value){this.delete(key);const cost=2*(key.length+JSON.stringify(value).length);if(cost>65536)return this;
  super.set(key,value);this.costs.set(key,cost);this.bytes+=cost;
  while(this.size>128||this.bytes>1048576)this.delete(this.keys().next().value);return this;}
}
let layer=null,layerUser=null,pipeline=null,epoch=1,streamId=1,enabled=true,cache=new CaptionCache(),pending=new Set(),currentKey='',currentSources=[],lastTranslatedKey='',requestMs=0;
let callbackTime=null,currentTime=null,lastClock=null,lastClockWall=0,rendererTimes=new Map(),lastUpdateMs=0,stopped=false;
let route=null,movieLayer=null,movieOwner=null,movieLanguage=null,movieTime=null,moviePipeline=null;
const completedEpochs=new Set();
const drawnRows=new Map();
const sampleTimes=new Map(),threadSampleTimes=new Map();
const movieOwnerType=api(cm,'FigSubtitleCACFLayerGetTypeID','uint64',[])().toNumber();
const movieKeys={};for(const name of ['subtitleSample','SubtitleContent','SubtitleExtendedLanguageTag'])movieKeys[name]=cs(name);
const stats={groups:0,changes:0,requests:0,translated_groups:0,fallback_groups:0,redraws:0,errors:0,stale:0};
const pacingEnabled=PROFILE.pacing!==false;
const pacer=makeCaptionPacer(value=>send(value));
function pacingClock(){return lastClock&&typeof lastClock.seconds==='number'?lastClock.seconds:null;}
function displayEntry(){
 if(!pacingEnabled)return cache.get(currentKey);
 const item=pacer.current();if(!item)return null;
 return {...item.entry,texts:[item.entry.texts.filter(Boolean).join('\n'),...currentSources.slice(1).map(()=>'')],
  presentation:{id:item.id,source_epoch:item.source_epoch,source_stream_id:item.source_stream_id,
   source_at:item.source_at,source_seconds:item.source_seconds}};
}
function observedCue(){send({kind:'caption_observed',epoch,route,lines:currentSources.length});}
function completedCue(value){
 if(value.presentation){
  const p=value.presentation;
  if(pacer.markDrawn(p.id,Date.now()))send({kind:'presentation_draw_complete',presentation_id:p.id,
   source_epoch:p.source_epoch,source_stream_id:p.source_stream_id,host_epoch:value.epoch,
   source_seconds:p.source_seconds,request_to_draw_ms:Date.now()-p.source_at,layout:value.layout});
  // A held older translation drawn on a newer native cue is NOT coverage of
  // that newer source. Keep presentation and original-cue receipts distinct.
  if(p.source_epoch!==value.epoch||p.source_stream_id!==streamId)return;
 }
 if(completedEpochs.has(value.epoch))return;
 let rows=drawnRows.get(value.epoch);
 if(!rows){rows=new Set();drawnRows.set(value.epoch,rows);}
 for(const index of value.drawnIndexes)rows.add(index);
 if(drawnRows.size>1000)drawnRows.delete(drawnRows.keys().next().value);
 if(rows.size<value.lineCount)return;
 completedEpochs.add(value.epoch);
 drawnRows.delete(value.epoch);
 if(completedEpochs.size>1000)completedEpochs.delete(completedEpochs.values().next().value);
 send({kind:'native_draw_complete',route:value.route,epoch:value.epoch,lines:value.lineCount,
       drawn_lines:rows.size,request_to_draw_ms:value.latency,layout:value.layout});
}
function nativeTime(p){const value=p.readS64().toString(),timescale=p.add(8).readS32(),flags=p.add(12).readU32(),native_epoch=p.add(16).readS64().toString();return {value,timescale,flags,native_epoch,seconds:timescale>0&&(flags&1)?Number(value)/timescale:null};}
function generation(reason,clear=false){epoch++;pending.clear();currentKey='';currentSources=[];currentTime=null;const reset=clear&&(/pipeline_changed$/.test(reason)||reason==='native_timeline_discontinuity'||reason==='subtitle_language_changed'||reason.startsWith('subtitle_route_'));if(clear){if(reset){streamId++;pacer.reset(reason,Date.now());}cache.clear();rendererTimes.clear();threadSampleTimes.clear();sampleTimes.clear();}send({kind:'caption_generation',epoch,stream_id:streamId,reset_context:reset,reason});}
function forgetLayer(){const old=layer,u=layerUser;layer=null;layerUser=null;if(u)release(u);if(old)release(old);}
function forgetMovie(){const owner=movieOwner;movieLayer=null;movieOwner=null;if(owner)release(owner);}
function setRoute(value){if(route!==value){generation('subtitle_route_'+value,true);if(value==='webvtt')forgetLayer();else forgetMovie();route=value;}}
function readAttr(p){const s=getString(p),n=getLength(s).toNumber();if(n<1||n>2048)return '';const b=Memory.alloc(n*4+1);return getCString(s,b,n*4+1,0x08000100)?b.readUtf8String():'';}
function gather(p,out,depth=0){
 if(depth>3||p.isNull())throw new Error('Unsupported caption structure');
 const id=type(p).toNumber();
 if(id===types.Array){const n=arrayCount(p).toNumber();if(n<0||n>32)throw new Error('Caption row count exceeds bound');for(let i=0;i<n;i++)gather(arrayAt(p,i),out,depth+1);return;}
 if(id===types.Dictionary){const a=dictGet(p,textKey);if(!a.isNull()&&type(a).toNumber()===types.AttributedString){const text=readAttr(a);if(text)out.push(text);}return;}
 throw new Error('Unsupported caption row type');
}
function clone(p,texts,index,depth=0){
 const id=type(p).toNumber();
 if(id===types.Array){const result=arrayCopy(ptr(0),0,p);if(result.isNull())throw new Error('Array copy failed');try{const n=arrayCount(p).toNumber();for(let i=0;i<n;i++){const c=clone(arrayAt(p,i),texts,index,depth+1);try{arraySet(result,i,c);}finally{release(c);}}return result;}catch(e){release(result);throw e;}}
 const original=dictGet(p,textKey);if(original.isNull()||type(original).toNumber()!==types.AttributedString||!readAttr(original))return retain(p);
 const result=dictCopy(ptr(0),0,p);if(result.isNull())throw new Error('Dictionary copy failed');
 let a=null,s=null;try{a=attrCopy(ptr(0),0,original);s=cs(texts[index.value++]);if(a.isNull()||s.isNull())throw new Error('Text copy failed');replaceString(a,[int64(0),getLength(getString(original))],s);dictSet(result,textKey,a);return result;}catch(e){release(result);throw e;}finally{if(a&&!a.isNull())release(a);if(s&&!s.isNull())release(s);}
}
function redrawCEA(presentation=false){
 if(!layer||PROFILE.disable_redraw)return;
 caLock();try{
  // The parent has ONLY a layout callback. Never mark it for display.
  if(!layer.add(0x98).readPointer().equals(cm.base.add(0x953e20)))throw new Error('Caption layout callback changed');
  const c=context(layer);if(c.isNull())return;
  const u=user(layer);if(u.isNull()||!layerUser||!u.equals(layerUser))return;
  const children=u.add(0x30).readPointer();if(children.isNull()||type(children).toNumber()!==types.Array)throw new Error('Caption child layers unavailable');
  const n=arrayCount(children).toNumber();if(n>16)throw new Error('Unexpected caption layer count');
  // A translation update prepares its own complete frame. Re-running Apple's
  // English layout here can collapse/clear the current backing store first.
  if(presentation)bilingual.layout();else needsLayout(layer);
  for(let i=0;i<n;i++){const child=arrayAt(children,i);if(child.add(0x90).readPointer().equals(cm.base.add(0x954210)))needsDisplay(child,ptr(0));}
  flush(c);stats.redraws++;
 }finally{caUnlock();}
}
function redraw(presentation=false){
 if(route!=='webvtt'){redrawCEA(presentation);return;}
 if(!movieLayer||!movieOwner||PROFILE.disable_redraw)return;
 caLock();try{
  if(!movieLayer.add(0x90).readPointer().equals(cm.base.add(0xb1d580))||!movieLayer.add(0x98).readPointer().equals(cm.base.add(0xb1d450)))throw new Error('Movie subtitle callbacks changed');
  if(!user(movieLayer).equals(movieOwner.add(0x20)))return;
  const c=context(movieLayer);if(c.isNull())return;
  needsLayout(movieLayer);needsDisplay(movieLayer,ptr(0));flush(c);stats.redraws++;
 }finally{caUnlock();}
}
const bilingual=makeBilingualRenderer();
// Switch the native frame directly. Restoring English geometry first schedules
// an intermediate paint; geometry is restored only on explicit reset/Stop.
function redrawPresentation(){redraw(enabled);}
function listen(){recv('translation',msg=>{
 const v=msg.payload;pending.delete(v.key);
 if(v.epoch!==epoch||v.stream_id!==undefined&&v.stream_id!==streamId){stats.stale++;listen();return;}
 try{if(v.texts&&v.texts.length){
  const entry={texts:v.texts,mode:v.subtitle_mode||'Translated',paragraph:!!v.paragraph,
   source_text:typeof v.display_source==='string'?v.display_source:currentSources.join('\n')};
  cache.set(v.key,entry);
  if(pacingEnabled){pacer.offer(entry,{...v,stream_id:streamId},Date.now());
   if(enabled&&pacer.tick(Date.now(),pacingClock()))redrawPresentation();
  }else if(enabled&&v.key===currentKey)redraw();
 }}catch(e){enabled=false;stats.errors++;send({kind:'bridge_error',error:String(e)});}listen();
});}listen();
const timeHook=Interceptor.attach(cm.base.add(0x95a350),{onEnter(args){this.previous=callbackTime;try{callbackTime=nativeTime(args[2]);}catch(e){callbackTime=null;}},onLeave(){callbackTime=this.previous;}});
const stateHook=Interceptor.attach(cm.base.add(0x955030),{onEnter(args){if(callbackTime){rendererTimes.set(args[0].toString(),callbackTime);if(rendererTimes.size>32)rendererTimes.delete(rendererTimes.keys().next().value);}}});
const pipelineHook=Interceptor.attach(cm.base.add(0x9592b0),{onEnter(args){if(pipeline&&!pipeline.equals(args[0])){generation('playback_pipeline_changed',true);forgetLayer();}pipeline=args[0];}});
const clockHook=Interceptor.attach(cm.getExportByName('CMTimebaseGetTime'),{onEnter(args){this.out=(this.returnAddress.compare(cm.base.add(0x9592b0))>=0&&this.returnAddress.compare(cm.base.add(0x959600))<0)?args[0]:null;},onLeave(){if(!this.out)return;try{const now=nativeTime(this.out),wall=Date.now();if(lastClock&&now.seconds!==null&&lastClock.seconds!==null){const delta=now.seconds-lastClock.seconds,elapsed=(wall-lastClockWall)/1000;if(now.native_epoch!==lastClock.native_epoch||delta< -0.25||delta>elapsed+2)generation('native_timeline_discontinuity',true);}lastClock=now;lastClockWall=wall;}catch(e){}}});
const userdataHook=Interceptor.attach(qc.getExportByName('CACFLayerSetUserData'),{onEnter(args){if(layer&&layer.equals(args[0])&&layerUser&&!layerUser.equals(args[1])){generation('caption_layer_retired',true);forgetLayer();}if(movieLayer&&movieLayer.equals(args[0])&&movieOwner&&!movieOwner.add(0x20).equals(args[1])){generation('movie_layer_retired',true);forgetMovie();}}});
const layerHook=Interceptor.attach(cm.base.add(0x953e20),{onEnter(args){try{setRoute('cea608');if(!layer||!layer.equals(args[0])){forgetLayer();layer=retain(args[0]);const u=user(layer);if(!u.isNull())layerUser=retain(u);generation('caption_layer_changed',true);}if(layerUser){currentTime=rendererTimes.get(layerUser.add(0x28).readPointer().toString())||null;}lastUpdateMs=Date.now();}catch(e){stats.errors++;send({kind:'bridge_error',error:String(e)});}},onLeave(){try{bilingual.layout();}catch(e){stats.errors++;send({kind:'draw_error',error:String(e)});}}});
// Movie captions use a complete attributed text block and a separate CA layer.
const movieLayerHook=Interceptor.attach(cm.base.add(0xb1d580),{onEnter(args){try{
 setRoute('webvtt');const u=user(args[0]);if(u.isNull())return;const owner=u.sub(0x20);
 if(type(owner).toNumber()!==movieOwnerType||!owner.add(0x28).readPointer().equals(args[0]))throw new Error('Unsupported movie subtitle owner');
 if(!movieOwner||!movieOwner.equals(owner)){forgetMovie();movieOwner=retain(owner);movieLayer=args[0];generation('movie_layer_changed',true);}currentTime=movieTime;lastUpdateMs=Date.now();
}catch(e){stats.errors++;send({kind:'bridge_error',error:String(e)});}}});
const movieParserHook=Interceptor.attach(cm.getExportByName('FigSubtitleSampleCreateFromPropertyList'),{onEnter(args){try{
 const sample=dictGet(args[0],movieKeys.subtitleSample);if(sample.isNull())return;
 const language=dictGet(sample,movieKeys.SubtitleExtendedLanguageTag);
 let name=null;if(!language.isNull()&&type(language).toNumber()===types.String){const n=getLength(language).toNumber(),b=Memory.alloc(n*4+1);if(n<64&&getCString(language,b,n*4+1,0x08000100))name=b.readUtf8String();}
 if(movieLanguage!==name){movieLanguage=name;generation('subtitle_language_changed',true);}
 const content=dictGet(sample,movieKeys.SubtitleContent);if(!content.isNull()&&type(content).toNumber()===types.Array&&arrayCount(content).toNumber()===0&&route==='webvtt')generation('subtitle_cleared');
}catch(e){stats.errors++;send({kind:'bridge_error',error:String(e)});}}});
const movieTimeHooks=[];
for(const [name,rva] of [['start',0x289db0],['duration',0x289a40]])movieTimeHooks.push(Interceptor.attach(cm.base.add(rva),{onEnter(args){this.out=(this.returnAddress.compare(cm.base.add(0x8bddc0))>=0&&this.returnAddress.compare(cm.base.add(0x8be730))<0)?args[0]:null;},onLeave(){if(!this.out)return;try{const id=Process.getCurrentThreadId(),t=nativeTime(this.out);if(name==='start'){threadSampleTimes.set(id,{start:t});if(threadSampleTimes.size>64)threadSampleTimes.delete(threadSampleTimes.keys().next().value);}else{const pair=threadSampleTimes.get(id);if(pair){threadSampleTimes.delete(id);pair.duration=t;sampleTimes.set(JSON.stringify(pair.start),pair);if(sampleTimes.size>64)sampleTimes.delete(sampleTimes.keys().next().value);}}}catch(e){}}}));
const movieDispatchHook=Interceptor.attach(cm.base.add(0x8bdc20),{onEnter(args){try{
 const p=args[0],nativePipeline=p.readPointer(),start=nativeTime(p.add(0x20));
 if(moviePipeline&&!moviePipeline.equals(nativePipeline)){generation('movie_pipeline_changed',true);forgetMovie();}moviePipeline=nativePipeline;
 movieTime=sampleTimes.get(JSON.stringify(start))||{start,duration:null};
 if(movieTime.duration&&movieTime.start.seconds!==null&&movieTime.duration.seconds!==null)movieTime={...movieTime,end_seconds:movieTime.start.seconds+movieTime.duration.seconds};
}catch(e){stats.errors++;send({kind:'bridge_error',error:String(e)});}}});
// CoreText renderer draw interface receives the complete CF subtitle sample.
// Its dispatch_sync_f call completes before onLeave, so temporary copies live
// through all length/range queries. The original scheduled sample stays intact.
const movieFrameHook=Interceptor.attach(cm.base.add(0xb14f10),{
 onEnter(args){try{
  if(!enabled||!movieLanguage||!/^en(?:-|$)/i.test(movieLanguage))return;
  const original=args[1];if(original.isNull()||type(original).toNumber()!==types.Dictionary)return;
  const content=dictGet(original,movieKeys.SubtitleContent);if(content.isNull()||type(content).toNumber()!==types.Array)return;
  const n=arrayCount(content).toNumber();if(n<1||n>16)return;
  const sources=[];for(let i=0;i<n;i++){const a=arrayAt(content,i);if(type(a).toNumber()!==types.AttributedString)return;sources.push(readAttr(a));}
  if(sources.some(s=>!s||/[\u3400-\u9fff]/.test(s)))return;setRoute('webvtt');
  const key=JSON.stringify(sources);stats.groups++;if(key!==currentKey){cache.delete(key);currentKey=key;currentSources=sources;currentTime=movieTime;epoch++;pending.clear();requestMs=Date.now();stats.changes++;send({kind:'caption_generation',epoch,stream_id:streamId});observedCue();}
  if(!cache.has(key)){stats.fallback_groups++;if(!pending.has(key)){pending.add(key);stats.requests++;send({kind:'translate_group',key,sources,epoch,stream_id:streamId,route,requested_ms:Date.now(),caption_time:currentTime});}}
  const entry=displayEntry();if(!entry)return;
  const texts=entry.mode==='Bilingual'?[entry.texts.filter(Boolean).join('\n')+'\n'+(entry.source_text||sources.join('\n')),...sources.slice(1).map(()=>'')]:entry.texts;
  const copy=dictCopy(ptr(0),0,original);let rows=null;
  try{rows=arrayCopy(ptr(0),0,content);for(let i=0;i<n;i++){let a=null,s=null;try{a=attrCopy(ptr(0),0,arrayAt(content,i));s=cs(texts[i]);replaceString(a,[int64(0),getLength(getString(a))],s);arraySet(rows,i,a);}finally{if(a)release(a);if(s)release(s);}}dictSet(copy,movieKeys.SubtitleContent,rows);}catch(e){release(copy);throw e;}finally{if(rows)release(rows);}
  this.copy=copy;this.epoch=epoch;this.route='webvtt';this.lineCount=n;this.drawnIndexes=Array.from({length:n},(_,i)=>i);this.latency=Date.now()-requestMs;this.presentation=entry.presentation;args[1]=copy;stats.translated_groups++;
  if(currentKey!==lastTranslatedKey){lastTranslatedKey=currentKey;send({kind:'native_group_translated',route,epoch,lines:sources.length,caption_time:currentTime,accepted_ms:Date.now()});}
 }catch(e){stats.errors++;send({kind:'draw_error',error:String(e)});}},onLeave(){if(this.copy){release(this.copy);completedCue(this);}}
});
const rowsHook=Interceptor.attach(cm.base.add(0x9474f0),{
 onEnter(args){try{
  if(!enabled)return;
  const sources=[];gather(args[0],sources);if(!sources.length){if(currentKey){currentKey='';currentSources=[];epoch++;pending.clear();send({kind:'caption_generation',epoch});}return;}
  const key=JSON.stringify(sources);stats.groups++;bilingual.observe(args[0],key);
  const changed=key!==currentKey;
  if(changed){cache.delete(key);currentKey=key;currentSources=sources;epoch++;pending.clear();requestMs=Date.now();stats.changes++;send({kind:'caption_generation',epoch,stream_id:streamId});}
  // Only the requested English-to-Chinese route; other scripts fall back.
  if(sources.some(s=>/[\u3400-\u9fff]/.test(s))||!sources.some(s=>/[a-zA-Z]/.test(s)))return;
  if(changed)observedCue();
  const texts=cache.get(key);
  if(!texts){stats.fallback_groups++;if(!pending.has(key)){pending.add(key);stats.requests++;send({kind:'translate_group',key,sources,epoch,stream_id:streamId,route,requested_ms:Date.now(),caption_time:currentTime});}return;}
  // This geometry routine updates its dictionaries. Keep its real inputs.
 }catch(e){stats.errors++;if(stats.errors<=3)send({kind:'bridge_error',error:String(e)});}},
 onLeave(){}
});
// Adjust measurement with a temporary attributed-string copy; no cue mutation.
const measureHook=Interceptor.attach(ct.getExportByName('CTLineCreateWithAttributedString'),{
 onEnter(args){try{
  if(!enabled)return;const caller=Process.findModuleByAddress(this.returnAddress);
  if(!caller||caller.name!=='CoreMedia.dll'||!['0x947960','0x9486d6'].includes(this.returnAddress.sub(cm.base).toString()))return;
  const entry=displayEntry();if(!entry||entry.mode==='Bilingual'||entry.paragraph)return;const texts=entry.texts,source=readAttr(args[0]),index=currentSources.indexOf(source);if(index<0)return;
  let a=null,s=null;try{a=attrCopy(ptr(0),0,args[0]);s=cs(texts[index]);if(a.isNull()||s.isNull())throw new Error('Measurement copy failed');
   replaceString(a,[int64(0),getLength(getString(args[0]))],s);this.copy=a;args[0]=a;a=null;
  }finally{if(a&&!a.isNull())release(a);if(s&&!s.isNull())release(s);}
 }catch(e){stats.errors++;if(stats.errors<=3)send({kind:'measurement_error',error:String(e)});}},
 onLeave(){if(this.copy)release(this.copy);}
});
// This routine only reads its row dictionaries, then draws through CoreText.
const drawHook=Interceptor.attach(cm.base.add(0x9578b0),{
 onEnter(args){try{
  if(!enabled)return;const entry=displayEntry();if(!entry)return;
  if(entry.mode==='Bilingual'||entry.paragraph){const empty=bilingual.suppress(args);if(empty)this.empty=empty;return;}
  const texts=entry.texts;
  const sources=[];gather(args[1],sources);if(!sources.length)return;
  const selected=sources.map(s=>{const i=currentSources.indexOf(s);return i<0?null:texts[i];});if(selected.some(s=>!s))return;
  const copy=clone(args[1],selected,{value:0});this.copy=copy;this.epoch=epoch;this.route='cea608';
  this.lineCount=currentSources.length;this.drawnIndexes=currentSources.flatMap((s,i)=>sources.includes(s)?[i]:[]);
  this.latency=Date.now()-requestMs;this.presentation=entry.presentation;args[1]=copy;stats.translated_groups++;
  if(currentKey!==lastTranslatedKey){lastTranslatedKey=currentKey;send({kind:'native_group_translated',epoch,lines:texts.length,accepted_ms:Date.now(),caption_time:currentTime,sources:stats.translated_groups<=3?currentSources:undefined,texts:stats.translated_groups<=3?texts:undefined});}
 }catch(e){stats.errors++;if(stats.errors<=3)send({kind:'draw_error',error:String(e)});}},
 onLeave(){if(this.empty)release(this.empty);if(this.copy){release(this.copy);completedCue(this);}}
});
send({kind:'ready',pid:Process.id,mode:'async-native-captions'});
const pacingTimer=setInterval(()=>{
 if(!enabled||stopped||!pacingEnabled)return;
 try{if(pacer.tick(Date.now(),pacingClock()))redrawPresentation();}
 catch(e){enabled=false;stats.errors++;send({kind:'draw_error',error:String(e)});}
},50);
rpc.exports={stats(){return {...stats,epoch,stream_id:streamId,requested_ms:requestMs,enabled,route,source_group:currentSources,key:currentKey,movie_language:movieLanguage,caption_time:currentTime,clock:lastClock,pacing:pacer.status(Date.now()),resources:{cache_entries:cache.size,cache_estimated_bytes:cache.bytes,cache_entry_limit:128,cache_byte_limit:1048576,thread_timing:threadSampleTimes.size,frames:bilingual.resources(),js_heap_bytes:Frida.heapSize},caption_age_ms:lastUpdateMs?Date.now()-lastUpdateMs:null};},toggle(value){enabled=!!value;pacer.reset('toggle',Date.now());epoch++;pending.clear();send({kind:'caption_generation',epoch});redrawPresentation();return {enabled,epoch};},clearcache(){pacer.reset('clear_cache',Date.now());cache.clear();pending.clear();epoch++;send({kind:'caption_generation',epoch});redrawPresentation();},stop(){if(stopped)return stats;stopped=true;clearInterval(pacingTimer);pacer.reset('stop',Date.now());enabled=false;epoch++;try{bilingual.restoreGeometry();redraw();}catch(e){send({kind:'restore_skipped',error:String(e)});}finally{const actions=[()=>bilingual.close(),...[drawHook,measureHook,rowsHook,layerHook,timeHook,stateHook,pipelineHook,clockHook,userdataHook,movieLayerHook,movieParserHook,movieDispatchHook,movieFrameHook,...movieTimeHooks].map(h=>()=>h.detach()),()=>forgetLayer(),()=>forgetMovie(),()=>release(textKey),...Object.values(movieKeys).map(v=>()=>release(v))];for(const action of actions){try{action();}catch(e){stats.errors++;send({kind:'cleanup_error',error:String(e)});}}cache.clear();pending.clear();completedEpochs.clear();drawnRows.clear();sampleTimes.clear();threadSampleTimes.clear();rendererTimes.clear();currentSources=[];currentKey='';pipeline=moviePipeline=movieTime=currentTime=lastClock=null;Interceptor.flush();}return stats;}};

// One request at a time from the bounded Python bridge. No synchronous RPC wait.
(function control(){recv('control',message=>{
 const v=message.payload;try{
  if(!['stats','stop','clearcache'].includes(v.method))throw Error('Unsupported control');
  const value=rpc.exports[v.method]();send({kind:'control_result',id:v.id,value});
 }catch(e){send({kind:'control_result',id:v.id,error:true});}
 if(v.method!=='stop')control();
});})();

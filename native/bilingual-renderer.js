// Multiline CoreText inside Apple's existing CEA caption child, never an overlay.
// All CF objects are private copies. Parent layout restores native geometry at Stop.
function makeBilingualRenderer(){
 const cg=Process.getModuleByName('CoreGraphics.dll');
 const getBounds=api(qc,'CACFLayerGetBounds','pointer',['pointer','pointer']);
 const getPosition=api(qc,'CACFLayerGetPosition','pointer',['pointer','pointer']);
 const getContents=api(qc,'CACFLayerGetContents','pointer',['pointer']);
 const setBounds=api(qc,'CACFLayerSetBounds','void',['pointer','pointer']);
 const setPosition=api(qc,'CACFLayerSetPosition','void',['pointer','pointer']);
 const geometryFlipped=api(qc,'CACFLayerIsGeometryFlipped','uchar',['pointer']);
 const createSetter=api(ct,'CTFramesetterCreateWithAttributedString','pointer',['pointer']);
 const createFrame=api(ct,'CTFramesetterCreateFrame','pointer',['pointer',['int64','int64'],'pointer','pointer']);
 const visibleRange=api(ct,'CTFrameGetVisibleStringRange','pointer',['pointer','pointer']);
 const getLines=api(ct,'CTFrameGetLines','pointer',['pointer']);
 const lineOrigins=api(ct,'CTFrameGetLineOrigins','void',['pointer',['int64','int64'],'pointer']);
 const lineBounds=api(ct,'CTLineGetTypographicBounds','double',['pointer','pointer','pointer','pointer']);
 const createLine=api(ct,'CTLineCreateWithAttributedString','pointer',['pointer']);
 const draw=api(ct,'CTFrameDraw','void',['pointer','pointer']);
 const createPath=api(cg,'CGPathCreateMutable','pointer',[]);
 const addRect=api(cg,'CGPathAddRect','void',['pointer','pointer','pointer']);
 const save=api(cg,'CGContextSaveGState','void',['pointer']),restore=api(cg,'CGContextRestoreGState','void',['pointer']);
 const fill=api(cg,'CGContextSetRGBFillColor','void',['pointer','double','double','double','double']);
 const shadow=api(cg,'CGContextSetShadow','void',['pointer',['double','double'],'double']);
 const translate=api(cg,'CGContextTranslateCTM','void',['pointer','double','double']);
 const scale=api(cg,'CGContextScaleCTM','void',['pointer','double','double']);
 const ctm=api(cg,'CGContextGetCTM','pointer',['pointer','pointer']);
 const clip=api(cg,'CGContextGetClipBoundingBox','pointer',['pointer','pointer']);
 const setAttr=api(cf,'CFAttributedStringSetAttribute','void',['pointer',['int64','int64'],'pointer','pointer']);
 const removeAttr=api(cf,'CFAttributedStringRemoveAttribute','void',['pointer',['int64','int64'],'pointer']);
 const removeAll=api(cf,'CFArrayRemoveAllValues','void',['pointer']);
 const foreground=ct.getExportByName('kCTForegroundColorAttributeName').readPointer();
 const fromContext=ct.getExportByName('kCTForegroundColorFromContextAttributeName').readPointer();
 const yes=cf.getExportByName('kCFBooleanTrue').readPointer();
 const frames=new Map(),active=new Map();let template=null,templateKey='',proofs=0,closed=false;
 function rect(x,y,w,h){const p=Memory.alloc(32);[x,y,w,h].forEach((v,i)=>p.add(i*8).writeDouble(v));return p;}
 function values(p,n){return Array.from({length:n},(_,i)=>p.add(i*8).readDouble());}
 function same(a,b){return a.length===b.length&&a.every((v,i)=>Math.abs(v-b[i])<.01);}
 function place(v,b,p,schedule=true){
  let changed=false;
  if(!same(b,[0,0,v.width,v.height])){setBounds(v.child,rect(0,0,v.width,v.height));changed=true;}
  if(!same(p,v.layout.position)){setPosition(v.child,rect(...v.layout.position,0,0));changed=true;}
  if(changed&&schedule)needsDisplay(v.child,ptr(0));
 }
 function cleanup(actions){for(const action of actions){try{action();}catch(e){stats.errors++;send({kind:'cleanup_error',error:String(e)});}}}
 function clearFrames(){const previous=Array.from(frames.values());frames.clear();cleanup(previous.flatMap(v=>[()=>release(v.frame),()=>release(v.child)]));}
 function drawable(v){return enabled&&layer&&layerUser&&v&&(v.presentation?
  v.presentation.source_stream_id===streamId&&pacer.displayable(v.presentation.id):v.key===currentKey&&v.epoch===epoch);}
 // Only Apple's verified caption-layout calls are guarded. New streams and Stop
 // are free to clear. Never retain or copy any video/compositor contents.
 const emptyBoundsHook=Interceptor.attach(qc.getExportByName('CACFLayerSetBounds'),{onEnter(args){try{
  if(!this.returnAddress.equals(cm.base.add(0x954177))&&!this.returnAddress.equals(cm.base.add(0x95414f)))return;
  const v=frames.get(args[0].toString());if(!drawable(v))return;
  const bounds=values(args[1],4),position=Memory.alloc(16);getPosition(position,v.child);
  v.nativeGeometry={bounds,position:values(position,2)};
  if(bounds[2]!==0&&bounds[3]!==0)return;
  v.original=bounds;v.position=v.nativeGeometry.position;v.layout.original_bounds=bounds;v.layout.original_position=v.position;
  this.kept=rect(0,0,v.width,v.height);args[1]=this.kept;
  send({kind:'native_clear_held',operation:'bounds',presentation_id:v.presentation&&v.presentation.id});
 }catch(e){stats.errors++;send({kind:'draw_error',error:String(e)});}},onLeave(){this.kept=null;}});
 const emptyContentsHook=Interceptor.attach(qc.getExportByName('CACFLayerSetContents'),{onEnter(args){try{
  if(!this.returnAddress.equals(cm.base.add(0x954182))||!args[1].isNull())return;
  const v=frames.get(args[0].toString());if(!drawable(v))return;
  const contents=getContents(v.child);if(contents.isNull())return;
  // This API's identical-value branch keeps the existing caption backing store.
  args[1]=contents;send({kind:'native_clear_held',operation:'contents',presentation_id:v.presentation&&v.presentation.id});
 }catch(e){stats.errors++;send({kind:'draw_error',error:String(e)});}}});
 function findTemplate(p){if(type(p).toNumber()===types.Array){for(let i=0;i<arrayCount(p).toNumber();i++){const a=findTemplate(arrayAt(p,i));if(a)return a;}}else{const a=dictGet(p,textKey);if(!a.isNull()&&readAttr(a))return a;}return null;}
 function observe(p,key){if(templateKey===key)return;const found=findTemplate(p),next=found?retain(found):null,old=template;template=next;templateKey=key;if(old)release(old);}
 function frame(setter,width,height){const p=createPath();if(p.isNull())throw Error('Subtitle path allocation failed');try{addRect(p,ptr(0),rect(8,6,width-16,height-12));return createFrame(setter,[int64(0),int64(0)],p,ptr(0));}finally{release(p);}}
 function full(f,n){const r=Memory.alloc(16);visibleRange(r,f);return r.readS64().toNumber()===0&&r.add(8).readS64().toNumber()===n;}
 function layout(){
  const entry=displayEntry();
  if(!enabled||!entry||(entry.mode!=='Bilingual'&&!entry.paragraph)){restoreGeometry(false);clearFrames();return;}
  // An empty raw cue still has a valid retained font template. Ready queued
  // translations may replace the held caption during that source gap.
  if(!template||!layerUser||(currentKey&&templateKey!==currentKey))return;
  const children=layerUser.add(0x30).readPointer(),candidates=[];
  for(let i=0;i<arrayCount(children).toNumber();i++){const child=arrayAt(children,i),b=Memory.alloc(32),p=Memory.alloc(16);getBounds(b,child);getPosition(p,child);const v=values(b,4);if(v[2]>0&&v[3]>0)candidates.push({child,b:v,p:values(p,2)});}
  if(!candidates.length)return;
  if(candidates.length!==1)throw Error('Bilingual native windows: '+JSON.stringify(candidates.map(v=>({bounds:v.b,position:v.p}))));
  const v=candidates[0],old=frames.get(v.child.toString());
  const inherited=old&&same(v.b,[0,0,old.width,old.height])&&same(v.p,old.layout.position);
  const original=old&&old.nativeGeometry?old.nativeGeometry.bounds:inherited?old.original:v.b;
  const originalPosition=old&&old.nativeGeometry?old.nativeGeometry.position:inherited?old.position:v.p;
  const chinese=entry.texts.filter(Boolean).join('\n'),english=entry.source_text||currentSources.join('\n'),isBilingual=entry.mode==='Bilingual',text=isBilingual?chinese+'\n'+english:chinese;
  const parentBounds=Memory.alloc(32);getBounds(parentBounds,layer);const pb=values(parentBounds,4);
  const identity=entry.presentation?entry.presentation.id:currentKey+':'+epoch;
  // The original English layout runs for every raw cue. Its changing text box
  // must not move or rewrap a translation that is still being read.
  if(old&&old.identity===identity&&old.content===text&&old.layout.mode===entry.mode&&same(old.layout.parent_bounds,pb)){
   old.original=original;old.position=originalPosition;old.key=currentKey;old.epoch=epoch;old.rows=currentSources.length;
   old.layout.original_bounds=original;old.layout.original_position=originalPosition;
   place(old,v.b,v.p);return;
  }
  const fa=Memory.alloc(8),fd=Memory.alloc(8),fontLine=createLine(template);let width;
  try{if(fontLine.isNull())throw Error('Subtitle font line allocation failed');lineBounds(fontLine,fa,fd,ptr(0));width=Math.max(v.b[2],Math.ceil(12*(fa.readDouble()+fd.readDouble())+16));}finally{if(!fontLine.isNull())release(fontLine);}
  let a=null,s=null,setter=null,probe=null,result=null;
  try{
   a=attrCopy(ptr(0),0,template);s=cs(text);if(a.isNull()||s.isNull())throw Error('Subtitle text allocation failed');
   replaceString(a,[int64(0),getLength(getString(a))],s);
   removeAttr(a,[int64(0),int64(text.length)],foreground);setAttr(a,[int64(0),int64(text.length)],fromContext,yes);
   setter=createSetter(a);if(setter.isNull())throw Error('Subtitle framesetter allocation failed');probe=frame(setter,width,2048);
   if(!full(probe,text.length))throw Error('Bilingual text exceeds native frame capacity');
   const lines=getLines(probe),n=arrayCount(lines).toNumber();if(n<(isBilingual?2:1)||n>32)throw Error('Unexpected subtitle line count');
   const origins=Memory.alloc(n*16),asc=Memory.alloc(8),desc=Memory.alloc(8),lead=Memory.alloc(8);lineOrigins(probe,[int64(0),int64(0)],origins);
   lineBounds(arrayAt(lines,0),asc,desc,lead);const top=asc.readDouble();lineBounds(arrayAt(lines,n-1),asc,desc,lead);
   const height=Math.ceil(origins.add(8).readDouble()-origins.add((n-1)*16+8).readDouble()+top+desc.readDouble()+16);
   if(!Number.isFinite(height)||height<16||height>600)throw Error('Bilingual height exceeds subtitle area');
   result=frame(setter,width,height);if(!full(result,text.length))throw Error('Bilingual text clipped after sizing');
   const flipped=!!geometryFlipped(layer),x=v.p[0]+(v.b[2]-width)/2,y=v.p[1]-(flipped?height-v.b[3]:0);
   const replacement={frame:result,child:v.child,original,position:originalPosition,key:currentKey,epoch,width,height,length:text.length,rows:currentSources.length,presentation:entry.presentation,identity,content:text,nativeGeometry:old&&old.nativeGeometry,
    layout:{mode:entry.mode,order:isBilingual?'zh-then-en':'translation-only',complete:true,characters:text.length,visible_characters:text.length,
      chinese_characters:chinese.length,english_characters:english.length,wrapped_lines:n,width,height,parent_bounds:pb,position:[x,y],
      original_bounds:original,original_position:originalPosition,parent_geometry_flipped:flipped,child_geometry_flipped:!!geometryFlipped(v.child)}};
   // Install a complete replacement before releasing ANY drawable old frame.
   // A source update or failed preparation must not expose the English draw.
   place(replacement,v.b,v.p,false);replacement.child=retain(v.child);
   frames.set(v.child.toString(),replacement);result=null;
   if(old){release(old.frame);release(old.child);}
   for(const [key,previous]of frames){if(key!==v.child.toString()){frames.delete(key);release(previous.frame);release(previous.child);}}
   needsDisplay(v.child,ptr(0));
  }finally{if(result&&!result.isNull())release(result);if(probe&&!probe.isNull())release(probe);if(setter&&!setter.isNull())release(setter);if(a&&!a.isNull())release(a);if(s&&!s.isNull())release(s);}
 }
 function paint(v,ctx,flip){save(ctx);try{if(flip){translate(ctx,0,v.height);scale(ctx,1,-1);}fill(ctx,1,1,1,1);shadow(ctx,[0,-1],2);draw(v.frame,ctx);}finally{restore(ctx);}}
 function proof(v){
  if(!PROFILE.layout_proof||proofs>=4)return;proofs++;
  const w=Math.ceil(v.width),h=Math.ceil(v.height),data=Memory.alloc(w*h*4);
  const space=api(cg,'CGColorSpaceCreateDeviceRGB','pointer',[])();let ctx=null;
  try{ctx=api(cg,'CGBitmapContextCreate','pointer',['pointer','uint64','uint64','uint64','uint64','pointer','uint'])(data,w,h,8,w*4,space,0x4001);if(ctx.isNull())throw Error('Text proof bitmap failed');const t=Memory.alloc(48);ctm(t,ctx);v.layout.bitmap_ctm=values(t,6);paint(v,ctx,false);send({kind:'bilingual_layout_image',epoch:v.epoch,width:w,height:h},data.readByteArray(w*h*4));}finally{if(ctx&&!ctx.isNull())api(cg,'CGContextRelease','void',['pointer'])(ctx);release(space);}
 }
 function finishDraw(state,phase){
  if(state.painted)return;paint(state.v,state.ctx,state.flip);state.painted=true;
  state.v.layout.paint_phase=phase;proof(state.v);stats.translated_groups++;
  completedCue({epoch:state.v.epoch,route:'cea608',lineCount:state.v.rows,drawnIndexes:Array.from({length:state.v.rows},(_,i)=>i),latency:Date.now()-requestMs,layout:state.v.layout,presentation:state.v.presentation});
 }
 const completionHook=Interceptor.attach(cf.getExportByName('CFNotificationCenterPostNotification'),{onEnter(args){try{
  if(!this.returnAddress.equals(cm.base.add(0x954416)))return;
  const state=active.get(Process.getCurrentThreadId());if(!state||!args[2].equals(state.context))return;
  // Native observers must see a complete translated frame, never the empty
  // original rows which were suppressed inside the child display callback.
  finishDraw(state,'before_native_completion');
 }catch(e){stats.errors++;send({kind:'draw_error',error:String(e)});}}});
 const hook=Interceptor.attach(cm.base.add(0x954210),{
  onEnter(args){try{const v=frames.get(args[0].toString());if(!drawable(v))return;
   const bounds=Memory.alloc(32);clip(bounds,args[1]);const b=values(bounds,4);
   if(b[0]>.5||b[1]>.5||b[0]+b[2]<v.width-.5||b[1]+b[3]<v.height-.5)throw Error('Native context clips bilingual frame');
   const transform=Memory.alloc(48);ctm(transform,args[1]);this.flip=transform.add(24).readDouble()<0;v.layout.native_ctm=values(transform,6);v.layout.flip=this.flip;v.layout.clip=b;
   const tid=Process.getCurrentThreadId(),nativeContext=context(layer);this.state={v:{...v,epoch,frame:retain(v.frame)},ctx:args[1],flip:this.flip,context:nativeContext,painted:false,previous:active.get(tid)};
   active.set(tid,this.state);
  }catch(e){stats.errors++;send({kind:'draw_error',error:String(e)});}},
  onLeave(){if(!this.state)return;const state=this.state,tid=Process.getCurrentThreadId();
   try{finishDraw(state,'callback_return_fallback');}
   catch(e){stats.errors++;send({kind:'draw_error',error:String(e)});}
   finally{if(state.previous)active.set(tid,state.previous);else active.delete(tid);release(state.v.frame);}}
 });
 function restoreGeometry(report=true){let restored=0;caLock();try{for(const v of frames.values()){setBounds(v.child,rect(...v.original));setPosition(v.child,rect(...v.position,0,0));const b=Memory.alloc(32);getBounds(b,v.child);if(values(b,4).some((n,i)=>Math.abs(n-v.original[i])>.01))throw Error('Native subtitle geometry restoration failed');needsDisplay(v.child,ptr(0));restored++;}}finally{caUnlock();}if(report)send({kind:'bilingual_geometry_restored',children:restored});}
 return {observe,layout,restoreGeometry,proofCurrent(){if(!PROFILE.layout_proof)throw Error('Layout diagnostics disabled');return Array.from(frames.values(),v=>{proof(v);return v.layout;});},suppress(args){const state=active.get(Process.getCurrentThreadId());if(!state||!state.ctx.equals(args[2]))return false;const a=arrayCopy(ptr(0),0,args[1]);try{removeAll(a);args[1]=a;return a;}catch(e){release(a);throw e;}},resources(){return {frames:frames.size,active_draws:active.size,template:!!template};},close(){if(closed)return;closed=true;cleanup([...[hook,completionHook,emptyBoundsHook,emptyContentsHook].map(h=>()=>h.detach()),()=>clearFrames(),()=>{const old=template;template=null;templateKey='';if(old)release(old);}]);}};
}

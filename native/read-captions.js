'use strict';
// Read-only caption observation. Never replace arguments, samples or renderer results.
const cm = Process.getModuleByName('CoreMedia.dll');
const cf = Process.getModuleByName('CoreFoundation.dll');
for (const name of ['AMPLibraryAgent.exe', 'CoreMedia.dll', 'CoreFoundation.dll']) {
  if (Process.getModuleByName(name).path.toLowerCase() !== (PROFILE.package_root + '\\' + name).toLowerCase())
    throw new Error('Unsupported module path: ' + name);
}
const needed = [0x9474f0, 0xb14f10];
for (const rva of needed) {
  const check = PROFILE.hooks.find(c => c.module === 'CoreMedia.dll' && c.rva === rva);
  if (!check) throw new Error('Missing compatibility entry');
  const actual = Array.from(new Uint8Array(cm.base.add(rva).readByteArray(check.bytes.length / 2)),
    b => b.toString(16).padStart(2, '0')).join('');
  if (actual !== check.bytes) throw new Error('Running code differs from verified build');
}
const api = (name, result, args) => new NativeFunction(cf.getExportByName(name), result, args);
const type = api('CFGetTypeID', 'uint64', ['pointer']);
const types = {};
for (const name of ['Array', 'Dictionary', 'AttributedString'])
  types[name] = api('CF' + name + 'GetTypeID', 'uint64', [])().toNumber();
const count = api('CFArrayGetCount', 'int64', ['pointer']);
const at = api('CFArrayGetValueAtIndex', 'pointer', ['pointer', 'int64']);
const get = api('CFDictionaryGetValue', 'pointer', ['pointer', 'pointer']);
const string = api('CFAttributedStringGetString', 'pointer', ['pointer']);
const length = api('CFStringGetLength', 'int64', ['pointer']);
const utf8 = api('CFStringGetCString', 'uchar', ['pointer', 'pointer', 'int64', 'uint']);
const make = api('CFStringCreateWithCharacters', 'pointer', ['pointer', 'pointer', 'int64']);
const release = api('CFRelease', 'void', ['pointer']);
const key = name => make(ptr(0), Memory.allocUtf16String(name), name.length);
const ceaKey = key('QuickTimeClosedCaptionStringKey');
const movieKey = key('SubtitleContent');
let current = '', route = '', updated = 0, stopped = false;
const stats = {callbacks: 0, changes: 0, errors: 0};
function text(p) {
  const s = string(p), n = length(s).toNumber();
  if (n < 1 || n > 2048) return '';
  const buffer = Memory.alloc(n * 4 + 1);
  return utf8(s, buffer, n * 4 + 1, 0x08000100) ? buffer.readUtf8String() : '';
}
function rows(p, result, depth = 0) {
  if (depth > 4 || p.isNull()) return;
  const id = type(p).toNumber();
  if (id === types.Array) {
    const n = count(p).toNumber();
    if (n < 0 || n > 32) throw new Error('Unsupported row count');
    for (let i = 0; i < n; i++) rows(at(p, i), result, depth + 1);
  } else if (id === types.Dictionary) {
    const value = get(p, ceaKey);
    if (!value.isNull() && type(value).toNumber() === types.AttributedString) {
      const valueText = text(value);
      if (valueText) result.push(valueText);
    }
  }
}
function publish(value, source) {
  stats.callbacks++;
  updated = Date.now();
  const changed = value !== current || source !== route;
  current = value; route = source;
  if (changed) {
    stats.changes++;
    send({kind: 'caption', text: current, route, updated_ms: updated});
  }
}
const hooks = [
  Interceptor.attach(cm.base.add(0x9474f0), {onEnter(args) {
    if (stopped) return;
    try { const found = []; rows(args[0], found); publish(found.join('\n'), 'CEA-608'); }
    catch (e) { stats.errors++; if (stats.errors <= 3) send({kind: 'read_error'}); }
  }}),
  Interceptor.attach(cm.base.add(0xb14f10), {onEnter(args) {
    if (stopped) return;
    try {
      const sample = args[1];
      if (sample.isNull() || type(sample).toNumber() !== types.Dictionary) return;
      const content = get(sample, movieKey);
      if (content.isNull() || type(content).toNumber() !== types.Array) return;
      const n = count(content).toNumber();
      if (n < 0 || n > 16) return;
      const found = [];
      for (let i = 0; i < n; i++) {
        const value = at(content, i);
        if (type(value).toNumber() !== types.AttributedString) return;
        const valueText = text(value);
        if (valueText) found.push(valueText);
      }
      publish(found.join('\n'), 'WebVTT');
    } catch (e) { stats.errors++; if (stats.errors <= 3) send({kind: 'read_error'}); }
  }})
];
// A heartbeat keeps event-only subtitle updates alive in the asynchronous UI.
// Cap unrefreshed text so a retired renderer cannot leave a permanent caption.
const timer = setInterval(() => {
  if (updated && !stopped) send({kind: 'caption', text: Date.now() - updated < 10000 ? current : '',
                               route, updated_ms: updated});
}, 250);
send({kind: 'ready', pid: Process.id});
rpc.exports = {
  stats() { return {...stats, route, text_active: !!current}; },
  stop() {
    if (!stopped) {
      stopped = true; clearInterval(timer);
      for (const hook of hooks) hook.detach();
      Interceptor.flush();
      release(ceaKey); release(movieKey);
    }
    return stats;
  }
};

// One request at a time from the bounded Python bridge. No synchronous RPC wait.
(function control(){recv('control',message=>{
 const v=message.payload;try{
  if(!['stats','stop','clearcache'].includes(v.method))throw Error('Unsupported control');
  const value=rpc.exports[v.method]();send({kind:'control_result',id:v.id,value});
 }catch(e){send({kind:'control_result',id:v.id,error:true});}
 if(v.method!=='stop')control();
});})();

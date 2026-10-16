"""Explicit shipped-JS check on an owned idle process, never the media player."""
from pathlib import Path
import json
import subprocess


def verify_pacing_runtime(native: Path, command: list[str]):
    import frida
    worker = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    session = None
    script = None
    try:
        session = frida.get_local_device().attach(worker.pid)
        code = (native/'caption-pacer.js').read_text('utf-8')
        for name in ('bilingual-renderer.js', 'native-renderer.js'):
            code += '\nnew Function(' + json.dumps((native/name).read_text('utf-8')) + ');'
        code += r'''
rpc.exports={check(){
 const p=makeCaptionPacer(),e={texts:['中'.repeat(24)]},source={epoch:1,stream_id:1,requested_ms:0,caption_time:{seconds:0}};
 const length=p.reading('短句')<p.reading('中'.repeat(24))&&p.characters('你好，A1！')===4;
 p.offer(e,source,0);p.tick(0,0);
 const receipt=p.status(0).active.shown_ms===null&&p.markDrawn('1:1',0);
 p.offer({texts:['后文']},{...source,epoch:2,requested_ms:1000,caption_time:{seconds:1}},1000);
 p.tick(2000,2);const held=p.current().id==='1:1';
 p.tick(2100,4);const progressive=Number.isFinite(p.status(2100).active.duration_ms)&&p.status(2100).active.duration_ms<p.reading(e.texts[0]);
 p.tick(2200,5);const caught=p.current().id==='1:2';
 p.reset('stop',2300);
 const hold=makeCaptionPacer();hold.offer({texts:['中'.repeat(14)]},source,0);hold.tick(0,0);hold.markDrawn('1:1',0);hold.tick(3000,3);
 const noFlicker=hold.current()!==null&&hold.status(3000).active.holding_for_next;
 return {pacing_policy:length&&receipt&&held&&progressive&&caught&&p.current()===null&&noFlicker,
         native_script_syntax:true};
},stats(){return {epoch:1,resources:{js_heap_bytes:Frida.heapSize}};},stop(){return {stopped:true};},clearcache(){}};'''
        code += '\n// One request at a time' + (native/'native-renderer.js').read_text('utf-8').split('// One request at a time')[1]
        script = session.create_script(code)
        import threading
        from .native_source import NativeSource
        source = NativeSource(threading.Event(), render=True)
        source._bind_script(worker.pid, script)
        script.load()
        result = script.exports_sync.check()
        result['native_control_deadline_transport'] = source._rpc(worker.pid, script, 'stats')['epoch'] == 1
        source.sessions[worker.pid] = (session, script)
        source._detach(worker.pid)
        import weakref
        import gc
        reference = weakref.ref(script)
        script = None
        gc.collect()
        result['destroyed_frida_wrapper_release'] = reference() is None and source.counts['restored'] == 1
        return result
    finally:
        if session:
            if not session.is_detached:
                session.detach()
        if script:
            from .frida_cleanup import release_destroyed_script
            release_destroyed_script(script)
        if worker.poll() is None:
            worker.terminate()
        worker.wait(timeout=5)

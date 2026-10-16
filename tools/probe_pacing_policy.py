"""Deterministic policy evidence on an owned Frida target; no Apple TV control."""
from pathlib import Path
import json
import subprocess
import sys
import frida

ROOT = Path(__file__).resolve().parents[1]
worker = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'],
    stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
session = None
try:
    session = frida.get_local_device().attach(worker.pid)
    code = (ROOT/'native/caption-pacer.js').read_text('utf-8') + '\n' + \
           (ROOT/'tests/pacing_cases.js').read_text('utf-8')
    code += r'''
rpc.exports={run(){
 const examples=[];
 for(const count of [5,10,20,30,60]){
  const values=[];
  for(const lag of [0,3,4,5]){
   const p=makeCaptionPacer();
   p.offer({texts:['字'.repeat(count)]},{epoch:1,stream_id:1,requested_ms:0,caption_time:{seconds:0}},0);
   p.tick(0,0);p.markDrawn('1:1',0);
   p.offer({texts:['后文']},{epoch:2,stream_id:1,requested_ms:10,caption_time:{seconds:1}},10);
   p.tick(100,lag);values.push({lag_seconds:lag,duration_ms:p.status(100).active.duration_ms});
  }
  examples.push({characters:count,values});
 }
 return {cases:captionPacingCases().all(),examples};
}};'''
    script = session.create_script(code)
    script.load()
    report = {'scope': 'deterministic synthetic time in actual Frida JS runtime; owned idle process; no native playback',
              **script.exports_sync.run()}
    output = ROOT/'evidence/pacing-0.1.9/policy-frida.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=True))
finally:
    if session:
        session.detach()
    worker.stdin.close()
    worker.wait(timeout=5)

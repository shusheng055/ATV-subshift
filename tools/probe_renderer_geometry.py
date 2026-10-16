"""Compare real renderer control flow on an owned worker with mocked native APIs."""
import json
import argparse
from pathlib import Path
import subprocess
import sys

import frida

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--evidence', type=Path, default=ROOT/'evidence/flicker-0.1.12')
args = parser.parse_args()
OUT = args.evidence.resolve()
worker = subprocess.Popen([sys.executable, '-c', 'import sys;sys.stdin.read()'],
    stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
session = None
try:
    session = frida.get_local_device().attach(worker.pid)
    report = {'scope': 'actual renderer JavaScript; controlled native/CoreText mocks; owned worker, not live playback'}
    for name, path in [('before', OUT/'before/native/bilingual-renderer.js'),
                       ('after', ROOT/'native/bilingual-renderer.js')]:
        code = (ROOT/'tests/renderer_cases.js').read_text('utf-8')
        code += '\nconst source=' + json.dumps(path.read_text('utf-8')) + ';'
        bridge_path = path.parent/'native-renderer.js'
        code += '\nconst bridge=' + json.dumps(bridge_path.read_text('utf-8')) + ';'
        code += r'''
rpc.exports={run(){
 const cases=captionRendererCases(source,bridge),results=[];
 for(const name of cases.names())try{cases.run(name);results.push({name,passed:true});}
 catch(error){results.push({name,passed:false,error:String(error)});}
 const f=rendererFixture(source);f.renderer.layout();f.draw();
 const points=[{position:f.object(f.child).position.slice(),frames_created:f.calls.frames}];
 for(const [index,x] of [266.5,281,273.5,288].entries()){
  f.native([0,0,150,32],[x,93]);f.env.epoch++;f.observe('source-'+(index+2));f.renderer.layout();f.draw();
  points.push({position:f.object(f.child).position.slice(),frames_created:f.calls.frames});
 }
 const c=rendererFixture(source);c.renderer.layout();c.draw();c.clear();
 return {cases:results,held_translation_points:points,
  first_completion:c.calls.commits[0]==='empty'?'empty_before_Chinese_paint':'translated_before_completion',
  after_native_clear:{bounds:c.object(c.child).bounds,contents_preserved:!c.object(c.child).contents.isNull()},
  unique_drawn_frames:new Set(f.calls.draws).size,errors:f.calls.messages.filter(m=>m.kind==='draw_error')};
}};'''
        script = session.create_script(code)
        script.load()
        try:
            report[name] = script.exports_sync.run()
        finally:
            script.unload()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'renderer-comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({name: {'passed':sum(c['passed'] for c in report[name]['cases']),
        'total':len(report[name]['cases']), 'unique_held_frames':report[name]['unique_drawn_frames']}
        for name in ('before','after')}))
finally:
    if session:
        session.detach()
    worker.stdin.close()
    worker.wait(timeout=5)

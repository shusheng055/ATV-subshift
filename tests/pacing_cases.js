// Shared deterministic cases, executed in Node AND Frida's actual JS runtime.
function captionPacingCases(){
 function ok(value,message){if(!value)throw Error(message||'Pacing assertion failed');}
 function offer(p,epoch,text,at=0,seconds=0,ready=at){return p.offer(
  {texts:[text],mode:'Translated',paragraph:true,source_text:'source '+epoch},
  {epoch,stream_id:1,requested_ms:at,caption_time:{seconds}},ready);}
 function begin(text,clock=0){const p=makeCaptionPacer();offer(p,1,text);p.tick(0,clock);p.markDrawn('1:1',0);return p;}
 const tests={
  unicode_character_count(){const p=makeCaptionPacer();ok(p.characters('你好，世界！ A1 🙂')===6);},
  longer_translation_reads_longer(){const p=makeCaptionPacer();ok(p.reading('中'.repeat(20))>p.reading('中'.repeat(5)));ok(p.reading('中'.repeat(1000))===6000);ok(p.reading('好')===1200);},
  reading_begins_at_native_receipt(){const p=makeCaptionPacer();offer(p,1,'好');p.tick(0,0);p.tick(1000,0);ok(p.status(1000).active.shown_ms===null);p.markDrawn('1:1',1000);p.tick(2199,0);ok(p.current().id==='1:1');p.tick(2200,0);ok(p.current().id==='1:1');ok(p.status(2200).active.holding_for_next);},
  next_cue_waits_for_long_translation(){const p=begin('中'.repeat(24));offer(p,2,'下一条',1000,1);p.tick(4649,0);ok(p.current().id==='1:1');p.tick(4650,0);ok(p.current().id==='1:2');},
  new_source_does_not_replace_active_text(){const p=begin('长'.repeat(24));offer(p,2,'新的译文',1000,1);p.tick(1000,1);ok(p.current().entry.texts[0]==='长'.repeat(24));},
  three_to_five_seconds_shortens_progressively(){const p=begin('长'.repeat(30));offer(p,2,'后文',1000,1);p.tick(1000,3);const a=p.status(1000).active.duration_ms;p.tick(1100,4);const b=p.status(1100).active.duration_ms;p.tick(1200,5);ok(p.current().id==='1:2');ok(a>b);ok(b>1000);},
  five_second_lag_still_has_readable_minimum(){const p=begin('短句');offer(p,2,'下一句',10,1);p.tick(699,5);ok(p.current().id==='1:1');ok(p.status(699).active.duration_ms===700);p.tick(700,5);ok(p.current().id==='1:2');},
  native_media_time_preferred_to_wall_time(){const p=begin('中'.repeat(24));offer(p,2,'后文',1000,1);p.tick(2000,0);ok(p.status(2000).active.lag_ms===0);p.tick(2100,4);ok(p.status(2100).active.lag_ms===4000);},
  wall_time_fallback_without_native_timestamp(){const p=makeCaptionPacer();offer(p,1,'长'.repeat(30),0,null);p.tick(0,null);p.markDrawn('1:1',0);offer(p,2,'后文',1000,null);p.tick(4000,null);ok(p.current().id==='1:2');},
  duplicate_translation_never_restarts_reading(){const p=begin('长'.repeat(20));ok(!offer(p,1,'长'.repeat(20),0,0,1000));ok(!p.markDrawn('1:1',1000));ok(p.status(1000).active.shown_ms===1000);},
  queued_translations_keep_source_order(){const p=makeCaptionPacer();offer(p,2,'二',2000,2);offer(p,1,'一',1000,1);p.tick(2100,2);ok(p.current().id==='1:1');},
  older_result_cannot_jump_backwards(){const p=makeCaptionPacer();offer(p,2,'二',2000,2);p.tick(2100,2);p.markDrawn('1:2',2100);ok(!offer(p,1,'一',1000,1,2200));ok(p.status(2200).dropped===1);},
  queue_is_bounded_and_drops_are_reported(){const events=[];const p=makeCaptionPacer(e=>events.push(e));for(let i=0;i<40;i++)offer(p,i,'中',i*10,i);ok(p.status(1000).queue_depth===12);ok(events.filter(e=>e.event==='dropped'&&e.reason==='queue_limit').length===28);},
  extreme_backlog_drops_only_obsolete_queued_entries(){const p=makeCaptionPacer();offer(p,1,'旧',0,null);offer(p,2,'新',11000,null);p.tick(12000,null);ok(p.current().id==='1:2');ok(p.status(12000).dropped===1);},
  seek_reset_clears_active_and_queue(){const p=begin('之前');offer(p,2,'排队',1000,1);p.reset('seek',1200);ok(p.current()===null);ok(p.status(1200).queue_depth===0);offer(p,1,'跳转后',2000,2);p.tick(2000,2);ok(p.current().entry.texts[0]==='跳转后');},
  missing_native_draw_never_counts_as_reading(){const events=[];const p=makeCaptionPacer(e=>events.push(e));offer(p,1,'未绘制');p.tick(0,0);offer(p,2,'后文',1000,1);p.tick(1500,1.5);ok(p.current().id==='1:2');ok(p.status(1500).drawn===0);ok(events.some(e=>e.event==='dropped'&&e.reason==='no_native_draw'));},
  stopped_output_does_not_reappear(){const p=begin('停止');p.reset('stop',100);p.tick(10000,10);ok(p.current()===null);},
  fourteen_characters_do_not_blank_at_three_seconds(){const p=begin('中'.repeat(14));for(let now=0;now<=12000;now+=50){p.tick(now,now/1000);ok(p.current().id==='1:1','Translation disappeared at '+now);}ok(p.status(12000).active.holding_for_next);},
  late_successor_replaces_without_empty_state(){const p=begin('中'.repeat(14));for(let now=0;now<=5000;now+=50){p.tick(now,now/1000);ok(p.current()!==null);}offer(p,2,'下一条',4000,4,5050);p.tick(5050,5.05);ok(p.current().id==='1:2');ok(p.fallback().id==='1:1');ok(p.status(5050).displayed.presentation_id==='1:1');p.markDrawn('1:2',5100);ok(p.fallback()===null);ok(p.status(5100).displayed.presentation_id==='1:2');},
  failed_successor_draw_keeps_previous_translation(){const p=begin('旧译文');offer(p,2,'新译文',2000,2);p.tick(2000,2);ok(p.current().id==='1:2');p.tick(3500,3.5);ok(p.current().id==='1:1');ok(p.status(3500).displayed.presentation_id==='1:1');},
  previous_reading_ends_at_replacement_draw_not_selection(){const events=[];const p=makeCaptionPacer(e=>events.push(e));offer(p,1,'旧译文');p.tick(0,0);p.markDrawn('1:1',0);offer(p,2,'新译文',2000,2);p.tick(2000,2);ok(!events.some(e=>e.event==='ended'));p.markDrawn('1:2',2100);const end=events.find(e=>e.event==='ended');ok(end.presentation_id==='1:1'&&end.shown_ms===2100);},
  old_frame_is_eligible_until_new_frame_draws(){const p=begin('旧译文');offer(p,2,'新译文',2000,2);p.tick(2000,2);ok(p.displayable('1:1')&&p.displayable('1:2'));p.markDrawn('1:2',2050);ok(!p.displayable('1:1')&&p.displayable('1:2'));},
  stop_during_pending_swap_clears_both_frames(){const p=begin('旧译文');offer(p,2,'新译文',2000,2);p.tick(2000,2);p.reset('stop',2050);ok(p.current()===null&&p.fallback()===null);ok(!p.displayable('1:1')&&!p.displayable('1:2'));},
  held_caption_is_not_reoffered_or_retimed(){const p=begin('长'.repeat(14));p.tick(10000,10);ok(!offer(p,1,'长'.repeat(14),0,0,10000));ok(p.status(10000).active.shown_ms===10000&&p.status(10000).drawn===1);},
  cea_and_webvtt_timestamp_shapes(){ok(captionSeconds({seconds:12.5})===12.5);ok(captionSeconds({start:{seconds:13},duration:{seconds:2}})===13);ok(captionSeconds({seconds:null})===null);},
  future_timestamp_is_not_negative_lag(){const p=makeCaptionPacer();offer(p,1,'将来',1000,10);p.tick(1000,9);ok(p.status(1000).active.lag_ms===0);}
 };
 return {names(){return Object.keys(tests);},run(name){tests[name]();return true;},all(){return Object.keys(tests).map(name=>({name,passed:(tests[name](),true)}));}};
}
if(typeof module!=='undefined'&&module.exports)module.exports=captionPacingCases;

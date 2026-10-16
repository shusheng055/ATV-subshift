"""Sentence assembly, contextual API requests and native lifetime regression tests."""
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subtitle_app.segments import SpeechBuffer, complete, unfinished, WAIT_MARKER
from subtitle_app.translation import ApiTranslator, TranslationError
from subtitle_app.terminology import TermTranslator
from subtitle_app.settings import Settings


class SentenceTests(unittest.TestCase):
    def test_missing_complement_translates_immediately_then_context_only(self):
        buffer = SpeechBuffer()
        buffer.observe("The only thing I want you to", 10)
        first = buffer.take(10)
        self.assertEqual(first.text, "The only thing I want you to")
        self.assertFalse(first.allow_wait)
        buffer.commit(first, 10.5)
        buffer.observe("do is stay here.", 11)
        segment = buffer.take(11)
        self.assertEqual(segment.text, "do is stay here.")
        self.assertEqual(segment.context, ("The only thing I want you to",))
        self.assertEqual(segment.started, 11)
        self.assertFalse(segment.allow_wait)
        self.assertIsNone(buffer.take(12))

    def test_rolling_overlap_is_not_repeated(self):
        buffer = SpeechBuffer()
        buffer.observe("We need to move", 10)
        buffer.observe("need to move into", 10.1)
        buffer.observe("move into the lead.", 10.2)
        self.assertEqual(buffer.take(10.2).text, "move into the lead.")

    def test_long_lived_visible_cue_keeps_its_continuation(self):
        buffer = SpeechBuffer()
        buffer.observe("The only thing I want you to", 10)
        buffer.observe("do is stay here.", 17, continuous=True)
        segment = buffer.take(17)
        self.assertEqual(segment.text, "do is stay here.")
        self.assertEqual(segment.context, ("The only thing I want you to",))

    def test_source_rewrite_and_duplicate_do_not_append(self):
        buffer = SpeechBuffer()
        buffer.observe("We need", 10)
        buffer.observe("We need more", 10.1)
        buffer.observe("We need more", 10.2)
        buffer.observe("We need more grip.", 10.3)
        self.assertEqual(buffer.take(10.3).text, "We need more grip.")

    def test_complete_cues_are_immediate_and_history_does_not_include_current(self):
        buffer = SpeechBuffer()
        buffer.observe("The driver is Max.", 10)
        self.assertEqual(buffer.take(10).context, ())
        buffer.observe("He is leading.", 12)
        segment = buffer.take(12)
        self.assertEqual(segment.context, ("The driver is Max.",))
        self.assertEqual(segment.text, "He is leading.")

    def test_partial_translation_never_allows_model_wait_or_retries_same_cue(self):
        buffer = SpeechBuffer()
        buffer.observe("The driver wants another lap", 10)
        first = buffer.take(10)
        self.assertFalse(first.allow_wait)
        self.assertEqual(first.reason, 'conservative')
        self.assertIsNone(buffer.take(11))
        self.assertIsNone(buffer.take(11.5))
        self.assertIsNone(buffer.take(12))

    def test_obvious_incomplete_fragment_is_sent_without_waiting(self):
        buffer = SpeechBuffer()
        buffer.observe("We stopped because", 10)
        self.assertEqual(buffer.take(10).text, "We stopped because")
        self.assertIsNone(buffer.take(11.5))

    def test_uncommitted_source_is_context_instead_of_accumulated_output(self):
        buffer = SpeechBuffer()
        buffer.observe("I want you to", 10)
        self.assertEqual(buffer.take(10).text, "I want you to")
        buffer.observe("stay here.", 12)
        segment = buffer.take(12)
        self.assertEqual(segment.text, "stay here.")
        self.assertEqual(segment.context, ("I want you to",))

    def test_complete_prefix_and_incomplete_tail_are_both_translated_now(self):
        buffer = SpeechBuffer()
        buffer.observe("We are ready. The only thing I want you to", 10)
        first = buffer.take(10)
        self.assertEqual(first.text, "We are ready. The only thing I want you to")
        buffer.commit(first, 10.2)
        self.assertIsNone(buffer.take(10.6))
        buffer.observe("The only thing I want you to do is stay here.", 11)
        second = buffer.take(11)
        self.assertEqual(second.text, "do is stay here.")
        self.assertEqual(second.context, (first.text,))

    def test_each_native_cue_has_only_one_translation_update(self):
        buffer = SpeechBuffer()
        buffer.observe("We are ready. He is waiting", 10)
        first = buffer.take(10)
        buffer.commit(first, 10.1)
        self.assertIsNone(buffer.take(11))
        buffer.observe("He is waiting for us.", 12, continuous=True)
        self.assertEqual(buffer.take(12).text, "for us.")

    def test_many_incomplete_cues_never_accumulate_into_a_later_dump(self):
        buffer = SpeechBuffer()
        for i, text in enumerate(['Because he', 'was going to', 'turn into the', 'last corner.']):
            now = 10+i*2
            buffer.observe(text, now)
            segment = buffer.take(now)
            self.assertEqual(segment.text, text)
            self.assertEqual(segment.ready_at-segment.observed, 0)
            self.assertFalse(segment.allow_wait)
            buffer.commit(segment, now+.5)

    def test_expired_or_different_speaker_source_does_not_trim_new_utterance(self):
        buffer = SpeechBuffer()
        buffer.observe('I want you to', 10)
        buffer.commit(buffer.take(10), 10.2)
        buffer.observe('you to stay.', 20)
        self.assertEqual(buffer.take(20).text, 'you to stay.')

    def test_consumed_top_row_is_trimmed_and_repeated_utterance_still_translates(self):
        buffer = SpeechBuffer()
        buffer.observe("We are ready.", 10)
        buffer.commit(buffer.take(10), 10.1)
        buffer.observe("We are ready. Let's go.", 11)
        self.assertEqual(buffer.take(11).text, "Let's go.")
        other = SpeechBuffer()
        other.observe("Yes.", 10)
        other.commit(other.take(10), 10.1)
        other.observe("Yes.", 11)
        self.assertEqual(other.take(11).text, "Yes.")

    def test_speaker_change_and_long_gap_do_not_join_unrelated_fragments(self):
        buffer = SpeechBuffer()
        buffer.observe("MAX: I want to", 10)
        buffer.observe("LEWIS: No.", 10.5)
        self.assertEqual(buffer.take(10.5).text, "LEWIS: No.")
        buffer.observe("Another programme.", 50)
        self.assertEqual(buffer.take(50).context, ())

    def test_context_is_bounded_and_resettable(self):
        buffer = SpeechBuffer()
        for i in range(20):
            buffer.observe(f"Sentence {i}.", 10+i)
            buffer.take(10+i)
        self.assertLessEqual(len(buffer.context(30)), 8)
        buffer.reset()
        self.assertEqual(buffer.context(31), ())
        self.assertIsNone(buffer.take(31))

    def test_punctuation_does_not_override_missing_complement(self):
        self.assertTrue(unfinished("I thought that..."))
        self.assertFalse(complete("If he comes back"))
        self.assertTrue(complete("Yes!"))
        self.assertTrue(complete("If he comes back, tell me."))
        self.assertFalse(complete("And then it’s."))


class ApiSegmentTests(unittest.TestCase):
    def api(self, protocol="chat", output="译文"):
        import httpx
        captured = []
        def respond(request):
            captured.append(json.loads(request.content))
            body = {
                "chat": {"choices": [{"finish_reason": "stop", "message": {"content": output}}]},
                "qwen-mt": {"choices": [{"finish_reason": "stop", "message": {"content": output}}]},
                "responses": {"status": "completed", "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": output}]}]},
                "messages": {"stop_reason": "end_turn", "content": [{"type": "text", "text": output}]},
                "gemini": {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": output}]}}]},
            }[protocol]
            return httpx.Response(200, json=body)
        api = ApiTranslator(Settings(mode="API", api_model="fixture", api_protocol=protocol), "fixture")
        api.client.close()
        api.client = httpx.Client(transport=httpx.MockTransport(respond))
        self.addCleanup(api.close)
        return api, captured

    def test_all_protocols_carry_context_without_translating_it_as_input(self):
        for protocol in ("chat", "responses", "messages", "gemini", "qwen-mt"):
            with self.subTest(protocol=protocol):
                api, captured = self.api(protocol)
                result = TermTranslator(api, "").translate_segment("He is leading.", ("Max is the driver.",))
                self.assertEqual(result, "译文")
                payload = captured[0]
                self.assertIn("Max is the driver.", json.dumps(payload))
                if protocol == "qwen-mt":
                    self.assertEqual(payload["messages"], [{"role": "user", "content": "He is leading."}])
                else:
                    text = (payload["input"][0]["content"] if protocol == "responses" else
                            payload["contents"][0]["parts"][0]["text"] if protocol == "gemini" else
                            payload["messages"][-1]["content"])
                    self.assertEqual(json.loads(text)["subtitle_to_translate"], "He is leading.")

    def test_enabled_vocabulary_categories_supply_domain_without_mutating_settings(self):
        from subtitle_app.presets import TermPreset
        api, captured = self.api()
        api.settings.term_presets = [TermPreset(name='赛车'), TermPreset(name='medical', enabled=False)]
        TermTranslator(api, '').translate_segment('He is dropping the car behind.')
        instruction = captured[0]['messages'][0]['content']
        self.assertIn('赛车', instruction)
        self.assertNotIn('medical', instruction)
        self.assertFalse(api.settings.term_presets[1].enabled)

    def test_protected_words_are_masked_in_one_request_and_restored(self):
        api, captured = self.api(output="让⟦ATV_KEEP_0⟧跟在⟦ATV_KEEP_1⟧后面。")
        value = TermTranslator(api, "Max\nLewis").translate_segment(
            "Tell Max to stay behind Lewis.", ("Max is ahead of Lewis.",))
        self.assertEqual(value, "让Max跟在Lewis后面。")
        self.assertEqual(len(captured), 1)
        user = json.loads(captured[0]["messages"][-1]["content"])
        self.assertNotIn("Max", user["subtitle_to_translate"])
        self.assertNotIn("Lewis", user["previous_subtitles"][0])
        self.assertIn("⟦ATV_KEEP_0⟧", user["previous_subtitles"][0])

    def test_missing_duplicate_unknown_and_history_placeholders_are_rejected(self):
        for output in ("漏掉了", "⟦ATV_KEEP_0⟧⟦ATV_KEEP_0⟧", "⟦ATV_KEEP_9⟧",
                       "⟦ATV_KEEP_0⟧⟦ATV_CONTEXT_0⟧"):
            with self.subTest(output=output):
                api, _ = self.api(output=output)
                with self.assertRaises(TranslationError):
                    TermTranslator(api, "Max").translate_segment("Tell Max.")

    def test_model_wait_is_rejected_and_never_a_subtitle_or_wait_state(self):
        api, _ = self.api(output=WAIT_MARKER)
        with self.assertRaises(TranslationError):
            TermTranslator(api, "").translate_segment("If that happens", allow_wait=True)
        with self.assertRaises(TranslationError):
            TermTranslator(api, "").translate_segment("If that happens", allow_wait=False)

    def test_partial_cue_policy_is_conservative_for_every_protocol(self):
        for protocol in ('chat', 'responses', 'messages', 'gemini', 'qwen-mt'):
            with self.subTest(protocol=protocol):
                api, captured = self.api(protocol, output='如果引擎出故障……')
                self.assertEqual(TermTranslator(api, '').translate_segment(
                    'If the engine fails', ('He is leading.',)), '如果引擎出故障……')
                payload = json.dumps(captured[0], ensure_ascii=False)
                self.assertIn('immediately', payload)
                self.assertIn('conservative', payload)
                self.assertNotIn(WAIT_MARKER, payload)

    def test_unchanged_source_is_not_reported_as_a_successful_translation(self):
        api, _ = self.api(output="An enormous advantage, who was so")
        with self.assertRaises(TranslationError):
            TermTranslator(api, "").translate_segment("An enormous advantage, who was so")
        api, _ = self.api(output="⟦ATV_KEEP_0⟧")
        self.assertEqual(TermTranslator(api, "Max").translate_segment("Max"), "Max")

    def test_literal_placeholder_roundtrip_does_not_trigger_recursive_replacement(self):
        api, _ = self.api(output="⟦ATV_KEEP_0⟧和⟦ATV_KEEP_1⟧")
        result = TermTranslator(api, "Max").translate_segment("⟦ATV_KEEP_1⟧ and Max")
        self.assertEqual(result, "⟦ATV_KEEP_1⟧和Max")

    def test_stale_network_request_is_cancelled_and_next_request_can_run(self):
        import asyncio
        import httpx
        api, _ = self.api()
        cancelled_tasks = []
        async def respond(request):
            passage = json.loads(json.loads(request.content)["messages"][-1]["content"])["subtitle_to_translate"]
            if passage == "Old sentence.":
                try:
                    await asyncio.sleep(3)
                except asyncio.CancelledError:
                    cancelled_tasks.append(True)
                    raise
            return httpx.Response(200, json={"choices": [
                {"finish_reason": "stop", "message": {"content": "新译文。"}}]})
        api.async_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        began = time.monotonic()
        with self.assertRaises(InterruptedError):
            TermTranslator(api, "").translate_segment("Old sentence.",
                cancelled=lambda: time.monotonic()-began > .12, deadline=began+5)
        self.assertLess(time.monotonic()-began, .6)
        self.assertTrue(cancelled_tasks)
        self.assertEqual(TermTranslator(api, "").translate_segment("New sentence.",
            cancelled=lambda: False, deadline=time.monotonic()+1), "新译文。")


if __name__ == "__main__":
    unittest.main(verbosity=2)

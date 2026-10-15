"""Offline creation-intent, timing and rendered-repair pipeline checks."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import kimi_ai as ai
from ai_images import normalize
from PIL import Image

spec = importlib.util.spec_from_file_location('ai_fixture', ROOT / 'tests/kimi-ai-check.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def drawing(count=100, speed=40, black=False):
    return {'version': 1, 'name': '轨光', 'description': '青色光带往返，轴灯同步。',
            'frame_count': count, 'speed_ms': speed, 'palette': ['#00C0D8'], 'scenes': [
                {'name': '流动', 'start': 0, 'end': count,
                 'top': [{'kind': 'scan', 'axis': 'x', 'color': '#000000' if black else '#00C0D8',
                          'width': .3, 'position': {'from': .2, 'to': .8, 'ease': 'sine'}}],
                 'keys': [{'kind': 'solid', 'color': '#000000' if black else '#00C0D8',
                           'opacity': {'from': .55, 'to': 1, 'ease': 'sine'}}]}]}


class CreativeChecks(unittest.TestCase):
    def payload(self, **extra):
        return {'ai': f.CONFIG.copy(), 'requestId': 'creative-offline', 'brief': '青色光带流动，4秒循环',
                'timing': 'auto', **extra}

    def test_upward_guidance_matches_real_wave_sampling(self):
        from lighting_recipe import compile_recipe
        r = drawing(17, 40)
        r['scenes'][0]['top'] = [{'kind': 'wave', 'color': '#FFFFFF', 'angle': 90,
                                  'frequency': 1, 'power': 4,
                                  'phase': {'from': 0, 'to': -1}}]
        d = compile_recipe(r)
        def peak_row(frame):
            return max(range(5), key=lambda y: int(frame[y*40][1:3],16))
        self.assertEqual(peak_row(d['frames'][0]), 1)
        self.assertEqual(peak_row(d['frames'][4]), 0)
        guidance = ai.selected_design_guidance('轴灯跟着向上升', False)
        self.assertIn('phase线性递减',guidance)
        self.assertIn('triangle/sine是往返',guidance)

    def test_explicit_legacy_contract_is_preserved(self):
        p = self.payload(frameCount=50, speedMs=100)
        t = ai.resolve_generation_parameters(p)
        self.assertEqual((t['frame_count'], t['speed_ms'], t['source']), (50, 100, 'explicit'))
        t = ai.resolve_generation_parameters(self.payload(frameCount=50, speedMs=100, brief='时长-8秒循环'))
        self.assertEqual((t['frame_count'], t['speed_ms'], t['source']), (50, 100, 'explicit'))
        self.assertEqual(ai.resolve_generation_parameters({})['frame_count'], 192)

    def test_auto_duration_and_no_preview_defaults(self):
        for brief, seconds in [('火焰，4秒循环', 4), ('极光，循环时长：6秒', 6),
                               ('青色，loop of 3.5 seconds', 3.5), ('时长25.5秒', 25.5),
                               ('火光，0.25s loop', .25)]:
            t = ai.resolve_generation_parameters(self.payload(brief=brief))
            self.assertEqual(t['loop_seconds'], seconds)
            self.assertTrue(1 <= t['frame_count'] <= 255 and 10 <= t['speed_ms'] <= 100)
        for brief, seconds in [('极光流动', 6), ('小猫眨眼', 6), ('火焰', 4)]:
            self.assertEqual(ai.resolve_generation_parameters(self.payload(brief=brief))['loop_seconds'], seconds)
        self.assertEqual(ai.resolve_generation_parameters(self.payload(brief='光点停留2秒再走'))['loop_seconds'], 4)
        self.assertEqual(ai.resolve_generation_parameters(self.payload(brief='角色', images=[{}]))['source'], 'auto')

    def test_common_total_duration_phrasing_does_not_silently_use_defaults(self):
        examples = [('做一个8秒的循环', 8), ('8秒钟循环', 8), ('循环持续8秒', 8),
                    ('create a loop lasting 8 seconds', 8), ('loop duration: 8 seconds', 8),
                    ('total duration is 8 seconds', 8), ('an 8-second loop', 8),
                    ('8 second long cycle', 8), ('duration: .5 seconds', .5),
                    ('循环时长0.1分钟', 6), ('a 0.1-minute loop', 6),
                    ('循环时长500毫秒', .5)]
        for brief, duration in examples:
            with self.subTest(brief=brief):
                timing = ai.resolve_generation_parameters(self.payload(brief=brief))
                self.assertEqual(timing['loop_seconds'], duration)
                self.assertEqual(timing['source'], 'brief')
        for brief in ('光点停留2秒再走', 'a dot holds for 2 seconds, then travels', '循环中停留2秒再继续'):
            with self.subTest(brief=brief):
                self.assertEqual(ai.resolve_generation_parameters(self.payload(brief=brief))['source'], 'auto')

    def test_signed_or_oversized_duration_cannot_be_reinterpreted_as_a_valid_suffix(self):
        for brief in ('总时长-8秒', '总时长-8秒循环', 'duration: -8 seconds loop',
                      '-8-second loop', 'duration: −8 seconds', '总时长－8秒钟',
                      '总时长1分钟', 'a 1-minute loop'):
            with self.subTest(brief=brief):
                opener = f.Opener()
                with self.assertRaises(ai.AIError) as error:
                    ai.generate(self.payload(brief=brief), opener=opener)
                self.assertEqual(error.exception.code, 'ai_invalid_parameters')
                self.assertEqual(opener.calls, [])

    def test_ambiguous_unsupported_or_unbounded_duration_does_not_call_model(self):
        for brief in ['4秒循环，循环时长6秒', '时长30秒', '时长0秒', '时长'+'9'*500+'秒']:
            op = f.Opener()
            with self.assertRaises(ai.AIError): ai.generate(self.payload(brief=brief), opener=op)
            self.assertEqual(op.calls, [])
        with self.assertRaises(ai.AIError): ai.resolve_generation_parameters({'timing':'unknown'})

    def test_image_and_text_guidance_are_separate_and_schema_is_smaller(self):
        text = ai.creative_messages(self.payload())
        raw = io.BytesIO(); Image.new('RGB', (8, 8), '#EEEEEE').save(raw, 'PNG')
        image = ai.creative_messages(self.payload(images=[normalize(raw.getvalue())]))
        self.assertIn('无图流程', text[0]['content']); self.assertNotIn('有图流程', text[0]['content'])
        self.assertIn('有图流程', image[0]['content']); self.assertNotIn('无图流程', image[0]['content'])
        self.assertIn('白色主体', image[0]['content'])
        self.assertEqual([p['type'] for p in image[1]['content']], ['text','image_url'])
        self.assertLess(len(text[0]['content']), 22000)
        self.assertNotIn('可选参考风格', json.loads(text[1]['content']))
        self.assertIn('逐层明确palette', text[0]['content'])
        self.assertNotIn('无缝旋涡着色器', text[0]['content'])

    def test_topic_guidance_respects_word_boundaries_and_static_image_intent(self):
        for brief in ('夜空萤火虫', 'fireflies in the night', 'a glowing firefly'):
            with self.subTest(brief=brief):
                guidance = ai.selected_design_guidance(brief, False)
                self.assertIn('萤火虫建议', guidance)
                self.assertNotIn('火焰建议', guidance)
        for brief in ('火焰', '篝火', 'a flame', 'a fire in the dark', 'lava'):
            with self.subTest(brief=brief):
                self.assertIn('火焰建议', ai.selected_design_guidance(brief, False))
        for brief in ('上海标志', '星巴克标志', 'an educational train logo'):
            with self.subTest(brief=brief):
                guidance = ai.selected_design_guidance(brief, False)
                self.assertNotIn('角色建议', guidance)
                self.assertNotIn('氛围建议', guidance)
                self.assertNotIn('雨建议', guidance)
        self.assertEqual(ai.resolve_generation_parameters(self.payload(brief='an educational train logo'))['loop_seconds'], 4)
        guidance = ai.selected_design_guidance('静态小猫图标，不要动作', True)
        self.assertIn('用户要求动画时', guidance)
        self.assertIn('明确要求静态时保留固定姿态', guidance)
        self.assertIn('明确静态要求优先', guidance)

    def test_auto_parameters_compile_and_quality_metadata_is_public_only(self):
        op = f.Opener(f.completion(json.dumps(drawing())))
        events = []
        r = ai.generate(self.payload(), opener=op, progress=lambda a,b: events.append(a))
        self.assertEqual((len(r['design']['frames']),r['design']['speed_ms']), (100,40))
        meta = r['design']['ai']
        self.assertEqual(meta['promptVersion'], 4)
        self.assertEqual(meta['timing']['source'],'brief')
        self.assertTrue(meta['quality']['passed'])
        self.assertIn('ai_quality',events)
        self.assertNotIn(f.SECRET,json.dumps(r))
        self.assertNotIn('dataUrl',json.dumps(r))

    def test_actual_black_pixels_trigger_one_repair_with_measured_reason(self):
        bad, good = drawing(black=True), drawing()
        op = f.Opener(f.completion(json.dumps(bad)),f.completion(json.dumps(good)))
        r = ai.generate(self.payload(),opener=op)
        self.assertTrue(r['repaired']); self.assertEqual(len(op.calls),2)
        repair = json.loads(op.calls[1][0].data)['messages'][-1]['content']
        self.assertIn('实际渲染检查',repair)
        self.assertIn('全程接近熄灭',repair)
        self.assertTrue(r['design']['ai']['quality']['passed'])
        self.assertEqual(r['usage']['total_tokens'],60)

    def test_quality_failure_is_not_imported_and_has_shared_repair_budget(self):
        black = f.completion(json.dumps(drawing(black=True)))
        op = f.Opener(black, f.completion(json.dumps(drawing(black=True))))
        with self.assertRaises(ai.AIError) as caught: ai.generate(self.payload(),opener=op)
        self.assertEqual(caught.exception.code,'ai_quality_failed')
        self.assertEqual(len(op.calls),2)
        op = f.Opener(f.completion('{}'),f.completion(json.dumps(drawing(black=True))))
        with self.assertRaises(ai.AIError) as caught: ai.generate(self.payload(),opener=op)
        self.assertEqual(caught.exception.code,'ai_quality_failed')
        self.assertEqual(len(op.calls),2)

    def test_deliberately_static_is_kept(self):
        t = ai.resolve_generation_parameters(self.payload(brief='静态蓝色，4秒循环'))
        r = drawing(t['frame_count'], t['speed_ms'])
        r['scenes'][0]['top']=[{'kind':'solid','color':'#102030'}]
        r['scenes'][0]['keys']=[]
        result=ai.generate(self.payload(brief='静态蓝色，4秒循环'),opener=f.Opener(f.completion(json.dumps(r))))
        self.assertFalse(result['repaired'])
        self.assertTrue(result['design']['ai']['quality']['passed'])


if __name__ == '__main__': unittest.main(verbosity=2)

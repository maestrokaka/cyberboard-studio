#!/usr/bin/env python3
"""Offline image-service and asset contract tests. No account, audio device or USB access."""
import base64
import io
import platform
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from companion import Wardrobe, CompanionError
from PIL import Image, ImageDraw


def png(bg=(0, 255, 0, 255)):
    image = Image.new('RGBA', (256, 512), bg)
    ImageDraw.Draw(image).rectangle((80, 40, 180, 480), fill=(255, 120, 40, 255))
    stream = io.BytesIO(); image.save(stream, 'PNG'); return stream.getvalue()


class Reply(io.BytesIO):
    pass


class Service:
    def __init__(self, reply): self.reply = reply; self.requests = []
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return Reply(json.dumps(self.reply).encode())


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = Service({'base_resp': {'status_code': 0}, 'data': {'image_base64': [base64.b64encode(png()).decode()]}})
        self.wardrobe = Wardrobe(self.root, ROOT, self.service)

    def test_configuration_isolated_and_hidden(self):
        status = self.wardrobe.save({'apiKey': 'test-not-real', 'region': 'global'})
        self.assertTrue(status['hasKey']); self.assertNotIn('test-not-real', json.dumps(status))
        self.assertEqual(self.wardrobe.reveal()['apiKey'], 'test-not-real')
        self.assertEqual(json.loads(self.wardrobe.config.read_text()), {'region': 'global'})
        self.wardrobe.save({'region': 'china', 'removeKey': True})
        self.assertFalse(self.wardrobe.settings()['hasKey'])
        for bad in ('other', '../china'):
            with self.assertRaises(CompanionError): self.wardrobe.save({'region': bad})

    def test_generate_preserves_identity_and_requires_apply(self):
        self.wardrobe.save({'apiKey': 'test-not-real'})
        result = self.wardrobe.generate({'prompt': '奶白外套与长裤', 'hair': 'long'})
        self.assertFalse(result['applied']); self.assertTrue(result['staticPose'])
        request, timeout = self.service.requests[0]; body = json.loads(request.data)
        self.assertEqual(timeout, 120); self.assertEqual(body['aspect_ratio'], '9:16')
        self.assertIn('adult 23-year-old', body['prompt']); self.assertIn('Waist-length', body['prompt'])
        self.assertEqual(len(body['subject_reference']), 1)
        self.assertEqual(base64.b64decode(body['subject_reference'][0]['image_file'].split(',')[1]), (ROOT/'web/assets/companion/sailor-long/idle.png').read_bytes())
        self.assertEqual(json.loads((self.wardrobe.folder/(result['id']+'.json')).read_text()), {'hair':'long'})
        with Image.open(self.wardrobe.folder/(result['id']+'.png')) as image:
            self.assertEqual(image.size, (768, 1536)); self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getchannel('A').getextrema(), (0,255)); self.assertFalse(image.info)
        self.assertFalse((self.root/'workspace.json').exists())
        self.wardrobe.delete({'id':result['id']}); self.assertFalse(list(self.wardrobe.folder.glob('*')))

    def test_rejects_bad_requests_before_network(self):
        self.wardrobe.save({'apiKey':'test-not-real'})
        for data in ({'prompt':''}, {'prompt':'a'*601}, {'prompt':'coat','hair':'../long'}):
            with self.assertRaises(CompanionError): self.wardrobe.generate(data)
        self.assertEqual(self.service.requests, [])
        for identity in ('sailor-long', '../any', 'custom-'+'0'*32+'.png', 42):
            with self.assertRaises(CompanionError): self.wardrobe.delete({'id':identity})
        self.assertTrue((ROOT/'web/assets/companion/sailor-long/idle.png').exists())

    def test_failed_service_never_saves_or_retries(self):
        self.wardrobe.save({'apiKey':'test-not-real'})
        for reply in ({'base_resp':{'status_code':1004}}, {'data':{'image_base64':['not base64']}}, {'data':{}}, []):
            self.service.reply = reply
            with self.assertRaises(CompanionError): self.wardrobe.generate({'prompt':'white jacket'})
        self.assertEqual(len(self.service.requests),4)
        self.assertFalse(list(self.wardrobe.folder.glob('*')))
        self.assertEqual(self.wardrobe.reveal()['apiKey'], 'test-not-real')

    def test_normalization_rejects_solid_background_and_empty(self):
        for raw in (b'not image', png((255,255,255,255)), b''):
            with self.assertRaises(CompanionError): Wardrobe.normalize(raw)
        empty = Image.new('RGBA',(256,512)); b=io.BytesIO();empty.save(b,'PNG')
        with self.assertRaises(CompanionError): Wardrobe.normalize(b.getvalue())

    def test_all_32_poses_and_60_audio_decode(self):
        catalog=json.loads((ROOT/'web/assets/companion/catalog.json').read_text())
        self.assertEqual(len(catalog['outfits']),4);self.assertEqual(len(catalog['zones']),15)
        self.assertEqual(sum(o['hair']=='long' for o in catalog['outfits']),1)
        for outfit in catalog['outfits']:
            self.assertEqual(len(outfit['frames']),8)
            for name in outfit['frames'].values():
                with Image.open(ROOT/'web'/name) as image:
                    self.assertEqual(image.size,(320,640));self.assertEqual(image.mode,'RGBA')
                    self.assertEqual(image.getchannel('A').getextrema(),(0,255))
        ffmpeg=Path('/Users/sheva/Documents/miao/demo-captures/2026-10-14/bin/ffmpeg')
        for voice in catalog['voices']:
            for zone in catalog['zones']:
                path=ROOT/'web/assets/companion/audio'/voice['id']/(zone['id']+'.mp3')
                self.assertTrue(path.stat().st_size>1000)
                if platform.system() == 'Darwin':
                    p=subprocess.run(['/usr/bin/afconvert',str(path),str(self.root/'decode.wav'),'-f','WAVE','-d','LEI16'],capture_output=True,timeout=10)
                    self.assertEqual(p.returncode,0,p.stderr.decode())
                elif ffmpeg.exists():
                    p=subprocess.run([str(ffmpeg),'-v','error','-i',str(path),'-f','null','-'],capture_output=True,timeout=10)
                    self.assertEqual(p.returncode,0,p.stderr.decode())
        self.assertFalse(catalog['defaults']['sound']);self.assertEqual(catalog['defaults']['mode'],'wake')

if __name__=='__main__': unittest.main()

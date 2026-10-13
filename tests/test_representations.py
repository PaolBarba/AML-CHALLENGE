"""Offline adapter checks using tiny random models, never pretrained checkpoints."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

AVAILABLE = importlib.util.find_spec('torch') is not None and importlib.util.find_spec('transformers') is not None


@unittest.skipUnless(AVAILABLE, 'Optional PyTorch/Transformers dependencies are not installed')
class RepresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from transformers import (BitImageProcessor, CLIPConfig, CLIPImageProcessor, CLIPModel,
                                  CLIPProcessor, CLIPTokenizer, Dinov2Config, Dinov2Model)
        from challenge.representations import RepresentationMetrics
        torch.set_num_threads(1)
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        clip, dino = root / 'clip', root / 'dino'
        clip.mkdir()
        (clip / 'vocab.json').write_text(json.dumps({'<|startoftext|>': 0, '<|endoftext|>': 1, 'red</w>': 2, 'blue</w>': 3}))
        (clip / 'merges.txt').write_text('#version: 0.2\n')
        tokenizer = CLIPTokenizer(str(clip / 'vocab.json'), str(clip / 'merges.txt'))
        CLIPProcessor(tokenizer=tokenizer, image_processor=CLIPImageProcessor(size={'shortest_edge': 32}, crop_size={'height': 32, 'width': 32})).save_pretrained(clip)
        cfg = CLIPConfig(projection_dim=8,
            text_config={'vocab_size': 4, 'hidden_size': 16, 'intermediate_size': 32, 'num_hidden_layers': 1, 'num_attention_heads': 2, 'bos_token_id': 0, 'eos_token_id': 1, 'pad_token_id': 1},
            vision_config={'image_size': 32, 'patch_size': 8, 'hidden_size': 16, 'intermediate_size': 32, 'num_hidden_layers': 1, 'num_attention_heads': 2})
        CLIPModel(cfg).save_pretrained(clip)
        Dinov2Model(Dinov2Config(hidden_size=24, num_hidden_layers=1, num_attention_heads=3, image_size=224, patch_size=14)).save_pretrained(dino)
        BitImageProcessor().save_pretrained(dino)
        cls.evaluator = RepresentationMetrics({'clip_directory': str(clip), 'dinov2_directory': str(dino)})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_patch_layout_and_identical_background(self):
        source = Image.new('RGB', (256, 192), (210, 45, 55))
        features, h, w = self.evaluator.patches(source)
        self.assertEqual((h, w), (16, 16))
        self.assertEqual(tuple(features.shape), (256, 24))
        result = self.evaluator.evaluate(source, source, Image.new('L', source.size, 0),
                                         {'source_description': 'red', 'target_description': 'blue'})
        self.assertAlmostEqual(result['dinov2_background_similarity'], 1., places=5)
        self.assertEqual(result['clip_directional_similarity'], 0.)
        self.assertTrue(-1 <= result['clip_target_alignment'] <= 1)

    def test_mask_free_reference_metrics(self):
        source = Image.new('RGB', (256, 192), (210, 45, 55))
        result = self.evaluator.evaluate_reference(source, source, 'red')
        self.assertAlmostEqual(result['structure_distance'], 0., places=6)
        self.assertTrue(-1 <= result['clip_similarity'] <= 1)
        self.assertNotIn('clip_similarity', self.evaluator.evaluate_reference(source, source, ''))

    def test_no_background_patches_and_no_descriptions(self):
        source = Image.new('RGB', (256, 192), (120, 130, 140))
        result = self.evaluator.evaluate(source, source, Image.new('L', source.size, 255), {})
        self.assertIsNone(result['dinov2_background_similarity'])
        self.assertNotIn('clip_directional_similarity', result)


if __name__ == '__main__':
    unittest.main()

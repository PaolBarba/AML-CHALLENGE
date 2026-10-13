"""Optional, frozen CLIP/DINOv2 diagnostics. These do not establish edit success."""
import math

import numpy as np
from PIL import Image


class RepresentationMetrics:
    def __init__(self, config):
        import torch
        from transformers import AutoImageProcessor, AutoModel, CLIPModel, CLIPProcessor
        self.torch = torch
        self.device = config.get('device', 'cpu')
        self.clip = self.clip_processor = self.dino = self.dino_processor = None
        # Local model directories keep evaluation independent of mutable remote checkpoints.
        if config.get('clip_directory'):
            self.clip_processor = CLIPProcessor.from_pretrained(config['clip_directory'], local_files_only=True, use_fast=False)
            self.clip = CLIPModel.from_pretrained(config['clip_directory'], local_files_only=True).to(self.device).eval()
        if config.get('dinov2_directory'):
            self.dino_processor = AutoImageProcessor.from_pretrained(config['dinov2_directory'], local_files_only=True, use_fast=False)
            self.dino = AutoModel.from_pretrained(config['dinov2_directory'], local_files_only=True).to(self.device).eval()
            if self.dino.config.model_type != 'dinov2':
                raise ValueError('Use a DINOv2 model without register tokens')

    def cosine(self, a, b):
        torch = self.torch
        if a.norm().item() < 1e-8 or b.norm().item() < 1e-8:
            return 0.0
        return float(torch.nn.functional.cosine_similarity(a, b, dim=-1).mean().item())

    def patches(self, image):
        # Resize the complete image: center cropping would lose background coordinates.
        resized = image.resize((224, 224), Image.Resampling.BICUBIC)
        inputs = self.dino_processor(images=resized, do_resize=False, do_center_crop=False, return_tensors='pt').to(self.device)
        size = self.dino.config.patch_size
        h, w = inputs.pixel_values.shape[-2:]
        with self.torch.inference_mode():
            features = self.dino(**inputs).last_hidden_state[:, 1:]
        if features.shape[1] != (h // size) * (w // size):
            raise ValueError('Unexpected DINOv2 patch layout')
        return features[0], h // size, w // size

    def evaluate(self, source, edited, allowed, task):
        result = {}
        torch = self.torch
        if self.clip:
            images = self.clip_processor(images=[source, edited], return_tensors='pt').to(self.device)
            with torch.inference_mode():
                features = self.clip.get_image_features(**images)
            features = torch.nn.functional.normalize(features, dim=-1)
            before, after = task.get('source_description'), task.get('target_description')
            if before and after:
                texts = self.clip_processor(text=[before, after], padding=True, truncation=True, max_length=self.clip.config.text_config.max_position_embeddings, return_tensors='pt').to(self.device)
                with torch.inference_mode():
                    text_features = self.clip.get_text_features(**texts)
                text_features = torch.nn.functional.normalize(text_features, dim=-1)
                result['clip_directional_similarity'] = self.cosine(features[1] - features[0], text_features[1] - text_features[0])
                result['clip_target_alignment'] = self.cosine(features[1], text_features[1])
        if self.dino:
            a, h, w = self.patches(source)
            b, _, _ = self.patches(edited)
            # Include only patches whose whole spatial footprint is outside the allowed edit region.
            full = np.asarray(allowed.resize((224, 224), Image.Resampling.NEAREST)) >= 128
            patch = self.dino.config.patch_size
            background = ~full[:h * patch, :w * patch].reshape(h, patch, w, patch).any(axis=(1, 3))
            indices = torch.as_tensor(background.reshape(-1), device=self.device)
            result['dinov2_background_similarity'] = self.cosine(a[indices], b[indices]) if indices.any().item() else None
        if any(v is not None and not math.isfinite(v) for v in result.values()):
            raise ValueError('Representation evaluator produced a non-finite value')
        return result

    def evaluate_reference(self, source, edited, prompt):
        result = {}
        torch = self.torch
        if self.clip and prompt.strip():
            images = self.clip_processor(images=[edited], return_tensors='pt').to(self.device)
            texts = self.clip_processor(text=[prompt], padding=True, truncation=True,
                                        max_length=self.clip.config.text_config.max_position_embeddings,
                                        return_tensors='pt').to(self.device)
            with torch.inference_mode():
                image_features = self.clip.get_image_features(**images)
                text_features = self.clip.get_text_features(**texts)
            result['clip_similarity'] = self.cosine(image_features, text_features)
        if self.dino:
            a, _, _ = self.patches(source)
            b, _, _ = self.patches(edited)
            a, b = torch.nn.functional.normalize(a, dim=-1), torch.nn.functional.normalize(b, dim=-1)
            result['structure_distance'] = float(((a @ a.T - b @ b.T) ** 2).mean().item())
        return result

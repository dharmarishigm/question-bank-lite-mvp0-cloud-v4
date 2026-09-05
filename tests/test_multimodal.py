import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from multimodal import build_content_blocks, crop_source_region, normalize_bbox, split_rich_text


class MultimodalTests(unittest.TestCase):
    def test_split_math_and_chemistry(self):
        blocks = split_rich_text(r"If $x^2=4$, react $\ce{Fe^{2+}}$ with oxidant.")
        kinds = [b['type'] for b in blocks]
        self.assertEqual(kinds, ['text', 'math', 'text', 'chemistry', 'text'])
        self.assertEqual(blocks[1]['content'], '$x^2=4$')
        self.assertIn('Fe^{2+}', blocks[3]['content'])

    def test_bbox_is_clamped(self):
        self.assertEqual(normalize_bbox([-1, .2, 2, .8]), [0.0, .2, 1.0, .8])
        self.assertEqual(normalize_bbox([.2, .2, .2, .8]), [])

    def test_visual_source_crop_is_created(self):
        image = Image.new('RGB', (100, 100), 'white')
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        with tempfile.TemporaryDirectory() as d:
            url = crop_source_region(buf.getvalue(), 'image/png', 1, [.2, .2, .8, .8], d, prefix='graph')
            self.assertTrue(url.startswith('/uploads/graph-'))
            out = Path(d) / Path(url).name
            self.assertTrue(out.exists())
            with Image.open(out) as cropped:
                self.assertEqual(cropped.size, (60, 60))

    def test_content_blocks_include_preserved_visual(self):
        blocks = build_content_blocks('Find $x$.', [{
            'type': 'graph', 'asset': '/uploads/g.png', 'page': 1,
            'bbox': [.1, .2, .8, .7], 'description': 'velocity-time graph',
            'graph': {'x_axis': 't', 'y_axis': 'v', 'labels': ['A']},
        }])
        self.assertEqual([b['type'] for b in blocks[:2]], ['text', 'math'])
        self.assertEqual(blocks[-1]['type'], 'graph')
        self.assertTrue(blocks[-1]['source_truth'])
        self.assertEqual(blocks[-1]['asset'], '/uploads/g.png')


if __name__ == '__main__':
    unittest.main()

import json
import unittest
import app

class ExplanationRenderingTests(unittest.TestCase):
    def payload(self):
        return dict(title='వివరణ',summary='సారాంశం',concept={'paragraphs':['మొదటి భాగం','రెండవ భాగం']},steps=[{'text':'మొదటి మెట్టు'},'రెండవ మెట్టు'],correct_answer='సరైన సమాధానం',distractors=[],background='నేపథ్యం',memory_tip='గుర్తుంచుకోండి',references=[])
    def test_telugu_containers_render_as_prose(self):
        text,structured=app.decode_explanation('```json\n'+json.dumps(self.payload())+'\n```')
        self.assertEqual(structured['concept'],'మొదటి భాగం\n\nరెండవ భాగం')
        self.assertEqual(structured['steps'][0],'మొదటి మెట్టు')
        self.assertNotIn('paragraphs',text)
    def test_double_encoded_json_and_math(self):
        text,structured=app.decode_explanation(json.dumps(json.dumps(self.payload())))
        self.assertIsNotNone(structured)
        self.assertEqual(app.explanation_prose(r'$\frac{1}{2}$'),r'$\frac{1}{2}$')

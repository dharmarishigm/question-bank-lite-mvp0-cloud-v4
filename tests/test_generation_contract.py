import json
import pytest

from llm_generate import (GeneratedQuestionBatch,GenerationRequest,
    generation_response_schema,is_near_duplicate,parse_generated_batch,validate_latex,validate_question)
from ai_runtime import serving_schema
from types import SimpleNamespace


def request(prompt='Create original arithmetic MCQs with four different choices.'):
    return GenerationRequest(exam_name='Synthetic validation',subject='Mental ability and EVS',generation_prompt=prompt,count=3)


def test_text_contract_is_small_and_does_not_include_persistence_fields():
    schema,visual=generation_response_schema(request())
    assert not visual
    properties=schema['properties']['questions']['items']['properties']
    assert set(properties)=={'statement','options','answer','solution','subject','chapter','topic','subtopic'}
    assert len(json.dumps(schema))<len(json.dumps(serving_schema(GeneratedQuestionBatch)))/3


def test_visual_contract_is_requested_explicitly_not_by_reference_syllabus():
    schema,visual=generation_response_schema(request('Create a non-verbal figure completion question.'))
    assert visual and 'visual_spec' in schema['properties']['questions']['items']['properties']
    plain=request().model_copy(update={'syllabus':'Arithmetic, mirror images, diagram completion and EVS'})
    assert generation_response_schema(plain)[1] is False


def visual_question():
    panel=lambda radius:{'primitives':[{'type':'CIRCLE','cx':200,'cy':200,'r':radius}]}
    return {'statement':'Choose the matching circle.','options':[{'label':label,'text':''} for label in 'ABCD'],
            'answer':'B','solution':'B has the same radius as the question.', 'visual_required':True,
            'visual_spec':{'question_figure':panel(40),'options':dict(zip('ABCD',[panel(20),panel(40),panel(60),panel(80)]))}}


def test_visual_choices_can_have_empty_or_identical_captions():
    raw=visual_question()
    for caption in ('','Diagram'):
        for option in raw['options']:option['text']=caption
        question=parse_generated_batch(SimpleNamespace(parsed={'questions':[raw]})).questions[0]
        validate_question(question)


def test_duplicate_diagrams_are_rejected_even_with_unique_captions():
    raw=visual_question()
    raw['visual_spec']['options']['D']=raw['visual_spec']['options']['A']
    for option in raw['options']:option['text']=option['label']
    question=parse_generated_batch(SimpleNamespace(parsed={'questions':[raw]})).questions[0]
    with pytest.raises(ValueError,match='diagrams must be distinct'):validate_question(question)


def test_missing_visual_captions_are_derived_only_from_existing_panels():
    raw=visual_question();raw['options']=[]
    question=parse_generated_batch(SimpleNamespace(parsed={'questions':[raw]})).questions[0]
    validate_question(question)
    assert [option.label for option in question.options]==list('ABCD')


def test_numeric_zero_option_is_not_discarded():
    raw={'statement':'Choose zero','options':[{'label':'A','value':0},{'label':'B','value':1}],'answer':'A','solution':'Zero is A.'}
    question=parse_generated_batch(SimpleNamespace(parsed={'questions':[raw]})).questions[0]
    validate_question(question)
    assert question.options[0].text=='0'


@pytest.mark.parametrize('content',[
    r'The value is \(\frac{3}{4}\).',
    r'Use \[x^2 + 2x + 1 = (x+1)^2\] to solve it.',
    r'Compute \(\begin{matrix}1 & 2 \\ 3 & 4\end{matrix}\).',
])
def test_complete_latex_is_accepted(content):
    validate_latex(content,'statement')


@pytest.mark.parametrize('content,reason',[
    (r'Find \(\frac{3}{4}.','unclosed math delimiter'),
    (r'Find \(\frac{3}{4\).','unclosed brace'),
    (r'Find \frac{3}{4}.','inside delimiters'),
    (r'Find \(\frac{}{4}\).','empty operand'),
    (r'Use \(\left(x+1\)\).','requires'),
])
def test_partial_or_non_renderable_latex_is_rejected(content,reason):
    with pytest.raises(ValueError,match=reason):validate_latex(content,'statement')


def test_question_validation_checks_latex_in_options_and_solution():
    question=parse_generated_batch(SimpleNamespace(parsed={'questions':[{
        'statement':'Choose the correct value.',
        'options':[{'label':'A','text':r'\frac{1}{2}'},{'label':'B','text':r'\(1\)'}],
        'answer':'B','solution':r'The result is \(1\).'}]})).questions[0]
    with pytest.raises(ValueError,match='option A'):validate_question(question)


def test_near_duplicate_detects_number_only_rewrites_but_not_new_reasoning():
    existing=['A shop has 48 pencils and packs 6 pencils in each box. How many boxes are needed?']
    assert is_near_duplicate('A shop has 72 pencils and packs 9 pencils in each box. How many boxes are needed?',existing)
    assert not is_near_duplicate('A rectangle has length 12 cm and width 5 cm. What is its perimeter?',existing)

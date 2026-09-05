from llm_extract import llm_status
from gcp_documentai import status as docai_status
from ocr import ocr_status

print('Question Bank Lite MVP-0 v3 setup')
print('Vertex AI :', llm_status())
print('DocumentAI:', docai_status())
print('Formula OCR:', ocr_status())
print('\nLocal UI is runnable regardless of GCP status.')
if not llm_status()['available']:
    print('To enable automatic AI digitization: set GCP_PROJECT_ID and authenticate with ADC.')
if not docai_status()['available']:
    print('To enable independent Math OCR: set DOCUMENTAI_PROCESSOR_ID and DOCUMENTAI_LOCATION.')

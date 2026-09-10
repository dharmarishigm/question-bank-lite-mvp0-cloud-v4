"""Deterministic patient based epidemiology forecast with an optional AI narrative layer."""
from contextlib import closing
from math import isfinite
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from blueprint_domain import Contract
from platform_api import _auth
from flag_api import access
from blueprint_gemini import structured_call

router = APIRouter(prefix='/api/flag/epidemiology', tags=['FLAG epidemiology model'])

class ForecastInputs(Contract):
    disease: str = Field(default='Diabetic Macular Edema', min_length=2, max_length=160)
    region: str = Field(default='USA', min_length=2, max_length=120)
    population_m: float = Field(default=38, gt=0, le=5000)
    cagr: float = Field(default=0.015, ge=-0.5, le=1)
    incidence: float = Field(default=0.015, ge=0, le=1)
    diagnosis_rate: float = Field(default=0.60, ge=0, le=1)
    treatment_rate: float = Field(default=0.70, ge=0, le=1)
    launch_year: int = Field(default=2027, ge=2020, le=2040)
    peak_share: float = Field(default=0.20, ge=0, le=1)
    loe_year: int | None = Field(default=2033, ge=2020, le=2050)
    price_usd: float = Field(default=1200, ge=0, le=100000)
    price_growth: float = Field(default=0.025, ge=-0.5, le=1)
    duration_years: float = Field(default=8, gt=0, le=30)
    alpha_share: float = Field(default=0.55, ge=0, le=1)
    beta_share: float = Field(default=0.25, ge=0, le=1)
    gamma_share: float = Field(default=0.20, ge=0, le=1)
    uptake: list[float] = Field(default=[0, 0, .15, .40, .65, .85, 1], min_length=2, max_length=15)
    start_year: int = Field(default=2025, ge=2020, le=2040)
    end_year: int = Field(default=2035, ge=2021, le=2050)

class ForecastSuggestion(ForecastInputs):
    rationale: str = Field(default='', max_length=1800)
    evidence_status: Literal['REFERENCE_ALIGNED','ASSUMPTION_REQUIRED'] = 'ASSUMPTION_REQUIRED'

def _clean(data):
    if data.end_year < data.start_year: raise HTTPException(422, 'End year must be after start year')
    if sum((data.alpha_share, data.beta_share, data.gamma_share)) > 1.001: raise HTTPException(422, 'Existing product shares cannot exceed 100%')
    if any(not isfinite(v) for v in data.uptake) or any(v < 0 or v > 1 for v in data.uptake): raise HTTPException(422, 'Uptake values must be between 0 and 1')
    return data

def forecast(data: ForecastInputs):
    data = _clean(data); years=list(range(data.start_year, data.end_year+1)); rows=[]
    for year in years:
        population=data.population_m*((1+data.cagr)**(year-data.start_year))
        eligible=population*data.incidence*data.diagnosis_rate*data.treatment_rate
        index=year-data.launch_year
        uptake=data.uptake[0] if index<0 else data.uptake[min(index,len(data.uptake)-1)]
        share=data.peak_share*uptake
        if data.loe_year and year>=data.loe_year: share*=max(0,1-0.8*min(1,year-data.loe_year+1))
        patients=eligible*share
        price=data.price_usd*((1+data.price_growth)**(year-data.start_year))
        revenue=patients*data.duration_years*price/1000
        rows.append({'year':year,'population_m':round(population,4),'eligible_pool_m':round(eligible,4),'uptake':round(uptake,4),'product_y_share':round(share,4),'product_y_patients_m':round(patients,4),'net_price_usd':round(price,2),'net_revenue_usd_m':round(revenue,3)})
    peak=max(rows,key=lambda x:x['product_y_share'])
    completeness=sum(v is not None for v in [data.disease,data.region,data.population_m,data.cagr,data.incidence,data.diagnosis_rate,data.treatment_rate,data.launch_year,data.peak_share,data.price_usd,data.uptake])/11
    confidence=round(min(.95,.55+.25*completeness+.10*(1 if data.loe_year else 0)),2)
    return {'model':'Patient based epidemiology model','inputs':data.model_dump(),'rows':rows,'peak':peak,'confidence':confidence,'confidence_reason':'Confidence reflects completeness of the supplied drivers and the transparent patient pool calculation. It is not a statistical validation score; calibrate incidence, diagnosis, treatment and uptake with local evidence before a commercial decision.','methodology':['Population grows from the base population by CAGR.','Eligible pool = population × incidence × diagnosis rate × treatment rate.','Product Y share follows the supplied uptake curve from launch.','Revenue = Product Y patients × treatment duration × net price.','LOE applies an 80% post-LOE share impact, matching the supplied template.']}

@router.get('/defaults')
def defaults(request: Request):
    access(request)
    return ForecastInputs().model_dump()

@router.post('/forecast')
def make_forecast(data: ForecastInputs, request: Request):
    access(request, True)
    return forecast(data)

@router.post('/suggest')
def suggest(data: dict, request: Request):
    user=access(request, True)
    disease=str(data.get('disease','')).strip();region=str(data.get('region','')).strip()
    if len(disease)<2 or len(region)<2: raise HTTPException(422,'Enter a disease and geographical region first')
    if len(disease)>160 or len(region)>120:raise HTTPException(422,'Disease or region is too long')
    from explanation_quota import reserve_explanation_call
    reserve_explanation_call(user['id'])
    try:
        result,meta=structured_call('EPIDEMIOLOGY_INPUT_SUGGESTION',
            'You are an epidemiology and market access forecasting analyst. Populate all inputs for a patient-based product forecast for the named disease and geography. '
            'Use plausible, internally consistent values and an uptake curve. Never present invented values as measured facts: mark ASSUMPTION_REQUIRED unless the user supplied a cited source. '
            'Keep rates between 0 and 1, existing product shares at or below 1, and explain the assumptions, population unit and how to validate them. '
            'Product Y is a hypothetical new product; do not make patient-specific medical claims. Return only the requested structured fields.',
            {'disease':disease,'region':region},ForecastSuggestion)
        _clean(result)
        output=result.model_dump();output['model']=meta.get('model','Vertex AI') if isinstance(meta,dict) else 'Vertex AI';return output
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error('Epidemiology suggestion failed: %s', type(exc).__name__)
        raise HTTPException(502, 'AI suggestions are unavailable. Your inputs have not been replaced. Ask the administrator to check the Vertex model, region and service-account access.') from exc

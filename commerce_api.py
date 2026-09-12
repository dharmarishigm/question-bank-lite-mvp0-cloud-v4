"""Public/student and admin commerce APIs."""
from __future__ import annotations
import json,time
from contextlib import closing
from pathlib import Path
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from platform_api import _auth,db,require_admin
from commerce_service import PRODUCT_TYPES,ENTITLEMENT_KINDS,audit,start_trial,redeem_grand_test
from admin_settings import get_setting

router=APIRouter(prefix="/api",tags=["Commerce"])

@router.get("/public/commerce-admin-page",include_in_schema=False)
def commerce_admin_page():return FileResponse(Path(__file__).parent/"static/commerce-admin.html",headers={"Cache-Control":"no-store"})

@router.get("/public/pricing-page",include_in_schema=False)
def pricing_page():return FileResponse(Path(__file__).parent/"static/pricing.html",headers={"Cache-Control":"no-store"})

@router.get("/public/commerce-config")
def public_commerce_config():
    with closing(db()) as conn:
        return {"commerce_enabled":bool(get_setting("commerce.enabled",conn=conn)),
                "demo_book":{"enabled":bool(get_setting("demo_book.enabled",conn=conn)),"title":get_setting("demo_book.title",conn=conn),"url":get_setting("demo_book.url",conn=conn)}}

class ProductInput(BaseModel):
    code:str=Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{2,63}$")
    name:str=Field(min_length=2,max_length=160)
    description:str=Field(default="",max_length=3000)
    product_type:str
    status:str="DRAFT"
    program_id:int|None=None
    grand_test_id:int|None=None
    entitlement_kind:str
    term_days:int|None=Field(default=None,ge=1,le=3650)
    credit_quantity:int|None=Field(default=None,ge=1,le=1000)
    inclusion_rules:dict=Field(default_factory=dict)
    display_metadata:dict=Field(default_factory=dict)

def validate_product(body):
    if body.product_type not in PRODUCT_TYPES:raise HTTPException(422,"Invalid product type")
    if body.entitlement_kind not in ENTITLEMENT_KINDS:raise HTTPException(422,"Invalid entitlement kind")
    if body.status not in {"DRAFT","ACTIVE","ARCHIVED"}:raise HTTPException(422,"Invalid product status")
    if body.product_type.startswith("PROGRAM_") and body.program_id is None:raise HTTPException(422,"Program product requires program_id")
    if body.product_type=="GRAND_TEST_SINGLE" and body.grand_test_id is None:raise HTTPException(422,"Single test product requires grand_test_id")
    if body.product_type=="GRAND_TEST_CREDIT_PACK" and not body.credit_quantity:raise HTTPException(422,"Credit pack requires credit_quantity")

@router.get("/catalog")
def catalog(program_id:int|None=None):
    now=time.time();params=[now,now];where="p.status='ACTIVE' AND pr.status='ACTIVE' AND pr.valid_from<=? AND (pr.valid_until IS NULL OR pr.valid_until>?)"
    if program_id is not None:where+=" AND (p.program_id=? OR p.program_id IS NULL)";params.append(program_id)
    with closing(db()) as conn:
        rows=conn.execute("SELECT p.*,pr.id price_id,pr.currency,pr.list_amount_minor,pr.sale_amount_minor,pr.tax_behavior,pr.tax_rate_bps FROM products p JOIN prices pr ON pr.product_id=p.id WHERE "+where+" ORDER BY p.product_type,p.id,pr.version DESC",params).fetchall()
    seen=set();items=[]
    for row in rows:
        if row["id"] in seen:continue
        seen.add(row["id"]);item=dict(row);item["inclusion_rules"]=json.loads(item.pop("inclusion_rules_json"));item["display_metadata"]=json.loads(item.pop("display_metadata_json"));items.append(item)
    return {"items":items}

@router.get("/me/entitlements")
def entitlements(request:Request):
    user=_auth(request);now=time.time()
    with closing(db()) as conn:
        items=conn.execute("SELECT * FROM entitlements WHERE user_id=? ORDER BY created_at DESC",(user["id"],)).fetchall()
        wallets=conn.execute("SELECT * FROM grand_test_credit_wallets WHERE user_id=? ORDER BY created_at DESC",(user["id"],)).fetchall()
    return {"items":[dict(x) for x in items],"grand_test_wallets":[dict(x) for x in wallets],"as_of":now}

@router.post("/trials",status_code=201)
async def create_trial(request:Request):
    user=_auth(request,True);body=await request.json();program_id=int(body.get("program_id") or 0)
    if not program_id:raise HTTPException(422,"program_id is required")
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE");result=start_trial(conn,user["id"],program_id);conn.commit()
    return result

@router.post("/grand-tests/{grand_test_id}/redeem",status_code=201)
async def redeem(grand_test_id:int,request:Request):
    user=_auth(request,True);body=await request.json();program_id=body.get("program_id")
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE");result=redeem_grand_test(conn,user["id"],grand_test_id,int(program_id) if program_id else None);conn.commit()
    return result

@router.get("/admin/products")
def admin_products(request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn:rows=conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return {"items":[dict(x) for x in rows]}

@router.post("/admin/products",status_code=201)
def create_product(body:ProductInput,request:Request):
    admin=require_admin(_auth(request,True));validate_product(body);now=time.time()
    with closing(db()) as conn:
        cur=conn.execute("INSERT INTO products(code,name,description,product_type,status,program_id,grand_test_id,entitlement_kind,term_days,credit_quantity,inclusion_rules_json,display_metadata_json,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (body.code,body.name,body.description,body.product_type,body.status,body.program_id,body.grand_test_id,body.entitlement_kind,body.term_days,body.credit_quantity,json.dumps(body.inclusion_rules),json.dumps(body.display_metadata),admin["id"],admin["id"],now,now))
        audit(conn,"PRODUCT_CREATED","PRODUCT",cur.lastrowid,actor=admin["id"],metadata={"code":body.code});conn.commit();row=conn.execute("SELECT * FROM products WHERE id=?",(cur.lastrowid,)).fetchone()
    return dict(row)

class PriceInput(BaseModel):
    currency:str=Field(default="INR",pattern=r"^[A-Z]{3}$")
    list_amount_minor:int=Field(ge=0,le=1000000000)
    sale_amount_minor:int=Field(ge=0,le=1000000000)
    tax_behavior:str="INCLUSIVE"
    tax_rate_bps:int=Field(default=0,ge=0,le=10000)
    valid_from:float|None=None
    valid_until:float|None=None
    status:str="DRAFT"

@router.post("/admin/products/{product_id}/prices",status_code=201)
def create_price(product_id:int,body:PriceInput,request:Request):
    admin=require_admin(_auth(request,True));now=time.time()
    if body.sale_amount_minor>body.list_amount_minor:raise HTTPException(422,"Sale amount cannot exceed list amount")
    if body.status not in {"DRAFT","ACTIVE","RETIRED"}:raise HTTPException(422,"Invalid price status")
    if body.tax_behavior not in {"INCLUSIVE","EXCLUSIVE"}:raise HTTPException(422,"Invalid tax behavior")
    with closing(db()) as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?",(product_id,)).fetchone():raise HTTPException(404,"Product not found")
        version=conn.execute("SELECT COALESCE(MAX(version),0)+1 n FROM prices WHERE product_id=?",(product_id,)).fetchone()["n"]
        if body.status=="ACTIVE":conn.execute("UPDATE prices SET status='RETIRED' WHERE product_id=? AND status='ACTIVE'",(product_id,))
        cur=conn.execute("INSERT INTO prices(product_id,version,currency,list_amount_minor,sale_amount_minor,tax_behavior,tax_rate_bps,valid_from,valid_until,status,created_by,approved_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (product_id,version,body.currency,body.list_amount_minor,body.sale_amount_minor,body.tax_behavior,body.tax_rate_bps,body.valid_from or now,body.valid_until,body.status,admin["id"],admin["id"] if body.status=="ACTIVE" else None,now))
        audit(conn,"PRICE_CREATED","PRICE",cur.lastrowid,actor=admin["id"],metadata={"product_id":product_id,"version":version});conn.commit();row=conn.execute("SELECT * FROM prices WHERE id=?",(cur.lastrowid,)).fetchone()
    return dict(row)

class DiscountInput(BaseModel):
    code:str=Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{2,31}$")
    name:str=Field(min_length=2,max_length=120)
    kind:str
    value:int=Field(gt=0)
    starts_at:float|None=None
    ends_at:float|None=None
    status:str="DRAFT"
    max_redemptions:int|None=Field(default=None,ge=1)
    max_per_user:int=Field(default=1,ge=1,le=100)
    minimum_amount_minor:int=Field(default=0,ge=0)
    first_purchase_only:bool=False
    product_rules:dict=Field(default_factory=dict)
    program_rules:dict=Field(default_factory=dict)

@router.post("/admin/discounts",status_code=201)
def create_discount(body:DiscountInput,request:Request):
    admin=require_admin(_auth(request,True));now=time.time()
    if body.kind not in {"FIXED_MINOR","PERCENT_BPS"}:raise HTTPException(422,"Invalid discount kind")
    if body.kind=="PERCENT_BPS" and body.value>10000:raise HTTPException(422,"Percentage discount cannot exceed 100%")
    if body.status not in {"DRAFT","ACTIVE","PAUSED","EXPIRED"}:raise HTTPException(422,"Invalid discount status")
    if body.ends_at and body.ends_at<=(body.starts_at or now):raise HTTPException(422,"Discount end must follow its start")
    with closing(db()) as conn:
        cur=conn.execute("INSERT INTO discounts(code,name,kind,value,starts_at,ends_at,status,max_redemptions,max_per_user,minimum_amount_minor,first_purchase_only,product_rules_json,program_rules_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(body.code,body.name,body.kind,body.value,body.starts_at or now,body.ends_at,body.status,body.max_redemptions,body.max_per_user,body.minimum_amount_minor,int(body.first_purchase_only),json.dumps(body.product_rules),json.dumps(body.program_rules),admin["id"],now,now))
        audit(conn,"DISCOUNT_CREATED","DISCOUNT",cur.lastrowid,actor=admin["id"],metadata={"code":body.code});conn.commit();row=conn.execute("SELECT * FROM discounts WHERE id=?",(cur.lastrowid,)).fetchone()
    return dict(row)

@router.get("/admin/discounts")
def admin_discounts(request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn:rows=conn.execute("SELECT * FROM discounts ORDER BY created_at DESC").fetchall()
    return {"items":[dict(x) for x in rows]}

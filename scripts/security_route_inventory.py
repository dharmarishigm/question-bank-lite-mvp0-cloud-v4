"""Static route inventory. Handler hints are not proof of authorization coverage."""
import ast,csv,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from security_boundary import public,quota_group
root=pathlib.Path(__file__).resolve().parents[1]
rows=[]
for file in root.glob('*.py'):
 tree=ast.parse(file.read_text());prefixes={}
 for node in tree.body:
  if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and getattr(node.value.func,'id','')=='APIRouter':
   prefix=next((ast.literal_eval(k.value) for k in node.value.keywords if k.arg=='prefix'),'')
   for target in node.targets:
    if isinstance(target,ast.Name):prefixes[target.id]=prefix
 for node in tree.body:
  if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  code=ast.get_source_segment(file.read_text(),node)
  for decorator in node.decorator_list:
   if not isinstance(decorator,ast.Call) or not isinstance(decorator.func,ast.Attribute) or decorator.func.attr not in {'get','post','put','patch','delete','head','options'} or not decorator.args:continue
   path=prefixes.get(getattr(decorator.func.value,'id',''),'')+ast.literal_eval(decorator.args[0]);method=decorator.func.attr.upper()
   if not path.startswith('/api/'):continue
   group,limit=quota_group(method,path)
   rows.append({'method':method,'path':path,'boundary':'public allowlist' if public(method,path) else 'session + CSRF for writes','rate_group':group,'user_rpm':limit,'handler_hint':';'.join(x for x in ('require_admin','_auth','actor','workspace','_session') if x in code),'source':str(file.relative_to(root))+':'+str(node.lineno),'review':'handler ownership review required'})
out=root/'docs'/'SECURITY_API_INVENTORY.csv'
with out.open('w',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(sorted(rows,key=lambda r:(r['path'],r['method'])))
print(f'{len(rows)} routes inventoried: {out.name}')

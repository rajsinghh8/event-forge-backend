"""Live Oracle-backed EventForge Bottle API."""
from __future__ import annotations
import json, os, re, uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any
from bottle import Bottle, HTTPResponse, request, response, run
from .database import database_from_environment, oracledb
from .security import JwtCodec, PasswordHasher

EMAIL=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$'); TASK={'TODO','IN_PROGRESS','BLOCKED','COMPLETED'}; RSVP={'PENDING','ACCEPTED','DECLINED','MAYBE'}
def now(): return datetime.now(timezone.utc).isoformat()
def fail(status,code,message,details=None): raise ApiError(status,code,message,details)
class ApiError(Exception):
 def __init__(self,status,code,message,details=None): self.status,self.code,self.message,self.details=status,code,message,details
def payload():
 if not isinstance(request.json,dict): fail(400,'INVALID_JSON','Request body must be a JSON object')
 return request.json
def text(d,k):
 v=d.get(k)
 if not isinstance(v,str) or not v.strip(): fail(422,'VALIDATION_ERROR',f'{k} is required')
 return v.strip()
def money(v,k,positive=False):
 try: n=Decimal(str(v))
 except (InvalidOperation,ValueError): fail(422,'VALIDATION_ERROR',f'{k} must be a decimal')
 if n<0 or positive and n<=0: fail(422,'VALIDATION_ERROR',f'{k} must be {"positive" if positive else "nonnegative"}')
 return n.quantize(Decimal('.01'))
def date(v,k):
 if not isinstance(v,str): fail(422,'VALIDATION_ERROR',f'{k} must be ISO-8601')
 try: return datetime.fromisoformat(v.replace('Z','+00:00'))
 except ValueError: fail(422,'VALIDATION_ERROR',f'{k} must be ISO-8601')
def out(v):
 if isinstance(v,datetime): return v.isoformat()
 if isinstance(v,Decimal): return format(v,'.2f')
 if hasattr(v,'read'): return v.read()
 return v

def openapi():
 """Hand-maintained contract; all live operations are listed below."""
 schemas={'Error':{'type':'object','properties':{'error':{'type':'object'}}},'Auth':{'type':'object','required':['email','password','display_name'],'properties':{'email':{'type':'string','format':'email'},'password':{'type':'string','minLength':8},'display_name':{'type':'string'}}},'Event':{'type':'object','required':['name','event_datetime'],'properties':{'name':{'type':'string'},'event_datetime':{'type':'string','format':'date-time'},'capacity':{'type':'integer'},'budget_limit':{'type':'number'}}}}
 paths={}
 def add(path,methods,body=None,params=[]):
  paths[path]={m:{'summary':m+' '+path,'security':[] if path.startswith('/api/auth') else [{'bearerAuth':[]}],'parameters':params,'requestBody':{'required':True,'content':{'application/json':{'schema':body or {'type':'object'}}}} if body else None,'responses':{'200':{'description':'Success'},'201':{'description':'Created'},'204':{'description':'Deleted'},'401':{'description':'Authentication required'},'404':{'description':'Not found'},'409':{'description':'Conflict'},'422':{'description':'Validation error'}}} for m in methods}
 for x in paths.values():
  for op in x.values():
   if op['requestBody'] is None: del op['requestBody']
 add('/api/auth/register',['post'],{'$ref':'#/components/schemas/Auth'}); add('/api/auth/login',['post'],{'type':'object','required':['email','password'],'properties':{'email':{'type':'string'},'password':{'type':'string'}}})
 add('/api/events',['get','post'],{'$ref':'#/components/schemas/Event'}); add('/api/events/{event_id}',['get','put','delete'],{'$ref':'#/components/schemas/Event'})
 specs={'tasks':{'title':'string','dependency_ids':'integer[]','status':'TODO|IN_PROGRESS|BLOCKED|COMPLETED'},'invitations':{'guest_name':'string','guest_email':'email','status':'PENDING|ACCEPTED|DECLINED|MAYBE'},'budget-categories':{'name':'string','planned_amount':'number'},'expenses':{'category_id':'integer','description':'string','amount':'number','expenditure_at':'date-time'},'schedule':{'title':'string','start_time':'date-time','end_time':'date-time'},'vendors':{'name':'string','service_type':'string','contact_name':'string','contact_email':'email','booking_reference':'string','cost':'number'}}
 for resource,fields in specs.items():
  add('/api/events/{event_id}/'+resource,['get','post'],{'type':'object','properties':{k:{'type':'string','description':v} for k,v in fields.items()}})
  add('/api/events/{event_id}/'+resource+'/{id}',['get','put','delete'],{'type':'object','properties':{k:{'type':'string','description':v} for k,v in fields.items()}})
 add('/api/events/{event_id}/vendors/{id}/payments',['post'],{'type':'object','required':['amount'],'properties':{'amount':{'type':'number'},'payment_at':{'type':'string','format':'date-time'},'note':{'type':'string'}}})
 add('/api/events/{event_id}/notifications',['get']); add('/api/events/{event_id}/notifications/{id}',['patch'],{'type':'object','properties':{'is_read':{'type':'boolean'}}}); add('/api/events/{event_id}/activity',['get'])
 return {'openapi':'3.0.3','info':{'title':'EventForge API','version':'1.0.0'},'paths':paths,'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'JWT'}},'schemas':schemas}}

def create_app():
 db=database_from_environment(); db.bootstrap()  # fail fast: no memory fallback exists
 app=Bottle(); codec=JwtCodec(os.getenv('JWT_SECRET','development-only-change-me'),ttl_seconds=int(os.getenv('JWT_EXPIRY_SECONDS','3600'))); hashes=PasswordHasher()
 def rows(cur):
  names=[d[0].lower() for d in cur.description or []]
  return [{n:out(v) for n,v in zip(names,row)} for row in cur.fetchall()]
 def one(cur):
  r=rows(cur); return r[0] if r else None
 def execute(cur,sql,bind={}): cur.execute(sql,bind); return cur
 def insert(cur,sql,bind):
  var=cur.var(oracledb.NUMBER); bind=dict(bind,id=var); cur.execute(sql+' RETURNING id INTO :id',bind); return int(var.getvalue()[0])
 def auth():
  h=request.headers.get('Authorization','')
  if not h.startswith('Bearer '): fail(401,'AUTHENTICATION_REQUIRED','Bearer token required')
  try:return int(codec.validate(h[7:]).subject)
  except Exception: fail(401,'INVALID_TOKEN','Token is invalid or expired')
 def owned(cur,eid,uid,lock=False):
  q='SELECT * FROM eventforge_events WHERE id=:eid AND owner_id=:uid'+(' FOR UPDATE' if lock else '')
  ev=one(execute(cur,q,{'eid':eid,'uid':uid}))
  if not ev: fail(404,'NOT_FOUND','Event not found')
  return ev
 def record(cur,eid,uid,action,details=None):
  insert(cur,'INSERT INTO eventforge_activity (event_id,actor_user_id,action,details) VALUES (:eid,:uid,:action,:details)',{'eid':eid,'uid':uid,'action':action,'details':json.dumps(details or {})})
 def notify(cur,eid,typ,msg): insert(cur,'INSERT INTO eventforge_notifications (event_id,notification_type,message) VALUES (:eid,:typ,:msg)',{'eid':eid,'typ':typ,'msg':msg})
 def getresource(cur,table,eid,rid):
  r=one(execute(cur,f'SELECT * FROM {table} WHERE id=:id AND event_id=:eid',{'id':rid,'eid':eid}))
  if not r: fail(404,'NOT_FOUND','Resource not found')
  return r
 def guarded(fn):
  @wraps(fn)
  def wrapped(*a,**kw):
   try:return fn(*a,**kw)
   except ApiError as e:return HTTPResponse(status=e.status,body=json.dumps({'error':{'code':e.code,'message':e.message,'details':e.details,'timestamp':now(),'correlation_id':request.environ.get('cid','')}}),headers={'Content-Type':'application/json'})
  return wrapped
 @app.hook('before_request')
 def before(): request.environ['cid']=request.headers.get('X-Correlation-ID') or str(uuid.uuid4())
 @app.hook('after_request')
 def after(): response.headers['X-Correlation-ID']=request.environ['cid']; response.content_type='application/json'
 @app.error(404)
 def missing(_): return {'error':{'code':'NOT_FOUND','message':'Route not found','timestamp':now()}}
 @app.get('/health')
 def health(): return {'status':'ok','time':now()}
 @app.get('/openapi.json')
 def spec(): return openapi()
 @app.get('/docs')
 def docs(): response.content_type='text/html'; return '<!doctype html><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui"})</script>'
 @app.post('/api/auth/register')
 @guarded
 def register():
  d=payload(); email=text(d,'email').lower(); password=text(d,'password'); name=text(d,'display_name')
  if not EMAIL.match(email) or len(password)<8: fail(422,'VALIDATION_ERROR','Invalid registration fields')
  try:
   with db.transaction() as con:
    cur=con.cursor(); uid=insert(cur,'INSERT INTO eventforge_users (email,password_hash,display_name) VALUES (:email,:password,:name)',{'email':email,'password':hashes.hash(password),'name':name}); user=one(execute(cur,'SELECT id,email,display_name,created_at FROM eventforge_users WHERE id=:id',{'id':uid}))
  except Exception as e:
   if getattr(getattr(e,'args',[None])[0],'code',None)==1: fail(409,'EMAIL_EXISTS','Email is already registered')
   raise
  response.status=201; return {'user':user,'token':codec.issue(str(uid))}
 @app.post('/api/auth/login')
 @guarded
 def login():
  d=payload()
  with db.transaction() as con:
   cur=con.cursor(); u=one(execute(cur,'SELECT * FROM eventforge_users WHERE email=:email',{'email':text(d,'email').lower()}))
  if not u or not hashes.verify(text(d,'password'),u['password_hash']): fail(401,'INVALID_CREDENTIALS','Invalid email or password')
  return {'user':{k:u[k] for k in ('id','email','display_name','created_at')},'token':codec.issue(str(u['id']))}
 def listing(cur,sql,bind):
  try: p=max(1,int(request.query.get('page','1'))); size=min(100,max(1,int(request.query.get('page_size','20'))))
  except ValueError: fail(422,'VALIDATION_ERROR','page and page_size must be integers')
  allrows=rows(execute(cur,sql,bind)); return {'items':allrows[(p-1)*size:p*size],'total':len(allrows),'page':p,'page_size':size}
 @app.route('/api/events',method=['GET','POST'])
 @guarded
 def events():
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor()
   if request.method=='GET': return listing(cur,'SELECT * FROM eventforge_events WHERE owner_id=:uid ORDER BY id',{'uid':uid})
   d=payload(); dt=date(text(d,'event_datetime'),'event_datetime'); cap=d.get('capacity')
   if cap is not None and (type(cap) is not int or cap<1): fail(422,'VALIDATION_ERROR','capacity must be a positive integer')
   eid=insert(cur,'INSERT INTO eventforge_events (owner_id,name,event_datetime,venue,capacity,budget_limit,status,description) VALUES (:uid,:name,:dt,:venue,:cap,:budget,:status,:descr)',{'uid':uid,'name':text(d,'name'),'dt':dt,'venue':d.get('venue'),'cap':cap,'budget':money(d.get('budget_limit',0),'budget_limit'),'status':d.get('status','DRAFT'),'descr':d.get('description')}); record(cur,eid,uid,'EVENT_CREATED'); response.status=201; return getresource_event(cur,eid,uid)
 def getresource_event(cur,eid,uid): return owned(cur,eid,uid)
 @app.route('/api/events/<eid:int>',method=['GET','PUT','DELETE'])
 @guarded
 def event_route(eid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); ev=owned(cur,eid,uid)
   if request.method=='GET':
    totals=one(execute(cur,'SELECT NVL((SELECT SUM(planned_amount) FROM eventforge_categories WHERE event_id=:eid),0) planned, NVL((SELECT SUM(amount) FROM eventforge_expenses WHERE event_id=:eid),0) actual FROM dual',{'eid':eid})); return dict(ev,planned_budget=totals['planned'],actual_spending=totals['actual'],remaining_budget=format(Decimal(str(ev['budget_limit']))-Decimal(str(totals['actual'])),'.2f'))
   if request.method=='DELETE': execute(cur,'DELETE FROM eventforge_events WHERE id=:eid AND owner_id=:uid',{'eid':eid,'uid':uid}); response.status=204; return ''
   d=payload(); sets=[]; b={'eid':eid,'uid':uid}; allowed=('name','venue','capacity','status','description')
   for k in allowed:
    if k in d: sets.append(k+'=:'+k); b[k]=d[k]
   if 'event_datetime' in d: sets.append('event_datetime=:event_datetime'); b['event_datetime']=date(d['event_datetime'],'event_datetime')
   if 'budget_limit' in d: sets.append('budget_limit=:budget_limit'); b['budget_limit']=money(d['budget_limit'],'budget_limit')
   if not sets: fail(422,'VALIDATION_ERROR','No mutable fields supplied')
   execute(cur,'UPDATE eventforge_events SET '+','.join(sets)+' WHERE id=:eid AND owner_id=:uid',b); record(cur,eid,uid,'EVENT_UPDATED'); return owned(cur,eid,uid)
 # Tasks, including dependency graph validation in the same transaction.
 def dependencies(cur,eid,task_id,ids):
  if not isinstance(ids,list) or any(type(x) is not int for x in ids): fail(422,'VALIDATION_ERROR','dependency_ids must be an array of integers')
  if task_id in ids: fail(422,'TASK_SELF_DEPENDENCY','A task cannot depend on itself')
  for dep in ids:
   if not getresource(cur,'eventforge_tasks',eid,dep): pass
  # New edges task -> dep must not reach task through existing dependency edges.
  for dep in ids:
   todo=[dep]; seen=set()
   while todo:
    x=todo.pop()
    if x==task_id: fail(409,'TASK_DEPENDENCY_CYCLE','Task dependency would create a cycle')
    if x not in seen:
     seen.add(x); todo += [r['dependency_id'] for r in rows(execute(cur,'SELECT dependency_id FROM eventforge_task_dependencies WHERE task_id=:id',{'id':x}))]
 @app.route('/api/events/<eid:int>/tasks',method=['GET','POST'])
 @guarded
 def tasks(eid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid)
   if request.method=='GET': return listing(cur,'SELECT t.*, (SELECT LISTAGG(dependency_id,\',\') WITHIN GROUP (ORDER BY dependency_id) FROM eventforge_task_dependencies d WHERE d.task_id=t.id) dependency_ids FROM eventforge_tasks t WHERE event_id=:eid ORDER BY id',{'eid':eid})
   d=payload(); status=d.get('status','TODO')
   if status not in TASK: fail(422,'VALIDATION_ERROR','Invalid task status')
   tid=insert(cur,'INSERT INTO eventforge_tasks (event_id,title,description,status,deadline) VALUES (:eid,:title,:descr,:status,:deadline)',{'eid':eid,'title':text(d,'title'),'descr':d.get('description'),'status':status,'deadline':date(d['deadline'],'deadline') if d.get('deadline') else None}); dependencies(cur,eid,tid,d.get('dependency_ids',[]))
   for dep in d.get('dependency_ids',[]): execute(cur,'INSERT INTO eventforge_task_dependencies (task_id,dependency_id) VALUES (:id,:dep)',{'id':tid,'dep':dep})
   if d.get('deadline') and date(d['deadline'],'deadline') < datetime.now(timezone.utc): notify(cur,eid,'overdue-task','A task has an overdue deadline')
   record(cur,eid,uid,'TASK_CREATED'); response.status=201; return getresource(cur,'eventforge_tasks',eid,tid)
 @app.route('/api/events/<eid:int>/tasks/<tid:int>',method=['GET','PUT','DELETE'])
 @guarded
 def task(eid,tid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid); old=getresource(cur,'eventforge_tasks',eid,tid)
   if request.method=='GET': return old
   if request.method=='DELETE': execute(cur,'DELETE FROM eventforge_task_dependencies WHERE task_id=:id OR dependency_id=:id',{'id':tid}); execute(cur,'DELETE FROM eventforge_tasks WHERE id=:id AND event_id=:eid',{'id':tid,'eid':eid}); response.status=204; return ''
   d=payload(); status=d.get('status',old['status'])
   if status not in TASK: fail(422,'VALIDATION_ERROR','Invalid task status')
   if status=='COMPLETED':
    incomplete=one(execute(cur,"SELECT 1 ok FROM eventforge_task_dependencies d JOIN eventforge_tasks t ON t.id=d.dependency_id WHERE d.task_id=:id AND t.status<>'COMPLETED' FETCH FIRST 1 ROWS ONLY",{'id':tid}))
    if incomplete: fail(409,'TASK_PREREQUISITES_INCOMPLETE','All prerequisite tasks must be completed')
   if 'dependency_ids' in d:
    dependencies(cur,eid,tid,d['dependency_ids']); execute(cur,'DELETE FROM eventforge_task_dependencies WHERE task_id=:id',{'id':tid})
    for dep in d['dependency_ids']: execute(cur,'INSERT INTO eventforge_task_dependencies (task_id,dependency_id) VALUES (:id,:dep)',{'id':tid,'dep':dep})
   execute(cur,'UPDATE eventforge_tasks SET title=:title,description=:descr,status=:status,deadline=:deadline WHERE id=:id AND event_id=:eid',{'title':d.get('title',old['title']),'descr':d.get('description',old['description']),'status':status,'deadline':date(d['deadline'],'deadline') if 'deadline' in d and d['deadline'] else old['deadline'],'id':tid,'eid':eid}); record(cur,eid,uid,'TASK_UPDATED'); return getresource(cur,'eventforge_tasks',eid,tid)
 # Generic small resource handlers retain event/owner predicates for each operation.
 def simple_routes(path,table,required_fields,amount_field=None):
  @app.route('/api/events/<eid:int>/'+path,method=['GET','POST'])
  @guarded
  def collection(eid):
   uid=auth()
   with db.transaction() as con:
    cur=con.cursor(); owned(cur,eid,uid)
    if request.method=='GET': return listing(cur,'SELECT * FROM '+table+' WHERE event_id=:eid ORDER BY id',{'eid':eid})
    d=payload(); vals={k:text(d,k) for k in required_fields}; vals['eid']=eid
    if amount_field: vals[amount_field]=money(d.get(amount_field,0),amount_field)
    cols=['event_id']+list(required_fields)+([amount_field] if amount_field else []); binds=[':eid']+[':'+k for k in required_fields]+([':'+amount_field] if amount_field else [])
    rid=insert(cur,'INSERT INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join(binds)+')',vals); record(cur,eid,uid,path.upper()+'_CREATED'); response.status=201; return getresource(cur,table,eid,rid)
  @app.route('/api/events/<eid:int>/'+path+'/<rid:int>',method=['GET','PUT','DELETE'])
  @guarded
  def item(eid,rid):
   uid=auth()
   with db.transaction() as con:
    cur=con.cursor(); owned(cur,eid,uid); old=getresource(cur,table,eid,rid)
    if request.method=='GET': return old
    if request.method=='DELETE':
     if table=='eventforge_vendors' and one(execute(cur,'SELECT id FROM eventforge_payments WHERE vendor_id=:id AND event_id=:eid FETCH FIRST 1 ROWS ONLY',{'id':rid,'eid':eid})): fail(409,'VENDOR_HAS_PAYMENTS','Vendor cannot be deleted while payments exist')
     execute(cur,'DELETE FROM '+table+' WHERE id=:id AND event_id=:eid',{'id':rid,'eid':eid}); response.status=204; return ''
    d=payload(); b={'id':rid,'eid':eid}; sets=[]
    for k in required_fields:
     if k in d: sets.append(k+'=:'+k); b[k]=text(d,k)
    if amount_field and amount_field in d: sets.append(amount_field+'=:'+amount_field); b[amount_field]=money(d[amount_field],amount_field)
    if not sets: fail(422,'VALIDATION_ERROR','No mutable fields supplied')
    execute(cur,'UPDATE '+table+' SET '+','.join(sets)+' WHERE id=:id AND event_id=:eid',b); record(cur,eid,uid,path.upper()+'_UPDATED'); return getresource(cur,table,eid,rid)
 simple_routes('budget-categories','eventforge_categories',('name',),'planned_amount')
 # Invitations lock the event counter and update RSVP/capacity atomically.
 @app.route('/api/events/<eid:int>/invitations',method=['GET','POST'])
 @guarded
 def invitations(eid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); ev=owned(cur,eid,uid,request.method=='POST')
   if request.method=='GET': return listing(cur,'SELECT * FROM eventforge_invitations WHERE event_id=:eid ORDER BY id',{'eid':eid})
   d=payload(); status=d.get('status','PENDING')
   if status not in RSVP: fail(422,'VALIDATION_ERROR','Invalid invitation status')
   if status=='ACCEPTED' and ev['capacity'] is not None and ev['confirmed_guest_count']>=ev['capacity']: fail(409,'CAPACITY_FULL','Event capacity is full')
   rid=insert(cur,'INSERT INTO eventforge_invitations (event_id,guest_name,guest_email,status) VALUES (:eid,:name,:email,:status)',{'eid':eid,'name':text(d,'guest_name'),'email':text(d,'guest_email'),'status':status})
   if status=='ACCEPTED': execute(cur,'UPDATE eventforge_events SET confirmed_guest_count=confirmed_guest_count+1 WHERE id=:eid',{'eid':eid})
   notify(cur,eid,'invitation','Invitation created'); record(cur,eid,uid,'INVITATION_CREATED'); response.status=201; return getresource(cur,'eventforge_invitations',eid,rid)
 @app.route('/api/events/<eid:int>/invitations/<rid:int>',method=['GET','PUT','DELETE'])
 @guarded
 def invitation(eid,rid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); ev=owned(cur,eid,uid,True); old=getresource(cur,'eventforge_invitations',eid,rid)
   if request.method=='GET': return old
   if request.method=='DELETE':
    if old['status']=='ACCEPTED': execute(cur,'UPDATE eventforge_events SET confirmed_guest_count=confirmed_guest_count-1 WHERE id=:eid',{'eid':eid})
    execute(cur,'DELETE FROM eventforge_invitations WHERE id=:id AND event_id=:eid',{'id':rid,'eid':eid}); response.status=204; return ''
   d=payload(); status=d.get('status',old['status'])
   if status not in RSVP: fail(422,'VALIDATION_ERROR','Invalid invitation status')
   delta=int(status=='ACCEPTED')-int(old['status']=='ACCEPTED')
   if delta and ev['capacity'] is not None and ev['confirmed_guest_count']>=ev['capacity']: fail(409,'CAPACITY_FULL','Event capacity is full')
   execute(cur,'UPDATE eventforge_invitations SET guest_name=:name,guest_email=:email,status=:status WHERE id=:id AND event_id=:eid',{'name':d.get('guest_name',old['guest_name']),'email':d.get('guest_email',old['guest_email']),'status':status,'id':rid,'eid':eid})
   if delta: execute(cur,'UPDATE eventforge_events SET confirmed_guest_count=confirmed_guest_count+:delta WHERE id=:eid',{'delta':delta,'eid':eid})
   notify(cur,eid,'invitation','Invitation RSVP updated'); record(cur,eid,uid,'INVITATION_UPDATED'); return getresource(cur,'eventforge_invitations',eid,rid)
 @app.route('/api/events/<eid:int>/expenses',method=['GET','POST'])
 @guarded
 def expenses(eid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); ev=owned(cur,eid,uid)
   if request.method=='GET':
    result=listing(cur,'SELECT e.* FROM eventforge_expenses e WHERE event_id=:eid ORDER BY id',{'eid':eid}); actual=one(execute(cur,'SELECT NVL(SUM(amount),0) actual FROM eventforge_expenses WHERE event_id=:eid',{'eid':eid}))['actual']; result.update({'planned':ev['budget_limit'],'actual':actual,'remaining':format(Decimal(str(ev['budget_limit']))-Decimal(str(actual)),'.2f')}); return result
   d=payload(); cat=getresource(cur,'eventforge_categories',eid,d.get('category_id')) if type(d.get('category_id')) is int else fail(422,'VALIDATION_ERROR','category_id is required')
   amount=money(d.get('amount'),'amount',True); rid=insert(cur,'INSERT INTO eventforge_expenses (event_id,category_id,description,amount,expenditure_at) VALUES (:eid,:cat,:descr,:amount,:at)',{'eid':eid,'cat':cat['id'],'descr':text(d,'description'),'amount':amount,'at':date(d['expenditure_at'],'expenditure_at') if d.get('expenditure_at') else datetime.now(timezone.utc)})
   actual=one(execute(cur,'SELECT SUM(amount) actual FROM eventforge_expenses WHERE event_id=:eid',{'eid':eid}))['actual']
   if Decimal(str(actual))>Decimal(str(ev['budget_limit'])): notify(cur,eid,'budget-warning','Event actual spending exceeds budget limit')
   record(cur,eid,uid,'EXPENSE_CREATED'); response.status=201; return getresource(cur,'eventforge_expenses',eid,rid)
 @app.route('/api/events/<eid:int>/expenses/<rid:int>',method=['GET','PUT','DELETE'])
 @guarded
 def expense(eid,rid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid); old=getresource(cur,'eventforge_expenses',eid,rid)
   if request.method=='GET': return old
   if request.method=='DELETE': execute(cur,'DELETE FROM eventforge_expenses WHERE id=:id AND event_id=:eid',{'id':rid,'eid':eid}); response.status=204; return ''
   d=payload(); catid=d.get('category_id',old['category_id']); getresource(cur,'eventforge_categories',eid,catid)
   execute(cur,'UPDATE eventforge_expenses SET category_id=:cat,description=:descr,amount=:amount,expenditure_at=:at WHERE id=:id AND event_id=:eid',{'cat':catid,'descr':d.get('description',old['description']),'amount':money(d.get('amount',old['amount']),'amount',True),'at':date(d['expenditure_at'],'expenditure_at') if 'expenditure_at' in d else old['expenditure_at'],'id':rid,'eid':eid}); record(cur,eid,uid,'EXPENSE_UPDATED'); return getresource(cur,'eventforge_expenses',eid,rid)
 def schedule_values(cur,eid,d,rid=None):
  start=date(text(d,'start_time'),'start_time'); end=date(text(d,'end_time'),'end_time')
  if start>=end: fail(422,'VALIDATION_ERROR','start_time must precede end_time')
  overlap=one(execute(cur,'SELECT id FROM eventforge_schedule WHERE event_id=:eid AND start_time < :end_at AND end_time > :start_at AND (:id IS NULL OR id<>:id) FETCH FIRST 1 ROWS ONLY',{'eid':eid,'start_at':start,'end_at':end,'id':rid}))
  if overlap: fail(409,'SCHEDULE_OVERLAP','Schedule intervals overlap')
  return start,end
 @app.route('/api/events/<eid:int>/schedule',method=['GET','POST'])
 @guarded
 def schedule(eid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid)
   if request.method=='GET':
    b={'eid':eid}; sql='SELECT * FROM eventforge_schedule WHERE event_id=:eid'
    if request.query.get('from'): sql+=' AND end_time>=:from_at'; b['from_at']=date(request.query.get('from'),'from')
    if request.query.get('to'): sql+=' AND start_time<=:to_at'; b['to_at']=date(request.query.get('to'),'to')
    return listing(cur,sql+' ORDER BY start_time',b)
   d=payload(); start,end=schedule_values(cur,eid,d); rid=insert(cur,'INSERT INTO eventforge_schedule (event_id,title,start_time,end_time,details) VALUES (:eid,:title,:start,:end,:details)',{'eid':eid,'title':text(d,'title'),'start':start,'end':end,'details':d.get('details')}); record(cur,eid,uid,'SCHEDULE_CREATED'); response.status=201; return getresource(cur,'eventforge_schedule',eid,rid)
 @app.route('/api/events/<eid:int>/schedule/<rid:int>',method=['GET','PUT','DELETE'])
 @guarded
 def schedule_item(eid,rid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid); old=getresource(cur,'eventforge_schedule',eid,rid)
   if request.method=='GET': return old
   if request.method=='DELETE': execute(cur,'DELETE FROM eventforge_schedule WHERE id=:id AND event_id=:eid',{'id':rid,'eid':eid}); response.status=204; return ''
   d=payload(); merged={'start_time':d.get('start_time',old['start_time']),'end_time':d.get('end_time',old['end_time'])}; start,end=schedule_values(cur,eid,merged,rid); execute(cur,'UPDATE eventforge_schedule SET title=:title,start_time=:start,end_time=:end,details=:details WHERE id=:id AND event_id=:eid',{'title':d.get('title',old['title']),'start':start,'end':end,'details':d.get('details',old['details']),'id':rid,'eid':eid}); return getresource(cur,'eventforge_schedule',eid,rid)
 # Vendor fields are intentionally explicit rather than accepting arbitrary booking data.
 simple_routes('vendors','eventforge_vendors',('name','service_type','contact_name','contact_email','booking_reference'),'cost')
 @app.post('/api/events/<eid:int>/vendors/<vid:int>/payments')
 @guarded
 def payment(eid,vid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid); vendor=getresource(cur,'eventforge_vendors',eid,vid); d=payload(); amount=money(d.get('amount'),'amount',True)
   if Decimal(str(vendor['paid_amount']))+amount>Decimal(str(vendor['cost'])): fail(409,'PAYMENT_EXCEEDS_COST','Payment exceeds vendor cost')
   rid=insert(cur,'INSERT INTO eventforge_payments (event_id,vendor_id,amount,payment_at,note) VALUES (:eid,:vid,:amount,:at,:note)',{'eid':eid,'vid':vid,'amount':amount,'at':date(d['payment_at'],'payment_at') if d.get('payment_at') else datetime.now(timezone.utc),'note':d.get('note')}); execute(cur,'UPDATE eventforge_vendors SET paid_amount=paid_amount+:amount WHERE id=:id AND event_id=:eid',{'amount':amount,'id':vid,'eid':eid}); record(cur,eid,uid,'VENDOR_PAYMENT_CREATED'); response.status=201; return getresource(cur,'eventforge_payments',eid,rid)
 @app.get('/api/events/<eid:int>/notifications')
 @guarded
 def notifications(eid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid); return listing(cur,'SELECT * FROM eventforge_notifications WHERE event_id=:eid ORDER BY id DESC',{'eid':eid})
 @app.patch('/api/events/<eid:int>/notifications/<rid:int>')
 @guarded
 def notification(eid,rid):
  uid=auth(); d=payload()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid); getresource(cur,'eventforge_notifications',eid,rid); execute(cur,'UPDATE eventforge_notifications SET is_read=:read WHERE id=:id AND event_id=:eid',{'read':1 if d.get('is_read',True) else 0,'id':rid,'eid':eid}); return getresource(cur,'eventforge_notifications',eid,rid)
 @app.get('/api/events/<eid:int>/activity')
 @guarded
 def activity(eid):
  uid=auth()
  with db.transaction() as con:
   cur=con.cursor(); owned(cur,eid,uid); return listing(cur,'SELECT * FROM eventforge_activity WHERE event_id=:eid ORDER BY id DESC',{'eid':eid})
 return app

app=create_app()
if __name__=='__main__': run(app,host='0.0.0.0',port=int(os.getenv('PORT','8000')),quiet=True)

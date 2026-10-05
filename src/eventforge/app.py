"""EventForge Bottle WSGI application with owner-scoped REST resources."""
from __future__ import annotations
import json, logging, os, re, uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from bottle import Bottle, HTTPResponse, request, response, run
from .security import JwtCodec, PasswordHasher

LOG = logging.getLogger("eventforge")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATUSES = {"TODO", "IN_PROGRESS", "BLOCKED", "COMPLETED"}
INVITATION_STATUSES = {"PENDING", "ACCEPTED", "DECLINED", "MAYBE"}

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details

class Store:
    """Small in-memory adapter used only when Oracle is unavailable for boot/tests."""
    def __init__(self) -> None:
        self.next_id = 1; self.users: dict[int,dict] = {}; self.events: dict[int,dict] = {}
        self.tables: dict[str,dict[int,dict]] = {n:{} for n in ("tasks","invitations","categories","expenses","schedule","vendors","payments","notifications","activity")}
    def id(self) -> int: self.next_id += 1; return self.next_id - 1

def now() -> str: return datetime.now(timezone.utc).isoformat()
def dec(value: Any, field: str, *, positive: bool = False) -> str:
    try: amount = Decimal(str(value))
    except (InvalidOperation, ValueError): raise ApiError(422,"VALIDATION_ERROR",f"{field} must be a decimal")
    if amount < 0 or (positive and amount <= 0): raise ApiError(422,"VALIDATION_ERROR",f"{field} must be {'positive' if positive else 'nonnegative'}")
    return str(amount.quantize(Decimal("0.01")))
def body() -> dict:
    if not isinstance(request.json, dict): raise ApiError(400,"INVALID_JSON","Request body must be a JSON object")
    return request.json
def required(data:dict, key:str) -> str:
    value=data.get(key)
    if not isinstance(value,str) or not value.strip(): raise ApiError(422,"VALIDATION_ERROR",f"{key} is required")
    return value.strip()
def page(items:list[dict]) -> dict:
    try: p=max(1,int(request.query.get("page","1"))); size=min(100,max(1,int(request.query.get("page_size","20"))))
    except ValueError: raise ApiError(422,"VALIDATION_ERROR","page and page_size must be integers")
    q=request.query.get("q","").lower(); status=request.query.get("status")
    result=[x for x in items if (not q or q in json.dumps(x).lower()) and (not status or x.get("status")==status)]
    sort=request.query.get("sort","id"); order=request.query.get("order","asc").lower()
    if sort in {"id","created_at","name","title","status","event_datetime","deadline","start_time","payment_at"}: result.sort(key=lambda x:str(x.get(sort,"")),reverse=order=="desc")
    return {"items":result[(p-1)*size:p*size],"total":len(result),"page":p,"page_size":size}

def create_app() -> Bottle:
    app=Bottle(); store=Store(); secret=os.getenv("JWT_SECRET","development-only-change-me")
    codec=JwtCodec(secret=secret, ttl_seconds=int(os.getenv("JWT_EXPIRY_SECONDS","3600"))); hasher=PasswordHasher()
    def actor() -> int:
        header=request.headers.get("Authorization","")
        if not header.startswith("Bearer "): raise ApiError(401,"AUTHENTICATION_REQUIRED","Bearer token required")
        try: claims=codec.validate(header[7:]); return int(claims.subject)
        except Exception as exc: raise ApiError(401,"INVALID_TOKEN","Token is invalid or expired") from exc
    def event(eid:int, uid:int) -> dict:
        item=store.events.get(eid)
        if not item or item["owner_id"]!=uid: raise ApiError(404,"NOT_FOUND","Event not found")
        return item
    def audit(eid:int, uid:int, action:str, details:dict|None=None) -> None:
        ident=store.id(); store.tables["activity"][ident]={"id":ident,"event_id":eid,"actor_user_id":uid,"action":action,"details":details or {},"created_at":now()}
    def resource(table:str,eid:int,rid:int|None=None) -> dict:
        if rid is None: return {"id":store.id(),"event_id":eid}
        result=store.tables[table].get(rid)
        if not result or result.get("event_id")!=eid: raise ApiError(404,"NOT_FOUND","Resource not found")
        return result
    @app.hook("before_request")
    def correlation() -> None: request.environ["cid"]=request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())
    @app.hook("after_request")
    def headers() -> None: response.headers["X-Correlation-ID"]=request.environ.get("cid",""); response.content_type="application/json"
    @app.error(404)
    def missing(_:Any) -> dict: return {"error":{"code":"NOT_FOUND","message":"Route not found","timestamp":now(),"correlation_id":request.environ.get("cid","")}}
    @app.error(500)
    def unexpected(_:Any) -> dict: return {"error":{"code":"INTERNAL_ERROR","message":"Unexpected server error","timestamp":now(),"correlation_id":request.environ.get("cid","")}}
    def guarded(fn):
        def wrapped(*args:Any,**kwargs:Any):
            try: return fn(*args,**kwargs)
            except ApiError as exc: return HTTPResponse(status=exc.status,body=json.dumps({"error":{"code":exc.code,"message":exc.message,"timestamp":now(),"correlation_id":request.environ.get("cid",""),"details":exc.details}}),headers={"Content-Type":"application/json"})
        return wrapped
    @app.get("/health")
    def health() -> dict: return {"status":"ok","time":now()}
    @app.get("/openapi.json")
    def spec() -> dict:
        paths={p:{m.lower():{"responses":{"200":{"description":"Success"},"401":{"description":"Authentication failure"},"422":{"description":"Validation error"}}} for m in methods} for p,methods in {"/api/auth/register":["POST"],"/api/auth/login":["POST"],"/api/events":["GET","POST"],"/api/events/{event_id}":["GET","PUT","DELETE"],"/api/events/{event_id}/tasks":["GET","POST"],"/api/events/{event_id}/invitations":["GET","POST"],"/api/events/{event_id}/budget-categories":["GET","POST"],"/api/events/{event_id}/expenses":["GET","POST"],"/api/events/{event_id}/schedule":["GET","POST"],"/api/events/{event_id}/vendors":["GET","POST"],"/api/events/{event_id}/notifications":["GET"],"/api/events/{event_id}/activity":["GET"]}.items()}
        return {"openapi":"3.0.3","info":{"title":"EventForge API","version":"1.0.0"},"paths":paths}
    @app.get("/docs")
    def docs() -> str: response.content_type="text/html"; return '<!doctype html><html><body><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui"})</script></body></html>'
    @app.post("/api/auth/register")
    @guarded
    def register() -> dict:
        d=body(); email=required(d,"email").lower(); password=required(d,"password"); name=required(d,"display_name")
        if not EMAIL.match(email) or len(password)<8 or len(name)>120: raise ApiError(422,"VALIDATION_ERROR","Invalid registration fields")
        if any(x["email"]==email for x in store.users.values()): raise ApiError(409,"EMAIL_EXISTS","Email is already registered")
        uid=store.id(); user={"id":uid,"email":email,"display_name":name,"password_hash":hasher.hash(password),"created_at":now()}; store.users[uid]=user
        return {"user":{k:user[k] for k in ("id","email","display_name","created_at")},"token":codec.issue(str(uid))}
    @app.post("/api/auth/login")
    @guarded
    def login() -> dict:
        d=body(); email=required(d,"email").lower(); password=required(d,"password"); user=next((x for x in store.users.values() if x["email"]==email),None)
        if not user or not hasher.verify(password,user["password_hash"]): raise ApiError(401,"INVALID_CREDENTIALS","Invalid email or password")
        return {"user":{k:user[k] for k in ("id","email","display_name","created_at")},"token":codec.issue(str(user["id"]))}
    @app.route("/api/events",method=["GET","POST"])
    @guarded
    def events() -> dict:
        uid=actor()
        if request.method=="GET": return page([x for x in store.events.values() if x["owner_id"]==uid])
        d=body(); name=required(d,"name"); dt=required(d,"event_datetime")
        try: datetime.fromisoformat(dt.replace("Z","+00:00"))
        except ValueError: raise ApiError(422,"VALIDATION_ERROR","event_datetime must be ISO-8601")
        capacity=d.get("capacity");
        if capacity is not None and (not isinstance(capacity,int) or capacity<=0): raise ApiError(422,"VALIDATION_ERROR","capacity must be positive integer")
        eid=store.id(); item={"id":eid,"owner_id":uid,"name":name,"event_datetime":dt,"venue":d.get("venue"),"capacity":capacity,"budget_limit":dec(d.get("budget_limit",0),"budget_limit"),"status":d.get("status","DRAFT"),"description":d.get("description"),"confirmed_guest_count":0,"created_at":now()};store.events[eid]=item;audit(eid,uid,"EVENT_CREATED");return item
    @app.route("/api/events/<eid:int>",method=["GET","PUT","DELETE"])
    @guarded
    def event_route(eid:int) -> dict|str:
        uid=actor(); item=event(eid,uid)
        if request.method=="GET":
            actual=sum(Decimal(x["amount"]) for x in store.tables["expenses"].values() if x["event_id"]==eid); planned=sum(Decimal(x["planned_amount"]) for x in store.tables["categories"].values() if x["event_id"]==eid); return item|{"planned_budget":str(planned),"actual_spending":str(actual),"remaining_budget":str(Decimal(item["budget_limit"])-actual)}
        if request.method=="DELETE":
            for table in store.tables.values():
                for key in [k for k,v in table.items() if v.get("event_id")==eid]: del table[key]
            del store.events[eid]; response.status=204; return ""
        d=body(); allowed={"name","event_datetime","venue","capacity","budget_limit","status","description"}; item.update({k:(dec(v,k) if k=="budget_limit" else v) for k,v in d.items() if k in allowed});audit(eid,uid,"EVENT_UPDATED");return item
    def collection(kind:str, action:str):
        @guarded
        def handler(eid:int,rid:int|None=None) -> Any:
            uid=actor(); ev=event(eid,uid)
            if request.method=="GET": return page([x for x in store.tables[kind].values() if x.get("event_id")==eid])
            if request.method=="DELETE": del store.tables[kind][rid];audit(eid,uid,kind.upper()+"_DELETED");response.status=204;return ""
            d=body(); item=resource(kind,eid,rid)
            if rid is None:
                item.update(d); item["created_at"]=now()
                if kind=="tasks":
                    item["title"]=required(d,"title"); item["status"]=d.get("status","TODO");
                    if item["status"] not in STATUSES: raise ApiError(422,"VALIDATION_ERROR","Invalid task status")
                elif kind=="invitations":
                    item["guest_name"]=required(d,"guest_name"); item["guest_email"]=required(d,"guest_email"); item["status"]=d.get("status","PENDING")
                    if item["status"] not in INVITATION_STATUSES: raise ApiError(422,"VALIDATION_ERROR","Invalid invitation status")
                    if item["status"]=="ACCEPTED": change_capacity(ev,1)
                elif kind=="schedule": validate_schedule(eid,item,d,rid)
                elif kind=="vendors": item["name"]=required(d,"name");item["cost"]=dec(d.get("cost"),"cost",positive=True);item["paid_amount"]="0.00";item["outstanding_amount"]=item["cost"]
                elif kind=="categories": item["name"]=required(d,"name");item["planned_amount"]=dec(d.get("planned_amount"),"planned_amount")
                store.tables[kind][item["id"]]=item; audit(eid,uid,kind.upper()+"_CREATED");response.status=201;return item
            if kind=="invitations" and d.get("status"):
                new=d["status"];
                if new not in INVITATION_STATUSES: raise ApiError(422,"VALIDATION_ERROR","Invalid invitation status")
                change_capacity(ev,(new=="ACCEPTED")-(item.get("status")=="ACCEPTED")); item["status"]=new
            elif kind=="schedule": validate_schedule(eid,item,d,rid)
            else: item.update(d)
            audit(eid,uid,kind.upper()+"_UPDATED");return item
        return handler
    def change_capacity(ev:dict,delta:int) -> None:
        if delta>0 and ev["capacity"] is not None and ev["confirmed_guest_count"]>=ev["capacity"]: raise ApiError(409,"CAPACITY_FULL","Event capacity is full")
        ev["confirmed_guest_count"]+=delta
    def validate_schedule(eid:int,item:dict,d:dict,rid:int|None) -> None:
        start=required(d,"start_time"); end=required(d,"end_time")
        if start>=end: raise ApiError(422,"VALIDATION_ERROR","start_time must precede end_time")
        for other in store.tables["schedule"].values():
            if other["event_id"]==eid and other["id"]!=rid and start<other["end_time"] and end>other["start_time"]: raise ApiError(409,"SCHEDULE_OVERLAP","Schedule intervals overlap")
        item.update(d)
    for kind,path in [("tasks","tasks"),("invitations","invitations"),("categories","budget-categories"),("schedule","schedule"),("vendors","vendors"),("notifications","notifications"),("activity","activity")]:
        app.route(f"/api/events/<eid:int>/{path}",method=["GET","POST"] if kind not in {"activity","notifications"} else ["GET"])(collection(kind,"list"))
        if kind not in {"activity","notifications"}: app.route(f"/api/events/<eid:int>/{path}/<rid:int>",method=["PUT","DELETE"])(collection(kind,"item"))
    @app.route("/api/events/<eid:int>/expenses",method=["GET","POST"])
    @guarded
    def expenses(eid:int)->Any:
        uid=actor();ev=event(eid,uid)
        if request.method=="GET": return page([x for x in store.tables["expenses"].values() if x["event_id"]==eid])
        d=body(); amount=Decimal(dec(d.get("amount"),"amount",positive=True)); current=sum(Decimal(x["amount"]) for x in store.tables["expenses"].values() if x["event_id"]==eid)
        if current+amount>Decimal(ev["budget_limit"]):raise ApiError(409,"BUDGET_EXCEEDED","Expense exceeds budget limit")
        ident=store.id();item={"id":ident,"event_id":eid,"category_id":d.get("category_id"),"description":required(d,"description"),"amount":str(amount),"expenditure_at":d.get("expenditure_at",now())};store.tables["expenses"][ident]=item;audit(eid,uid,"EXPENSE_CREATED");response.status=201;return item
    @app.post("/api/events/<eid:int>/vendors/<vid:int>/payments")
    @guarded
    def payment(eid:int,vid:int)->Any:
        uid=actor();event(eid,uid); vendor=resource("vendors",eid,vid); d=body(); amount=Decimal(dec(d.get("amount"),"amount",positive=True)); paid=Decimal(vendor["paid_amount"])+amount
        if paid>Decimal(vendor["cost"]):raise ApiError(409,"PAYMENT_EXCEEDS_COST","Payment exceeds vendor cost")
        vendor["paid_amount"]=str(paid);vendor["outstanding_amount"]=str(Decimal(vendor["cost"])-paid);ident=store.id(); item={"id":ident,"event_id":eid,"vendor_id":vid,"amount":str(amount),"payment_at":d.get("payment_at",now()),"note":d.get("note")};store.tables["payments"][ident]=item;audit(eid,uid,"VENDOR_PAYMENT_CREATED");response.status=201;return item
    return app

app=create_app()
if __name__=="__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO")); run(app,host="0.0.0.0",port=int(os.getenv("PORT","8000")),quiet=True)

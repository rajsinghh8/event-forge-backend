"""Budget-category and expense business operations (direct parameterized psycopg SQL)."""
from decimal import Decimal, InvalidOperation
from uuid import uuid4
import json
from datetime import date

from .errors import ValidationError, NotFoundError, ForbiddenError, BusinessRuleError


def _decimal(value, field, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{field} is required")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field} must be a decimal string")
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValidationError(f"{field} must be {'positive' if positive else 'non-negative'}")
    return result


def _required(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{key} is required")
    return value.strip()


class BudgetService:
    """Owner-scoped category and expense operations. All writes are atomic."""
    def __init__(self, db, audit_writer=None, event_service=None):
        self.db, self.audit_writer, self.event_service = db, audit_writer, event_service

    def _event(self, owner_id, event_id, lock=False):
        suffix = " FOR UPDATE" if lock else ""
        event = self.db.fetchone(f"SELECT id, owner_id, planned_budget FROM events WHERE id=%s{suffix}", (event_id,))
        if not event: raise NotFoundError("Event not found")
        if str(event["owner_id"]) != str(owner_id): raise ForbiddenError("Event is not owned by the authenticated user")
        return event

    def _category(self, owner_id, event_id, category_id, lock=False):
        self._event(owner_id, event_id, lock)
        suffix = " FOR UPDATE" if lock else ""
        row = self.db.fetchone(f"SELECT * FROM budget_categories WHERE id=%s AND event_id=%s{suffix}", (category_id, event_id))
        if not row: raise NotFoundError("Budget category not found")
        return row

    @staticmethod
    def _category_out(row, actual=Decimal("0")):
        d = dict(row); planned = Decimal(str(d["planned_amount"])); actual = Decimal(str(actual or 0))
        d.update(plannedAmount=str(planned), actualAmount=str(actual), remainingAmount=str(planned-actual))
        d.pop("planned_amount", None)
        return d

    @staticmethod
    def _expense_out(row):
        d = dict(row); d["amount"] = str(d["amount"]); return d

    def _actual(self, category_id):
        row = self.db.fetchone("SELECT COALESCE(SUM(amount), 0) AS actual FROM expenses WHERE budget_category_id=%s", (category_id,))
        return Decimal(str(row["actual"] or 0))

    def _audit(self, event_id, owner_id, resource, resource_id, action, details):
        if self.audit_writer:
            return self.audit_writer.record(event_id, owner_id, resource, resource_id, action, details)
        self.db.execute("INSERT INTO audit_logs (id,event_id,actor_user_id,resource_type,resource_id,action,details,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,NOW())", (str(uuid4()), event_id, owner_id, resource, resource_id, action, json.dumps(details, default=str)))

    def _threshold(self, event_id, category, actual):
        planned = Decimal(str(category["planned_amount"]))
        if planned and actual >= planned * Decimal("0.90"):
            state = f"{actual}/{planned}"
            self.db.execute("INSERT INTO notifications (id,event_id,kind,source_type,source_id,state_key,message,created_at) VALUES (%s,%s,'budget_threshold','budget_category',%s,%s,%s,NOW()) ON CONFLICT (event_id,kind,source_type,source_id,state_key) DO NOTHING", (str(uuid4()), event_id, category["id"], state, f"Budget category {category['name']} has reached 90% of its planned amount"))

    def list_categories(self, owner_id, event_id, query):
        self._event(owner_id, event_id)
        page, size = int(query.get("page", 1)), int(query.get("size", 20))
        if page < 1 or not 1 <= size <= 100: raise ValidationError("Invalid page or size")
        sort = query.get("sort", "created_at"); allowed = {"name":"c.name", "planned_amount":"c.planned_amount", "created_at":"c.created_at", "updated_at":"c.updated_at"}
        desc = sort.startswith("-"); key = sort[1:] if desc else sort
        if key not in allowed: raise ValidationError("Invalid sort field")
        where, args = ["c.event_id=%s"], [event_id]
        if query.get("name"):
            where.append("c.name ILIKE %s"); args.append("%" + query["name"] + "%")
        clause = " AND ".join(where)
        count = self.db.fetchone(f"SELECT COUNT(*) AS total FROM budget_categories c WHERE {clause}", tuple(args))["total"]
        rows = self.db.fetchall(f"SELECT c.*,COALESCE(SUM(e.amount),0) actual FROM budget_categories c LEFT JOIN expenses e ON e.budget_category_id=c.id WHERE {clause} GROUP BY c.id ORDER BY {allowed[key]} {'DESC' if desc else 'ASC'} LIMIT %s OFFSET %s", tuple(args+[size,(page-1)*size]))
        return {"items":[self._category_out(r,r["actual"]) for r in rows],"total":count,"page":page,"size":size}

    def create_category(self, owner_id,event_id,payload):
        name, planned = _required(payload,"name"), _decimal(payload.get("plannedAmount", payload.get("planned_amount")), "plannedAmount")
        with self.db.transaction():
            self._event(owner_id,event_id,True)
            exists=self.db.fetchone("SELECT id FROM budget_categories WHERE event_id=%s AND name=%s",(event_id,name))
            if exists: raise BusinessRuleError("Category name must be unique within an event")
            cid=str(uuid4()); row=self.db.fetchone("INSERT INTO budget_categories (id,event_id,name,planned_amount,created_at,updated_at) VALUES (%s,%s,%s,%s,NOW(),NOW()) RETURNING *",(cid,event_id,name,planned))
            self._audit(event_id,owner_id,"budget_category",cid,"create",{"name":name,"plannedAmount":str(planned)})
            return self._category_out(row)

    def get_category(self,owner_id,event_id,category_id):
        row=self._category(owner_id,event_id,category_id); return self._category_out(row,self._actual(category_id))

    def update_category(self,owner_id,event_id,category_id,payload):
        if not payload: raise ValidationError("Request body cannot be empty")
        with self.db.transaction():
            old=self._category(owner_id,event_id,category_id,True); name=payload.get("name",old["name"])
            if not isinstance(name,str) or not name.strip(): raise ValidationError("name must be non-empty")
            planned=_decimal(payload.get("plannedAmount",payload.get("planned_amount",old["planned_amount"])),"plannedAmount")
            actual=self._actual(category_id)
            if planned < actual: raise BusinessRuleError("Planned amount cannot be lower than actual spending")
            dup=self.db.fetchone("SELECT id FROM budget_categories WHERE event_id=%s AND name=%s AND id<>%s",(event_id,name.strip(),category_id))
            if dup: raise BusinessRuleError("Category name must be unique within an event")
            row=self.db.fetchone("UPDATE budget_categories SET name=%s,planned_amount=%s,updated_at=NOW() WHERE id=%s RETURNING *",(name.strip(),planned,category_id))
            self._audit(event_id,owner_id,"budget_category",category_id,"update",{"name":name.strip(),"plannedAmount":str(planned)})
            self._threshold(event_id,row,actual); return self._category_out(row,actual)

    def delete_category(self,owner_id,event_id,category_id):
        with self.db.transaction():
            row=self._category(owner_id,event_id,category_id,True)
            if self._actual(category_id): raise BusinessRuleError("Only an empty budget category can be deleted")
            self.db.execute("DELETE FROM budget_categories WHERE id=%s",(category_id,)); self._audit(event_id,owner_id,"budget_category",category_id,"delete",{"name":row["name"]})

    def list_expenses(self,owner_id,event_id,category_id,query):
        self._category(owner_id,event_id,category_id); page,size=int(query.get("page",1)),int(query.get("size",20))
        if page<1 or not 1<=size<=100: raise ValidationError("Invalid page or size")
        sort=query.get("sort","incurred_on"); allowed={"name":"name","amount":"amount","incurred_on":"incurred_on","created_at":"created_at"}; desc=sort.startswith("-"); key=sort[1:] if desc else sort
        if key not in allowed: raise ValidationError("Invalid sort field")
        clauses=["budget_category_id=%s"]; args=[category_id]
        if query.get("name"): clauses.append("name ILIKE %s");args.append("%"+query["name"]+"%")
        for q,col,op in (("startDate","incurred_on",">="),("endDate","incurred_on","<=")):
            if query.get(q):
                try: date.fromisoformat(query[q])
                except ValueError: raise ValidationError(f"{q} must be an ISO date")
                clauses.append(f"{col}{op}%s");args.append(query[q])
        where=" AND ".join(clauses); total=self.db.fetchone(f"SELECT COUNT(*) total FROM expenses WHERE {where}",tuple(args))["total"]
        rows=self.db.fetchall(f"SELECT * FROM expenses WHERE {where} ORDER BY {allowed[key]} {'DESC' if desc else 'ASC'} LIMIT %s OFFSET %s",tuple(args+[size,(page-1)*size]))
        return {"items":[self._expense_out(x) for x in rows],"total":total,"page":page,"size":size}

    def get_expense(self,owner,event,cat,eid):
        self._category(owner,event,cat); row=self.db.fetchone("SELECT * FROM expenses WHERE id=%s AND budget_category_id=%s",(eid,cat))
        if not row: raise NotFoundError("Expense not found")
        return self._expense_out(row)

    def _expense_payload(self,payload,old=None):
        name=payload.get("name",old["name"] if old else None); amount=payload.get("amount",old["amount"] if old else None); incurred=payload.get("incurredOn",payload.get("incurred_on",old["incurred_on"] if old else None)); notes=payload.get("notes",old["notes"] if old else None)
        if not isinstance(name,str) or not name.strip(): raise ValidationError("name is required")
        amount=_decimal(amount,"amount",True)
        try: incurred=date.fromisoformat(str(incurred))
        except ValueError: raise ValidationError("incurredOn must be an ISO date")
        if notes is not None and not isinstance(notes,str): raise ValidationError("notes must be a string or null")
        return name.strip(),amount,incurred,notes

    def create_expense(self,owner,event,cat,payload):
        with self.db.transaction():
            category=self._category(owner,event,cat,True); name,amount,incurred,notes=self._expense_payload(payload)
            actual=self._actual(cat)
            if actual+amount > Decimal(str(category["planned_amount"])): raise BusinessRuleError("Expense exceeds category planned amount")
            eid=str(uuid4()); row=self.db.fetchone("INSERT INTO expenses (id,budget_category_id,name,amount,incurred_on,notes,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,NOW(),NOW()) RETURNING *",(eid,cat,name,amount,incurred,notes))
            self._audit(event,owner,"expense",eid,"create",{"name":name,"amount":str(amount)}); self._threshold(event,category,actual+amount); return self._expense_out(row)

    def update_expense(self,owner,event,cat,eid,payload):
        with self.db.transaction():
            category=self._category(owner,event,cat,True); old=self.db.fetchone("SELECT * FROM expenses WHERE id=%s AND budget_category_id=%s FOR UPDATE",(eid,cat))
            if not old: raise NotFoundError("Expense not found")
            name,amount,incurred,notes=self._expense_payload(payload,old); actual=self._actual(cat)-Decimal(str(old["amount"]))+amount
            if actual>Decimal(str(category["planned_amount"])): raise BusinessRuleError("Expense exceeds category planned amount")
            row=self.db.fetchone("UPDATE expenses SET name=%s,amount=%s,incurred_on=%s,notes=%s,updated_at=NOW() WHERE id=%s RETURNING *",(name,amount,incurred,notes,eid))
            self._audit(event,owner,"expense",eid,"update",{"name":name,"amount":str(amount)}); self._threshold(event,category,actual); return self._expense_out(row)

    def delete_expense(self,owner,event,cat,eid):
        with self.db.transaction():
            self._category(owner,event,cat,True); old=self.db.fetchone("SELECT * FROM expenses WHERE id=%s AND budget_category_id=%s FOR UPDATE",(eid,cat))
            if not old: raise NotFoundError("Expense not found")
            self.db.execute("DELETE FROM expenses WHERE id=%s",(eid,)); self._audit(event,owner,"expense",eid,"delete",{"name":old["name"],"amount":str(old["amount"])})

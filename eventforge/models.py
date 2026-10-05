from __future__ import annotations
from datetime import date,datetime
from decimal import Decimal
from typing import Any
TASK_STATUSES=frozenset({'todo','in_progress','done','cancelled'}); PRIORITIES=frozenset({'low','medium','high'}); GUEST_STATUSES=frozenset({'invited','accepted','declined'})
SORT_ALLOWLISTS={'events':{'id','name','start_date','created_at'},'tasks':{'id','title','due_at','priority','status'},'guests':{'id','name','status'}}
def serialize(value:Any)->Any:
 if isinstance(value,Decimal):return format(value.quantize(Decimal('0.01')),'f')
 if isinstance(value,(datetime,date)):return value.isoformat()
 if isinstance(value,dict):return {k:serialize(v) for k,v in value.items() if k!='password_hash'}
 if isinstance(value,(list,tuple)):return [serialize(v) for v in value]
 return value

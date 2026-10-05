from __future__ import annotations

from datetime import date, datetime
from typing import Any

from eventforge.errors import ValidationError
from eventforge.handlers.base import AuthenticatedHandler
from eventforge.models import serialize
from eventforge.validation import pagination, query_options

def _filtered_page(rows, arguments, *, fields, filters, default_sort='id'):
 limit,offset=pagination(arguments);query=query_options(arguments,allowed_sort=fields,allowed_filters=filters,default_sort=default_sort);sort=query.pop('sort');text=query.get('text','').lower();out=[]
 for row in rows:
  if text and text not in str(row.get('title',row.get('name',''))).lower():continue
  if any(str(row.get(key)) != str(value) for key,value in query.items() if key not in {'text','startDate','endDate'}):continue
  temporal=str(row.get('start_at',row.get('paid_on','')))
  if query.get('startDate') and temporal[:10] < query['startDate']:continue
  if query.get('endDate') and temporal[:10] > query['endDate']:continue
  out.append(row)
 field=sort.lstrip('-');out.sort(key=lambda row:(row.get(field) is None,row.get(field)),reverse=sort.startswith('-'))
 return {'items':out[offset:offset+limit],'total':len(out),'limit':limit,'offset':offset}


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str): raise ValidationError(f'{field} must be an ISO-8601 datetime')
    try: return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc: raise ValidationError(f'{field} must be an ISO-8601 datetime') from exc

def _date(value: object, field: str) -> date:
    if not isinstance(value, str): raise ValidationError(f'{field} must be an ISO-8601 date')
    try: return date.fromisoformat(value)
    except ValueError as exc: raise ValidationError(f'{field} must be an ISO-8601 date') from exc

def _required_text(data: dict[str, Any], field: str) -> str:
    value=data.get(field)
    if not isinstance(value,str) or not value.strip(): raise ValidationError(f'{field} is required')
    return value.strip()

class ScheduleItemsHandler(AuthenticatedHandler):
 async def get(self,event_id,item_id=None):
  if item_id is None:
   result=_filtered_page(self.service.list_schedule_items(self.user_id,int(event_id)),self.request.arguments,fields={'id','title','start_at','end_at'},filters={'text','startDate','endDate'},default_sort='start_at')
  else: result=self.service.schedule_item(self.user_id,int(event_id),int(item_id))
  self.write_json(serialize(result))
 async def post(self,event_id,item_id=None):self.write_json(serialize(self.service.create_schedule_item(self.user_id,int(event_id),self._payload(self.body()))),201)
 async def put(self,event_id,item_id):self.write_json(serialize(self.service.update_schedule_item(self.user_id,int(event_id),int(item_id),self._payload(self.body()))))
 async def delete(self,event_id,item_id):self.service.delete_schedule_item(self.user_id,int(event_id),int(item_id));self.set_status(204);self.finish()
 def _payload(self,data:dict[str,Any])->dict[str,Any]:
  return {'title':_required_text(data,'title'),'start_at':_datetime(data.get('start_at'),'start_at'),'end_at':_datetime(data.get('end_at'),'end_at'),**({ 'description':data['description']} if 'description' in data else {})}

class VendorsHandler(AuthenticatedHandler):
 async def get(self,event_id,vendor_id=None):
  if vendor_id is None:
   result=_filtered_page(self.service.list_vendors(self.user_id,int(event_id)),self.request.arguments,fields={'id','name','created_at'},filters={'text','name'},default_sort='id')
  else: result=self.service.vendor(self.user_id,int(event_id),int(vendor_id))
  self.write_json(serialize(result))
 async def post(self,event_id,vendor_id=None):self.write_json(serialize(self.service.create_vendor(self.user_id,int(event_id),self._payload(self.body()))),201)
 async def put(self,event_id,vendor_id):self.write_json(serialize(self.service.update_vendor(self.user_id,int(event_id),int(vendor_id),self._payload(self.body()))))
 async def delete(self,event_id,vendor_id):self.service.delete_vendor(self.user_id,int(event_id),int(vendor_id));self.set_status(204);self.finish()
 def _payload(self,data:dict[str,Any])->dict[str,Any]:
  if 'total_amount' not in data: raise ValidationError('total_amount is required')
  return {'name':_required_text(data,'name'),'total_amount':data['total_amount'],**{key:data[key] for key in ('contact_name','contact_email') if key in data}}

class VendorPaymentsHandler(AuthenticatedHandler):
 async def get(self,event_id,vendor_id,payment_id=None):
  result=self.service.list_vendor_payments(self.user_id,int(event_id),int(vendor_id)) if payment_id is None else self.service.vendor_payment(self.user_id,int(event_id),int(vendor_id),int(payment_id));self.write_json(serialize(result))
 async def post(self,event_id,vendor_id,payment_id=None):self.write_json(serialize(self.service.create_vendor_payment(self.user_id,int(event_id),int(vendor_id),self._payload(self.body()))),201)
 async def put(self,event_id,vendor_id,payment_id):self.write_json(serialize(self.service.update_vendor_payment(self.user_id,int(event_id),int(vendor_id),int(payment_id),self._payload(self.body()))))
 async def delete(self,event_id,vendor_id,payment_id):self.service.delete_vendor_payment(self.user_id,int(event_id),int(vendor_id),int(payment_id));self.set_status(204);self.finish()
 def _payload(self,data:dict[str,Any])->dict[str,Any]:
  if 'amount' not in data: raise ValidationError('amount is required')
  return {'amount':data['amount'],'paid_on':_date(data.get('paid_on'),'paid_on'),**({ 'reference':data['reference']} if 'reference' in data else {})}

from contextlib import nullcontext
from datetime import date, datetime, timedelta
from decimal import Decimal
import unittest

from eventforge.errors import ConflictError
from eventforge.resource_services.operations import OperationsResourceService

class FakeOperationsRepository:
 def __init__(self):self.items=[];self.vendors=[];self.payments=[];self.audits=[]
 def transaction(self):return nullcontext()
 def get_event(self,u,e):return {'id':e} if (u,e)==(1,1) else None
 def list_schedule_items(self,u,e):return self.items.copy() if self.get_event(u,e) else []
 def get_schedule_item(self,u,e,i):return next((x for x in self.items if x['id']==i and self.get_event(u,e)),None)
 def create_schedule_item(self,e,v):x={'id':len(self.items)+1,'event_id':e,**v};self.items.append(x);return x
 def update_schedule_item(self,u,e,i,v):x=self.get_schedule_item(u,e,i);x.update(v);return x
 def delete_schedule_item(self,u,e,i):
  x=self.get_schedule_item(u,e,i)
  if x:self.items.remove(x)
  return x is not None
 def list_vendors(self,u,e):return self.vendors.copy() if self.get_event(u,e) else []
 def get_vendor(self,u,e,i):return next((x for x in self.vendors if x['id']==i and self.get_event(u,e)),None)
 def create_vendor(self,e,v):x={'id':len(self.vendors)+1,'event_id':e,**v};self.vendors.append(x);return x
 def update_vendor(self,u,e,i,v):x=self.get_vendor(u,e,i);x.update(v);return x
 def delete_vendor(self,u,e,i):
  x=self.get_vendor(u,e,i)
  if x:self.vendors.remove(x)
  return x is not None
 def vendor_paid_total(self,v,exclude_payment_id=None):return sum((x['amount'] for x in self.payments if x['vendor_id']==v and x['id']!=exclude_payment_id),Decimal())
 def list_vendor_payments(self,u,e,v):return [x for x in self.payments if x['vendor_id']==v] if self.get_vendor(u,e,v) else []
 def get_vendor_payment(self,u,e,v,p):return next((x for x in self.payments if x['id']==p and x['vendor_id']==v and self.get_vendor(u,e,v)),None)
 def create_vendor_payment(self,v,values):x={'id':len(self.payments)+1,'vendor_id':v,**values};self.payments.append(x);return x
 def update_vendor_payment(self,u,e,v,p,values):x=self.get_vendor_payment(u,e,v,p);x.update(values);return x
 def delete_vendor_payment(self,u,e,v,p):
  x=self.get_vendor_payment(u,e,v,p)
  if x:self.payments.remove(x)
  return x is not None
 def record_audit(self,**kwargs):self.audits.append(kwargs)

class OperationsTests(unittest.TestCase):
 def setUp(self):self.repo=FakeOperationsRepository();self.service=OperationsResourceService(self.repo)
 def test_schedule_overlap_is_rejected_and_audited(self):
  start=datetime(2025,1,1,10);self.service.create_schedule_item(1,1,{'title':'one','start_at':start,'end_at':start+timedelta(hours=1)})
  with self.assertRaises(ConflictError):self.service.create_schedule_item(1,1,{'title':'two','start_at':start+timedelta(minutes=30),'end_at':start+timedelta(hours=2)})
  self.assertEqual(self.repo.audits[0]['entity_type'],'schedule_item')
 def test_payment_limit_and_decimal_vendor_view(self):
  vendor=self.service.create_vendor(1,1,{'name':'caterer','total_amount':'100.00'})
  self.service.create_vendor_payment(1,1,1,{'amount':'30.25','paid_on':date(2025,1,2)})
  view=self.service.get_vendor(1,1,1)
  self.assertEqual((view['total_amount'],view['totalPaid'],view['outstanding']),('100.00','30.25','69.75'))
  with self.assertRaises(ConflictError):self.service.create_vendor_payment(1,1,1,{'amount':'70.00','paid_on':date(2025,1,3)})
  self.assertEqual(vendor['totalPaid'],'0')

if __name__=='__main__':unittest.main()

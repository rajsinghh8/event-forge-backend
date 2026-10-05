from eventforge.handlers.auth import RegisterHandler,LoginHandler
from eventforge.handlers.docs import OpenApiHandler,DocsHandler,HealthHandler
from eventforge.handlers.events import EventsHandler,EventHandler,NestedHandler
from eventforge.handlers.budget import BudgetHandler,BudgetCategoriesHandler,ExpensesHandler
from eventforge.handlers.notifications import NotificationsHandler
from eventforge.handlers.operations import ScheduleItemsHandler, VendorsHandler, VendorPaymentsHandler

def routes(service,settings):
 common={'service':service,'settings':settings}
 nested=lambda table:{**common,'table':table}
 return [(r'/health',HealthHandler,common),(r'/api/auth/register',RegisterHandler,common),(r'/api/auth/login',LoginHandler,common),(r'/openapi.json',OpenApiHandler,common),(r'/docs',DocsHandler,common),(r'/api/events',EventsHandler,common),(r'/api/events/(\d+)',EventHandler,common),
 (r'/api/events/(\d+)/tasks',NestedHandler,nested('tasks')),(r'/api/events/(\d+)/tasks/(\d+)',NestedHandler,nested('tasks')),(r'/api/events/(\d+)/guests',NestedHandler,nested('guests')),(r'/api/events/(\d+)/guests/(\d+)',NestedHandler,nested('guests')),
 (r'/api/events/(\d+)/budget',BudgetHandler,common),(r'/api/events/(\d+)/budget/categories',BudgetCategoriesHandler,common),(r'/api/events/(\d+)/budget/categories/(\d+)',BudgetCategoriesHandler,common),(r'/api/events/(\d+)/expenses',ExpensesHandler,common),(r'/api/events/(\d+)/expenses/(\d+)',ExpensesHandler,common),
 # Retain the original category URLs as aliases while delegating to the budget facade.
 (r'/api/events/(\d+)/budget-categories',BudgetCategoriesHandler,common),(r'/api/events/(\d+)/budget-categories/(\d+)',BudgetCategoriesHandler,common),
 (r'/api/events/(\d+)/schedule-items',ScheduleItemsHandler,common),(r'/api/events/(\d+)/schedule-items/(\d+)',ScheduleItemsHandler,common),(r'/api/events/(\d+)/vendors',VendorsHandler,common),(r'/api/events/(\d+)/vendors/(\d+)',VendorsHandler,common),(r'/api/events/(\d+)/vendors/(\d+)/payments',VendorPaymentsHandler,common),(r'/api/events/(\d+)/vendors/(\d+)/payments/(\d+)',VendorPaymentsHandler,common),(r'/api/notifications',NotificationsHandler,common),(r'/api/notifications/(\d+)',NotificationsHandler,common)]

from eventforge.handlers.auth import RegisterHandler,LoginHandler
from eventforge.handlers.docs import OpenApiHandler,DocsHandler,HealthHandler
from eventforge.handlers.events import EventsHandler,EventHandler,NestedHandler
from eventforge.handlers.notifications import NotificationsHandler
def routes(service,settings):
 common={'service':service,'settings':settings}
 nested=lambda table:{**common,'table':table}
 return [(r'/health',HealthHandler,common),(r'/api/auth/register',RegisterHandler,common),(r'/api/auth/login',LoginHandler,common),(r'/openapi.json',OpenApiHandler,common),(r'/docs',DocsHandler,common),(r'/api/events',EventsHandler,common),(r'/api/events/(\\d+)',EventHandler,common),
 (r'/api/events/(\\d+)/tasks',NestedHandler,nested('tasks')),(r'/api/events/(\\d+)/tasks/(\\d+)',NestedHandler,nested('tasks')),(r'/api/events/(\\d+)/guests',NestedHandler,nested('guests')),(r'/api/events/(\\d+)/guests/(\\d+)',NestedHandler,nested('guests')),(r'/api/events/(\\d+)/budget-categories',NestedHandler,nested('budget_categories')),(r'/api/events/(\\d+)/budget-categories/(\\d+)',NestedHandler,nested('budget_categories')),(r'/api/events/(\\d+)/schedule-items',NestedHandler,nested('schedule_items')),(r'/api/events/(\\d+)/schedule-items/(\\d+)',NestedHandler,nested('schedule_items')),(r'/api/events/(\\d+)/vendors',NestedHandler,nested('vendors')),(r'/api/events/(\\d+)/vendors/(\\d+)',NestedHandler,nested('vendors')),(r'/api/notifications',NotificationsHandler,common),(r'/api/notifications/(\\d+)',NotificationsHandler,common)]

from __future__ import annotations
import logging
import tornado.ioloop
from eventforge.app import create_application
from eventforge.config import load_settings
def main()->None:
 logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s');settings=load_settings();app=create_application(settings);app.listen(settings.port,address='0.0.0.0')
 try:tornado.ioloop.IOLoop.current().start()
 finally:app.scheduler.stop()
if __name__=='__main__':main()

from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator, Any
import mysql.connector
from eventforge.config import Settings
class Database:
 def __init__(self, settings: Settings)->None:self._s=settings
 @contextmanager
 def connection(self)->Iterator[Any]:
  conn=mysql.connector.connect(host=self._s.mysql_host,port=self._s.mysql_port,user=self._s.mysql_user,password=self._s.mysql_password,database=self._s.mysql_database)
  try:yield conn
  finally:conn.close()
 @contextmanager
 def transaction(self)->Iterator[Any]:
  with self.connection() as conn:
   try:yield conn;conn.commit()
   except Exception:conn.rollback();raise
 def initialize_schema(self)->None:
  statements=['''CREATE TABLE IF NOT EXISTS users (id BIGINT AUTO_INCREMENT PRIMARY KEY,email VARCHAR(254) NOT NULL UNIQUE,password_hash VARCHAR(100) NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''','''CREATE TABLE IF NOT EXISTS events (id BIGINT AUTO_INCREMENT PRIMARY KEY,owner_id BIGINT NOT NULL,name VARCHAR(255) NOT NULL,description TEXT NULL,start_date DATE NULL,end_date DATE NULL,capacity INT NULL,planned_budget DECIMAL(14,2) NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,INDEX(owner_id),FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE)''']
  resources={'tasks':'event_id BIGINT NOT NULL,title VARCHAR(255) NOT NULL,description TEXT,status VARCHAR(32),priority VARCHAR(32),due_at DATETIME NULL,dependency_task_id BIGINT NULL','guests':'event_id BIGINT NOT NULL,name VARCHAR(255) NOT NULL,email VARCHAR(254) NULL,status VARCHAR(32)','budget_categories':'event_id BIGINT NOT NULL,name VARCHAR(255) NOT NULL,planned_amount DECIMAL(14,2) NOT NULL','schedule_items':'event_id BIGINT NOT NULL,title VARCHAR(255) NOT NULL,description TEXT,start_at DATETIME NOT NULL,end_at DATETIME NOT NULL','vendors':'event_id BIGINT NOT NULL,name VARCHAR(255) NOT NULL,contact_name VARCHAR(255),contact_email VARCHAR(254),total_amount DECIMAL(14,2) NOT NULL'}
  for table,cols in resources.items():statements.append(f'CREATE TABLE IF NOT EXISTS {table} (id BIGINT AUTO_INCREMENT PRIMARY KEY,{cols},created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,INDEX(event_id),FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE)')
  statements += ['''CREATE TABLE IF NOT EXISTS expenses (id BIGINT AUTO_INCREMENT PRIMARY KEY,budget_category_id BIGINT NOT NULL,name VARCHAR(255) NOT NULL,amount DECIMAL(14,2) NOT NULL,spent_on DATE NOT NULL,notes TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,FOREIGN KEY(budget_category_id) REFERENCES budget_categories(id) ON DELETE CASCADE)''','''CREATE TABLE IF NOT EXISTS vendor_payments (id BIGINT AUTO_INCREMENT PRIMARY KEY,vendor_id BIGINT NOT NULL,amount DECIMAL(14,2) NOT NULL,paid_on DATE NOT NULL,reference VARCHAR(255),created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,FOREIGN KEY(vendor_id) REFERENCES vendors(id) ON DELETE CASCADE)''','''CREATE TABLE IF NOT EXISTS notification_sources (source_key VARCHAR(191) PRIMARY KEY,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''','''CREATE TABLE IF NOT EXISTS notifications (id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id BIGINT NOT NULL,event_id BIGINT NULL,kind VARCHAR(64) NOT NULL,title VARCHAR(255) NOT NULL,message TEXT NOT NULL,source_type VARCHAR(64),source_id BIGINT,source_state VARCHAR(191),is_read BOOLEAN NOT NULL DEFAULT FALSE,read_at DATETIME NULL,created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,INDEX(user_id,created_at),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE)''','''CREATE TABLE IF NOT EXISTS audit_logs (id BIGINT AUTO_INCREMENT PRIMARY KEY,event_id BIGINT NOT NULL,actor_user_id BIGINT NOT NULL,resource_type VARCHAR(64),resource_id BIGINT,action VARCHAR(32),details JSON NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,INDEX(event_id),FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE CASCADE)''','ALTER TABLE notifications ADD COLUMN IF NOT EXISTS title VARCHAR(255) NOT NULL DEFAULT \'Notification\'','ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at DATETIME NULL']
  with self.transaction() as conn:
   cursor=conn.cursor()
   for statement in statements:cursor.execute(statement)

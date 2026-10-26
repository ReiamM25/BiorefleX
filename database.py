# database.py
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import datetime

DATABASE_URL = "sqlite:///bioreflex_local.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserAccount(Base):
    __tablename__ = "user_accounts"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String, default="Lab Technician")

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String, unique=True, index=True)
    name = Column(String)
    age = Column(Integer)
    gender = Column(String)
    orders = relationship("LabOrder", back_populates="patient")

class LabOrder(Base):
    __tablename__ = "lab_orders"
    id = Column(Integer, primary_key=True, index=True)
    order_code = Column(String, unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    base_price = Column(Float, default=0.0)
    add_on_revenue = Column(Float, default=0.0)
    total_revenue = Column(Float, default=0.0)
    status = Column(String, default="Pending")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    patient = relationship("Patient", back_populates="orders")
    results = relationship("ClinicalResult", back_populates="order", uselist=False)

class ClinicalResult(Base):
    __tablename__ = "clinical_results"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("lab_orders.id"))
    panel_type = Column(String)
    clinical_flag = Column(String)
    reflex_order = Column(String)
    tube_alert = Column(String)
    added_value_iqd = Column(Float, default=0.0)
    hgb = Column(Float, nullable=True)
    rbc = Column(Float, nullable=True)
    mcv = Column(Float, nullable=True)
    mentzer_index = Column(Float, nullable=True)
    ast = Column(Float, nullable=True)
    alt = Column(Float, nullable=True)
    fib4_index = Column(Float, nullable=True)
    creatinine = Column(Float, nullable=True)
    egfr_val = Column(Float, nullable=True)
    tsh = Column(Float, nullable=True)
    glucose = Column(Float, nullable=True)
    insulin = Column(Float, nullable=True)
    homa_ir = Column(Float, nullable=True)
    order = relationship("LabOrder", back_populates="results")

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if not db.query(UserAccount).filter(UserAccount.username == "admin").first():
        default_user = UserAccount(username="admin", password="123", role="Lab Supervisor")
        db.add(default_user)
        db.commit()
    db.close()

if __name__ == "__main__":
    init_db()
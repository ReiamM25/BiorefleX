# app.py (FastAPI Backend with Authentication & Landing Page Endpoints)
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import pandas as pd

from database import SessionLocal, init_db, Patient, LabOrder, ClinicalResult, AnalyzerLog, User
from clinical_engine import MasterClinicalEngine

app = FastAPI(title="BioRefleX Enterprise Clinical Engine", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
def startup_event():
    init_db()
    # Seed default users if none exist
    db = SessionLocal()
    if db.query(User).count() == 0:
        default_users = [
            User(username="tech_riyam", role="Lab Technician"),
            User(username="dr_pathologist", role="Clinical Pathologist"),
            User(username="admin", role="Administrator")
        ]
        db.add_all(default_users)
        db.commit()
    db.close()

@app.get("/")
def read_landing_page():
    """Landing page metadata and system overview."""
    return {
        "app_name": "BioRefleX Enterprise LIS & Triage Command Center",
        "version": "2.1.0",
        "status": "Online",
        "features": [
            "Multi-Panel Clinical Evaluation (CBC, Liver, Renal, Thyroid, Metabolic)",
            "Automated & Manual Data Entry",
            "ASTM/HL7 Analyzer Device Stream Integration",
            "Role-Based Access Control (Lab Tech, Pathologist, Admin)"
        ]
    }

@app.post("/api/login")
def login(credentials: dict, db: Session = Depends(get_db)):
    """Simple role-based login handler for the login screen."""
    username = credentials.get("username", "").strip()
    user = db.query(User).filter(User.username == username).first()
    
    if not user:
        # Auto-create user if valid role requested
        role = credentials.get("role", "Lab Technician")
        user = User(username=username or "operator", role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        
    return {
        "status": "success",
        "message": f"Welcome back, {user.username}!",
        "role": user.role,
        "user_id": user.id
    }

@app.post("/api/evaluate-and-save")
def evaluate_and_save(data: dict, db: Session = Depends(get_db)):
    """Handles manual or analyzer test entry, computes multi-panel clinical indices, and persists to DB."""
    patient_id = data.get("patient_id", f"IQ-PAT-{pd.Timestamp.now().strftime('%H%M%S')}")
    name = data.get("name", "Walk-in Patient")
    age = int(data.get("age", 30))
    gender = data.get("gender", "female")
    
    # Extract clinical values
    hgb = float(data.get("hgb", 13.0))
    rbc = float(data.get("rbc", 4.5))
    mcv = float(data.get("mcv", 88.0))
    wbc = float(data.get("wbc", 7.0))
    platelets = float(data.get("platelets", 250.0))
    ast = float(data.get("ast", 25.0))
    alt = float(data.get("alt", 22.0))
    creatinine = float(data.get("creatinine", 0.8))
    glucose = float(data.get("glucose", 95.0))
    tsh = float(data.get("tsh", 2.0))

    # Run Clinical Rules Engine across multiple panels
    hem_res = MasterClinicalEngine.evaluate_hematology(hgb, rbc, mcv, platelets, gender)
    liv_res = MasterClinicalEngine.evaluate_liver(ast, alt, age, platelets)
    ren_res = MasterClinicalEngine.evaluate_renal(creatinine, age, gender)
    thy_res = MasterClinicalEngine.evaluate_thyroid(tsh)
    met_res = MasterClinicalEngine.evaluate_metabolic(glucose)

    total_added_iqd = hem_res["added_iqd"] + liv_res["added_iqd"] + ren_res["added_iqd"] + thy_res["added_iqd"] + met_res["added_iqd"]
    primary_flag = hem_res["flag"] if hem_res["flag"] != "طبيعي / دم ضمن المعدل" else liv_res["flag"]

    # Save to Database
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if not patient:
        patient = Patient(patient_id=patient_id, name=name, age=age, gender=gender)
        db.add(patient)
        db.commit()
        db.refresh(patient)

    order_code = f"ORD-{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}"
    order = LabOrder(
        order_code=order_code,
        patient_id=patient.id,
        source=data.get("source", "Manual Entry"),
        base_price=10000.0,
        add_on_revenue=total_added_iqd,
        total_revenue=10000.0 + total_added_iqd,
        status="Completed"
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    result = ClinicalResult(
        order_id=order.id,
        hgb=hgb, rbc=rbc, mcv=mcv, wbc=wbc, platelets=platelets,
        mentzer_index=hem_res["indices"]["mentzer"],
        ast=ast, alt=alt, fib4_index=liv_res["indices"]["fib4"],
        creatinine=creatinine, egfr_val=ren_res["indices"]["egfr"],
        glucose=glucose, homa_ir=met_res["indices"]["homa_ir"],
        tsh=tsh,
        clinical_flag=primary_flag,
        reflex_order=hem_res["reflex"],
        tube_alert=hem_res["tube_alert"],
        added_value_iqd=total_added_iqd
    )
    db.add(result)
    db.commit()

    return {
        "status": "success",
        "order_code": order_code,
        "patient_id": patient_id,
        "clinical_evaluation": {
            "hematology": hem_res,
            "liver": liv_res,
            "renal": ren_res,
            "thyroid": thy_res,
            "metabolic": met_res,
            "total_added_iqd": total_added_iqd
        }
    }

@app.get("/api/records")
def get_records(db: Session = Depends(get_db)):
    orders = db.query(LabOrder).all()
    data = []
    for o in orders:
        res = o.results
        pat = o.patient
        data.append({
            "order_code": o.order_code,
            "patient_name": pat.name if pat else "Unknown",
            "age": pat.age if pat else 0,
            "gender": pat.gender if pat else "N/A",
            "source": o.source,
            "total_revenue": o.total_revenue,
            "clinical_flag": res.clinical_flag if res else "N/A",
            "reflex_order": res.reflex_order if res else "None",
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M")
        })
    return data

@app.post("/api/analyzer/webhook")
def analyzer_webhook(payload: dict, db: Session = Depends(get_db)):
    """Simulates ASTM/HL7 TCP device integration endpoint for automated analyzer streaming."""
    instrument_id = payload.get("instrument_id", "SYSMEX-XN1000")
    raw_packet = payload.get("raw_packet", "")
    
    log = AnalyzerLog(instrument_id=instrument_id, raw_packet=raw_packet)
    db.add(log)
    db.commit()
    
    return {"status": "received", "instrument": instrument_id, "logged_id": log.id}
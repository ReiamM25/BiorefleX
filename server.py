# server.py
import os
import io
import csv
import urllib.parse
import uvicorn
from typing import List
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, Patient, LabOrder, ClinicalResult
from clinical_engine import MasterClinicalEngine

app = FastAPI(title="BioReflex Pro - Local LIMS & Command Center")

current_dir = os.path.dirname(os.path.abspath(__file__))
templates_dir = os.path.join(current_dir, "templates")
os.makedirs(templates_dir, exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 1. LANDING PAGE & LOGIN ---
@app.get("/landing", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
def landing_login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={}
    )

# --- 2. RECEPTION & MANUAL PATIENT ENTRY ---
@app.get("/", response_class=HTMLResponse)
def home_reception(request: Request, db: Session = Depends(get_db)):
    recent_orders = db.query(LabOrder).order_by(LabOrder.id.desc()).limit(20).all()
    total_patients = db.query(Patient).count()
    next_patient_id = f"IQ-{total_patients + 1001}"
    return templates.TemplateResponse(
        request=request,
        name="reception.html",
        context={"orders": recent_orders, "next_patient_id": next_patient_id, "active_page": "reception"}
    )

@app.post("/register-patient")
def register_patient(
    patient_id: str = Form(...),
    name: str = Form(...),
    age: int = Form(...),
    gender: str = Form(...),
    tests: List[str] = Form([]),
    db: Session = Depends(get_db)
):
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if not patient:
        patient = Patient(patient_id=patient_id, name=name, age=age, gender=gender)
        db.add(patient)
        db.flush()

    prices = {"CBC": 10000.0, "Liver": 15000.0, "Renal": 15000.0, "Metabolic": 20000.0, "Thyroid": 15000.0}
    base_cost = sum([prices.get(t, 10000.0) for t in tests]) if tests else 10000.0

    order = LabOrder(
        order_code=f"ORD-{db.query(LabOrder).count() + 1001}",
        patient_id=patient.id,
        base_price=base_cost,
        add_on_revenue=0.0,
        total_revenue=base_cost,
        status="Pending"
    )
    db.add(order)
    db.commit()
    return RedirectResponse(url="/lab-console", status_code=303)

# --- 3. LAB CONSOLE & MANUAL TEST DATA ENTRY ---
@app.get("/lab-console", response_class=HTMLResponse)
def lab_console_page(request: Request, db: Session = Depends(get_db)):
    results = db.query(ClinicalResult).order_by(ClinicalResult.id.desc()).limit(30).all()
    pending_orders = db.query(LabOrder).filter(LabOrder.status == "Pending").order_by(LabOrder.id.desc()).limit(15).all()
    return templates.TemplateResponse(
        request=request,
        name="lab_console.html",
        context={"results": results, "pending_orders": pending_orders, "active_page": "lab_console"}
    )

@app.post("/submit-lab-test")
def submit_lab_test(
    order_id: int = Form(...),
    panel: str = Form(...),
    val1: float = Form(...),
    val2: float = Form(None),
    val3: float = Form(None),
    db: Session = Depends(get_db)
):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        return RedirectResponse(url="/lab-console", status_code=303)

    patient = order.patient
    eval_res = {}

    if panel == "CBC":
        eval_res = MasterClinicalEngine.evaluate_hematology(hgb=val1, rbc=(val2 or 4.5), mcv=(val3 or 80.0), gender=patient.gender)
        calc_idx = eval_res["indices"].get("mentzer")
    elif panel == "Liver":
        eval_res = MasterClinicalEngine.evaluate_liver(ast=val1, alt=(val2 or 30.0), age=patient.age)
        calc_idx = eval_res["indices"].get("fib4")
    elif panel == "Renal":
        eval_res = MasterClinicalEngine.evaluate_renal(creatinine=val1, age=patient.age, gender=patient.gender)
        calc_idx = eval_res["indices"].get("egfr")
    elif panel == "Thyroid":
        eval_res = MasterClinicalEngine.evaluate_thyroid(tsh=val1)
        calc_idx = eval_res["indices"].get("tsh")
    else:  # Metabolic
        eval_res = MasterClinicalEngine.evaluate_metabolic(glucose=val1, insulin=(val2 or 10.0))
        calc_idx = eval_res["indices"].get("homa_ir")

    order.status = "Completed"
    order.add_on_revenue = eval_res["added_iqd"]
    order.total_revenue = order.base_price + eval_res["added_iqd"]

    result = db.query(ClinicalResult).filter(ClinicalResult.order_id == order.id).first()
    if not result:
        result = ClinicalResult(order_id=order.id)
        db.add(result)

    result.panel_type = panel
    result.clinical_flag = eval_res["flag"]
    result.reflex_order = eval_res["reflex"]
    result.tube_alert = eval_res["tube_alert"]
    result.added_value_iqd = eval_res["added_iqd"]

    if panel == "CBC":
        result.hgb, result.rbc, result.mcv = val1, val2, val3
        result.mentzer_index = calc_idx
    elif panel == "Liver":
        result.ast, result.alt = val1, val2
        result.fib4_index = calc_idx
    elif panel == "Renal":
        result.creatinine = val1
        result.egfr_val = calc_idx
    elif panel == "Thyroid":
        result.tsh = val1
    elif panel == "Metabolic":
        result.glucose, result.insulin = val1, val2
        result.homa_ir = calc_idx

    db.commit()
    return RedirectResponse(url="/lab-console", status_code=303)

# --- 4. BATCH FILE UPLOAD & ANALYZED EXPORT ---
@app.get("/batch-upload", response_class=HTMLResponse)
def batch_upload_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="batch_upload.html",
        context={"active_page": "batch_upload"}
    )

@app.post("/export-analyzed-file")
async def export_analyzed_file(file: UploadFile = File(...)):
    contents = await file.read()
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return HTMLResponse("Please upload a CSV file.", status_code=400)

    reader = csv.DictReader(io.StringIO(contents.decode("utf-8-sig")))
    fieldnames = list(reader.fieldnames or [])

    analyzed_rows = []
    for row in reader:
        def numeric_value(column: str, default: float) -> float:
            value = row.get(column)
            return float(value) if value not in (None, "") else default

        hgb = numeric_value("hgb", 13.0)
        rbc = numeric_value("rbc", 4.5)
        mcv = numeric_value("mcv", 85.0)
        plt = numeric_value("platelets", 250.0)
        gender = str(row.get("gender") or "female")

        eval_res = MasterClinicalEngine.evaluate_hematology(hgb=hgb, rbc=rbc, mcv=mcv, platelets=plt, gender=gender)

        row_dict = dict(row)
        row_dict["mentzer_index"] = eval_res["indices"].get("mentzer")
        row_dict["clinical_flag"] = eval_res["flag"]
        row_dict["reflex_order"] = eval_res["reflex"]
        row_dict["tube_alert"] = eval_res["tube_alert"]
        row_dict["added_value_iqd"] = eval_res["added_iqd"]
        analyzed_rows.append(row_dict)

    stream = io.StringIO()
    extra_fields = ["mentzer_index", "clinical_flag", "reflex_order", "tube_alert", "added_value_iqd"]
    writer = csv.DictWriter(stream, fieldnames=fieldnames + [name for name in extra_fields if name not in fieldnames])
    writer.writeheader()
    writer.writerows(analyzed_rows)
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=analyzed_bioreflex_report.csv"
    return response

# --- 5. PRINTABLE REPORT & WHATSAPP ---
@app.get("/report/{order_id}", response_class=HTMLResponse)
def print_report(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        return HTMLResponse("الطلب غير موجود", status_code=404)

    patient = order.patient
    res = order.results
    tests_detail = []
    if res and res.panel_type == "CBC":
        tests_detail.append({"name": "Hemoglobin (Hgb)", "val": res.hgb or 0.0, "ref": "12.0 - 16.0", "unit": "g/dL", "status": "اختبار", "color": "text-teal-400"})

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={"order": order, "patient": patient, "res": res, "tests_detail": tests_detail, "wa_link": "#", "active_page": "lab_console"}
    )

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
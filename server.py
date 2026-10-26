# server.py
import os
import io
import urllib.parse
import pandas as pd
import uvicorn
from typing import List
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, Patient, LabOrder, ClinicalResult, UserAccount, init_db
from clinical_engine import MasterClinicalEngine

app = FastAPI(title="BioRefleX Pro - Multi-Panel Clinical LIMS")
init_db()

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

# 1. صفحة تسجيل الدخول المنفصلة
@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})

@app.post("/login-action")
def login_action(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(UserAccount).filter(UserAccount.username == username, UserAccount.password == password).first()
    if user:
        return RedirectResponse(url="/reception", status_code=303)
    return RedirectResponse(url="/login?error=1", status_code=303)

# 2. محطة الاستقبال وقيد المرضى والتحاليل المطلوبة
@app.get("/reception", response_class=HTMLResponse)
def home_reception(request: Request, search: str = None, db: Session = Depends(get_db)):
    query = db.query(LabOrder)
    if search:
        query = query.join(Patient).filter(Patient.name.contains(search) | Patient.patient_id.contains(search))
    
    recent_orders = query.order_by(LabOrder.id.desc()).limit(20).all()
    total_patients = db.query(Patient).count()
    next_patient_id = f"IQ-{total_patients + 1001}"
    
    return templates.TemplateResponse(
        request=request,
        name="reception.html",
        context={"orders": recent_orders, "next_patient_id": next_patient_id, "active_page": "reception", "search": search or ""}
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
    selected_panels_str = ",".join(tests) if tests else "CBC"
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
    db.flush()

    # إنشاء سجّل النتائج وربطه باللوحات المطلوبة
    clinical_res = ClinicalResult(
        order_id=order.id,
        panel_type=selected_panels_str,
        clinical_flag="قيد المعالجة",
        reflex_order="لم يتم التقييم بعد",
        tube_alert="يتطلب سحب العينة"
    )
    db.add(clinical_res)
    db.commit()
    return RedirectResponse(url="/lab-console", status_code=303)

# 3. محطة المختبر والفرز الديناميكي بحسب تحاليل المريض
@app.get("/lab-console", response_class=HTMLResponse)
def lab_console_page(request: Request, db: Session = Depends(get_db)):
    results = db.query(ClinicalResult).order_by(ClinicalResult.id.desc()).limit(30).all()
    pending_orders = db.query(LabOrder).filter(LabOrder.status == "Pending").order_by(LabOrder.id.desc()).limit(15).all()
    
    # تحضير اللوحات المطلوبة لكل طلب معلق لتصفيتها في الواجهة
    pending_data = []
    for p_ord in pending_orders:
        panels_list = p_ord.results.panel_type.split(",") if (p_ord.results and p_ord.results.panel_type) else ["CBC"]
        pending_data.append({
            "order": p_ord,
            "panels": panels_list
        })

    return templates.TemplateResponse(
        request=request,
        name="lab_console.html",
        context={"results": results, "pending_data": pending_data, "active_page": "lab_console"}
    )

@app.post("/submit-lab-test")
def submit_lab_test(
    order_id: int = Form(...),
    hgb: float = Form(None),
    rbc: float = Form(None),
    mcv: float = Form(None),
    ast: float = Form(None),
    alt: float = Form(None),
    creatinine: float = Form(None),
    tsh: float = Form(None),
    glucose: float = Form(None),
    insulin: float = Form(None),
    db: Session = Depends(get_db)
):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        return RedirectResponse(url="/lab-console", status_code=303)

    patient = order.patient
    result = db.query(ClinicalResult).filter(ClinicalResult.order_id == order.id).first()
    if not result:
        result = ClinicalResult(order_id=order.id)
        db.add(result)

    requested_panels = result.panel_type.split(",") if result.panel_type else ["CBC"]
    flags, reflexes, tubes = [], [], []
    total_added_iqd = 0.0

    # تقييم الفحوصات المطلوبة فقط وتحديث القيم
    if "CBC" in requested_panels and hgb is not None:
        eval_cbc = MasterClinicalEngine.evaluate_hematology(hgb=hgb, rbc=(rbc or 4.5), mcv=(mcv or 80.0), gender=patient.gender)
        result.hgb, result.rbc, result.mcv = hgb, rbc, mcv
        result.mentzer_index = eval_cbc["indices"].get("mentzer")
        flags.append(f"CBC: {eval_cbc['flag']}")
        reflexes.append(eval_cbc['reflex'])
        tubes.append(eval_cbc['tube_alert'])
        total_added_iqd += eval_cbc['added_iqd']

    if "Liver" in requested_panels and ast is not None:
        eval_liv = MasterClinicalEngine.evaluate_liver(ast=ast, alt=(alt or 30.0), age=patient.age)
        result.ast, result.alt = ast, alt
        result.fib4_index = eval_liv["indices"].get("fib4")
        flags.append(f"Liver: {eval_liv['flag']}")
        reflexes.append(eval_liv['reflex'])
        tubes.append(eval_liv['tube_alert'])
        total_added_iqd += eval_liv['added_iqd']

    if "Renal" in requested_panels and creatinine is not None:
        eval_ren = MasterClinicalEngine.evaluate_renal(creatinine=creatinine, age=patient.age, gender=patient.gender)
        result.creatinine = creatinine
        result.egfr_val = eval_ren["indices"].get("egfr")
        flags.append(f"Renal: {eval_ren['flag']}")
        reflexes.append(eval_ren['reflex'])
        tubes.append(eval_ren['tube_alert'])
        total_added_iqd += eval_ren['added_iqd']

    if "Thyroid" in requested_panels and tsh is not None:
        eval_thy = MasterClinicalEngine.evaluate_thyroid(tsh=tsh)
        result.tsh = tsh
        flags.append(f"Thyroid: {eval_thy['flag']}")
        reflexes.append(eval_thy['reflex'])
        tubes.append(eval_thy['tube_alert'])
        total_added_iqd += eval_thy['added_iqd']

    if "Metabolic" in requested_panels and glucose is not None:
        eval_met = MasterClinicalEngine.evaluate_metabolic(glucose=glucose, insulin=(insulin or 10.0))
        result.glucose, result.insulin = glucose, insulin
        result.homa_ir = eval_met["indices"].get("homa_ir")
        flags.append(f"Metabolic: {eval_met['flag']}")
        reflexes.append(eval_met['reflex'])
        tubes.append(eval_met['tube_alert'])
        total_added_iqd += eval_met['added_iqd']

    order.status = "Completed"
    order.add_on_revenue = total_added_iqd
    order.total_revenue = order.base_price + total_added_iqd

    result.clinical_flag = " | ".join(flags) if flags else "مكتمل (طبيعي)"
    result.reflex_order = " | ".join(set(reflexes)) if reflexes else "لا توجد فحوصات ارتكاسية"
    result.tube_alert = " | ".join(set(tubes)) if tubes else "تم حفظ الأنابيب"
    result.added_value_iqd = total_added_iqd

    db.commit()
    return RedirectResponse(url="/lab-console", status_code=303)

# 4. التقرير الطبي وتوليد التوضيحات للواتساب
@app.get("/report/{order_id}", response_class=HTMLResponse)
def print_report(order_id: int, request: Request, patient_phone: str = "", patient_full_name: str = "", db: Session = Depends(get_db)):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        return HTMLResponse("الطلب غير موجود", status_code=404)

    patient = order.patient
    res = order.results
    tests_detail = []
    
    # بناء رسالة الواتساب المفصلة والشاملة
    p_name = patient_full_name if patient_full_name else patient.name
    msg_lines = [
        f"🏥 *التقرير الطبي الصادر من نظام BioRefleX Pro*",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"👤 *اسم المريض:* {p_name}",
        f"🆔 *معرف المريض:* {patient.patient_id}",
        f"📋 *رقم الطلب:* {order.order_code}",
        f"🎂 *العمر / الجنس:* {patient.age} سنة | {patient.gender}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🔬 *تفاصيل الفحوصات والنتائج المخبرية:*"
    ]

    if res:
        if res.hgb is not None:
            tests_detail.append({"name": "Hemoglobin (Hgb)", "val": res.hgb, "ref": "12.0 - 16.0 g/dL"})
            msg_lines.append(f"• هيموغلوبين الدم (Hgb): {res.hgb} g/dL")
        if res.rbc is not None:
            tests_detail.append({"name": "RBC Count", "val": res.rbc, "ref": "4.0 - 5.5 M/µL"})
            msg_lines.append(f"• كريات الدم الحمراء (RBC): {res.rbc} M/µL")
        if res.mcv is not None:
            tests_detail.append({"name": "MCV Index", "val": res.mcv, "ref": "80 - 100 fL"})
            msg_lines.append(f"• الحجم الكريوي المتوسط (MCV): {res.mcv} fL")
        if res.ast is not None:
            tests_detail.append({"name": "AST (SGOT)", "val": res.ast, "ref": "10 - 40 U/L"})
            msg_lines.append(f"• إنزيم الكبد AST: {res.ast} U/L")
        if res.alt is not None:
            tests_detail.append({"name": "ALT (SGPT)", "val": res.alt, "ref": "7 - 56 U/L"})
            msg_lines.append(f"• إنزيم الكبد ALT: {res.alt} U/L")
        if res.creatinine is not None:
            tests_detail.append({"name": "Serum Creatinine", "val": res.creatinine, "ref": "0.6 - 1.2 mg/dL"})
            msg_lines.append(f"• كيراتينين الدم: {res.creatinine} mg/dL")
        if res.tsh is not None:
            tests_detail.append({"name": "TSH", "val": res.tsh, "ref": "0.4 - 4.5 µIU/mL"})
            msg_lines.append(f"• هرمون الغدة الدرقية (TSH): {res.tsh} µIU/mL")
        if res.glucose is not None:
            tests_detail.append({"name": "Fasting Glucose", "val": res.glucose, "ref": "70 - 99 mg/dL"})
            msg_lines.append(f"• السكر الصائم: {res.glucose} mg/dL")

        msg_lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🩺 *التشخيص والفرز السريري:* {res.clinical_flag}",
            f"💡 *التوصيات الارتكاسية (Reflex):* {res.reflex_order}",
            f"🧪 *تنبيه أنابيب الفحص:* {res.tube_alert}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"نتمنى لكم دوام الصحة والعافية."
        ])

    full_whatsapp_msg = "\n".join(msg_lines)
    encoded_message = urllib.parse.quote(full_whatsapp_msg)
    
    # تنظيف رقم الهاتف وإضافة رمز الدولة افتراضياً إن لم يوجد
    clean_phone = patient_phone.strip().replace("+", "").replace(" ", "")
    if clean_phone and not clean_phone.startswith("964"):
        if clean_phone.startswith("07"):
            clean_phone = "964" + clean_phone[1:]

    wa_link = f"https://wa.me/{clean_phone}?text={encoded_message}" if clean_phone else "#"

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "order": order, 
            "patient": patient, 
            "res": res, 
            "tests_detail": tests_detail, 
            "wa_link": wa_link, 
            "patient_phone": patient_phone,
            "patient_full_name": p_name,
            "active_page": "lab_console"
        }
    )

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
# clinical_engine.py
class MasterClinicalEngine:
    @staticmethod
    def evaluate_hematology(hgb, rbc=4.5, mcv=80.0, platelets=250.0, gender="female"):
        flag = "Normal"
        reflex = "None"
        tube_alert = "EDTA (Lavender Tube)"
        added_iqd = 0.0
        mentzer = mcv / rbc if rbc > 0 else 0.0

        if mcv < 80 and mentzer < 13:
            flag = "Microcytic (Possible Thalassemia Minor)"
            reflex = "Hemoglobin Electrophoresis (HbA2/HbF)"
            added_iqd = 15000.0
        elif mcv < 80 and mentzer >= 13:
            flag = "Microcytic (Possible Iron Deficiency Anemia)"
            reflex = "Serum Iron, Ferritin & TIBC"
            added_iqd = 12000.0

        return {
            "flag": flag,
            "reflex": reflex,
            "tube_alert": tube_alert,
            "added_iqd": added_iqd,
            "indices": {"mentzer": mentzer}
        }

    @staticmethod
    def evaluate_liver(ast, alt, age=30):
        flag = "Normal"
        reflex = "None"
        tube_alert = "SST (Yellow/Red Tube)"
        added_iqd = 0.0
        fib4 = (age * ast) / ((alt ** 0.5) * 40.0) if alt > 0 else 0.0

        if fib4 > 3.25:
            flag = "High Risk Liver Fibrosis (F4)"
            reflex = "FibroScan & Gastroenterology Referral"
            added_iqd = 25000.0
        elif fib4 > 1.45:
            flag = "Moderate Liver Fibrosis Risk"
            reflex = "Liver Ultrasound & Repeat Panel"
            added_iqd = 10000.0

        return {
            "flag": flag,
            "reflex": reflex,
            "tube_alert": tube_alert,
            "added_iqd": added_iqd,
            "indices": {"fib4": fib4}
        }

    @staticmethod
    def evaluate_renal(creatinine, age=30, gender="female"):
        flag = "Normal"
        reflex = "None"
        tube_alert = "SST or Heparin Tube"
        added_iqd = 0.0
        kappa = 0.7 if gender.lower() in ["female", "أنثى"] else 0.9
        alpha = -0.329 if gender.lower() in ["female", "أنثى"] else -0.411
        min_val = min(creatinine / kappa, 1.0)
        max_val = max(creatinine / kappa, 1.0)
        
        factor = 1.018 if gender.lower() in ["female", "أنثى"] else 1.0
        egfr = 141 * (min_val ** alpha) * (max_val ** -1.209) * (0.993 ** age) * factor

        if egfr < 60:
            flag = "Reduced eGFR (CKD Stage 3+)"
            reflex = "Urine Albumin-to-Creatinine Ratio (ACR) & Renal Ultrasound"
            added_iqd = 18000.0

        return {
            "flag": flag,
            "reflex": reflex,
            "tube_alert": tube_alert,
            "added_iqd": added_iqd,
            "indices": {"egfr": egfr}
        }

    @staticmethod
    def evaluate_thyroid(tsh):
        flag = "Normal"
        reflex = "None"
        tube_alert = "SST Tube"
        added_iqd = 0.0

        if tsh > 4.5:
            flag = "Possible Hypothyroidism"
            reflex = "Free T4 & Anti-TPO Antibodies"
            added_iqd = 15000.0
        elif tsh < 0.4:
            flag = "Possible Hyperthyroidism"
            reflex = "Free T3, Free T4 & TSH Receptor Antibodies"
            added_iqd = 20000.0

        return {
            "flag": flag,
            "reflex": reflex,
            "tube_alert": tube_alert,
            "added_iqd": added_iqd,
            "indices": {"tsh": tsh}
        }

    @staticmethod
    def evaluate_metabolic(glucose, insulin=10.0):
        flag = "Normal"
        reflex = "None"
        tube_alert = "Sodium Fluoride / SST Tube"
        added_iqd = 0.0
        homa_ir = (glucose * insulin) / 405.0

        if homa_ir > 2.5 or glucose > 126:
            flag = "Insulin Resistance / Hyperglycemia Risk"
            reflex = "HbA1c & Lipid Profile"
            added_iqd = 15000.0

        return {
            "flag": flag,
            "reflex": reflex,
            "tube_alert": tube_alert,
            "added_iqd": added_iqd,
            "indices": {"homa_ir": homa_ir}
        }
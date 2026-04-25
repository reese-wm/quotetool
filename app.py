from datetime import datetime
import re
from urllib.parse import quote as url_quote

from flask import Flask, render_template, request

app = Flask(__name__)

COMPANY_NAME = "Big Valley Heating Ltd."
COMPANY_ADDRESS = "11868 216 St, Maple Ridge, BC, V2X 5H8"
COMPANY_WEBSITE = "www.bigvalleyheating.ca"
GAS_LICENSE = "LGA0003228"
ELECTRICAL_LICENSE = "LEL0100644"
OFFICE_EMAIL = "shopbigvalley@gmail.com"


def parse_number(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


@app.context_processor
def company_context():
    return {
        "company_name": COMPANY_NAME,
        "company_address": COMPANY_ADDRESS,
        "company_website": COMPANY_WEBSITE,
        "gas_license": GAS_LICENSE,
        "electrical_license": ELECTRICAL_LICENSE,
        "office_email": OFFICE_EMAIL,
    }


def build_mailto_link(recipient, subject, body):
    if not recipient:
        return None
    return f"mailto:{recipient}?subject={url_quote(subject)}&body={url_quote(body)}"


def build_install_quote_emails(result):
    customer_name = result.get("customer") or "Customer"
    quote_date = result.get("date") or "today"
    total = "${:,.2f}".format(parse_number(result.get("total")))
    estimator_name = result.get("estimator_name") or "Big Valley Heating"
    estimator_email = result.get("estimator_email") or OFFICE_EMAIL

    customer_subject = f"Big Valley Heating Quote for {customer_name}"
    customer_body = (
        f"Hello {customer_name},\n\n"
        f"Attached is your installation quote dated {quote_date}.\n"
        f"Quoted total: {total}\n\n"
        f"If you have any questions, please reply to {estimator_email}.\n\n"
        f"Thank you,\n"
        f"{estimator_name}\n"
        f"{COMPANY_NAME}\n"
        f"{COMPANY_ADDRESS}\n"
        f"{COMPANY_WEBSITE}"
    )

    office_subject = f"Install Quote Copy - {customer_name} - {quote_date}"
    office_body = (
        f"Office copy of installation quote.\n\n"
        f"Customer: {customer_name}\n"
        f"Date: {quote_date}\n"
        f"Customer Email: {result.get('email') or 'Not provided'}\n"
        f"Estimator: {estimator_name}\n"
        f"Estimator Email: {estimator_email}\n"
        f"Quoted Total: {total}\n"
        f"Model: {result.get('model') or 'Not provided'}\n"
        f"Address: {result.get('address') or 'Not provided'}\n"
    )

    return {
        "customer": build_mailto_link(result.get("email"), customer_subject, customer_body),
        "office": build_mailto_link(OFFICE_EMAIL, office_subject, office_body),
    }


def build_service_bill_emails(result):
    customer_name = result.get("customer") or "Customer"
    service_date = result.get("service_date") or "today"
    total = "${:,.2f}".format(parse_number(result.get("total")))

    customer_subject = f"Big Valley Heating Service Bill for {customer_name}"
    customer_body = (
        f"Hello {customer_name},\n\n"
        f"Attached is your service bill dated {service_date}.\n"
        f"Service total: {total}\n\n"
        f"If you have any questions, please contact {OFFICE_EMAIL}.\n\n"
        f"Thank you,\n"
        f"{COMPANY_NAME}\n"
        f"{COMPANY_ADDRESS}\n"
        f"{COMPANY_WEBSITE}"
    )

    office_subject = f"Service Bill Copy - {customer_name} - {service_date}"
    office_body = (
        f"Office copy of service bill.\n\n"
        f"Customer: {customer_name}\n"
        f"Date: {service_date}\n"
        f"Customer Email: {result.get('email') or 'Not provided'}\n"
        f"Technician: {result.get('technician') or 'Not provided'}\n"
        f"Service Total: {total}\n"
        f"Address: {result.get('address') or 'Not provided'}\n"
        f"Work Completed: {result.get('work_completed') or 'Not provided'}\n"
    )

    return {
        "customer": build_mailto_link(result.get("email"), customer_subject, customer_body),
        "office": build_mailto_link(OFFICE_EMAIL, office_subject, office_body),
    }


def calculate_install_quote(data):
    customer = data.get("customer", "")
    address = data.get("address", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    estimator_name = data.get("estimator_name", "")
    estimator_email = data.get("estimator_email", "")
    date = data.get("date", "")
    notes = data.get("notes", "")
    equipment = parse_number(data.get("equipment"))
    model = data.get("model", "")
    pipe = parse_number(data.get("pipe"))
    lineset = parse_number(data.get("lineset"))
    difficulty = parse_number(data.get("difficulty"), 1)
    electrical = parse_number(data.get("electrical"))
    additional = parse_number(data.get("additional"))
    slim_duct = parse_number(data.get("slim_duct"))
    thermostat = parse_number(data.get("thermostat"))
    sensor = parse_number(data.get("sensor"))
    neutralizer = parse_number(data.get("neutralizer"))
    pad = parse_number(data.get("pad"))
    heat_loss = parse_number(data.get("heat_loss"))

    materials = (equipment * 1.12) + 1000
    freight = 100
    permit = 200
    pipe_cost = pipe * 6
    lineset_cost = lineset * 10
    labour = 1800 * difficulty
    slim_duct_rate = 8
    slim_duct_cost = slim_duct * slim_duct_rate

    subtotal = (
        materials
        + freight
        + permit
        + pipe_cost
        + lineset_cost
        + slim_duct_cost
        + labour
        + electrical
        + additional
        + thermostat
        + sensor
        + neutralizer
        + pad
        + heat_loss
    )

    tax_rate = 0.05
    commission_rate = 0.07

    commission = subtotal * commission_rate
    subtotal_with_commission = subtotal + commission
    tax = subtotal_with_commission * tax_rate
    total = subtotal_with_commission + tax

    return {
        "customer": customer,
        "address": address,
        "phone": phone,
        "email": email,
        "estimator_name": estimator_name,
        "estimator_email": estimator_email,
        "date": date,
        "notes": notes,
        "model": model,
        "materials": materials,
        "freight": freight,
        "permit": permit,
        "pipe_cost": pipe_cost,
        "lineset_cost": lineset_cost,
        "slim_duct_cost": slim_duct_cost,
        "labour": labour,
        "thermostat": thermostat,
        "sensor": sensor,
        "neutralizer": neutralizer,
        "pad": pad,
        "heat_loss": heat_loss,
        "subtotal": subtotal,
        "commission": commission,
        "subtotal_with_commission": subtotal_with_commission,
        "tax": tax,
        "total": total,
    }


def build_service_bill(data):
    customer = data.get("customer", "")
    address = data.get("address", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    service_date = data.get("service_date", "")
    technician = data.get("technician", "")
    work_completed = data.get("work_completed", "")
    materials_used = data.get("materials_used", "")
    callout_fee = parse_number(data.get("callout_fee"))
    labour = parse_number(data.get("labour"))
    parts = parse_number(data.get("parts"))
    misc = parse_number(data.get("misc"))
    tax_rate = parse_number(data.get("tax_rate"), 5)
    payment_terms = data.get("payment_terms", "Due upon receipt")

    subtotal = callout_fee + labour + parts + misc
    tax = subtotal * (tax_rate / 100)
    total = subtotal + tax

    return {
        "customer": customer,
        "address": address,
        "phone": phone,
        "email": email,
        "service_date": service_date,
        "technician": technician,
        "work_completed": work_completed,
        "materials_used": materials_used,
        "callout_fee": callout_fee,
        "labour": labour,
        "parts": parts,
        "misc": misc,
        "tax_rate": tax_rate,
        "tax": tax,
        "subtotal": subtotal,
        "total": total,
        "payment_terms": payment_terms,
    }


def build_po_number(customer_name, order_date):
    clean_name = re.sub(r"[^A-Z0-9]", "", customer_name.upper())
    customer_code = (clean_name[:4] or "CUST").ljust(4, "X")

    try:
        date_code = datetime.strptime(order_date, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        date_code = datetime.now().strftime("%Y%m%d")

    return f"PO-{customer_code}-{date_code}"


def build_purchase_order(data):
    customer = data.get("customer", "")
    vendor = data.get("vendor", "")
    order_date = data.get("order_date", "")
    requested_by = data.get("requested_by", "")
    job_reference = data.get("job_reference", "")
    item_description = data.get("item_description", "")
    notes = data.get("notes", "")
    amount = parse_number(data.get("amount"))
    po_number = build_po_number(customer, order_date)

    return {
        "po_number": po_number,
        "customer": customer,
        "vendor": vendor,
        "order_date": order_date,
        "requested_by": requested_by,
        "job_reference": job_reference,
        "item_description": item_description,
        "notes": notes,
        "amount": amount,
    }


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/install-quote", methods=["GET", "POST"])
def install_quote():
    result = None
    if request.method == "POST":
        result = calculate_install_quote(request.form)
    return render_template("furnace.html", result=result)


@app.route("/quote", methods=["POST"])
def quote():
    result = request.form.to_dict()
    email_links = build_install_quote_emails(result)
    return render_template("quote.html", result=result, email_links=email_links)


@app.route("/service-quote", methods=["GET", "POST"])
def service_quote():
    if request.method == "POST":
        result = build_service_bill(request.form)
        email_links = build_service_bill_emails(result)
        return render_template("service_bill.html", result=result, email_links=email_links)
    return render_template("service_quote.html")


@app.route("/purchase-order", methods=["GET", "POST"])
def purchase_order():
    if request.method == "POST":
        result = build_purchase_order(request.form)
        return render_template("purchase_order.html", result=result)
    return render_template("purchase_order_form.html")


if __name__ == "__main__":
    app.run(debug=True)

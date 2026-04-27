from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
import os
import re
import smtplib

from flask import Flask, render_template, request, send_file
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)

COMPANY_NAME = "Big Valley Heating Ltd."
COMPANY_ADDRESS = "11868 216 St, Maple Ridge, BC, V2X 5H8"
COMPANY_WEBSITE = "www.bigvalleyheating.ca"
GAS_LICENSE = "LGA0003228"
ELECTRICAL_LICENSE = "LEL0100644"
OFFICE_EMAIL = "shopbigvalley@gmail.com"


def load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_local_env()


def parse_number(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


def format_currency(value):
    return "${:,.2f}".format(parse_number(value))


def safe_filename(value, fallback):
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip()).strip("-").lower()
    return cleaned or fallback


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def smtp_config():
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "username": os.getenv("SMTP_USERNAME", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": os.getenv("SMTP_FROM_EMAIL", "") or os.getenv("SMTP_USERNAME", ""),
        "use_tls": env_flag("SMTP_USE_TLS", True),
    }


def smtp_is_ready():
    config = smtp_config()
    return bool(config["host"] and config["port"] and config["from_email"])


def ensure_space(pdf, current_y, needed_height):
    if current_y - needed_height < 54:
        pdf.showPage()
        return 752
    return current_y


def draw_line(pdf, text, x, y, font_name="Helvetica", font_size=10):
    pdf.setFont(font_name, font_size)
    pdf.drawString(x, y, text)


def draw_paragraph(pdf, text, x, y, width=470, font_name="Helvetica", font_size=10, leading=14):
    text_object = pdf.beginText(x, y)
    text_object.setFont(font_name, font_size)

    words = (text or "").split()
    if not words:
        pdf.drawText(text_object)
        return y - leading

    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if pdf.stringWidth(candidate, font_name, font_size) <= width:
            line = candidate
        else:
            text_object.textLine(line)
            line = word
    if line:
        text_object.textLine(line)

    pdf.drawText(text_object)
    return text_object.getY() - 2


def build_pdf_response(filename, builder):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    builder(pdf)
    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


def draw_company_header(pdf, document_title, reference_text):
    pdf.setTitle(document_title)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(54, 752, COMPANY_NAME)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(54, 736, COMPANY_ADDRESS)
    pdf.drawString(54, 722, COMPANY_WEBSITE)
    pdf.drawString(54, 708, f"Gas Contractor License: {GAS_LICENSE}")
    pdf.drawString(54, 694, f"Electrical Contractor License: {ELECTRICAL_LICENSE}")

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawRightString(558, 752, document_title)
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(558, 736, reference_text)
    pdf.line(54, 682, 558, 682)
    return 660


def render_install_quote_pdf(result):
    customer_name = result.get("customer") or "customer"
    filename = f"install-quote-{safe_filename(customer_name, 'customer')}.pdf"

    def builder(pdf):
        y = draw_company_header(
            pdf,
            "Installation Quote",
            f"Prepared for {result.get('customer') or 'Customer'}",
        )

        left_lines = [
            f"Customer: {result.get('customer') or 'Not provided'}",
            f"Job Site: {result.get('address') or 'Not provided'}",
            f"Phone: {result.get('phone') or 'Not provided'}",
            f"Email: {result.get('email') or 'Not provided'}",
        ]
        right_lines = [
            f"Date: {result.get('date') or 'Not provided'}",
            f"Estimator: {result.get('estimator_name') or 'Not provided'}",
            f"Estimator Email: {result.get('estimator_email') or 'Not provided'}",
            f"Model: {result.get('model') or 'Not provided'}",
        ]

        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Customer Details")
        pdf.drawString(324, y, "Quote Details")
        y -= 18
        for index in range(max(len(left_lines), len(right_lines))):
            if index < len(left_lines):
                draw_line(pdf, left_lines[index], 54, y)
            if index < len(right_lines):
                draw_line(pdf, right_lines[index], 324, y)
            y -= 14

        y -= 6
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Pricing Summary")
        y -= 18
        pricing_lines = [
            ("Installation Package", format_currency(result.get("subtotal_with_commission"))),
            ("GST (5%)", format_currency(result.get("tax"))),
            ("Total", format_currency(result.get("total"))),
        ]
        for label, value in pricing_lines:
            draw_line(pdf, label, 54, y)
            pdf.drawRightString(558, y, value)
            y -= 14

        y -= 10
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Job Notes")
        y -= 18
        y = draw_paragraph(pdf, result.get("notes") or "No additional notes provided.", 54, y)

        y -= 18
        y = ensure_space(pdf, y, 110)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Terms")
        y -= 18
        y = draw_paragraph(
            pdf,
            "Payment due upon receipt of invoice. A 50% deposit plus GST is required upon acceptance, with the balance due upon completion.",
            54,
            y,
        )
        y -= 8
        y = draw_paragraph(
            pdf,
            "Please confirm equipment is registered to receive any available extended warranties.",
            54,
            y,
        )
        y -= 8
        draw_paragraph(
            pdf,
            "This proposal may be withdrawn if not accepted within 15 days.",
            54,
            y,
        )

    return build_pdf_response(filename, builder)


def render_service_bill_pdf(result):
    customer_name = result.get("customer") or "customer"
    filename = f"service-bill-{safe_filename(customer_name, 'customer')}.pdf"

    def builder(pdf):
        y = draw_company_header(
            pdf,
            "Service Bill",
            f"Prepared for {result.get('customer') or 'Customer'}",
        )

        left_lines = [
            f"Customer: {result.get('customer') or 'Not provided'}",
            f"Service Address: {result.get('address') or 'Not provided'}",
            f"Phone: {result.get('phone') or 'Not provided'}",
            f"Email: {result.get('email') or 'Not provided'}",
        ]
        right_lines = [
            f"Service Date: {result.get('service_date') or 'Not provided'}",
            f"Technician: {result.get('technician') or 'Not provided'}",
            f"Payment Terms: {result.get('payment_terms') or 'Not provided'}",
        ]

        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Customer Details")
        pdf.drawString(324, y, "Service Details")
        y -= 18
        for index in range(max(len(left_lines), len(right_lines))):
            if index < len(left_lines):
                draw_line(pdf, left_lines[index], 54, y)
            if index < len(right_lines):
                draw_line(pdf, right_lines[index], 324, y)
            y -= 14

        y -= 6
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Charges")
        y -= 18
        charge_lines = [
            ("Call-Out Fee", format_currency(result.get("callout_fee"))),
            ("Labour", format_currency(result.get("labour"))),
            ("Parts", format_currency(result.get("parts"))),
            ("Miscellaneous", format_currency(result.get("misc"))),
            ("Subtotal", format_currency(result.get("subtotal"))),
            (f"Tax ({parse_number(result.get('tax_rate')):.2f}%)", format_currency(result.get("tax"))),
            ("Total", format_currency(result.get("total"))),
        ]
        for label, value in charge_lines:
            draw_line(pdf, label, 54, y)
            pdf.drawRightString(558, y, value)
            y -= 14

        y -= 10
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Work Completed")
        y -= 18
        y = draw_paragraph(pdf, result.get("work_completed") or "No work summary entered.", 54, y)

        y -= 18
        y = ensure_space(pdf, y, 80)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Materials / Parts Notes")
        y -= 18
        draw_paragraph(pdf, result.get("materials_used") or "No materials or part notes entered.", 54, y)

    return build_pdf_response(filename, builder)


def render_purchase_order_pdf(result):
    customer_name = result.get("customer") or "customer"
    filename = f"purchase-order-{safe_filename(customer_name, 'customer')}.pdf"

    def builder(pdf):
        y = draw_company_header(
            pdf,
            "Purchase Order",
            result.get("po_number") or "PO reference",
        )

        detail_lines = [
            f"PO Number: {result.get('po_number') or 'Not provided'}",
            f"Customer: {result.get('customer') or 'Not provided'}",
            f"Vendor: {result.get('vendor') or 'Not provided'}",
            f"Order Date: {result.get('order_date') or 'Not provided'}",
            f"Requested By: {result.get('requested_by') or 'Not provided'}",
            f"Job Reference: {result.get('job_reference') or 'Not provided'}",
            f"Order Amount: {format_currency(result.get('amount'))}",
        ]
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Order Details")
        y -= 18
        for line in detail_lines:
            draw_line(pdf, line, 54, y)
            y -= 14

        y -= 10
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Item Description")
        y -= 18
        y = draw_paragraph(pdf, result.get("item_description") or "No item description entered.", 54, y)

        y -= 18
        y = ensure_space(pdf, y, 80)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Notes")
        y -= 18
        draw_paragraph(pdf, result.get("notes") or "No additional notes entered.", 54, y)

    return build_pdf_response(filename, builder)


@app.context_processor
def company_context():
    return {
        "company_name": COMPANY_NAME,
        "company_address": COMPANY_ADDRESS,
        "company_website": COMPANY_WEBSITE,
        "gas_license": GAS_LICENSE,
        "electrical_license": ELECTRICAL_LICENSE,
        "office_email": OFFICE_EMAIL,
        "smtp_ready": smtp_is_ready(),
    }


def send_smtp_email(recipient, subject, body, reply_to=None):
    config = smtp_config()

    if not smtp_is_ready():
        return False, "SMTP is not configured yet."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["from_email"]
    message["To"] = recipient
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=20) as server:
            if config["use_tls"]:
                server.starttls()
            if config["username"] and config["password"]:
                server.login(config["username"], config["password"])
            server.send_message(message)
        return True, f"Email sent to {recipient}."
    except Exception as exc:
        return False, f"Email failed: {exc}"


def build_install_quote_email_content(result, send_to_office=False):
    customer_name = result.get("customer") or "Customer"
    quote_date = result.get("date") or "today"
    total = "${:,.2f}".format(parse_number(result.get("total")))
    estimator_name = result.get("estimator_name") or "Big Valley Heating"
    estimator_email = result.get("estimator_email") or OFFICE_EMAIL

    if send_to_office:
        return {
            "recipient": OFFICE_EMAIL,
            "reply_to": estimator_email,
            "subject": f"Install Quote Copy - {customer_name} - {quote_date}",
            "body": (
                f"Office copy of installation quote.\n\n"
                f"Customer: {customer_name}\n"
                f"Date: {quote_date}\n"
                f"Customer Email: {result.get('email') or 'Not provided'}\n"
                f"Estimator: {estimator_name}\n"
                f"Estimator Email: {estimator_email}\n"
                f"Quoted Total: {total}\n"
                f"Model: {result.get('model') or 'Not provided'}\n"
                f"Address: {result.get('address') or 'Not provided'}\n"
                f"Job Notes: {result.get('notes') or 'None'}\n"
            ),
        }

    return {
        "recipient": result.get("email") or "",
        "reply_to": estimator_email,
        "subject": f"Big Valley Heating Quote for {customer_name}",
        "body": (
            f"Hello {customer_name},\n\n"
            f"Here is your installation quote dated {quote_date}.\n"
            f"Quoted total: {total}\n"
            f"Model: {result.get('model') or 'Not provided'}\n"
            f"Job site: {result.get('address') or 'Not provided'}\n\n"
            f"If you have any questions, please reply to {estimator_email}.\n\n"
            f"Thank you,\n"
            f"{estimator_name}\n"
            f"{COMPANY_NAME}\n"
            f"{COMPANY_ADDRESS}\n"
            f"{COMPANY_WEBSITE}\n"
            f"Gas Contractor License: {GAS_LICENSE}\n"
            f"Electrical Contractor License: {ELECTRICAL_LICENSE}"
        ),
    }


def build_service_bill_email_content(result, send_to_office=False):
    customer_name = result.get("customer") or "Customer"
    service_date = result.get("service_date") or "today"
    total = "${:,.2f}".format(parse_number(result.get("total")))

    if send_to_office:
        return {
            "recipient": OFFICE_EMAIL,
            "reply_to": OFFICE_EMAIL,
            "subject": f"Service Bill Copy - {customer_name} - {service_date}",
            "body": (
                f"Office copy of service bill.\n\n"
                f"Customer: {customer_name}\n"
                f"Date: {service_date}\n"
                f"Customer Email: {result.get('email') or 'Not provided'}\n"
                f"Technician: {result.get('technician') or 'Not provided'}\n"
                f"Service Total: {total}\n"
                f"Address: {result.get('address') or 'Not provided'}\n"
                f"Work Completed: {result.get('work_completed') or 'Not provided'}\n"
                f"Materials / Parts Notes: {result.get('materials_used') or 'None'}\n"
            ),
        }

    return {
        "recipient": result.get("email") or "",
        "reply_to": OFFICE_EMAIL,
        "subject": f"Big Valley Heating Service Bill for {customer_name}",
        "body": (
            f"Hello {customer_name},\n\n"
            f"Here is your service bill dated {service_date}.\n"
            f"Service total: {total}\n"
            f"Technician: {result.get('technician') or 'Not provided'}\n"
            f"Service address: {result.get('address') or 'Not provided'}\n\n"
            f"If you have any questions, please contact {OFFICE_EMAIL}.\n\n"
            f"Thank you,\n"
            f"{COMPANY_NAME}\n"
            f"{COMPANY_ADDRESS}\n"
            f"{COMPANY_WEBSITE}\n"
            f"Gas Contractor License: {GAS_LICENSE}\n"
            f"Electrical Contractor License: {ELECTRICAL_LICENSE}"
        ),
    }


def send_quote_email(result, quote_kind, send_to_office=False):
    if quote_kind == "install":
        payload = build_install_quote_email_content(result, send_to_office=send_to_office)
    else:
        payload = build_service_bill_email_content(result, send_to_office=send_to_office)

    recipient = payload["recipient"]
    if not recipient:
        return False, "No recipient email is available for this quote."

    return send_smtp_email(
        recipient=recipient,
        subject=payload["subject"],
        body=payload["body"],
        reply_to=payload["reply_to"],
    )


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
    return render_template("quote.html", result=result)


@app.route("/quote/email", methods=["POST"])
def send_install_quote_email():
    result = request.form.to_dict()
    send_to_office = request.form.get("send_target") == "office"
    email_status_ok, email_status_message = send_quote_email(
        result,
        quote_kind="install",
        send_to_office=send_to_office,
    )
    return render_template(
        "quote.html",
        result=result,
        email_status_ok=email_status_ok,
        email_status_message=email_status_message,
    )


@app.route("/quote/pdf", methods=["POST"])
def install_quote_pdf():
    result = request.form.to_dict()
    return render_install_quote_pdf(result)


@app.route("/service-quote", methods=["GET", "POST"])
def service_quote():
    if request.method == "POST":
        result = build_service_bill(request.form)
        return render_template("service_bill.html", result=result)
    return render_template("service_quote.html")


@app.route("/service-quote/email", methods=["POST"])
def send_service_bill_email():
    result = build_service_bill(request.form)
    send_to_office = request.form.get("send_target") == "office"
    email_status_ok, email_status_message = send_quote_email(
        result,
        quote_kind="service",
        send_to_office=send_to_office,
    )
    return render_template(
        "service_bill.html",
        result=result,
        email_status_ok=email_status_ok,
        email_status_message=email_status_message,
    )


@app.route("/service-quote/pdf", methods=["POST"])
def service_bill_pdf():
    result = build_service_bill(request.form)
    return render_service_bill_pdf(result)


@app.route("/purchase-order", methods=["GET", "POST"])
def purchase_order():
    if request.method == "POST":
        result = build_purchase_order(request.form)
        return render_template("purchase_order.html", result=result)
    return render_template("purchase_order_form.html")


@app.route("/purchase-order/pdf", methods=["POST"])
def purchase_order_pdf():
    result = build_purchase_order(request.form)
    return render_purchase_order_pdf(result)


if __name__ == "__main__":
    app.run(debug=True)

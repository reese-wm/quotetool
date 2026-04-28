from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
import os
import re
import smtplib
from urllib.parse import quote as url_quote

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
PERMIT_OPTIONS = {
    "0": "No Permit",
    "200_gas": "Gas Permit",
    "200_electrical": "Electrical Permit",
    "400_both": "Gas & Electrical Permit",
}


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


def normalize_upper_text(value):
    return (value or "").strip().upper()


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
        "password": "".join(os.getenv("SMTP_PASSWORD", "").split()),
        "from_email": os.getenv("SMTP_FROM_EMAIL", "") or os.getenv("SMTP_USERNAME", ""),
        "use_tls": env_flag("SMTP_USE_TLS", True),
    }


def smtp_is_ready():
    config = smtp_config()
    return bool(config["host"] and config["port"] and config["from_email"])


def build_mailto_link(recipient, subject, body):
    return f"mailto:{recipient}?subject={url_quote(subject)}&body={url_quote(body)}"


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


def build_pdf_bytes(builder):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    builder(pdf)
    pdf.save()
    return buffer.getvalue()


def build_pdf_response(filename, builder):
    pdf_bytes = build_pdf_bytes(builder)
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


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


def deliver_office_copy(result, quote_kind, pdf_builder):
    filename, pdf_bytes = pdf_builder(result)

    if smtp_is_ready():
        return send_quote_email(
            result,
            quote_kind=quote_kind,
            send_to_office=True,
            attachments=[
                {
                    "filename": filename,
                    "content": pdf_bytes,
                    "maintype": "application",
                    "subtype": "pdf",
                }
            ],
        )

    return False, "Office email skipped because SMTP is not configured."


def build_install_quote_pdf_document(result):
    customer_name = result.get("customer") or "customer"
    filename = f"install-quote-{safe_filename(customer_name, 'customer')}.pdf"
    model_text = normalize_upper_text(result.get("model")) or "NOT PROVIDED"
    notes_text = normalize_upper_text(result.get("notes")) or "NO ADDITIONAL NOTES PROVIDED."

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
            f"Model: {model_text}",
        ]
        permit_label = result.get("permit_label")
        if permit_label and permit_label != "No Permit":
            right_lines.append(f"Includes: {permit_label}")

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
        y = draw_paragraph(pdf, notes_text, 54, y)

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

    return filename, build_pdf_bytes(builder)


def render_install_quote_pdf(result):
    filename, pdf_bytes = build_install_quote_pdf_document(result)
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


def build_service_bill_pdf_document(result):
    customer_name = result.get("customer") or "customer"
    filename = f"service-bill-{safe_filename(customer_name, 'customer')}.pdf"
    equipment_model = normalize_upper_text(result.get("equipment_model")) or "NOT ENTERED"
    equipment_serial = normalize_upper_text(result.get("equipment_serial")) or "NOT ENTERED"
    work_completed = normalize_upper_text(result.get("work_completed")) or "NO WORK SUMMARY ENTERED."
    materials_used = normalize_upper_text(result.get("materials_used")) or "NO MATERIALS OR PART NOTES ENTERED."

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
        pdf.drawString(54, y, "Equipment")
        y -= 18
        draw_line(pdf, f"Model Number: {equipment_model}", 54, y)
        y -= 14
        draw_line(pdf, f"Serial Number: {equipment_serial}", 54, y)
        y -= 20

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
        y = draw_paragraph(pdf, work_completed, 54, y)

        y -= 18
        y = ensure_space(pdf, y, 80)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, "Materials / Parts Notes")
        y -= 18
        draw_paragraph(pdf, materials_used, 54, y)

    return filename, build_pdf_bytes(builder)


def render_service_bill_pdf(result):
    filename, pdf_bytes = build_service_bill_pdf_document(result)
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


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


def send_smtp_email(recipient, subject, body, reply_to=None, attachments=None):
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
    for attachment in attachments or []:
        message.add_attachment(
            attachment["content"],
            maintype=attachment.get("maintype", "application"),
            subtype=attachment.get("subtype", "octet-stream"),
            filename=attachment["filename"],
        )

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
    model_text = normalize_upper_text(result.get("model")) or "NOT PROVIDED"
    notes_text = normalize_upper_text(result.get("notes")) or "NONE"

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
                f"Model: {model_text}\n"
                f"Address: {result.get('address') or 'Not provided'}\n"
                f"Job Notes: {notes_text}\n"
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
            f"Model: {model_text}\n"
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


def build_install_quote_customer_mailto(result):
    customer_name = result.get("customer") or "Customer"
    quote_date = result.get("date") or datetime.now().strftime("%Y-%m-%d")
    total = format_currency(result.get("total"))
    customer_email = result.get("email") or "Not provided"
    model_text = normalize_upper_text(result.get("model")) or "NOT PROVIDED"
    notes_text = normalize_upper_text(result.get("notes")) or "NONE"

    subject = f"Customer Quote Draft - {customer_name} - {quote_date}"
    body = (
        f"Please send this installation quote to the customer.\n\n"
        f"Customer: {customer_name}\n"
        f"Customer Email: {customer_email}\n"
        f"Job Site: {result.get('address') or 'Not provided'}\n"
        f"Quote Date: {quote_date}\n"
        f"Quoted Total: {total}\n"
        f"Model: {model_text}\n"
        f"Estimator: {result.get('estimator_name') or 'Not provided'}\n"
        f"Estimator Email: {result.get('estimator_email') or 'Not provided'}\n"
        f"Notes: {notes_text}\n"
    )
    return build_mailto_link(OFFICE_EMAIL, subject, body)


def build_service_bill_email_content(result, send_to_office=False):
    customer_name = result.get("customer") or "Customer"
    service_date = result.get("service_date") or "today"
    total = "${:,.2f}".format(parse_number(result.get("total")))
    equipment_model = normalize_upper_text(result.get("equipment_model")) or "NOT ENTERED"
    equipment_serial = normalize_upper_text(result.get("equipment_serial")) or "NOT ENTERED"
    work_completed = normalize_upper_text(result.get("work_completed")) or "NOT PROVIDED"
    materials_used = normalize_upper_text(result.get("materials_used")) or "NONE"

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
                f"Equipment Model: {equipment_model}\n"
                f"Equipment Serial: {equipment_serial}\n"
                f"Work Completed: {work_completed}\n"
                f"Materials / Parts Notes: {materials_used}\n"
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
            f"Equipment model: {equipment_model}\n"
            f"Equipment serial: {equipment_serial}\n\n"
            f"If you have any questions, please contact {OFFICE_EMAIL}.\n\n"
            f"Thank you,\n"
            f"{COMPANY_NAME}\n"
            f"{COMPANY_ADDRESS}\n"
            f"{COMPANY_WEBSITE}\n"
            f"Gas Contractor License: {GAS_LICENSE}\n"
            f"Electrical Contractor License: {ELECTRICAL_LICENSE}"
        ),
    }


def build_service_bill_customer_mailto(result):
    customer_name = result.get("customer") or "Customer"
    service_date = result.get("service_date") or datetime.now().strftime("%Y-%m-%d")
    total = format_currency(result.get("total"))
    customer_email = result.get("email") or "Not provided"
    equipment_model = normalize_upper_text(result.get("equipment_model")) or "NOT ENTERED"
    equipment_serial = normalize_upper_text(result.get("equipment_serial")) or "NOT ENTERED"
    work_completed = normalize_upper_text(result.get("work_completed")) or "NOT PROVIDED"
    materials_used = normalize_upper_text(result.get("materials_used")) or "NONE"

    subject = f"Customer Service Bill Draft - {customer_name} - {service_date}"
    body = (
        f"Please send this service bill to the customer.\n\n"
        f"Customer: {customer_name}\n"
        f"Customer Email: {customer_email}\n"
        f"Service Address: {result.get('address') or 'Not provided'}\n"
        f"Service Date: {service_date}\n"
        f"Service Total: {total}\n"
        f"Technician: {result.get('technician') or 'Not provided'}\n"
        f"Equipment Model: {equipment_model}\n"
        f"Equipment Serial: {equipment_serial}\n"
        f"Work Completed: {work_completed}\n"
        f"Materials / Parts Notes: {materials_used}\n"
    )
    return build_mailto_link(OFFICE_EMAIL, subject, body)


def send_quote_email(result, quote_kind, send_to_office=False, attachments=None):
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
        attachments=attachments,
    )


def calculate_install_quote(data):
    customer = data.get("customer", "")
    address = data.get("address", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    estimator_name = data.get("estimator_name", "")
    estimator_email = data.get("estimator_email", "")
    date = data.get("date", "")
    notes = normalize_upper_text(data.get("notes", ""))
    equipment = parse_number(data.get("equipment"))
    model = normalize_upper_text(data.get("model", ""))
    pipe = parse_number(data.get("pipe"))
    lineset = parse_number(data.get("lineset"))
    permit_option = data.get("permit_option", "0")
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
    permit = parse_number((permit_option or "0").split("_", 1)[0])
    permit_label = PERMIT_OPTIONS.get(permit_option, "No Permit")
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
        "permit_label": permit_label,
        "permit_option": permit_option,
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
    work_completed = normalize_upper_text(data.get("work_completed", ""))
    materials_used = normalize_upper_text(data.get("materials_used", ""))
    equipment_model = normalize_upper_text(data.get("equipment_model", ""))
    equipment_serial = normalize_upper_text(data.get("equipment_serial", ""))
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
        "equipment_model": equipment_model,
        "equipment_serial": equipment_serial,
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
    return render_template(
        "quote.html",
        result=result,
        customer_mailto_link=build_install_quote_customer_mailto(result),
    )


@app.route("/quote/email", methods=["POST"])
def send_install_quote_email():
    result = request.form.to_dict()
    send_to_office = request.form.get("send_target") == "office"
    if send_to_office:
        email_status_ok, email_status_message = deliver_office_copy(
            result,
            quote_kind="install",
            pdf_builder=build_install_quote_pdf_document,
        )
    else:
        email_status_ok, email_status_message = send_quote_email(
            result,
            quote_kind="install",
            send_to_office=False,
        )
    return render_template(
        "quote.html",
        result=result,
        customer_mailto_link=build_install_quote_customer_mailto(result),
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
        return render_template(
            "service_bill.html",
            result=result,
            customer_mailto_link=build_service_bill_customer_mailto(result),
        )
    return render_template("service_quote.html")


@app.route("/service-quote/email", methods=["POST"])
def send_service_bill_email():
    result = build_service_bill(request.form)
    send_to_office = request.form.get("send_target") == "office"
    if send_to_office:
        email_status_ok, email_status_message = deliver_office_copy(
            result,
            quote_kind="service",
            pdf_builder=build_service_bill_pdf_document,
        )
    else:
        email_status_ok, email_status_message = send_quote_email(
            result,
            quote_kind="service",
            send_to_office=False,
        )
    return render_template(
        "service_bill.html",
        result=result,
        customer_mailto_link=build_service_bill_customer_mailto(result),
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

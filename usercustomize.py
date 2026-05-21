from functools import wraps
import mimetypes
import os
import re

try:
    from flask import Flask
except ImportError:
    Flask = None


PHOTO_UPLOAD_FIELD = "photos"
MAX_OFFICE_PHOTOS = 12


def safe_attachment_filename(value, fallback):
    name = os.path.basename((value or "").strip())
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return cleaned or fallback


def build_photo_attachments(files):
    attachments = []
    skipped_names = []
    uploads = list(files or [])

    for upload in uploads[:MAX_OFFICE_PHOTOS]:
        original_name = upload.filename or ""
        if not original_name:
            continue

        content_type = upload.mimetype or mimetypes.guess_type(original_name)[0] or ""
        if not content_type.startswith("image/"):
            skipped_names.append(original_name)
            continue

        content = upload.read()
        if not content:
            skipped_names.append(original_name)
            continue

        maintype, subtype = content_type.split("/", 1)
        attachments.append(
            {
                "filename": safe_attachment_filename(original_name, f"photo-{len(attachments) + 1}.jpg"),
                "content": content,
                "maintype": maintype,
                "subtype": subtype,
            }
        )

    remaining_files = uploads[MAX_OFFICE_PHOTOS:]
    skipped_count = len(skipped_names) + len([upload for upload in remaining_files if upload.filename])
    return attachments, skipped_count


def append_photo_status(message, photo_count, skipped_count):
    if photo_count:
        plural = "" if photo_count == 1 else "s"
        message = f"{message} Attached {photo_count} photo{plural}."
    if skipped_count:
        plural = "" if skipped_count == 1 else "s"
        message = f"{message} {skipped_count} upload{plural} skipped because only photos are attached."
    return message


def build_office_delivery(module_globals, result, quote_kind, pdf_builder_name):
    photo_attachments, skipped_photo_count = build_photo_attachments(
        module_globals["request"].files.getlist(PHOTO_UPLOAD_FIELD)
    )

    if not module_globals["smtp_is_ready"]():
        return False, "Office email skipped because SMTP is not configured."

    filename, pdf_bytes = module_globals[pdf_builder_name](result)
    email_status_ok, email_status_message = module_globals["send_quote_email"](
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
        ]
        + photo_attachments,
    )
    return email_status_ok, append_photo_status(
        email_status_message,
        len(photo_attachments) if email_status_ok else 0,
        skipped_photo_count,
    )


def wrap_install_email_route(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        module_globals = func.__globals__
        request = module_globals["request"]
        if request.form.get("send_target") != "office":
            return func(*args, **kwargs)

        result = request.form.to_dict()
        email_status_ok, email_status_message = build_office_delivery(
            module_globals,
            result,
            "install",
            "build_install_quote_pdf_document",
        )
        return module_globals["render_template"](
            "quote.html",
            result=result,
            customer_mailto_link=module_globals["build_install_quote_customer_mailto"](result),
            email_status_ok=email_status_ok,
            email_status_message=email_status_message,
        )

    return wrapped


def wrap_service_email_route(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        module_globals = func.__globals__
        request = module_globals["request"]
        if request.form.get("send_target") != "office":
            return func(*args, **kwargs)

        result = module_globals["build_service_bill"](request.form)
        email_status_ok, email_status_message = build_office_delivery(
            module_globals,
            result,
            "service",
            "build_service_bill_pdf_document",
        )
        return module_globals["render_template"](
            "service_bill.html",
            result=result,
            customer_mailto_link=module_globals["build_service_bill_customer_mailto"](result),
            email_status_ok=email_status_ok,
            email_status_message=email_status_message,
        )

    return wrapped


if Flask is not None:
    original_route = Flask.route

    def photo_route(self, rule, **options):
        decorator = original_route(self, rule, **options)

        def wrapped_decorator(func):
            if rule == "/quote/email":
                func = wrap_install_email_route(func)
            elif rule == "/service-quote/email":
                func = wrap_service_email_route(func)
            return decorator(func)

        return wrapped_decorator

    Flask.route = photo_route

import importlib.abc
import importlib.machinery
import os
import re
import socket
import smtplib
import sys

try:
    from reportlab.pdfgen.canvas import Canvas
except ImportError:
    Canvas = None


def _create_ipv4_socket(host, port, timeout, source_address=None):
    last_error = None
    address_info = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)

    for family, socktype, proto, _, sockaddr in address_info:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            if sock:
                sock.close()

    if last_error:
        raise last_error
    raise OSError(f"No IPv4 address found for SMTP host {host}.")


def _smtp_get_ipv4_socket(self, host, port, timeout):
    return _create_ipv4_socket(
        host,
        port,
        timeout,
        getattr(self, "source_address", None),
    )


smtplib.SMTP._get_socket = _smtp_get_ipv4_socket


def _install_calendar_jobs_route(app_module):
    flask_app = getattr(app_module, "app", None)
    if flask_app is None:
        return
    route_exists = "service_quote_calendar_jobs" in flask_app.view_functions

    def _calendar_ids():
        ids_text = os.getenv("GOOGLE_CALENDAR_IDS") or os.getenv("GOOGLE_CALENDAR_ID", "")
        return [value.strip() for value in re.split(r"[,;\n]+", ids_text) if value.strip()]

    def _calendar_status():
        if getattr(app_module, "service_account", None) is None or getattr(app_module, "build", None) is None:
            return False, "Google Calendar libraries are not installed yet."
        if not os.getenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON") and not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and not os.getenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE") and not os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"):
            return False, "Add a Google Calendar service account JSON secret and GOOGLE_CALENDAR_ID to enable job import."
        service_account_file = os.getenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
        if service_account_file and not os.path.exists(service_account_file):
            return False, "Google Calendar service account file could not be found on this server."
        if not _calendar_ids():
            return False, "Add GOOGLE_CALENDAR_ID or GOOGLE_CALENDAR_IDS to enable job import."
        return True, ""

    def _calendar_service():
        ready, message = _calendar_status()
        if not ready:
            raise RuntimeError(message)

        service_account_json = os.getenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        service_account_file = os.getenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
        if service_account_json:
            credentials = app_module.service_account.Credentials.from_service_account_info(
                app_module.json.loads(service_account_json),
                scopes=[app_module.GOOGLE_CALENDAR_SCOPE],
            )
        else:
            credentials = app_module.service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=[app_module.GOOGLE_CALENDAR_SCOPE],
            )

        return app_module.build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def _description_lines(description):
        cleaned = re.sub(r"<br\s*/?>", "\n", description or "", flags=re.IGNORECASE)
        cleaned = re.sub(r"</p\s*>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        return [line.strip(" -") for line in cleaned.splitlines() if line.strip()]

    def _work_completed(description):
        for line in _description_lines(description):
            if (
                not re.search(r"\b(morning|afternoon|evening)\s+appointment\b", line, re.IGNORECASE)
                and not re.match(r"^(entered by|confirmed|location|view map|guests|when|where|calendar)\b", line, re.IGNORECASE)
                and not app_module.EMAIL_PATTERN.search(line)
            ):
                return line
        return ""

    def _transform_event(event):
        job = app_module.transform_calendar_event(event)
        start_data = event.get("start", {})
        job["work_completed"] = _work_completed(event.get("description", ""))
        job["sort_key"] = start_data.get("dateTime") or start_data.get("date") or ""
        return job

    def _fetch_jobs(service_date):
        calendar_service = _calendar_service()
        timezone = app_module.get_calendar_zone()

        try:
            target_date = app_module.datetime.strptime(service_date, "%Y-%m-%d").date()
        except ValueError:
            target_date = app_module.datetime.now(timezone).date()

        day_start = app_module.datetime.combine(target_date, app_module.datetime.min.time(), tzinfo=timezone)
        day_end = day_start + app_module.timedelta(days=1)
        jobs = []

        for calendar_id in _calendar_ids():
            response = calendar_service.events().list(
                calendarId=calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            for event in response.get("items", []):
                job = _transform_event(event)
                job["calendar_id"] = calendar_id
                jobs.append(job)

        return sorted(jobs, key=lambda job: (job.get("sort_key") or "", job.get("summary") or ""))

    original_calendar_config = app_module.calendar_config

    def _patched_calendar_config():
        config = dict(original_calendar_config())
        ids = _calendar_ids()
        config["calendar_id"] = ids[0] if ids else config.get("calendar_id", "")
        config["calendar_ids"] = ids
        return config

    app_module.calendar_config = _patched_calendar_config
    app_module.calendar_status = _calendar_status
    app_module.fetch_calendar_jobs_for_date = _fetch_jobs

    if route_exists:
        return

    @flask_app.route("/service-quote/calendar-jobs", methods=["GET"])
    def service_quote_calendar_jobs():
        default_service_date = app_module.datetime.now(app_module.get_calendar_zone()).strftime("%Y-%m-%d")
        calendar_date = app_module.request.args.get("calendar_date") or default_service_date
        calendar_ready, calendar_status_message = _calendar_status()

        if not calendar_ready:
            return {
                "ready": False,
                "message": calendar_status_message,
                "jobs": [],
                "calendar_date": calendar_date,
            }

        try:
            jobs = _fetch_jobs(calendar_date)
        except Exception as exc:
            return {
                "ready": False,
                "message": f"Calendar jobs could not be loaded right now: {exc}",
                "jobs": [],
                "calendar_date": calendar_date,
            }

        return {
            "ready": True,
            "message": "",
            "jobs": jobs,
            "calendar_date": calendar_date,
        }


class _AppPatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped_loader):
        self.wrapped_loader = wrapped_loader

    def create_module(self, spec):
        if hasattr(self.wrapped_loader, "create_module"):
            return self.wrapped_loader.create_module(spec)
        return None

    def exec_module(self, module):
        self.wrapped_loader.exec_module(module)
        _install_calendar_jobs_route(module)


class _AppPatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != "app":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _AppPatchLoader(spec.loader)
        return spec


if "app" in sys.modules:
    _install_calendar_jobs_route(sys.modules["app"])
else:
    sys.meta_path.insert(0, _AppPatchFinder())


if Canvas is not None:
    _reportlab_draw_string = Canvas.drawString
    _reportlab_draw_right_string = Canvas.drawRightString
    _reportlab_begin_text = Canvas.beginText
    _reportlab_show_page = Canvas.showPage

    def _split_service_address(address):
        parts = [part.strip() for part in address.split(",") if part.strip()]
        if len(parts) >= 2:
            return parts[0], ", ".join(parts[1:])
        return address.strip(), ""

    def _shift_after_service_address(self, y):
        shift = getattr(self, "_bv_service_address_shift", 0)
        start_y = getattr(self, "_bv_service_address_start_y", None)
        if shift and start_y is not None and y < start_y:
            return y - shift
        return y

    def _draw_service_address_safely(self, x, y, text, *args, **kwargs):
        if isinstance(text, str) and text.startswith("Service Address:") and x <= 60:
            street, city_line = _split_service_address(text.split(":", 1)[1])
            _reportlab_draw_string(self, x, y, f"Service Address: {street}", *args, **kwargs)
            if city_line:
                _reportlab_draw_string(self, x + 82, y - 11, city_line, *args, **kwargs)
                self._bv_service_address_shift = max(getattr(self, "_bv_service_address_shift", 0), 11)
                self._bv_service_address_start_y = y
            return None

        shifted_y = _shift_after_service_address(self, y)
        if text in {"Work Completed", "Materials / Parts Notes"} and x <= 60:
            shifted_y += 6
        return _reportlab_draw_string(self, x, shifted_y, text, *args, **kwargs)

    def _draw_right_string_with_shift(self, x, y, text, *args, **kwargs):
        return _reportlab_draw_right_string(self, x, _shift_after_service_address(self, y), text, *args, **kwargs)

    def _begin_text_with_shift(self, x=0, y=0, direction=None):
        return _reportlab_begin_text(self, x, _shift_after_service_address(self, y), direction=direction)

    def _show_page_and_reset_shift(self):
        if hasattr(self, "_bv_service_address_shift"):
            self._bv_service_address_shift = 0
            self._bv_service_address_start_y = None
        return _reportlab_show_page(self)

    Canvas.drawString = _draw_service_address_safely
    Canvas.drawRightString = _draw_right_string_with_shift
    Canvas.beginText = _begin_text_with_shift
    Canvas.showPage = _show_page_and_reset_shift

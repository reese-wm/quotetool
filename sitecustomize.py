import socket
import smtplib

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

        return _reportlab_draw_string(self, x, _shift_after_service_address(self, y), text, *args, **kwargs)

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

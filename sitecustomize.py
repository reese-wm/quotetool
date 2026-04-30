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

    def _draw_service_address_safely(self, x, y, text, *args, **kwargs):
        if isinstance(text, str) and text.startswith("Service Address:") and x <= 60:
            font_name = getattr(self, "_fontname", "Helvetica")
            original_size = getattr(self, "_fontsize", 10)
            font_size = original_size
            max_width = 245

            while font_size > 6.5 and self.stringWidth(text, font_name, font_size) > max_width:
                font_size -= 0.5

            if font_size != original_size:
                self.setFont(font_name, font_size)
                try:
                    return _reportlab_draw_string(self, x, y, text, *args, **kwargs)
                finally:
                    self.setFont(font_name, original_size)

        return _reportlab_draw_string(self, x, y, text, *args, **kwargs)

    Canvas.drawString = _draw_service_address_safely

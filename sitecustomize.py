import socket
import smtplib


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

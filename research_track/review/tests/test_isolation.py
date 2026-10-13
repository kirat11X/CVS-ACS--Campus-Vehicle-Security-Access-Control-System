import socket


def test_network_socket_creation_is_disabled():
    try:
        socket.socket()
    except RuntimeError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("socket creation was not blocked")

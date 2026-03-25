import socket
import threading
from .bt_api import AF_BTH, BTHPROTO_RFCOMM, SOCKADDR_BTH


class SocketTrap:
    CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    def __init__(self, log_fn):
        self._log = log_fn
        self._running = False
        self._sockets = []
        self._threads = []

    def start(self):
        if self._running:
            return
        self._running = True
        for ch in self.CHANNELS:
            t = threading.Thread(target=self._listen, args=(ch,), daemon=True)
            t.start()
            self._threads.append(t)
        self._log("Socket trap active on RFCOMM channels 1-12")

    def stop(self):
        self._running = False
        for s in self._sockets:
            try:
                s.close()
            except Exception:
                pass
        self._sockets.clear()

    def _listen(self, channel: int):
        try:
            sock = socket.socket(AF_BTH, socket.SOCK_STREAM, BTHPROTO_RFCOMM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sockaddr = SOCKADDR_BTH()
            sockaddr.addressFamily = AF_BTH
            sockaddr.btAddr = 0
            sockaddr.port = channel
            sock.bind(sockaddr)
            sock.listen(5)
            self._sockets.append(sock)
        except Exception:
            return
        while self._running:
            try:
                sock.settimeout(1.0)
                try:
                    conn, _ = sock.accept()
                    conn.close()
                    self._log(f"Trapped & dropped connection on RFCOMM ch{channel}")
                except socket.timeout:
                    continue
            except Exception:
                break

#!/usr/bin/env python3
"""latcmp - compare execution latency between ANY two vantage points.

Read-only (no orders, no creds) so it is safe to run anywhere, unlike
tools/latprobe.py which places real 5-share probe orders and needs PM_LIVE=1.

Run the SAME file both places so the comparison is apples-to-apples:
    python3 winner-vacuum/tools/latcmp.py                 # here
    kubectl exec -i -n every-tick-single <pod> -- python3 - < winner-vacuum/tools/latcmp.py

Modes:  cold  (default) DNS/TCP/TLS/first-byte on a FRESH connection
        warm  keep-alive round trips  <-- what the live bot actually pays
        cpu   sha256 throughput + secp256k1 signing + which ECC backend
        all
"""
import socket, ssl, time, statistics as st, sys, importlib

COLD = [("clob.polymarket.com", "/time", "CLOB (order path)"),
        ("gamma-api.polymarket.com", "/markets?limit=1", "gamma"),
        ("data-api.polymarket.com", "/activity?limit=1", "data-api"),
        ("ws-live-data.polymarket.com", "/", "RTDS ws host")]


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))]


def cold(n=12):
    print("%-22s %8s %8s %8s %8s %8s" % ("target", "dns_ms", "tcp_p50", "tls_p50", "http_p50", "http_p90"))
    ctx = ssl.create_default_context()
    for host, path, lbl in COLD:
        t0 = time.perf_counter()
        try:
            ip = socket.gethostbyname(host)
        except Exception as e:
            print("%-22s DNS FAIL %s" % (lbl, str(e)[:40])); continue
        dns = (time.perf_counter() - t0) * 1000
        tcp, tls, http = [], [], []
        for _ in range(n):
            try:
                t = time.perf_counter(); s = socket.create_connection((ip, 443), timeout=8)
                tcp.append((time.perf_counter() - t) * 1000)
                t = time.perf_counter(); ss = ctx.wrap_socket(s, server_hostname=host)
                tls.append((time.perf_counter() - t) * 1000)
                t = time.perf_counter()
                ss.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n".encode())
                ss.recv(1); http.append((time.perf_counter() - t) * 1000)
                ss.close()
            except Exception:
                pass
        if not tcp:
            print("%-22s unreachable (ip %s)" % (lbl, ip)); continue
        print("%-22s %8.1f %8.1f %8.1f %8.1f %8.1f   ip=%s" % (
            lbl, dns, q(tcp, .5), q(tls, .5), q(http, .5), q(http, .9), ip))


def warm(n=30):
    print("%-20s %7s %7s %7s %7s %7s %7s" % ("target(warm)", "n", "p50", "p90", "p99", "min", "jitter"))
    ctx = ssl.create_default_context()
    for host, path, lbl in COLD[:2]:
        try:
            ss = ctx.wrap_socket(socket.create_connection((host, 443), timeout=8), server_hostname=host)
            ss.settimeout(8)
        except Exception as e:
            print("%-20s connect fail %s" % (lbl, str(e)[:40])); continue
        rt = []
        for _ in range(n):
            try:
                t = time.perf_counter()
                ss.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nConnection: keep-alive\r\n\r\n".encode())
                buf = b""
                while b"\r\n\r\n" not in buf:
                    c = ss.recv(65535)
                    if not c: raise IOError("closed")
                    buf += c
                cl = 0
                for line in buf.split(b"\r\n\r\n", 1)[0].split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"): cl = int(line.split(b":")[1])
                body = buf.split(b"\r\n\r\n", 1)[1]
                while len(body) < cl:
                    c = ss.recv(65535)
                    if not c: break
                    body += c
                rt.append((time.perf_counter() - t) * 1000)
            except Exception:
                try:
                    ss = ctx.wrap_socket(socket.create_connection((host, 443), timeout=8), server_hostname=host)
                    ss.settimeout(8)
                except Exception:
                    break
        if rt:
            print("%-20s %7d %7.1f %7.1f %7.1f %7.1f %7.1f" % (
                lbl, len(rt), q(rt, .5), q(rt, .9), q(rt, .99), min(rt), st.pstdev(rt)))


def cpu():
    import hashlib
    t = time.perf_counter(); x = b'0' * 64
    for _ in range(200000): x = hashlib.sha256(x).digest()
    print('  sha256 200k iters: %8.1f ms' % ((time.perf_counter() - t) * 1000))
    for m in ('coincurve', 'eth_keys', 'eth_account'):
        try:
            mod = importlib.import_module(m); print('  %-12s %s' % (m, getattr(mod, '__version__', '?')))
        except Exception as e:
            print('  %-12s MISSING (%s)' % (m, str(e)[:40]))
    try:
        from eth_keys.backends import get_backend_class
        print('  eth_keys backend:', get_backend_class().__name__)
    except Exception as e:
        print('  backend probe failed:', str(e)[:60])
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
        a = Account.create(); msg = encode_defunct(text='x' * 128); ts = []
        for _ in range(20):
            t = time.perf_counter(); Account.sign_message(msg, a.key); ts.append((time.perf_counter() - t) * 1000)
        ts.sort()
        print('  eth sign n=20: p50=%.2f ms  min=%.2f  p90=%.2f' % (ts[len(ts) // 2], ts[0], ts[int(len(ts) * .9)]))
    except Exception as e:
        print('  eth_account unavailable:', str(e)[:60])


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if mode in ('cold', 'all'): cold()
    if mode in ('warm', 'all'): print(); warm()
    if mode in ('cpu', 'all'): print(); cpu()

"""Serve one public CA with bounded, concurrent connections; never expose a directory."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import argparse

PUBLIC_CA=Path(__file__).resolve().parents[1]/'backend/.runtime/mobile-qa/tls/public-ca.cer'

class CertificateServer(ThreadingHTTPServer):
    daemon_threads=True
    def get_request(self):
        connection,address=super().get_request()
        connection.settimeout(5)
        return connection,address

def make_server(host,port=18413,certificate=PUBLIC_CA):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def certificate_response(self,include_body):
            if self.path!='/public-ca.cer':self.send_error(404);return
            try:data=Path(certificate).read_bytes()
            except OSError:self.send_error(503,'Certificate unavailable');return
            self.send_response(200)
            self.send_header('Content-Type','application/x-x509-ca-cert')
            self.send_header('Content-Disposition','attachment; filename="public-ca.cer"')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Connection','close')
            self.end_headers()
            if include_body:
                try:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):self.certificate_response(True)
        def do_HEAD(self):self.certificate_response(False)
    return CertificateServer((host,port),Handler)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);args=p.parse_args()
    with make_server(args.host) as server:server.serve_forever()

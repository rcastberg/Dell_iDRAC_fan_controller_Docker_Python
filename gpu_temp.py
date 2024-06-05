# Python WEB server to get NVIDIA gpu temp
from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import time
import os

hostName = "0.0.0.0"
serverPort = 980

class MyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        #temperature = os.system(
        temperature = subprocess.check_output(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"])
        self.wfile.write(bytes(temperature))

if __name__ == "__main__":        
    webServer = HTTPServer((hostName, serverPort), MyServer)
    print("Server started http://%s:%s" % (hostName, serverPort))
    try:
        webServer.serve_forever()
    except KeyboardInterrupt:
        pass

    webServer.server_close()
    print("Server stopped.")

import os
import socket
import socketserver
import http.server
from time import sleep
from select import select
from threading import Thread
from urllib.parse import urlparse
from configparser import ConfigParser

config = ConfigParser()
config.read('proxy.ini')


def proxy_factory():
    class Proxy(http.server.SimpleHTTPRequestHandler):
        incoming_data_path = 'incoming_data.txt'
        socket_timeout = 5

        def send_headers_ok(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

        def get_data(self):
            header_value = self.headers['Content-Length']
            if header_value:
                data_length = int(header_value)
                if data_length:
                    data = self.rfile.read(data_length)
                    return data

        def check_for_get_url_redirect(self):
            scheme = urlparse(self.path).scheme
            netloc = urlparse(self.path).netloc
            netloc_without_www = netloc.replace('www.', '')
            if netloc_without_www in config:
                return '{}://{}'.format(scheme, config[netloc_without_www]['redirect_to'])

        def check_for_connect_url_redirect(self):
            netloc = self.path.split(':')[0]
            netloc_without_www = netloc.replace('www.', '')
            if netloc_without_www in config:
                return '{}{}:{}'.format('www.' if 'www.' in self.path else '',
                                        config[netloc_without_www]['redirect_to'],
                                        self.path.split(':')[-1])

        def get_outer_conn(self):
            outer_conn = socket.socket()
            host_port_split = self.path.split(':')
            host_port = host_port_split[0], int(host_port_split[-1])
            try:
                print('Connection {}: Started'.format(outer_conn.fileno()))
                outer_conn.connect(host_port)
            except socket.error:
                print('Connection {}: Connection failed'.format(outer_conn.fileno()))
                self.send_error(404)
            return outer_conn

        def send_data_to_hosts(self, outer_conn):
            wait_items = [self.connection, outer_conn]
            socket_idle = 0
            while True:
                input_ready, output_ready, exception_ready = select(wait_items, [], wait_items, 3)
                if exception_ready:
                    print('Connection {}: Error'.format(outer_conn.fileno()))
                    return
                if input_ready:
                    for item in input_ready:
                        try:
                            data = item.recv(8192)
                        except (ConnectionResetError, ConnectionAbortedError):
                            print('Connection {}: Closed by peer'.format(outer_conn.fileno()))
                            return
                        if data:
                            if item is outer_conn:
                                local_conn = self.connection
                            else:
                                local_conn = outer_conn
                            local_conn.send(data)
                        else:
                            if socket_idle < self.socket_timeout:
                                sleep(1)
                                socket_idle += 1
                                print('Connection {}: Waiting for data'.format(outer_conn.fileno()))
                            else:
                                return
                else:
                    return

        def do_HEAD(self):
            self.send_headers_ok()

        def do_GET(self):
            if self.path == 'http://detectportal.firefox.com/success.txt':
                self.send_response(501)
                self.end_headers()
            else:
                redirect_url = self.check_for_get_url_redirect()
                if redirect_url:
                    self.send_response(301)
                    self.send_header('Location', redirect_url)
                    self.end_headers()
                else:
                    self.send_headers_ok()
                    self.wfile.write('<html><body><h1>This is proxy server.</h1></body></html>'.encode())

        def do_POST(self):
            data = self.get_data()
            if data:
                self.send_headers_ok()
                try:
                    data_to_print = data.decode()
                except UnicodeDecodeError:
                    data_to_print = data
                print('Incoming data: "{}"'.format(data_to_print))
            else:
                self.send_header('Empty data', 204)

        def do_PUT(self):
            data = self.get_data()
            if data:
                self.send_headers_ok()
                print('Incoming data: "{}"'.format(data.decode()))
                with open(self.incoming_data_path, 'wb') as f:
                    f.write(data)
            else:
                self.send_header('Empty data', 204)

        def do_DELETE(self):
            if os.path.isfile(self.incoming_data_path):
                os.remove(self.incoming_data_path)
                self.send_headers_ok()
            else:
                self.send_header('Resourse not found', 204)
                self.end_headers()

        def do_CONNECT(self):
            redirect_url = self.check_for_connect_url_redirect()
            if redirect_url:
                self.path = redirect_url
            outer_conn = self.get_outer_conn()
            try:
                if outer_conn:
                    self.log_request(200)
                    self.wfile.write('{} 200 Connection established\nProxy-agent: {}\n\n'
                                     .format(self.protocol_version, self.version_string()).encode())
                    self.send_data_to_hosts(outer_conn)
            finally:
                print('Connection {}: Closing'.format(outer_conn.fileno()))
                outer_conn.close()
                self.connection.close()
    return Proxy


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


class Proxy:
    def __init__(self):
        self.base_url = 'localhost'
        self.port = 1234
        while True:
            try:
                self.server = ThreadedTCPServer((self.base_url, self.port), proxy_factory())
            except OSError:
                self.port += 1
            else:
                break
        self.server_thread = Thread(target=self.server.serve_forever)

    def start(self):
        self.server_thread.start()
        print('Proxy started on http://{}:{}'.format(self.base_url, self.port))
        sleep(60)
        print('Proxy closing by timeout')
        self.shutdown()

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()


proxy = Proxy()
proxy.start()

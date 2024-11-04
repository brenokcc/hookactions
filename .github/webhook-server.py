#!/usr/bin/env python3
import os
import uuid
import time
import json
import subprocess
import threading
import signal
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler


"""
Run the server:
   ./.github/webhook-server.py

Simulate a pull request:
    curl -X POST http://127.0.0.1:9999 -d '{"action": "opened", "pull_request": {"comments_url": null, "base": {"ref": "main"}, "head": {"ref": "main"}}}'

Simulate a merge
    curl -X POST http://127.0.0.1:9999 -d '{"action": "closed", "pull_request": {"comments_url": null, "merged": true, "base": {"ref": "main"}, "head": {"ref": "main"}}}'
"""

PORT = 9999

def stop(*args):
    print('Bye!')

def execute(cmd, file_name):
    print(f'Executing "{cmd}" and logging into "{file_name}"...')
    with open(os.path.join('logs', 'tasks', file_name), 'w') as file:
        p = subprocess.Popen(cmd.split(), stdout=file, stderr=file, cwd=".")
        p.communicate()
        return p.returncode == 0

def comment(url, text):
    print(text)
    if url:
        headers={'Authorization': 'Bearer {}'.format(os.environ['TAVOS_API_TOKEN'])}
        payload = {"body":text}
        response = requests.post(url, json=payload, headers=headers)
        print(response.json())

def dequeue():
    try:
        while True:
            data = queue()
            if data:
                cmd, file_name, url = data.pop()
                queue(data)
                success = execute(cmd, file_name)
                message = "Task {} completed with {}.".format(file_name, "success" if success else "error")
                comment(url, message)
            else:
                # print('Waiting for task...')
                time.sleep(5)
    except KeyboardInterrupt:
        pass

def queue(data=None):
    if data is not None:
        with open("queue.json", "w") as file:
            file.write(json.dumps(data))
    else:
        data = []
        if os.path.exists("queue.json"):
            with open("queue.json") as file:
                data = json.loads(file.read())
    return data

def push(cmd, file_name, url=None):
    data = queue()
    data.append((cmd, file_name, url))
    queue(data)

def pop():
    data = queue()
    if data:
        item = data.pop()
        queue(data)
        return item

def process(host_name, data):
    message = ''
    task_name = uuid.uuid1().hex
    log_file_url = 'http://{}/{}'.format(host_name, task_name)
    pull_request = data.get('pull_request')
    if pull_request:
        action = data.get('action')
        merged = pull_request.get('merged')
        comments_url = pull_request.get('comments_url')
        base_branch = data.get('pull_request').get('base').get('ref')
        head_branch = data.get('pull_request').get('head').get('ref')
        if action in ('opened', 'synchronize', 'edited'):
            push(f"echo {head_branch}", task_name, comments_url)
            message = 'Task was queued to test branch "{}". {}'.format(head_branch, log_file_url)
            comment(comments_url, message)
        elif action == 'closed' and merged:
            push(f"docker-compose up -d --build", task_name, comments_url)
            message = 'Task was queued to update branch "{}" after merge with "{}". {}'.format(base_branch, head_branch, log_file_url)
            comment(comments_url, message)
    return message


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        self._data = {}
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        file_name = self.path[1:]
        file_path = os.path.join('logs', 'tasks', file_name)
        if file_name and os.path.exists(file_path):
            with open(file_path, 'rb') as file:
                data = file.read()
        else:
            data = b':)'
        self.wfile.write(data)

    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        data = json.loads(self.rfile.read(int(self.headers.get('Content-Length'))).decode())
        print(data)
        message = process(self.headers['Host'], data)
        with open(os.path.join('logs', 'server.log'), 'a') as file:
            file.write('<<< {}\n\n'.format(data))
            file.write('>>> {}\n\n'.format(message))
        self.wfile.write(message.encode())

os.makedirs(os.path.join('logs', 'tasks'), exist_ok=True)
signal.signal(signal.SIGTERM, stop)
httpd = HTTPServer(('127.0.0.1', PORT), SimpleHTTPRequestHandler)
try:
    print('Listening 127.0.0.1:{} ...'.format(PORT))
    threading.Thread(target=dequeue).start()
    httpd.serve_forever()
except KeyboardInterrupt:
    stop()
    print('Stopped!')

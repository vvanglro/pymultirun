## multirun
A multi-process runtime library with health checks, Excerpted from uvicorn.

If the script needs to use multiple processes and run for a long time, use it.

---

### Installation
```shell
pip install pymultirun
```

---

### Usage
Create a script that you want to run in multiple processes, in `example.py`:
```python
import socket

from multirun import run_multiprocess
import asyncio

async def handle_echo(reader, writer):
    data = await reader.read(100)
    message = data.decode()
    addr = writer.get_extra_info('peername')

    print(f"Received {message!r} from {addr!r}")

    print(f"Send: {message!r}")
    writer.write(data)
    await writer.drain()

    print("Close the connection")
    writer.close()
    await writer.wait_closed()

async def main(sock: socket.socket):
    server = await asyncio.start_server(
        handle_echo, sock=sock)

    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f'Serving on {addrs}')

    async with server:
        await server.serve_forever()

def worker(sock: socket.socket) -> None:
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main(sock))
    finally:
        loop.close()


if __name__ == '__main__':
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.bind(("::", 8888))
        run_multiprocess(worker, workers=2, args=(sock, ))
```
You can also use the command line, in `example.py`:
```python
import os
import time

def worker_function(name: str, age:int, sleep_time=1, **kwargs):
    pid = os.getpid()
    count = 0
    print(f"Name {name}, Age {age}, Kwargs {kwargs}.")

    try:
        while True:
            time.sleep(sleep_time)
            count += 1
            print(f"Worker {name} (PID: {pid}) - count: {count}")
    except KeyboardInterrupt:
        print(f"Worker {name} (PID: {pid}) shutting down")
```
Run it:
```shell
multirun example:worker_function --workers 2 --timeout 3  --args vvanglro --args 23  --kwargs a 1 
```

---

### Signal

You can use signals to stop the workers:

```shell
kill -SIGINT <pid>
```

Restart the workers:
```shell
kill -SIGHUP <pid>
```

Add workers:
```shell
kill -SIGTTIN <pid>
```

Reduce workers:
```shell
kill -SIGTTOU <pid>
```

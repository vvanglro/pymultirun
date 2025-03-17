from __future__ import annotations

import logging
import os
import signal
import threading
from multiprocessing import Pipe, Process as _Process
from typing import Any, Callable


LOG_LEVELS: dict[str, int] = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

SIGNALS = {
    getattr(signal, f"SIG{x}"): x
    for x in "INT TERM BREAK HUP QUIT TTIN TTOU USR1 USR2 WINCH".split()
    if hasattr(signal, f"SIG{x}")
}

logger = logging.getLogger("multirun")

def configure_logging(level: str | int):
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)


class Process:
    def __init__(
            self,
            target: Callable[..., Any],
            args: tuple[Any, ...] = (),
            kwargs: dict[str, Any] = None,
    ) -> None:
        self.real_target = target
        self.args = args
        self.kwargs = kwargs or {}

        self.parent_conn, self.child_conn = Pipe()
        self.process = _Process(target=self.target, daemon=True)

    def ping(self, timeout: float = 5) -> bool:
        self.parent_conn.send(b"ping")
        if self.parent_conn.poll(timeout):
            self.parent_conn.recv()
            return True
        return False

    def pong(self) -> None:
        self.child_conn.recv()
        self.child_conn.send(b"pong")

    def always_pong(self) -> None:
        while True:
            try:
                self.pong()
            except (EOFError, OSError):
                break

    def target(self) -> Any:  # pragma: no cover
        if os.name == "nt":  # pragma: py-not-win32
            # Windows doesn't support SIGTERM, so we use SIGBREAK instead.
            # And then we raise SIGTERM when SIGBREAK is received.
            signal.signal(
                signal.SIGBREAK,  # type: ignore[attr-defined]
                lambda sig, frame: signal.raise_signal(signal.SIGTERM),
            )

        threading.Thread(target=self.always_pong, daemon=True).start()
        return self.real_target(*self.args, **self.kwargs)

    def is_alive(self, timeout: float = 5) -> bool:
        if not self.process.is_alive():
            return False  # pragma: full coverage

        return self.ping(timeout)

    def start(self) -> None:
        self.process.start()

    def terminate(self) -> None:
        if self.process.exitcode is None:  # Process is still running
            assert self.process.pid is not None
            if os.name == "nt":  # pragma: py-not-win32
                # Windows doesn't support SIGTERM.
                # So send SIGBREAK, and then in process raise SIGTERM.
                os.kill(self.process.pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.kill(self.process.pid, signal.SIGTERM)
            logger.info(f"Terminated child process [{self.process.pid}]")

            self.parent_conn.close()
            self.child_conn.close()

    def kill(self) -> None:
        # In Windows, the method will call `TerminateProcess` to kill the process.
        # In Unix, the method will send SIGKILL to the process.
        self.process.kill()

    def join(self) -> None:
        logger.info(f"Waiting for child process [{self.process.pid}]")
        self.process.join()

    @property
    def pid(self) -> int | None:
        return self.process.pid


class Multiprocess:
    def __init__(
            self,
            target: Callable[..., Any],
            workers: int = 1,
            timeout: float = 5,
            args: tuple[Any, ...] = (),
            kwargs: dict[str, Any] = None,
    ) -> None:
        """
        Initialize a multi-process manager to run a target function in multiple worker processes.

        Args:
            target: The function to run in worker processes
            workers: Number of worker processes to spawn
            timeout: Process health check timeout
            args: Positional arguments to pass to the target function
            kwargs: Keyword arguments to pass to the target function
        """
        self.target = target
        self.timeout = timeout
        self.args = args
        self.kwargs = kwargs or {}
        self.processes_num = max(1, workers)
        self.processes: list[Process] = []

        self.should_exit = threading.Event()
        self.signal_queue: list[int] = []

        for sig in SIGNALS:
            signal.signal(sig, lambda sig, frame: self.signal_queue.append(sig))

    def init_processes(self) -> None:
        for _ in range(self.processes_num):
            process = Process(
                self.target,
                args=self.args,
                kwargs=self.kwargs,
            )
            process.start()
            self.processes.append(process)

    def terminate_all(self) -> None:
        for process in self.processes:
            process.terminate()

    def join_all(self) -> None:
        for process in self.processes:
            process.join()

    def restart_all(self) -> None:
        for idx, process in enumerate(self.processes):
            process.terminate()
            process.join()
            new_process = Process(
                self.target,
                args=self.args,
                kwargs=self.kwargs,
            )
            new_process.start()
            self.processes[idx] = new_process

    def run(self) -> None:
        """Start and manage the worker processes until signaled to stop."""
        logger.info(f"Started parent process [{os.getpid()}]")

        self.init_processes()

        while not self.should_exit.wait(0.5):
            self.handle_signals()
            self.keep_subprocess_alive()

        self.terminate_all()
        self.join_all()

        logger.info(f"Stopping parent process [{os.getpid()}]")

    def keep_subprocess_alive(self) -> None:
        if self.should_exit.is_set():
            return  # parent process is exiting, no need to keep subprocess alive

        for idx, process in enumerate(self.processes):
            if process.is_alive(self.timeout):
                continue

            process.kill()  # process is hung, kill it
            process.join()

            if self.should_exit.is_set():
                return  # pragma: full coverage

            logger.info(f"Child process [{process.pid}] died")
            process = Process(
                self.target,
                args=self.args,
                kwargs=self.kwargs,
            )
            process.start()
            self.processes[idx] = process

    def handle_signals(self) -> None:
        for sig in tuple(self.signal_queue):
            self.signal_queue.remove(sig)
            sig_name = SIGNALS[sig]
            sig_handler = getattr(self, f"handle_{sig_name.lower()}", None)
            if sig_handler is not None:
                sig_handler()
            else:  # pragma: no cover
                logger.debug(f"Received signal {sig_name}, but no handler is defined for it.")

    def handle_int(self) -> None:
        logger.info("Received SIGINT, exiting.")
        self.should_exit.set()

    def handle_term(self) -> None:
        logger.info("Received SIGTERM, exiting.")
        self.should_exit.set()

    def handle_break(self) -> None:  # pragma: py-not-win32
        logger.info("Received SIGBREAK, exiting.")
        self.should_exit.set()

    def handle_hup(self) -> None:  # pragma: py-win32
        logger.info("Received SIGHUP, restarting processes.")
        self.restart_all()

    def handle_ttin(self) -> None:  # pragma: py-win32
        logger.info("Received SIGTTIN, increasing the number of processes.")
        self.processes_num += 1
        process = Process(
            self.target,
            args=self.args,
            kwargs=self.kwargs,
        )
        process.start()
        self.processes.append(process)

    def handle_ttou(self) -> None:  # pragma: py-win32
        logger.info("Received SIGTTOU, decreasing number of processes.")
        if self.processes_num <= 1:
            logger.info("Already reached one process, cannot decrease the number of processes anymore.")
            return
        self.processes_num -= 1
        process = self.processes.pop()
        process.terminate()
        process.join()


def run_multiprocess(
        target: Callable[..., Any],
        workers: int = 1,
        log_level: str = None,
        timeout: int = 5,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] = None,
) -> None:
    """
    Run a function in multiple worker processes with monitoring and process management.

    Args:
        target: The function to run in multiple processes
        workers: Number of worker processes to spawn
        timeout: Process health check timeout
        args: Positional arguments to pass to the target function
        kwargs: Keyword arguments to pass to the target function
        log_level:

    Example:
        ```python
        def my_worker(name, count=1):
            print(f"Worker {name} started with count {count}")
            # Worker logic here

        # Run 4 workers with arguments
        run_multiprocess(
            my_worker,
            workers=4,
            args=("worker",),
            kwargs={"count": 10}
        )
        ```
    """
    if not log_level:
        log_level = logging.INFO
    else:
        log_level = LOG_LEVELS.get(log_level, logging.INFO)

    configure_logging(log_level)

    mp = Multiprocess(target, workers, timeout, args, kwargs or {})
    mp.run()

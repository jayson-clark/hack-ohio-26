"""Live events: every write publishes one, and each SSE client has a queue."""

import queue
import threading
import time


class Bus:
    def __init__(self):
        self.subscribers: set[queue.Queue] = set()
        self.lock = threading.Lock()

    def publish(self, kind, data):
        event = {"type": kind, "data": data, "at": time.time()}
        with self.lock:
            for sub in self.subscribers:
                sub.put(event)

    def subscribe(self):
        sub = queue.Queue()
        with self.lock:
            self.subscribers.add(sub)
        return sub

    def unsubscribe(self, sub):
        with self.lock:
            self.subscribers.discard(sub)

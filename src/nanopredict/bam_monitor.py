"""Background barcode-yield monitoring of completed BAM batches."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any

from .bam_fallback import BamYieldCounter
from .paths import state_dir


class BamYieldMonitor:
    def __init__(self, poll_seconds=20., start_thread=True, persistence_root=None):
        self.poll_seconds = poll_seconds
        self.persistence_root = persistence_root
        self._lock = threading.RLock()
        self._event = threading.Event()
        self._stop = threading.Event()
        self._context = None
        self._counter = None
        self._status = self._waiting('Waiting for MinKNOW BAM output')
        self._thread = None
        if start_thread:
            self._thread = threading.Thread(target=self._run, daemon=True, name='nanopredict-bam')
            self._thread.start()

    @staticmethod
    def _waiting(message, state='waiting'):
        return {'state': state, 'files_processed': 0, 'reads_scanned': 0,
                'barcodes': [], 'message': message}

    def update_context(self, context):
        with self._lock:
            if self._context is None or self._context['run_key'] != context['run_key']:
                self._counter = None
                self._status = self._waiting('Waiting for a completed BAM batch')
            self._context = {key: context.get(key) for key in
                             ('run_key', 'reads_directory', 'output_path', 'bam_reads_enabled')}
        self._event.set()
        if self._thread is None:
            self.scan_once()

    def set_waiting(self):
        with self._lock:
            self._context = None
            self._counter = None
            self._status = self._waiting('Waiting for an active sequencing run')

    def _run(self):
        while not self._stop.is_set():
            self._event.wait(self.poll_seconds)
            self._event.clear()
            if not self._stop.is_set():
                self.scan_once()

    def scan_once(self):
        with self._lock:
            context = dict(self._context) if self._context else None
        if context is None:
            return
        selected = context.get('reads_directory') or context.get('output_path')
        root = Path(selected) if selected else None
        if context.get('bam_reads_enabled') is False:
            status = self._waiting('Enable BAM output in MinKNOW', 'unavailable')
        elif root is None or not root.is_dir():
            status = self._waiting('Waiting for the MinKNOW output directory')
        else:
            try:
                with self._lock:
                    if context != self._context:
                        return
                    if self._counter is None or self._counter.root != root:
                        self._counter = BamYieldCounter(root, context['run_key'],
                            self.persistence_root or state_dir() / 'barcode-yield')
                    counter = self._counter
                counter.scan()
                status = {'state': 'collecting' if counter.processed else 'waiting',
                          'files_processed': len(counter.processed),
                          'reads_scanned': counter.total_reads, 'barcodes': counter.barcode_status(),
                          'message': 'Monitoring completed BAM batches' if counter.processed
                                     else 'Waiting for a completed BAM batch'}
            except (OSError, TypeError, ValueError) as exc:
                status = self._waiting(str(exc), 'error')
        status['last_update'] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            if context == self._context:
                self._status = status

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def close(self):
        self._stop.set()
        self._event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.poll_seconds+1, 5))

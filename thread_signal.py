from __future__ import annotations

import logging
import signal
import threading
import time


class Producer(threading.Thread):
    """Background worker that runs until stop_event is set."""

    def __init__(self, stop_event: threading.Event, interval: float = 2.0) -> None:
        super().__init__(name="ProducerThread", daemon=False)
        self.stop_event = stop_event
        self.interval = interval

    def run(self) -> None:
        logging.info("Producer started.")

        try:
            while not self.stop_event.is_set():
                logging.info("Sub-thread is working.")

                # Lets the thread stop immediately instead of waiting for sleep().
                if self.stop_event.wait(self.interval):
                    break

        except Exception:
            logging.exception("Unexpected error in producer thread.")

        finally:
            logging.info("Producer stopped cleanly.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(threadName)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    stop_event = threading.Event()
    producer = Producer(stop_event, interval=2.0)

    def shutdown_handler(signum: int, _frame: object) -> None:
        signal_name = signal.Signals(signum).name
        logging.warning("Received %s. Requesting shutdown...", signal_name)
        stop_event.set()

    # Signal handlers must be registered from the main thread.
    signal.signal(signal.SIGINT, shutdown_handler)

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown_handler)

    logging.info("Main thread started. Press Ctrl+C to stop.")
    producer.start()

    try:
        # Keep the main thread responsive while the worker runs.
        while producer.is_alive():
            producer.join(timeout=0.5)

    except KeyboardInterrupt:
        # Fallback in case Ctrl+C arrives before the signal callback runs.
        logging.warning("Keyboard interrupt received.")
        stop_event.set()

    finally:
        stop_event.set()
        producer.join()
        logging.info("Main thread ended.")


if __name__ == "__main__":
    main()

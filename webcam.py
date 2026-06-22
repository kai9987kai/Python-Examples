#!/usr/bin/env python3
"""
Advanced OpenCV Webcam Viewer

Controls:
    q / ESC  Quit
    g        Toggle grayscale / colour
    m        Toggle mirror mode
    s        Save screenshot
"""

import argparse
import time
from pathlib import Path

import cv2


def parse_args():
    parser = argparse.ArgumentParser(description="Advanced OpenCV webcam viewer")

    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Camera index to use (default: 0)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="Requested camera width (default: 1280)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=720,
        help="Requested camera height (default: 720)",
    )
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="Start with horizontal mirror mode enabled",
    )

    return parser.parse_args()


def save_screenshot(frame, output_dir="screenshots"):
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    filename = output_path / f"webcam_{int(time.time())}.jpg"

    if cv2.imwrite(str(filename), frame):
        print(f"[+] Screenshot saved: {filename}")
    else:
        print("[-] Failed to save screenshot")


def main():
    args = parse_args()

    cap = cv2.VideoCapture(args.camera)

    if not cap.isOpened():
        print(f"[-] Could not open camera {args.camera}")
        print("    Try another camera index, for example: --camera 1")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    grayscale_mode = False
    mirror_mode = args.mirror

    previous_time = time.time()
    fps = 0.0

    print("[+] Camera started")
    print("    Controls: q/ESC quit | g grayscale | m mirror | s screenshot")

    try:
        while True:
            success, frame = cap.read()

            if not success or frame is None:
                print("[-] Failed to read frame from camera")
                break

            if mirror_mode:
                frame = cv2.flip(frame, 1)

            display_frame = frame

            if grayscale_mode:
                display_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                display_frame = cv2.cvtColor(display_frame, cv2.COLOR_GRAY2BGR)

            current_time = time.time()
            elapsed = current_time - previous_time

            if elapsed > 0:
                fps = 1.0 / elapsed

            previous_time = current_time

            mode_text = "GRAY" if grayscale_mode else "COLOUR"
            mirror_text = "ON" if mirror_mode else "OFF"

            cv2.putText(
                display_frame,
                f"FPS: {fps:.1f}",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.putText(
                display_frame,
                f"Mode: {mode_text} | Mirror: {mirror_text}",
                (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow("Advanced Webcam Viewer", display_frame)

            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27):  # q or ESC
                break

            elif key == ord("g"):
                grayscale_mode = not grayscale_mode

            elif key == ord("m"):
                mirror_mode = not mirror_mode

            elif key == ord("s"):
                save_screenshot(display_frame)

    except KeyboardInterrupt:
        print("\n[!] Stopped by user")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[+] Camera released and windows closed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

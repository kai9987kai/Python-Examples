import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
import os
import time


# ============================================================
# CONFIGURATION
# ============================================================

WINDOW_NAME = "Advanced Live Sketch Studio"

CAMERA_INDEX = 0

CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
TARGET_FPS = 30.0

OUTPUT_DIR = Path("sketch_output")


# ============================================================
# SKETCH MODES
# ============================================================

MODES = {
    1: "Classic",
    2: "Pencil",
    3: "Ink",
    4: "Color Sketch",
    5: "Edges",
    6: "Original",
}


# ============================================================
# IMAGE PROCESSING UTILITIES
# ============================================================

def odd(value: int, minimum: int = 3) -> int:
    """
    Ensure a value is an odd integer.

    Many OpenCV kernel sizes must be odd values.
    """

    value = max(minimum, int(value))

    if value % 2 == 0:
        value += 1

    return value


def adaptive_canny(
    gray: np.ndarray,
    sigma: float = 0.33
) -> np.ndarray:
    """
    Automatically calculate Canny thresholds using
    the median intensity of the image.

    This makes the edge detector adapt better to
    bright and dark scenes than fixed thresholds.
    """

    median = float(np.median(gray))

    lower = int(
        max(
            0,
            (1.0 - sigma) * median
        )
    )

    upper = int(
        min(
            255,
            (1.0 + sigma) * median
        )
    )

    if upper <= lower:
        upper = min(
            255,
            lower + 1
        )

    edges = cv2.Canny(
        gray,
        lower,
        upper,
        L2gradient=True
    )

    return edges


# ============================================================
# MODE 1
# CLASSIC BLACK-AND-WHITE SKETCH
# ============================================================

def classic_sketch(
    frame: np.ndarray
) -> np.ndarray:

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    blurred = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    edges = adaptive_canny(
        blurred,
        sigma=0.33
    )

    kernel = np.ones(
        (2, 2),
        dtype=np.uint8
    )

    edges = cv2.dilate(
        edges,
        kernel,
        iterations=1
    )

    sketch = cv2.bitwise_not(
        edges
    )

    return sketch


# ============================================================
# MODE 2
# PENCIL SHADING
# ============================================================

def pencil_sketch(
    frame: np.ndarray
) -> np.ndarray:

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    # Invert image
    inverted = cv2.bitwise_not(
        gray
    )

    # Create smooth "graphite" lighting
    blurred = cv2.GaussianBlur(
        inverted,
        (21, 21),
        0
    )

    # Dodge blend approximation
    denominator = (
        255 - blurred
    )

    # Avoid division by zero
    denominator = np.maximum(
        denominator,
        1
    )

    sketch = cv2.divide(
        gray,
        denominator,
        scale=256.0
    )

    # Improve local-looking contrast
    sketch = cv2.equalizeHist(
        sketch
    )

    return sketch


# ============================================================
# MODE 3
# HIGH-CONTRAST INK DRAWING
# ============================================================

def ink_sketch(
    frame: np.ndarray
) -> np.ndarray:

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    # Edge-preserving smoothing
    smooth = cv2.bilateralFilter(
        gray,
        7,
        50,
        50
    )

    ink = cv2.adaptiveThreshold(
        smooth,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        4
    )

    return ink


# ============================================================
# MODE 4
# COLOR / COMIC SKETCH
# ============================================================

def color_sketch(
    frame: np.ndarray
) -> np.ndarray:

    # Preserve major colour regions while smoothing noise
    smooth = cv2.bilateralFilter(
        frame,
        9,
        75,
        75
    )

    gray = cv2.cvtColor(
        smooth,
        cv2.COLOR_BGR2GRAY
    )

    edges = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY,
        9,
        5
    )

    edges_bgr = cv2.cvtColor(
        edges,
        cv2.COLOR_GRAY2BGR
    )

    result = cv2.bitwise_and(
        smooth,
        edges_bgr
    )

    return result


# ============================================================
# MODE 5
# PURE EDGE VISUALISATION
# ============================================================

def edge_view(
    frame: np.ndarray
) -> np.ndarray:

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    edges = adaptive_canny(
        gray
    )

    edges = cv2.cvtColor(
        edges,
        cv2.COLOR_GRAY2BGR
    )

    return edges


# ============================================================
# PROCESS CURRENT MODE
# ============================================================

def apply_mode(
    frame: np.ndarray,
    mode: int
) -> np.ndarray:

    if mode == 1:

        output = classic_sketch(
            frame
        )

    elif mode == 2:

        output = pencil_sketch(
            frame
        )

    elif mode == 3:

        output = ink_sketch(
            frame
        )

    elif mode == 4:

        output = color_sketch(
            frame
        )

    elif mode == 5:

        return edge_view(
            frame
        )

    else:

        return frame.copy()

    # Convert grayscale outputs to BGR so every
    # processing mode has the same output shape.

    if output.ndim == 2:

        return cv2.cvtColor(
            output,
            cv2.COLOR_GRAY2BGR
        )

    return output


# ============================================================
# HEAD-UP DISPLAY
# ============================================================

def add_hud(
    image: np.ndarray,
    mode: int,
    fps: float,
    recording: bool,
    paused: bool,
) -> np.ndarray:

    canvas = image.copy()

    height, width = canvas.shape[:2]

    # --------------------------------------------------------
    # Semi-transparent header
    # --------------------------------------------------------

    overlay = canvas.copy()

    cv2.rectangle(
        overlay,
        (0, 0),
        (width, 74),
        (0, 0, 0),
        -1
    )

    cv2.addWeighted(
        overlay,
        0.55,
        canvas,
        0.45,
        0,
        canvas
    )

    # --------------------------------------------------------
    # Mode + FPS
    # --------------------------------------------------------

    status = (
        f"Mode {mode}: {MODES[mode]}"
        f"   |   FPS: {fps:5.1f}"
    )

    cv2.putText(
        canvas,
        status,
        (16, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        (255, 255, 255),
        2,
        cv2.LINE_AA
    )

    # --------------------------------------------------------
    # Controls
    # --------------------------------------------------------

    controls = (
        "1-6 modes | "
        "S snapshot | "
        "R record | "
        "SPACE pause | "
        "H HUD | "
        "Q/ESC quit"
    )

    cv2.putText(
        canvas,
        controls,
        (16, 57),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (225, 225, 225),
        1,
        cv2.LINE_AA
    )

    # --------------------------------------------------------
    # Recording indicator
    # --------------------------------------------------------

    x = width - 150

    if recording:

        cv2.circle(
            canvas,
            (x, 24),
            8,
            (0, 0, 255),
            -1
        )

        cv2.putText(
            canvas,
            "REC",
            (x + 15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (0, 0, 255),
            2,
            cv2.LINE_AA
        )

    # --------------------------------------------------------
    # Pause indicator
    # --------------------------------------------------------

    if paused:

        cv2.putText(
            canvas,
            "PAUSED",
            (
                max(
                    10,
                    width - 135
                ),
                58
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (0, 220, 255),
            2,
            cv2.LINE_AA
        )

    return canvas


# ============================================================
# CAMERA INITIALISATION
# ============================================================

def open_camera(
    index: int
) -> cv2.VideoCapture:

    backends = []

    # DirectShow can reduce webcam startup/backend issues
    # on many Windows configurations.
    if os.name == "nt":

        backends.append(
            cv2.CAP_DSHOW
        )

    # Generic OpenCV backend fallback.
    backends.append(
        cv2.CAP_ANY
    )

    for backend in backends:

        cap = cv2.VideoCapture(
            index,
            backend
        )

        if cap.isOpened():

            cap.set(
                cv2.CAP_PROP_FRAME_WIDTH,
                CAPTURE_WIDTH
            )

            cap.set(
                cv2.CAP_PROP_FRAME_HEIGHT,
                CAPTURE_HEIGHT
            )

            cap.set(
                cv2.CAP_PROP_FPS,
                TARGET_FPS
            )

            return cap

        cap.release()

    raise RuntimeError(
        f"Could not open camera index {index}. "
        "Check camera permissions, close other camera "
        "applications, or try another camera index."
    )


# ============================================================
# VIDEO RECORDING
# ============================================================

def make_video_writer(
    frame: np.ndarray,
    fps: float
) -> tuple[cv2.VideoWriter, Path]:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    path = OUTPUT_DIR / (
        f"sketch_{stamp}.mp4"
    )

    height, width = frame.shape[:2]

    # MPEG-4 codec
    fourcc = cv2.VideoWriter_fourcc(
        *"mp4v"
    )

    # Prevent unusable FPS values during startup.
    safe_fps = (
        fps
        if 5.0 <= fps <= 120.0
        else TARGET_FPS
    )

    writer = cv2.VideoWriter(
        str(path),
        fourcc,
        safe_fps,
        (width, height)
    )

    # --------------------------------------------------------
    # AVI/MJPEG fallback if MP4 writer unavailable
    # --------------------------------------------------------

    if not writer.isOpened():

        writer.release()

        path = OUTPUT_DIR / (
            f"sketch_{stamp}.avi"
        )

        fourcc = cv2.VideoWriter_fourcc(
            *"MJPG"
        )

        writer = cv2.VideoWriter(
            str(path),
            fourcc,
            safe_fps,
            (width, height)
        )

    if not writer.isOpened():

        raise RuntimeError(
            "Could not create a video output file."
        )

    return writer, path


# ============================================================
# SNAPSHOTS
# ============================================================

def save_snapshot(
    frame: np.ndarray
) -> Path:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    path = OUTPUT_DIR / (
        f"snapshot_{stamp}.png"
    )

    success = cv2.imwrite(
        str(path),
        frame
    )

    if not success:

        raise RuntimeError(
            f"Failed to save snapshot: {path}"
        )

    return path


# ============================================================
# MAIN APPLICATION
# ============================================================

def main() -> None:

    cap = open_camera(
        CAMERA_INDEX
    )

    cv2.namedWindow(
        WINDOW_NAME,
        cv2.WINDOW_NORMAL
    )

    # --------------------------------------------------------
    # Application state
    # --------------------------------------------------------

    mode = 1

    show_hud = True

    paused = False

    frozen_frame = None

    writer = None

    recording_path = None

    # --------------------------------------------------------
    # FPS calculation
    # --------------------------------------------------------

    last_time = time.perf_counter()

    fps = 0.0

    fps_smoothing = 0.90

    # --------------------------------------------------------
    # Terminal information
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print(" ADVANCED LIVE SKETCH STUDIO")
    print("=" * 60)

    print()
    print("Controls:")

    print("  1  Classic sketch")
    print("  2  Pencil shading")
    print("  3  Ink / adaptive threshold")
    print("  4  Color sketch")
    print("  5  Edge view")
    print("  6  Original camera")

    print()

    print("  S       Save snapshot")
    print("  R       Start / stop recording")
    print("  SPACE   Pause / resume")
    print("  H       Toggle HUD")
    print("  Q       Quit")
    print("  ESC     Quit")

    print()

    # ========================================================
    # MAIN CAMERA LOOP
    # ========================================================

    try:

        while True:

            # ------------------------------------------------
            # CAPTURE FRAME
            # ------------------------------------------------

            if not paused:

                ok, frame = cap.read()

                if (
                    not ok
                    or frame is None
                    or frame.size == 0
                ):

                    print(
                        "Warning: camera frame read failed."
                    )

                    time.sleep(
                        0.02
                    )

                    continue

                frozen_frame = frame.copy()

            elif frozen_frame is None:

                continue

            # ------------------------------------------------
            # SELECT SOURCE
            # ------------------------------------------------

            if paused:

                source = frozen_frame

            else:

                source = frame

            # ------------------------------------------------
            # APPLY VISUAL EFFECT
            # ------------------------------------------------

            processed = apply_mode(
                source,
                mode
            )

            # ------------------------------------------------
            # FPS
            # ------------------------------------------------

            now = time.perf_counter()

            delta_time = max(
                now - last_time,
                1e-6
            )

            instant_fps = (
                1.0 / delta_time
            )

            if fps == 0.0:

                fps = instant_fps

            else:

                fps = (
                    fps_smoothing * fps
                    +
                    (1.0 - fps_smoothing)
                    * instant_fps
                )

            last_time = now

            # ------------------------------------------------
            # HUD
            # ------------------------------------------------

            if show_hud:

                display = add_hud(
                    processed,
                    mode,
                    fps,
                    writer is not None,
                    paused
                )

            else:

                display = processed.copy()

            # ------------------------------------------------
            # RECORD VIDEO
            # ------------------------------------------------

            if (
                writer is not None
                and not paused
            ):

                writer.write(
                    display
                )

            # ------------------------------------------------
            # DISPLAY
            # ------------------------------------------------

            cv2.imshow(
                WINDOW_NAME,
                display
            )

            # ------------------------------------------------
            # KEYBOARD INPUT
            # ------------------------------------------------

            key = (
                cv2.waitKey(1)
                & 0xFF
            )

            # ------------------------------------------------
            # QUIT
            # ------------------------------------------------

            if key in (
                27,
                ord("q"),
                ord("Q")
            ):

                break

            # ------------------------------------------------
            # MODES 1-6
            # ------------------------------------------------

            if (
                ord("1")
                <= key
                <= ord("6")
            ):

                mode = (
                    key
                    - ord("0")
                )

                print(
                    f"Mode -> "
                    f"{mode}: "
                    f"{MODES[mode]}"
                )

            # ------------------------------------------------
            # SNAPSHOT
            # ------------------------------------------------

            elif key in (
                ord("s"),
                ord("S")
            ):

                path = save_snapshot(
                    display
                )

                print(
                    "Snapshot saved:"
                )

                print(
                    path.resolve()
                )

            # ------------------------------------------------
            # RECORD
            # ------------------------------------------------

            elif key in (
                ord("r"),
                ord("R")
            ):

                if writer is None:

                    writer, recording_path = (
                        make_video_writer(
                            display,
                            fps
                        )
                    )

                    print(
                        "Recording started:"
                    )

                    print(
                        recording_path.resolve()
                    )

                else:

                    writer.release()

                    writer = None

                    print(
                        "Recording saved:"
                    )

                    print(
                        recording_path.resolve()
                    )

                    recording_path = None

            # ------------------------------------------------
            # PAUSE
            # ------------------------------------------------

            elif key == 32:

                paused = not paused

                if paused:

                    print(
                        "Camera paused."
                    )

                else:

                    print(
                        "Camera resumed."
                    )

            # ------------------------------------------------
            # HUD TOGGLE
            # ------------------------------------------------

            elif key in (
                ord("h"),
                ord("H")
            ):

                show_hud = (
                    not show_hud
                )

    # ========================================================
    # CLEANUP
    # ========================================================

    finally:

        if writer is not None:

            writer.release()

        cap.release()

        cv2.destroyAllWindows()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()

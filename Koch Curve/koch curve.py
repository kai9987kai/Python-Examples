        raw = koch_points(self.length, self.level, self.mode)
        rotation = transformed(raw, self.angle)
        horizontal_span = max(p.real for p in rotation) - min(p.real for p in rotation)
        vertical_span = max(p.imag for p in rotation) - min(p.imag for p in rotation)
        width = max(250, self.screen.window_width() - 100)
        height = max(250, self.screen.window_height() - 260)
        scale_to_fit = min(1.0, width / max(horizontal_span, 1),
                           height / max(vertical_span, 1))
        self.points = [p * scale_to_fit * self.zoom - 35j for p in rotation]
        self.pen.penup()
        self.pen.goto(self.points[0].real, self.points[0].imag)
        self.pen.pencolor(palette_color(self.palette, 0))
        self.pen.fillcolor(palette_color(self.palette, 0.24))
        self.pen.pendown()
        if self.filled and self.mode != "curve":
            self.pen.begin_fill()
        self._write_hud()
        self.screen.update()
        self._schedule(current)

    def _schedule(self, epoch: int) -> None:
        self.screen.ontimer(lambda token=epoch: self._draw_batch(token), 1 if not self.animate else 22)

    def _draw_batch(self, epoch: int) -> None:
        if epoch != self.epoch or self.paused or self.done:
            return
        segments = len(self.points) - 1
        chunk = 28 if self.animate else 750
        stop = min(segments, self.cursor + chunk)
        for index in range(self.cursor, stop):
            if index % self.colored_every == 0:
                self.pen.pencolor(palette_color(self.palette, index / max(1, segments - 1)))
            p = self.points[index + 1]
            self.pen.goto(p.real, p.imag)
        self.cursor = stop
        if self.cursor >= segments:
            if self.filled and self.mode != "curve":
                self.pen.end_fill()
            self.done = True
        progress_bucket = self.cursor * 20 // max(1, segments)
        if progress_bucket != self._last_progress_bucket or self.done:
            self._last_progress_bucket = progress_bucket
            self._write_hud()
        try:
            self.screen.update()
            if not self.done:
                self._schedule(epoch)
        except (self.turtle_module.Terminator, RuntimeError):
            pass  # Window has been closed.

    def save_svg(self) -> None:
        from tkinter import filedialog, messagebox
        name = f"koch_{self.mode}_level_{self.level}.svg"
        filepath = filedialog.asksaveasfilename(title="Export Koch fractal as SVG",
                                                initialfile=name,
                                                defaultextension=".svg",
                                                filetypes=[("Scalable Vector Graphics", "*.svg")])
        if filepath:
            try:
                raw = koch_points(self.length, self.level, self.mode)
                rotated = [p * complex(math.cos(math.radians(self.angle)),
                                       math.sin(math.radians(self.angle))) for p in raw]
                saved = export_svg(Path(filepath), rotated, self.mode, self.level,
                                   self.palette, self.filled, self.bg_dark)
                messagebox.showinfo("SVG exported", f"Saved complete vector fractal:\n{saved}")
            except OSError as exc:
                messagebox.showerror("Export failed", str(exc))
        self.screen.listen()

    def start(self) -> None:
        self.screen.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--level', type=int, default=4, help='Iteration depth (0–7)')
    parser.add_argument('--length', type=float, default=300.0, help='Initial side length')
    parser.add_argument('--mode', choices=MODES, default='snowflake')
    parser.add_argument('--palette', choices=PALETTES, default='ice')
    parser.add_argument('--animate', action='store_true', help='Use slower drawing animation')
    parser.add_argument('--fill', action='store_true', help='Fill enclosed fractals')
    parser.add_argument('--light', action='store_true', help='Use a light background')
    parser.add_argument('--export', type=Path, help='Also export a full vector SVG')
    parser.add_argument('--no-gui', action='store_true', help='Run without a display (requires --export)')
    parser.add_argument('--self-test', action='store_true', help='Run mathematical regression tests and exit')
    args = parser.parse_args()
    if args.self_test:
        run_self_tests()
        return
    if args.no_gui and not args.export:
        parser.error('--no-gui requires --export')
    try:
        points = koch_points(args.length, args.level, args.mode)
    except ValueError as error:
        parser.error(str(error))
    if args.export:
        try:
            path = export_svg(args.export, points, args.mode, args.level,
                              args.palette, args.fill, not args.light)
        except OSError as error:
            parser.error(f'export failed: {error}')
        print(f'Exported {path} with {len(points)-1:,} segments')
    if not args.no_gui:
        try:
            KochExplorer(args.length, args.level, args.mode, args.palette,
                         args.animate, args.fill, not args.light).start()
        except ImportError as error:
            parser.error(f'Tkinter is not installed: {error}. Use --no-gui --export FILE.svg')
        except Exception as error:
            if type(error).__name__ == 'TclError':
                parser.error(f'cannot open graphical window: {error}. Use --no-gui --export FILE.svg')
            raise


if __name__ == '__main__':
    main()

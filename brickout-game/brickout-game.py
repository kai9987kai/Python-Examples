                self.write_records()
                return False
            if event.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.window_size = (max(640, event.w), max(360, event.h))
                self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
            elif event.type == pygame.MOUSEMOTION:
                self.mouse_target, _ = self.to_world(event.pos)
                self.mouse_timer = 1.25
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state == "playing":
                    if any(ball.attached for ball in self.balls):
                        self.launch()
                    else:
                        self.firing = True
                        self.fire_lasers()
                else:
                    mouse = self.to_world(event.pos)
                    for rect, action in self.buttons:
                        if rect.collidepoint(mouse):
                            self.perform_action(action)
                            break
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.firing = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F11:
                    self.fullscreen_toggle()
                elif event.key == pygame.K_m:
                    self.sound_on = not self.sound_on
                    self.write_records()
                elif event.key == pygame.K_ESCAPE:
                    if self.state == "playing":
                        self.state = "paused"
                        self.firing = False
                    elif self.state == "paused":
                        self.state = "playing"
                    else:
                        self.state = "menu"
                elif event.key == pygame.K_p:
                    if self.state == "playing":
                        self.state = "paused"
                        self.firing = False
                    elif self.state == "paused":
                        self.state = "playing"
                elif self.state == "playing":
                    if event.key == pygame.K_SPACE:
                        self.launch()
                    elif event.key == pygame.K_r:
                        self.new_game()
                elif self.state in ("menu", "help", "paused", "game_over", "victory"):
                    if event.key == pygame.K_RETURN:
                        if self.state == "paused":
                            self.state = "playing"
                        elif self.state == "help":
                            self.state = "menu"
                        else:
                            self.new_game()
                    elif self.state == "menu":
                        if event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                            self.difficulty = list(DIFFICULTIES)[event.key - pygame.K_1]
                            self.write_records()
                        elif event.key == pygame.K_TAB:
                            self.perform_action("mode")
        return True

    def run(self, *, max_frames: Optional[int] = None) -> None:
        running = True
        frames = 0
        while running:
            elapsed = min(self.clock.tick(FPS_LIMIT) / 1000.0, 1 / 20)
            running = self.events()
            if not running:
                break
            self.accumulator += elapsed
            steps = 0
            while self.accumulator >= STEP and steps < 7:
                self.update(STEP)
                self.accumulator -= STEP
                steps += 1
            if steps >= 7:
                self.accumulator = 0.0
            self.draw()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break
        self.write_records()
        pygame.quit()


def smoke_test() -> None:
    """Optional graphical/physics self-test, using SDL's headless driver."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    game = Game(headless=True)
    game.write_records = lambda: None  # Do not alter real achievements during tests.
    game.new_game()
    assert len(game.bricks) > 0
    game.launch()
    game.damage_brick(game.bricks[0])
    for power in POWERUPS:
        game.use_powerup(power)
    for frame in range(1500):
        game.update(STEP)
        if frame % 150 == 0:
            game.draw()
        for ball in game.balls:
            assert math.isfinite(ball.pos.x) and math.isfinite(ball.pos.y)
            assert math.isfinite(ball.vel.x) and math.isfinite(ball.vel.y)
        assert 0 <= game.lives <= 9
        if game.state in ("game_over", "victory"):
            break
    print("SMOKE TEST PASSED: scene rendering, input-independent logic, power-ups, physics")
    pygame.quit()


def main() -> None:
    try:
        if "--smoke-test" in sys.argv:
            smoke_test()
        else:
            Game().run()
    except pygame.error as error:
        print(f"Pygame could not initialize or run: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

import pygame
import sys

# Initialize pygame
pygame.init()

# --- Settings ---
WIDTH, HEIGHT = 900, 600
FPS = 60
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Mortal Kombat Inspired Game")

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED   = (200, 50, 50)
BLUE  = (50, 100, 200)
GRAY  = (100, 100, 100)
GREEN = (50, 200, 50)
YELLOW = (220, 220, 50)

# Characters you can pick
CHARACTERS = [
    {"name": "Scorpion", "color": YELLOW},
    {"name": "Sub-Zero", "color": BLUE},
    {"name": "Kitana", "color": (0,180,255)},
    {"name": "Raiden", "color": (220,220,255)},
]

PLAYER_KEYS = [
    {"left": pygame.K_a, "right": pygame.K_d, "up": pygame.K_w, "down": pygame.K_s, "attack": pygame.K_j},
    {"left": pygame.K_LEFT, "right": pygame.K_RIGHT, "up": pygame.K_UP, "down": pygame.K_DOWN, "attack": pygame.K_KP0},
]

# Fonts
def get_font(size): return pygame.font.SysFont("arial", size, bold=True)

# Game states
MENU, CHAR_SELECT, VERSUS, FIGHT, GAME_OVER = "menu", "charselect", "versus", "fight", "gameover"

# Player/fighter class
class Fighter:
    def __init__(self, name, color, pos, controls):
        self.name = name
        self.color = color
        self.rect = pygame.Rect(*pos, 60, 120)
        self.health = 100
        self.max_health = 100
        self.controls = controls
        self.attack_cooldown = 0

    def move(self, keys):
        speed = 5
        if keys[self.controls["left"]]:  self.rect.x -= speed
        if keys[self.controls["right"]]: self.rect.x += speed
        if keys[self.controls["up"]]:    self.rect.y -= speed
        if keys[self.controls["down"]]:  self.rect.y += speed
        # Stay inside the arena:
        self.rect.x = max(0, min(self.rect.x, WIDTH - self.rect.width))
        self.rect.y = max(200, min(self.rect.y, HEIGHT - self.rect.height))

    def attack(self, opponent):
        if self.attack_cooldown == 0:
            # If close enough, deal damage
            if self.rect.colliderect(opponent.rect.inflate(20, 0)):
                opponent.health -= 10
                self.attack_cooldown = 30  # Cooldown frames

    def draw(self, surf):
        pygame.draw.rect(surf, self.color, self.rect)
        name_text = get_font(22).render(self.name, True, WHITE)
        surf.blit(name_text, (self.rect.x + 5, self.rect.y - 28))

    def update(self):
        if self.attack_cooldown > 0:
            self.attack_cooldown -= 1

# Draw health bars
def draw_health_bar(surf, x, y, percent, color, name):
    pygame.draw.rect(surf, GRAY, (x, y, 240, 24))
    pygame.draw.rect(surf, color, (x, y, 240 * percent // 100, 24))
    label = get_font(20).render(f"{name}", True, WHITE)
    surf.blit(label, (x + 5, y - 22))
    hp_text = get_font(18).render(f"{percent}/100", True, WHITE)
    surf.blit(hp_text, (x + 180, y - 3))

# Main menu
def main_menu():
    while True:
        screen.fill(BLACK)
        title = get_font(64).render("MORTAL KOMBAT", True, RED)
        screen.blit(title, (WIDTH//2 - title.get_width()//2, 80))
        play_text = get_font(36).render("Press ENTER to Start", True, WHITE)
        quit_text = get_font(28).render("Press Q to Quit", True, GRAY)
        screen.blit(play_text, (WIDTH//2 - play_text.get_width()//2, 250))
        screen.blit(quit_text, (WIDTH//2 - quit_text.get_width()//2, 330))
        pygame.display.flip()
        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    return
                if event.key == pygame.K_q:
                    sys.exit()

# Character selection
def character_select():
    selected = [0, 1]
    picking = 0  # 0 for P1, 1 for P2
    done = [False, False]
    while True:
        screen.fill(BLACK)
        info = get_font(34).render(f"Player {picking+1}: Choose your fighter!", True, YELLOW)
        screen.blit(info, (WIDTH//2 - info.get_width()//2, 60))
        for i, char in enumerate(CHARACTERS):
            x = 180 + i*160
            y = 200
            color = char["color"] if not (done[0] and selected[0]==i) and not (done[1] and selected[1]==i) else GRAY
            pygame.draw.rect(screen, color, (x, y, 100, 120))
            name = get_font(22).render(char["name"], True, WHITE)
            screen.blit(name, (x + 5, y + 130))
            # highlight
            if selected[picking] == i:
                pygame.draw.rect(screen, GREEN, (x-4, y-4, 108, 128), 4)
        instruct = get_font(22).render("Use <- and ->, ENTER to pick!", True, WHITE)
        screen.blit(instruct, (WIDTH//2 - instruct.get_width()//2, HEIGHT-90))
        pygame.display.flip()
        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_LEFT:
                    selected[picking] = (selected[picking] - 1) % len(CHARACTERS)
                if event.key == pygame.K_RIGHT:
                    selected[picking] = (selected[picking] + 1) % len(CHARACTERS)
                if event.key == pygame.K_RETURN:
                    # Can't pick same character
                    if picking == 1 and selected[1] == selected[0]:
                        continue
                    done[picking] = True
                    if picking == 1 and all(done):
                        return selected
                    picking = 1 if picking == 0 else 0
                if event.key == pygame.K_ESCAPE:
                    return [0, 1]

# Versus screen
def versus_screen(p1, p2):
    timer = 90
    while timer > 0:
        screen.fill(BLACK)
        txt = get_font(44).render("VERSUS!", True, RED)
        screen.blit(txt, (WIDTH//2 - txt.get_width()//2, 80))
        left = get_font(32).render(p1["name"], True, p1["color"])
        right = get_font(32).render(p2["name"], True, p2["color"])
        screen.blit(left, (180, HEIGHT//2-30))
        screen.blit(right, (WIDTH-300, HEIGHT//2-30))
        pygame.display.flip()
        pygame.time.delay(15)
        timer -= 1

# Game over screen
def game_over_screen(winner):
    while True:
        screen.fill(BLACK)
        msg = get_font(48).render(f"{winner} wins!", True, GREEN)
        screen.blit(msg, (WIDTH//2 - msg.get_width()//2, 180))
        again = get_font(28).render("Press ENTER to return to menu", True, WHITE)
        screen.blit(again, (WIDTH//2 - again.get_width()//2, 320))
        pygame.display.flip()
        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                return

# Fight/gameplay
def fight_game(selected_chars):
    p1data = CHARACTERS[selected_chars[0]]
    p2data = CHARACTERS[selected_chars[1]]
    p1 = Fighter(p1data["name"], p1data["color"], (120, HEIGHT-210), PLAYER_KEYS[0])
    p2 = Fighter(p2data["name"], p2data["color"], (WIDTH-180, HEIGHT-210), PLAYER_KEYS[1])
    clock = pygame.time.Clock()
    running = True
    winner = None
    while running:
        keys = pygame.key.get_pressed()
        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == p1.controls["attack"]:
                    p1.attack(p2)
                if event.key == p2.controls["attack"]:
                    p2.attack(p1)

        if p1.health > 0 and p2.health > 0:
            p1.move(keys)
            p2.move(keys)
            p1.update()
            p2.update()
        else:
            winner = p1.name if p1.health > 0 else p2.name
            running = False

        screen.fill(BLACK)
        # Draw health bars
        draw_health_bar(screen, 40, 40, max(0, p1.health), p1.color, p1.name)
        draw_health_bar(screen, WIDTH-280, 40, max(0, p2.health), p2.color, p2.name)
        # Draw fighters
        p1.draw(screen)
        p2.draw(screen)
        # Attack instructions
        atk1 = get_font(18).render("P1 Attack: J", True, WHITE)
        atk2 = get_font(18).render("P2 Attack: Numpad 0", True, WHITE)
        screen.blit(atk1, (40, 120))
        screen.blit(atk2, (WIDTH-210, 120))
        pygame.display.flip()
        clock.tick(FPS)
    game_over_screen(winner)

# Main game loop
def main():
    while True:
        main_menu()
        chars = character_select()
        versus_screen(CHARACTERS[chars[0]], CHARACTERS[chars[1]])
        fight_game(chars)

if __name__ == "__main__":
    main()

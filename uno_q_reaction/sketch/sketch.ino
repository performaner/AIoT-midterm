#include <Arduino_LED_Matrix.h>
#include <Arduino_RouterBridge.h>
#include <ctype.h>
Arduino_LED_Matrix matrix;
uint8_t pixels[104];
int activeState = 5;
int leftScore = 0, rightScore = 0;
uint32_t frameAt = 0;
int scrollX = 13;
bool scorePause = true;
const char* winnerText = "";
uint32_t hitAt = 0;

const uint8_t digits[10][5] = {
  {7,5,5,5,7}, {2,6,2,2,7}, {7,1,7,4,7}, {7,1,7,1,7}, {5,5,7,1,1},
  {7,4,7,1,7}, {7,4,7,5,7}, {7,1,2,2,2}, {7,5,7,5,7}, {7,5,7,1,7}
};
const uint8_t narrowDigits[10][5] = {
  {3,3,3,3,3}, {1,1,1,1,1}, {3,1,3,2,3}, {3,1,3,1,3}, {2,2,3,1,1},
  {3,2,3,1,3}, {3,2,3,3,3}, {3,1,1,2,2}, {3,3,0,3,3}, {3,3,3,1,3}
};
// Five-column, seven-row uppercase font. Text is case-folded for LED legibility.
const char letters[] = "ACEGILNOPRSTUWY12!";
const uint8_t font[][7] = {
  {14,17,17,31,17,17,17}, {14,17,16,16,16,17,14},
  {31,16,16,30,16,16,31}, {14,17,16,23,17,17,15},
  {14,4,4,4,4,4,14}, {16,16,16,16,16,16,31},
  {17,25,25,21,19,19,17}, {14,17,17,17,17,17,14},
  {30,17,17,30,16,16,16}, {30,17,17,30,20,18,17},
  {15,16,16,14,1,1,30}, {31,4,4,4,4,4,4},
  {17,17,17,17,17,17,14}, {17,17,17,21,21,21,10},
  {17,17,10,4,4,4,4}, {4,12,4,4,4,4,14},
  {14,17,1,2,4,8,31}, {4,4,4,4,4,0,4}
};

void rgb(bool red, bool green, bool blue) {
  // UNO Q MCU-controlled RGB LED3 is active-low.
  digitalWrite(LED3_R, red ? LOW : HIGH);
  digitalWrite(LED3_G, green ? LOW : HIGH);
  digitalWrite(LED3_B, blue ? LOW : HIGH);
}

void draw_digit(int digit, int left, bool narrow) {
  int width = narrow ? 2 : 3;
  const uint8_t* rows = narrow ? narrowDigits[digit] : digits[digit];
  for (int y = 0; y < 5; y++)
    for (int x = 0; x < width; x++)
      pixels[(y + 1) * 13 + left + x] = (rows[y] >> (width - 1 - x)) & 1;
}

void draw_score() {
  memset(pixels, 0, sizeof(pixels));
  if (leftScore >= 10) {
    draw_digit(leftScore / 10, 0, true);
    draw_digit(leftScore % 10, 3, true);
  } else {
    draw_digit(leftScore, 1, false);
  }
  if (rightScore >= 10) {
    draw_digit(rightScore / 10, 8, true);
    draw_digit(rightScore % 10, 11, true);
  } else {
    draw_digit(rightScore, 9, false);
  }
  pixels[2 * 13 + 6] = pixels[4 * 13 + 6] = 1;
  matrix.draw(pixels);
}

void draw_text(int offset) {
  memset(pixels, 0, sizeof(pixels));
  for (size_t i = 0; winnerText[i]; i++) {
    int start = offset + int(i) * 6;
    if (start > 12 || start + 4 < 0) continue;
    char ch = char(toupper(static_cast<unsigned char>(winnerText[i])));
    const char* found = strchr(letters, ch);
    if (!found) continue;
    int glyph = int(found - letters);
    for (int y = 0; y < 7; y++)
      for (int x = 0; x < 5; x++)
        if (start + x >= 0 && start + x < 13)
          pixels[y * 13 + start + x] = (font[glyph][y] >> (4 - x)) & 1;
  }
  matrix.draw(pixels);
}

bool is_final(int state) {
  return state == 7 || state == 8 || state == 15;
}

bool is_hit(int state) {
  return (state >= 12 && state <= 14) || state == 16;
}

int show_duel_v7(int state, int score1, int score2) {
  if (state < 0 || state > 16 || score1 < 0 || score1 > 99 || score2 < 0 ||
      score2 > 99 || score1 + score2 > 99) return -1;
  if (((state == 7 || state == 13) && score1 <= score2) ||
      ((state == 8 || state == 14) && score2 <= score1) ||
      ((state == 15 || state == 16) && (score1 != score2 || score1 == 0))) return -1;
  if (is_final(state) && state == activeState && leftScore == score1 && rightScore == score2) return state;
  activeState = state;
  leftScore = score1;
  rightScore = score2;
  rgb(state == 3 || state == 4 || state == 10,
      state == 2 || state == 6 || state == 9 || is_hit(state),
      state == 1 || state == 11);
  // Keep the matrix dark throughout the round so only RGB LED3 signals the cue.
  matrix.setGrayscaleBits(1);
  if (is_final(state)) {
    winnerText = state == 15 ? "TIE" :
                 state == 7 ? "Congratulations! Player 1 WIN" : "Congratulations! Player 2 WIN";
    scrollX = 13;
    scorePause = true;
    frameAt = millis();
    draw_score();
  } else if (state == 5) {
    draw_score();
  } else if (state >= 9) {
    // A hit is a ring. Formal hits return to score or winner marquee locally.
    const uint8_t ring[7] = {14,17,17,17,17,17,14};
    const uint8_t cross[7] = {17,10,4,4,4,10,17};
    const uint8_t letterP[7] = {30,17,17,30,16,16,16};
    const uint8_t* glyph = (state == 9 || is_hit(state)) ? ring : state == 10 ? cross : letterP;
    if (is_hit(state)) hitAt = millis();
    memset(pixels, 0, sizeof(pixels));
    for (int y = 0; y < 7; y++)
      for (int x = 0; x < 5; x++)
        pixels[y * 13 + 4 + x] = (glyph[y] >> (4 - x)) & 1;
    matrix.draw(pixels);
  } else {
    memset(pixels, 0, sizeof(pixels));
    for (int y = 0; y < 8; y++) {
      for (int x = 0; x < 13; x++) {
        bool on = false;
        if (state == 0) on = x == 0 || x == 12 || y == 0 || y == 7;
        pixels[y * 13 + x] = on ? 1 : 0;
      }
    }
    matrix.draw(pixels);
  }
  return state;
}

void update_marquee() {
  if (!is_final(activeState)) return;
  uint32_t now = millis();
  if (uint32_t(now - frameAt) < (scorePause ? 1500u : 65u)) return;
  frameAt = now;
  scorePause = false;
  draw_text(scrollX--);
  if (scrollX < -int(strlen(winnerText) * 6)) {
    scrollX = 13;
    scorePause = true;
    draw_score();
  }
}

void setup() {
  pinMode(LED3_R, OUTPUT);
  pinMode(LED3_G, OUTPUT);
  pinMode(LED3_B, OUTPUT);
  matrix.begin();
  matrix.setGrayscaleBits(1);
  show_duel_v7(5, 0, 0);
  Bridge.begin();
  // Execute RPC in the Arduino loop context so marquee and draws cannot race.
  Bridge.provide_safe("show_duel_v7", show_duel_v7);
  Bridge.provide_safe("duel_version", []() -> int { return 7; });
}

void loop() {
  if (is_hit(activeState) && uint32_t(millis() - hitAt) >= 700u) {
    int nextState = activeState == 12 ? 5 : activeState == 16 ? 15 : activeState - 6;
    show_duel_v7(nextState, leftScore, rightScore);
  }
  update_marquee();
  delay(1);
}

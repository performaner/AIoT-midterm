"""Native simulation of sketch logic, not an Arduino toolchain/hardware test."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('g++'), 'Optional g++ compiler is not installed')
class FirmwareTests(unittest.TestCase):
    def test_rgb_scores_and_interruptible_marquee(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'Arduino_LED_Matrix.h').write_text('''#pragma once
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cassert>
constexpr int LOW=0, HIGH=1, OUTPUT=1, LED3_R=0, LED3_G=1, LED3_B=2;
uint32_t sim_now=0;
int pins[3]={1,1,1};
uint32_t millis(){return sim_now;}
void delay(int){}
void pinMode(int,int){}
void digitalWrite(int pin,int value){pins[pin]=value;}
struct Arduino_LED_Matrix {
  uint8_t last[104]={};
  void begin(){}
  int bits=1;
  void setGrayscaleBits(int value){bits=value;}
  void draw(const uint8_t* buf){memcpy(last,buf,104);}
};
''', encoding='utf-8')
            (folder / 'Arduino_RouterBridge.h').write_text('''#pragma once
struct BridgeStub {
  void begin(){}
  template<class F> void provide_safe(const char*,F){}
} Bridge;
''', encoding='utf-8')
            sketch = (Path(__file__).resolve().parents[1] / 'uno_q_reaction/sketch/sketch.ino').read_text(encoding='utf-8')
            main = r'''
int main() {
  setup();
  assert(show_duel_v7(2,0,0)==2);
  assert(pins[LED3_G]==LOW && pins[LED3_R]==HIGH);
  uint8_t go[104]; memcpy(go,pixels,104);
  show_duel_v7(3,0,0);
  assert(pins[LED3_R]==LOW && pins[LED3_G]==HIGH);
  assert(memcmp(go,pixels,104)==0);
  show_duel_v7(4,0,0); assert(pins[LED3_R]==LOW);
  show_duel_v7(6,0,0); assert(pins[LED3_G]==LOW);
  show_duel_v7(5,2,1);
  assert(pixels[2*13+6] && pixels[4*13+6]);
  for(int y=0;y<5;y++) for(int x=0;x<3;x++) {
    assert(pixels[(y+1)*13+1+x]==((digits[2][y]>>(2-x))&1));
    assert(pixels[(y+1)*13+9+x]==((digits[1][y]>>(2-x))&1));
  }
  assert(show_duel_v7(7,1,2)==-1);
  show_duel_v7(7,3,1);
  assert(strcmp(winnerText,"Congratulations! Player 1 WIN")==0);
  for(const char* p=winnerText;*p;p++)
    assert(*p==' ' || strchr(letters,toupper(*p))!=nullptr);
  uint8_t score[104]; memcpy(score,pixels,104);
  sim_now=1499; loop(); assert(memcmp(score,pixels,104)==0);
  sim_now=1500; loop(); assert(scrollX==12);
  bool lit=false;
  for(int i=0;i<30;i++) {sim_now+=65;loop();for(auto p:pixels) lit=lit||p;}
  assert(lit);
  int before=scrollX;show_duel_v7(7,3,1);assert(scrollX==before);
  show_duel_v7(1,0,0); memcpy(score,pixels,104);
  assert(pins[LED3_B]==LOW);
  for(auto p:pixels) assert(p==0);
  sim_now+=5000;loop();assert(memcmp(score,pixels,104)==0);
  const int cues[] = {2,3,4,6};
  for(int cue : cues) {
    show_duel_v7(cue,0,0);
    assert(memcmp(score,pixels,104)==0);
  }
  show_duel_v7(8,2,3);assert(strcmp(winnerText,"Congratulations! Player 2 WIN")==0);
  show_duel_v7(9,0,0); assert(pins[LED3_G]==LOW && pixels[0*13+5]);
  show_duel_v7(10,0,0); assert(pins[LED3_R]==LOW && pixels[3*13+6]);
  show_duel_v7(11,0,0); assert(pins[LED3_B]==LOW && pixels[0*13+5]);
  assert(show_duel_v7(12,1,0)==12);
  assert(pixels[0*13+5] && !pixels[3*13+6]);
  sim_now+=699;loop();assert(activeState==12);
  sim_now+=1;loop();assert(activeState==5);
  assert(show_duel_v7(13,3,1)==13);
  sim_now+=700;loop();assert(activeState==7);
  assert(show_duel_v7(15,0,0)==-1);
  bool returned=false;
  for(int i=0;i<230;i++){sim_now+=65;loop();if(scorePause&&i>30)returned=true;}
  assert(returned);
  assert(show_duel_v7(7,60,39)==7);
  for(int y=0;y<5;y++) for(int x=0;x<2;x++) {
    assert(pixels[(y+1)*13+x]==((narrowDigits[6][y]>>(1-x))&1));
    assert(pixels[(y+1)*13+3+x]==((narrowDigits[0][y]>>(1-x))&1));
    assert(pixels[(y+1)*13+8+x]==((narrowDigits[3][y]>>(1-x))&1));
    assert(pixels[(y+1)*13+11+x]==((narrowDigits[9][y]>>(1-x))&1));
  }
  assert(show_duel_v7(16,49,49)==16);
  sim_now+=700;loop();assert(activeState==15 && strcmp(winnerText,"TIE")==0);
  sim_now+=1500;loop();assert(scrollX==12);
}
'''
            source = folder / 'test.cpp'
            source.write_text(sketch + main, encoding='utf-8')
            binary = folder / 'test.exe'
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(folder), str(source), '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)

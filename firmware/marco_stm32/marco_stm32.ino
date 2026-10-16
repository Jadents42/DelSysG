// MARCO STM32 Blackpill firmware (STM32duino)
//
// 6 quadrature encoders (x4 decoding, interrupt driven) + 4 limit switches.
// Reports to the Raspberry Pi over USART2 (PA2 = TX, PA3 = RX) at 921600 baud.
//
// Output lines, each terminated by '\n':
//   enc1: <count>  ...  enc6: <count>     every REPORT_PERIOD_MS
//   lim: <s1>,<s2>,<s3>,<s4>              every REPORT_PERIOD_MS and on any change
//                                         1 = pressed, 0 = open
//
// The "lim" line is comma separated on purpose: the old Pi parser does
// int(value) on every line, which raises ValueError here, so it skips the
// line instead of mistaking it for an encoder.
//
// Arduino IDE settings:
//   Board: Generic STM32F4 series, part: BlackPill F411CE (or F401CC)
//   USB support: None   (PA11/PA12 are used by encoders 2/3)
//   U(S)ART support: Enabled (generic 'Serial')

#include <Arduino.h>

// STM32 core 3.x renamed its UART class from HardwareSerial to Uart.
#if STM32_CORE_VERSION_MAJOR >= 3
Uart PiSerial(PA3, PA2);            // RX, TX
#else
HardwareSerial PiSerial(PA3, PA2);  // RX, TX
#endif

const uint32_t BAUD = 921600;
const uint32_t REPORT_PERIOD_MS = 10;
const uint32_t DEBOUNCE_MS = 5;
const uint32_t LED_PERIOD_MS = 500;

// ---------------- Encoders ----------------
// {A, B} per encoder. Swap A and B to flip an encoder's count direction.
// Every pin has a unique pin number, so each gets its own EXTI line.
const uint8_t NUM_ENC = 6;
const uint32_t ENC_PINS[NUM_ENC][2] = {
  {PB13, PB14},  // enc1 - rail 0
  {PA10, PA11},  // enc2 - rail 1
  {PA12, PA15},  // enc3 - rail 2
  {PB3,  PB4},   // enc4 - rail 3
  {PB5,  PB6},   // enc5 - divider 1
  {PB7,  PB8},   // enc6 - divider 2
};

// Index: (previous AB << 2) | current AB. Invalid transitions count as 0.
const int8_t QDEC[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};

PinName encPinName[NUM_ENC][2];
volatile int32_t encCount[NUM_ENC];
volatile uint8_t encState[NUM_ENC];

static inline uint8_t readAB(uint8_t i) {
  return (digitalReadFast(encPinName[i][0]) << 1) | digitalReadFast(encPinName[i][1]);
}

static inline void encUpdate(uint8_t i) {
  uint8_t ab = readAB(i);
  encCount[i] += QDEC[(encState[i] << 2) | ab];
  encState[i] = ab;
}

template <uint8_t I>
void encIsr() { encUpdate(I); }

void (*const ENC_ISRS[NUM_ENC])() = {
  encIsr<0>, encIsr<1>, encIsr<2>, encIsr<3>, encIsr<4>, encIsr<5>,
};

// ---------------- Limit switches ----------------
// External 10k pull-up to 3.3V, switch to GND: pressed reads LOW.
// Polled, not interrupt driven: PA5/PA6 share EXTI lines with PB5/PB6.
// Note: PA0 is also the Blackpill's onboard KEY button.
const uint8_t NUM_LIM = 4;
const uint32_t LIM_PINS[NUM_LIM] = {PA6, PA5, PA1, PA0};  // lim1..lim4

uint8_t limRaw[NUM_LIM];
uint8_t limStable[NUM_LIM];
uint32_t limChangedAt[NUM_LIM];

static inline uint8_t readLimit(uint8_t i) {
  return digitalRead(LIM_PINS[i]) == LOW;
}

// Returns true if any debounced switch state changed.
bool pollLimits(uint32_t now) {
  bool changed = false;
  for (uint8_t i = 0; i < NUM_LIM; i++) {
    uint8_t r = readLimit(i);
    if (r != limRaw[i]) {
      limRaw[i] = r;
      limChangedAt[i] = now;
    } else if (r != limStable[i] && now - limChangedAt[i] >= DEBOUNCE_MS) {
      limStable[i] = r;
      changed = true;
    }
  }
  return changed;
}

// ---------------- Reporting ----------------
void sendEncoders() {
  int32_t snap[NUM_ENC];
  noInterrupts();
  for (uint8_t i = 0; i < NUM_ENC; i++) snap[i] = encCount[i];
  interrupts();

  for (uint8_t i = 0; i < NUM_ENC; i++) {
    PiSerial.print("enc");
    PiSerial.print(i + 1);
    PiSerial.print(": ");
    PiSerial.print(snap[i]);
    PiSerial.print('\n');
  }
}

void sendLimits() {
  PiSerial.print("lim: ");
  for (uint8_t i = 0; i < NUM_LIM; i++) {
    if (i) PiSerial.print(',');
    PiSerial.print(limStable[i]);
  }
  PiSerial.print('\n');
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  PiSerial.begin(BAUD);

  for (uint8_t i = 0; i < NUM_LIM; i++) {
    pinMode(LIM_PINS[i], INPUT_PULLUP);  // backs up the external 10k
    limRaw[i] = limStable[i] = readLimit(i);
    limChangedAt[i] = millis();
  }

  for (uint8_t i = 0; i < NUM_ENC; i++) {
    for (uint8_t c = 0; c < 2; c++) {
      pinMode(ENC_PINS[i][c], INPUT_PULLUP);
      encPinName[i][c] = digitalPinToPinName(ENC_PINS[i][c]);
    }
    encCount[i] = 0;
    encState[i] = readAB(i);
    attachInterrupt(digitalPinToInterrupt(ENC_PINS[i][0]), ENC_ISRS[i], CHANGE);
    attachInterrupt(digitalPinToInterrupt(ENC_PINS[i][1]), ENC_ISRS[i], CHANGE);
  }
}

void loop() {
  static uint32_t lastReport = 0;
  static uint32_t lastLed = 0;
  uint32_t now = millis();

  // The STM32 no longer takes commands; discard anything the Pi sends.
  while (PiSerial.available()) PiSerial.read();

  if (pollLimits(now)) sendLimits();

  if (now - lastReport >= REPORT_PERIOD_MS) {
    lastReport = now;
    sendEncoders();
    sendLimits();
  }

  if (now - lastLed >= LED_PERIOD_MS) {
    lastLed = now;
    digitalToggle(LED_BUILTIN);
  }
}

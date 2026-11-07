/*
  ESP32 QKD teaching project — Wi-Fi gate simulator and local trigger counter.

  HTTP API on the trusted LAN:
    GET  /api/telemetry
    POST /api/control with {"action":"set_chain","chain":[...]}
    GET  /api/simulation-trigger
    POST /api/message with the documented ordinary-text round-trip contract
    POST /api/aos-demo/provision from Key Generator with password + 32-byte key + UTF-8 message
    POST /api/aos-demo/downlink from Communication/Base Station with password only

  The gate chain remains a classical state-vector calculation. PB4/GPIO22 is
  active-low and, in this project only, increments a volatile simulation
  trigger counter. The counter does not cause ESP-side circuit execution.

  DEMO-ONLY WARNING: password and AES key are volatile teaching material sent
  over unencrypted plain HTTP on a trusted LAN. This is not secure provisioning,
  a secure transport, CCSDS-compliant satellite software, or a QKD claim.
  Frozen frame profile: 6-octet primary header (no FHEC or Insert Zone) +
  14-octet Security Header + 32-octet Data Field + 16-octet tag = 68 octets;
  no OCF or FECF is present.
*/

#include <Arduino.h>
#include <ArduinoJson.h>  // ArduinoJson 6.21.x
#include <WiFi.h>
#include <WebServer.h>
#include <esp_random.h>
#include <mbedtls/gcm.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>
#include <stdio.h>
#include <string.h>
#include "aos_demo_profile.h"

static constexpr uint8_t STATUS_LED_PIN = 2;  // OUTPUT ONLY; never read as input
static constexpr uint8_t PB1_H_PIN = 18;
static constexpr uint8_t PB2_X_PIN = 19;
static constexpr uint8_t PB3_SLOT_PIN = 21;
static constexpr uint8_t PB4_SIMULATION_PIN = 22;
static constexpr uint8_t PB5_DISPLAY_PIN = 25;
static constexpr uint8_t PB6_RESET_PIN = 27;

// Many ESP32 development boards wire the GPIO2 LED active-low. Change this
// one setting if your board's LED polarity differs.
static constexpr uint8_t LED_ON_LEVEL = HIGH;
static constexpr uint32_t DEBOUNCE_MS = 35;
static constexpr size_t MAX_CHAIN_GATES = 64;
static constexpr size_t MAX_MESSAGE_BODY_BYTES = 1024;
static constexpr size_t MAX_MESSAGE_TEXT_BYTES = 256;
static constexpr size_t MAX_MESSAGE_ID_BYTES = 32;
static constexpr size_t MESSAGE_CACHE_SIZE = 8;
static constexpr size_t DEMO_KEY_BYTES = 32;
static constexpr size_t DEMO_KEY_HEX_CHARS = 64;
static constexpr size_t DEMO_PAIRING_PASSWORD_BYTES = 32;
static constexpr size_t DEMO_PAIRING_PASSWORD_CAPACITY = 128;
static constexpr size_t DEMO_PROVISION_BODY_MAX = 768;
static constexpr size_t DEMO_DOWNLINK_BODY_MAX = 256;
static constexpr size_t DEMO_AOS_PRIMARY_HEADER_BYTES = 6;
static constexpr size_t DEMO_AOS_SECURITY_HEADER_BYTES = 14;
static constexpr size_t DEMO_AOS_DATA_BYTES = 32;
static constexpr size_t DEMO_AOS_TAG_BYTES = 16;
static constexpr size_t DEMO_AOS_FRAME_BYTES = DEMO_AOS_PRIMARY_HEADER_BYTES +
                                                DEMO_AOS_SECURITY_HEADER_BYTES +
                                                DEMO_AOS_DATA_BYTES + DEMO_AOS_TAG_BYTES;
static_assert(DEMO_AOS_FRAME_BYTES == 68, "Frozen demo AOS frame profile must be exactly 68 octets");
static constexpr char MESSAGE_REPLY_PREFIX[] = "ESP32 received: ";
static const char *const WIFI_SSID = "YOUR_WIFI_SSID";
static const char *const WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
static WebServer server(80);

static const char *const BUTTON_NAMES[] = {
  "PB1/H", "PB2/X", "PB3/slot", "PB4/simulation-trigger", "PB5/display", "PB6/reset"
};
static const uint8_t BUTTON_PINS[] = {
  PB1_H_PIN, PB2_X_PIN, PB3_SLOT_PIN, PB4_SIMULATION_PIN, PB5_DISPLAY_PIN, PB6_RESET_PIN
};
static constexpr size_t BUTTON_COUNT = sizeof(BUTTON_PINS) / sizeof(BUTTON_PINS[0]);
uint8_t buttonStable[BUTTON_COUNT];
uint8_t buttonCandidate[BUTTON_COUNT];
uint32_t buttonCandidateSince[BUTTON_COUNT];

// Store validated gates in a compact, normalized representation. Every
// successful response serializes this as explicit gate objects.
enum GateType : uint8_t { GATE_I, GATE_H, GATE_X, GATE_Y, GATE_Z, GATE_S, GATE_T, GATE_CNOT };
struct ChainGate {
  GateType gate;
  uint8_t target;
  uint8_t control;
};
struct ComplexValue {
  float real;
  float imag;
};

ChainGate storedChain[MAX_CHAIN_GATES];
size_t storedChainLength = 0;
bool hasStoredChain = false;
uint8_t displayState = 0;
uint8_t messageIndex = 1;  // PB3 cycles through slots 1..5
bool cipherDisplayMode = false;
volatile uint32_t simulationTriggerCount = 0;

ComplexValue simulationAmplitudes[4] = {{1.0f, 0.0f}, {0.0f, 0.0f}, {0.0f, 0.0f}, {0.0f, 0.0f}};
float simulationProbabilities[4] = {1.0f, 0.0f, 0.0f, 0.0f};
size_t simulationQubitCount = 1;
bool hasStoredSimulation = false;

struct MessageCacheEntry {
  bool valid;
  uint32_t sequence;
  uint32_t espSequence;
  size_t messageLength;
  size_t replyLength;
  char messageId[MAX_MESSAGE_ID_BYTES + 1];
  char message[MAX_MESSAGE_TEXT_BYTES + 1];
  char crc32[9];
  char reply[MAX_MESSAGE_TEXT_BYTES + sizeof(MESSAGE_REPLY_PREFIX)];
};
MessageCacheEntry messageCache[MESSAGE_CACHE_SIZE] = {};
size_t nextMessageCacheSlot = 0;
uint32_t espSequenceCounter = 0;

// Pairing password, AES key, and encoded message are ordinary volatile RAM
// only. Hardware reset/reboot returns these globals to zero; no persistence or
// logging path exists. PB4 is not connected to this state.
static char demoPairingPassword[DEMO_PAIRING_PASSWORD_CAPACITY + 1] = {};
static size_t demoPairingPasswordLength = 0;
static uint8_t demoKey[DEMO_KEY_BYTES] = {};
static uint8_t demoAosDataField[DEMO_AOS_DATA_BYTES] = {};
static bool demoProvisioned = false;
static uint8_t demoNoncePrefix[8] = {};
static uint32_t demoNonceCounter = 0;
static bool demoNoncePrefixReady = false;
// Non-secret random identifier used only to detect a new volatile ESP boot session.
static uint8_t bootSessionId[16] = {};
// Non-secret random identifier replaced after each accepted volatile provision.
static uint8_t provisionSessionId[16] = {};

const char *gateName(GateType gate) {
  switch (gate) {
    case GATE_I: return "I";
    case GATE_H: return "H";
    case GATE_X: return "X";
    case GATE_Y: return "Y";
    case GATE_Z: return "Z";
    case GATE_S: return "S";
    case GATE_T: return "T";
    case GATE_CNOT: return "CNOT";
  }
  return "";
}

bool parseGateName(const char *name, GateType &gate) {
  if (strcmp(name, "I") == 0) gate = GATE_I;
  else if (strcmp(name, "H") == 0) gate = GATE_H;
  else if (strcmp(name, "X") == 0) gate = GATE_X;
  else if (strcmp(name, "Y") == 0) gate = GATE_Y;
  else if (strcmp(name, "Z") == 0) gate = GATE_Z;
  else if (strcmp(name, "S") == 0) gate = GATE_S;
  else if (strcmp(name, "T") == 0) gate = GATE_T;
  else if (strcmp(name, "CNOT") == 0) gate = GATE_CNOT;
  else return false;
  return true;
}

void applySingleQubitGate(ComplexValue &a, ComplexValue &b, GateType gate) {
  const float invSqrt2 = 0.7071067811865475f;
  const ComplexValue originalA = a;
  const ComplexValue originalB = b;
  switch (gate) {
    case GATE_I:
      return;
    case GATE_H:
      a = {(originalA.real + originalB.real) * invSqrt2, (originalA.imag + originalB.imag) * invSqrt2};
      b = {(originalA.real - originalB.real) * invSqrt2, (originalA.imag - originalB.imag) * invSqrt2};
      return;
    case GATE_X:
      a = originalB; b = originalA;
      return;
    case GATE_Y:
      a = {originalB.imag, -originalB.real}; b = {-originalA.imag, originalA.real};
      return;
    case GATE_Z:
      a = originalA; b = {-originalB.real, -originalB.imag};
      return;
    case GATE_S:
      a = originalA; b = {-originalB.imag, originalB.real};
      return;
    case GATE_T:
      a = originalA;
      b = {(originalB.real - originalB.imag) * invSqrt2, (originalB.real + originalB.imag) * invSqrt2};
      return;
    case GATE_CNOT:
      return;  // CNOT is handled as a two-qubit operation.
  }
}

void applySingleQubitGate(ComplexValue state[4], size_t qubitCount, uint8_t target, GateType gate) {
  if (qubitCount == 1) {
    applySingleQubitGate(state[0], state[1], gate);
    return;
  }
  // q0 is the MSB (bit 1); q1 is the LSB (bit 0).
  const size_t targetMask = (target == 0) ? 2 : 1;
  for (size_t basis = 0; basis < 4; ++basis) {
    if ((basis & targetMask) == 0) {
      const size_t pairedBasis = basis | targetMask;
      applySingleQubitGate(state[basis], state[pairedBasis], gate);
    }
  }
}

void applyCnot(ComplexValue state[4]) {
  // The only supported CNOT is control q0 -> target q1; swap |10> and |11>.
  const ComplexValue temporary = state[2];
  state[2] = state[3];
  state[3] = temporary;
}

bool computeSimulation(const ChainGate gates[], size_t gateCount, bool twoQubit,
                       ComplexValue outputAmplitudes[4], float outputProbabilities[4]) {
  const size_t basisCount = twoQubit ? 4 : 2;
  for (size_t i = 0; i < 4; ++i) {
    outputAmplitudes[i] = {0.0f, 0.0f};
    outputProbabilities[i] = 0.0f;
  }
  outputAmplitudes[0] = {1.0f, 0.0f};
  const size_t qubitCount = twoQubit ? 2 : 1;
  for (size_t i = 0; i < gateCount; ++i) {
    if (gates[i].gate == GATE_CNOT) applyCnot(outputAmplitudes);
    else applySingleQubitGate(outputAmplitudes, qubitCount, gates[i].target, gates[i].gate);
  }
  for (size_t i = 0; i < basisCount; ++i) {
    outputProbabilities[i] = outputAmplitudes[i].real * outputAmplitudes[i].real +
                             outputAmplitudes[i].imag * outputAmplitudes[i].imag;
  }
  return true;
}

void addState(JsonObject simulation, const char *name, const ComplexValue state[4],
              const float probabilities[4], size_t qubitCount) {
  JsonObject stateObject = simulation.createNestedObject(name);
  JsonArray amplitudes = stateObject.createNestedArray("amplitudes");
  JsonArray probabilityArray = stateObject.createNestedArray("probabilities");
  const size_t basisCount = (qubitCount == 2) ? 4 : 2;
  static const char *const twoQubitBasis[] = {"00", "01", "10", "11"};
  for (size_t i = 0; i < basisCount; ++i) {
    JsonObject amplitude = amplitudes.createNestedObject();
    JsonObject probability = probabilityArray.createNestedObject();
    if (qubitCount == 2) {
      amplitude["basis"] = twoQubitBasis[i];
      probability["basis"] = twoQubitBasis[i];
    } else {
      amplitude["basis"] = i;
      probability["basis"] = i;
    }
    amplitude["real"] = state[i].real;
    amplitude["imag"] = state[i].imag;
    probability["value"] = probabilities[i];
  }
}

void addSimulation(JsonObject response) {
  if (!hasStoredSimulation) return;
  static const ComplexValue initialAmplitudes[4] = {
    {1.0f, 0.0f}, {0.0f, 0.0f}, {0.0f, 0.0f}, {0.0f, 0.0f}
  };
  static const float initialProbabilities[4] = {1.0f, 0.0f, 0.0f, 0.0f};
  JsonObject simulation = response.createNestedObject("simulation");
  simulation["type"] = "classical_state_vector";
  simulation["interpretation"] = "classical calculation; not a quantum processor, measurement, or physical-state observation";
  simulation["qubit_count"] = simulationQubitCount;
  JsonArray basisOrder = simulation.createNestedArray("basis_order");
  if (simulationQubitCount == 2) {
    basisOrder.add("00"); basisOrder.add("01"); basisOrder.add("10"); basisOrder.add("11");
  } else {
    basisOrder.add(0); basisOrder.add(1);
  }
  addState(simulation, "initial_state", initialAmplitudes, initialProbabilities, simulationQubitCount);
  addState(simulation, "final_state", simulationAmplitudes, simulationProbabilities, simulationQubitCount);
  simulation["measurement_performed"] = false;
}

void addStoredChain(JsonObject response) {
  JsonArray chain = response.createNestedArray("chain");
  for (size_t i = 0; i < storedChainLength; ++i) {
    JsonObject item = chain.createNestedObject();
    item["gate"] = gateName(storedChain[i].gate);
    if (storedChain[i].gate == GATE_CNOT) item["control"] = storedChain[i].control;
    item["target"] = storedChain[i].target;
  }
}

void encodeLowerHex(const uint8_t *bytes, size_t length, char *output);

void addTelemetry(JsonObject telemetry) {
  telemetry["device"] = "qg-esp32";
  telemetry["uptime_ms"] = static_cast<uint32_t>(millis());
  char bootSessionIdHex[sizeof(bootSessionId) * 2 + 1];
  encodeLowerHex(bootSessionId, sizeof(bootSessionId), bootSessionIdHex);
  telemetry["boot_id"] = bootSessionIdHex;
  char provisionSessionIdHex[sizeof(provisionSessionId) * 2 + 1];
  encodeLowerHex(provisionSessionId, sizeof(provisionSessionId), provisionSessionIdHex);
  telemetry["provision_id"] = provisionSessionIdHex;
  // This is the physical-button display convention, not simulation output.
  telemetry["state"] = displayState;
  telemetry["message_index"] = messageIndex;
  telemetry["display_mode"] = cipherDisplayMode ? "cipher" : "qubit";
  telemetry["reseed_count"] = 0;  // Legacy telemetry field; this project does not reseed.
  if (hasStoredChain) {
    addStoredChain(telemetry);
    addSimulation(telemetry);
  }
}

void sendJsonResponse(int statusCode, JsonDocument &document) {
  String body;
  serializeJson(document, body);
  server.send(statusCode, "application/json", body);
}

void secureWipe(void *memory, size_t length) {
  volatile uint8_t *bytes = static_cast<volatile uint8_t *>(memory);
  while (length-- != 0) *bytes++ = 0;
}

struct ScopedByteWipe {
  uint8_t *bytes;
  size_t length;
  ~ScopedByteWipe() { secureWipe(bytes, length); }
};

struct ScopedStringWipe {
  String &value;
  ~ScopedStringWipe() {
    for (size_t i = 0; i < value.length(); ++i) value.setCharAt(i, '\0');
  }
};

bool hasJsonContentType() {
  String contentType = server.header("Content-Type");
  contentType.trim();
  contentType.toLowerCase();
  return contentType == "application/json" || contentType.startsWith("application/json;");
}

int hexNibble(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  return -1;
}

bool decodeExactHex(const char *text, size_t textLength, uint8_t *output, size_t outputLength) {
  if (text == nullptr || textLength != outputLength * 2) return false;
  for (size_t i = 0; i < outputLength; ++i) {
    const int high = hexNibble(text[i * 2]);
    const int low = hexNibble(text[i * 2 + 1]);
    if (high < 0 || low < 0) return false;
    output[i] = static_cast<uint8_t>((high << 4) | low);
  }
  return true;
}

void encodeLowerHex(const uint8_t *bytes, size_t length, char *output) {
  static const char HEX[] = "0123456789abcdef";
  for (size_t i = 0; i < length; ++i) {
    output[2 * i] = HEX[bytes[i] >> 4];
    output[2 * i + 1] = HEX[bytes[i] & 0x0f];
  }
  output[2 * length] = '\0';
}

bool sha256Digest(const uint8_t *input, size_t inputLength, uint8_t output[32]) {
#if MBEDTLS_VERSION_NUMBER >= 0x03000000
  return mbedtls_sha256(input, inputLength, output, 0) == 0;
#else
  return mbedtls_sha256_ret(input, inputLength, output, 0) == 0;
#endif
}

void sendDemoApiError(int statusCode, const char *error) {
  DynamicJsonDocument response(256);
  response["accepted"] = false;
  response["error"] = error;
  sendJsonResponse(statusCode, response);
}

void clearDemoProvisioningRam() {
  secureWipe(demoPairingPassword, sizeof(demoPairingPassword));
  demoPairingPasswordLength = 0;
  secureWipe(demoKey, sizeof(demoKey));
  secureWipe(demoAosDataField, sizeof(demoAosDataField));
  secureWipe(provisionSessionId, sizeof(provisionSessionId));
  demoProvisioned = false;
}

bool isValidPairingPassword(const char *value, size_t length) {
  if (value == nullptr || length != DEMO_PAIRING_PASSWORD_BYTES) return false;
  for (size_t i = 0; i < length; ++i) {
    const char ch = value[i];
    const bool allowed = (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') ||
                         (ch >= '0' && ch <= '9') || ch == '_' || ch == '-';
    if (!allowed) return false;
  }
  return true;
}

bool matchesDemoPairingPassword(const char *candidate, size_t candidateLength) {
  uint32_t difference = static_cast<uint32_t>(candidateLength ^ demoPairingPasswordLength);
  for (size_t i = 0; i < DEMO_PAIRING_PASSWORD_CAPACITY; ++i) {
    const uint8_t supplied = (candidate != nullptr && i < candidateLength)
                                 ? static_cast<uint8_t>(candidate[i]) : 0;
    const uint8_t expected = i < demoPairingPasswordLength
                                 ? static_cast<uint8_t>(demoPairingPassword[i]) : 0;
    difference |= static_cast<uint32_t>(supplied ^ expected);
  }
  return difference == 0;
}

bool allocateDemoIv(uint8_t iv[12]) {
  if (!demoNoncePrefixReady || demoNonceCounter == UINT32_MAX) return false;
  ++demoNonceCounter;  // Never wraps; exhausted counter fails closed.
  memcpy(iv, demoNoncePrefix, sizeof(demoNoncePrefix));
  iv[8] = static_cast<uint8_t>(demoNonceCounter >> 24);
  iv[9] = static_cast<uint8_t>(demoNonceCounter >> 16);
  iv[10] = static_cast<uint8_t>(demoNonceCounter >> 8);
  iv[11] = static_cast<uint8_t>(demoNonceCounter);
  return true;
}

void sendControlError(const char *message) {
  DynamicJsonDocument response(256);
  response["error"] = message;
  sendJsonResponse(400, response);
}

bool isIntegerInRange(JsonVariantConst value, int minimum, int maximum) {
  if (!value.is<int>()) return false;
  const int number = value.as<int>();
  return number >= minimum && number <= maximum;
}

bool isValidMessageId(const char *value, size_t length) {
  if (length == 0 || length > MAX_MESSAGE_ID_BYTES) return false;
  for (size_t i = 0; i < length; ++i) {
    const char ch = value[i];
    const bool allowed = (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') ||
                         (ch >= '0' && ch <= '9') || ch == '_' || ch == '-';
    if (!allowed) return false;
  }
  return true;
}

bool isValidUtf8Text(const uint8_t *bytes, size_t length) {
  size_t i = 0;
  while (i < length) {
    const uint8_t first = bytes[i];
    if (first <= 0x7f) { ++i; continue; }
    if (first >= 0xc2 && first <= 0xdf) {
      if (i + 1 >= length || (bytes[i + 1] & 0xc0) != 0x80) return false;
      i += 2;
      continue;
    }
    if (first >= 0xe0 && first <= 0xef) {
      if (i + 2 >= length) return false;
      const uint8_t second = bytes[i + 1];
      const uint8_t third = bytes[i + 2];
      if ((third & 0xc0) != 0x80 || (second & 0xc0) != 0x80 ||
          (first == 0xe0 && second < 0xa0) || (first == 0xed && second >= 0xa0)) return false;
      i += 3;
      continue;
    }
    if (first >= 0xf0 && first <= 0xf4) {
      if (i + 3 >= length) return false;
      const uint8_t second = bytes[i + 1];
      if ((bytes[i + 2] & 0xc0) != 0x80 || (bytes[i + 3] & 0xc0) != 0x80 ||
          (second & 0xc0) != 0x80 || (first == 0xf0 && second < 0x90) ||
          (first == 0xf4 && second > 0x8f)) return false;
      i += 4;
      continue;
    }
    return false;
  }
  return true;
}

uint32_t crc32Update(uint32_t crc, const uint8_t *bytes, size_t length) {
  for (size_t i = 0; i < length; ++i) {
    crc ^= bytes[i];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 1u) ? ((crc >> 1) ^ 0xedb88320u) : (crc >> 1);
    }
  }
  return crc;
}

uint32_t calculateMessageCrc32(const uint8_t *message, size_t messageLength) {
  return crc32Update(0xffffffffu, message, messageLength) ^ 0xffffffffu;
}

bool isLowercaseCrc32(const char *value, size_t length) {
  if (length != 8) return false;
  for (size_t i = 0; i < length; ++i) {
    if (!((value[i] >= '0' && value[i] <= '9') || (value[i] >= 'a' && value[i] <= 'f'))) return false;
  }
  return true;
}

void sendMessageError(int statusCode, const char *error, const char *computedCrc32 = nullptr,
                      const char *messageId = nullptr, bool includeSequence = false,
                      uint32_t sequence = 0) {
  DynamicJsonDocument response(384);
  response["device"] = "esp32-qkd-teaching";
  response["ack"] = false;
  const char *status = "bad_request";
  if (statusCode == 409) status = "id_conflict";
  else if (statusCode == 413) status = "too_large";
  else if (statusCode == 422) status = "crc_mismatch";
  response["status"] = status;
  response["integrity"] = statusCode == 422 ? "invalid" : "not_checked";
  response["error"] = error;
  if (messageId != nullptr) response["message_id"] = messageId;
  if (includeSequence) response["sequence"] = sequence;
  if (computedCrc32 != nullptr) response["computed_crc32"] = computedCrc32;
  sendJsonResponse(statusCode, response);
}

void sendCachedMessageReply(const MessageCacheEntry &entry, bool duplicate) {
  DynamicJsonDocument response(768);
  JsonObject root = response.to<JsonObject>();
  root["device"] = "esp32-qkd-teaching";
  root["message_id"] = entry.messageId;
  root["sequence"] = entry.sequence;
  root["ack"] = true;
  root["status"] = duplicate ? "duplicate" : "accepted";
  root["esp_sequence"] = entry.espSequence;
  root["received_message"] = JsonString(entry.message, entry.messageLength, JsonString::Linked);
  root["reply_message"] = JsonString(entry.reply, entry.replyLength, JsonString::Linked);
  root["request_crc32"] = entry.crc32;
  root["computed_crc32"] = entry.crc32;
  root["integrity"] = "valid";
  root["duplicate"] = duplicate;
  sendJsonResponse(200, response);
}

void handlePostMessage() {
  String contentType = server.header("Content-Type");
  contentType.trim();
  contentType.toLowerCase();
  if (!(contentType == "application/json" || contentType.startsWith("application/json;"))) {
    sendMessageError(415, "content_type_must_be_application_json");
    return;
  }

  const String body = server.arg("plain");
  if (body.length() == 0) {
    sendMessageError(400, "body_invalid_length");
    return;
  }
  if (body.length() > MAX_MESSAGE_BODY_BYTES) {
    sendMessageError(413, "body_too_large");
    return;
  }

  DynamicJsonDocument request(4096);
  const DeserializationError parseError = deserializeJson(request, body);
  if (parseError || !request.is<JsonObject>()) {
    sendMessageError(400, "invalid_json_object");
    return;
  }

  JsonObjectConst object = request.as<JsonObjectConst>();
  if (object.size() != 4 || !object.containsKey("message_id") || !object.containsKey("sequence") ||
      !object.containsKey("message") || !object.containsKey("crc32")) {
    sendMessageError(400, "request_must_contain_only_message_id_sequence_message_crc32");
    return;
  }

  if (!object["message_id"].is<const char *>()) {
    sendMessageError(400, "invalid_message_id");
    return;
  }
  const JsonString messageIdValue = object["message_id"].as<JsonString>();
  if (!isValidMessageId(messageIdValue.c_str(), messageIdValue.size())) {
    sendMessageError(400, "invalid_message_id");
    return;
  }
  const char *messageId = messageIdValue.c_str();

  if (!object["sequence"].is<uint32_t>()) {
    sendMessageError(400, "sequence_must_be_uint32");
    return;
  }
  const uint32_t sequence = object["sequence"].as<uint32_t>();
  if (sequence == 0) {
    sendMessageError(400, "sequence_must_be_positive");
    return;
  }

  if (!object["message"].is<const char *>()) {
    sendMessageError(400, "message_must_be_a_nonempty_utf8_string");
    return;
  }
  const JsonString messageValue = object["message"].as<JsonString>();
  const size_t messageLength = messageValue.size();
  const uint8_t *messageBytes = reinterpret_cast<const uint8_t *>(messageValue.c_str());
  if (messageLength == 0 || !isValidUtf8Text(messageBytes, messageLength)) {
    sendMessageError(400, "message_must_be_nonempty_valid_utf8");
    return;
  }
  if (messageLength > MAX_MESSAGE_TEXT_BYTES) {
    sendMessageError(400, "message_too_large");
    return;
  }

  if (!object["crc32"].is<const char *>()) {
    sendMessageError(400, "crc32_must_be_8_lowercase_hex_digits");
    return;
  }
  const JsonString crcValue = object["crc32"].as<JsonString>();
  if (!isLowercaseCrc32(crcValue.c_str(), crcValue.size())) {
    sendMessageError(400, "crc32_must_be_8_lowercase_hex_digits");
    return;
  }
  const uint32_t expectedCrc = calculateMessageCrc32(messageBytes, messageLength);
  char expectedCrcText[9];
  snprintf(expectedCrcText, sizeof(expectedCrcText), "%08lx", static_cast<unsigned long>(expectedCrc));

  for (size_t i = 0; i < MESSAGE_CACHE_SIZE; ++i) {
    const MessageCacheEntry &entry = messageCache[i];
    if (!entry.valid || strcmp(entry.messageId, messageId) != 0) continue;
    const bool exactDuplicate = entry.sequence == sequence && entry.messageLength == messageLength &&
                                memcmp(entry.message, messageBytes, messageLength) == 0 &&
                                strcmp(entry.crc32, crcValue.c_str()) == 0;
    if (exactDuplicate) {
      sendCachedMessageReply(entry, true);
    } else {
      sendMessageError(409, "id_conflict", nullptr, messageId, true, sequence);
    }
    return;
  }

  if (strcmp(crcValue.c_str(), expectedCrcText) != 0) {
    sendMessageError(422, "crc_mismatch", expectedCrcText, messageId, true, sequence);
    return;
  }

  // Sequence is a caller correlation value only; it is validated and echoed,
  // but is not globally ordered or used to gate acceptance.
  espSequenceCounter = (espSequenceCounter == UINT32_MAX) ? 1 : espSequenceCounter + 1;
  MessageCacheEntry &entry = messageCache[nextMessageCacheSlot];
  entry.valid = true;
  entry.sequence = sequence;
  entry.espSequence = espSequenceCounter;
  entry.messageLength = messageLength;
  memcpy(entry.messageId, messageId, messageIdValue.size());
  entry.messageId[messageIdValue.size()] = '\0';
  memcpy(entry.message, messageBytes, messageLength);
  entry.message[messageLength] = '\0';
  memcpy(entry.crc32, crcValue.c_str(), 9);
  const size_t prefixLength = sizeof(MESSAGE_REPLY_PREFIX) - 1;
  memcpy(entry.reply, MESSAGE_REPLY_PREFIX, prefixLength);
  memcpy(entry.reply + prefixLength, messageBytes, messageLength);
  entry.replyLength = prefixLength + messageLength;
  entry.reply[entry.replyLength] = '\0';
  nextMessageCacheSlot = (nextMessageCacheSlot + 1) % MESSAGE_CACHE_SIZE;
  sendCachedMessageReply(entry, false);
}

bool handleSetChain(JsonObjectConst request) {
  JsonArrayConst chain = request["chain"].as<JsonArrayConst>();
  if (chain.isNull()) {
    sendControlError("chain_must_be_an_array");
    return false;
  }
  if (chain.size() > MAX_CHAIN_GATES) {
    sendControlError("chain_too_long_max_64_gates");
    return false;
  }

  // All parsing, shape checks, gate checks, and qubit checks happen in local
  // storage. The previously accepted chain and simulation remain untouched on
  // every validation failure.
  ChainGate validated[MAX_CHAIN_GATES];
  size_t validatedLength = 0;
  bool sawString = false;
  bool sawObject = false;
  bool twoQubit = false;
  for (JsonVariantConst item : chain) {
    if (item.is<const char *>()) {
      sawString = true;
      const char *name = item.as<const char *>();
      GateType gate;
      if (!parseGateName(name, gate)) {
        sendControlError("unsupported_gate_name");
        return false;
      }
      if (gate == GATE_CNOT) {
        sendControlError("bare_string_chain_supports_single_qubit_gates_only");
        return false;
      }
      validated[validatedLength++] = {gate, 0, 0};  // legacy string uses one-qubit semantics
      continue;
    }

    if (!item.is<JsonObjectConst>()) {
      sendControlError("each_chain_item_must_be_a_gate_object_or_legacy_gate_string");
      return false;
    }
    sawObject = true;
    JsonObjectConst object = item.as<JsonObjectConst>();
    if (!object["gate"].is<const char *>()) {
      sendControlError("gate_object_requires_string_gate");
      return false;
    }
    GateType gate;
    if (!parseGateName(object["gate"].as<const char *>(), gate)) {
      sendControlError("unsupported_gate_name");
      return false;
    }

    if (gate == GATE_CNOT) {
      if (!object.containsKey("control") || !object.containsKey("target")) {
        sendControlError("cnot_requires_control_and_target");
        return false;
      }
      if (object.size() != 3) {
        sendControlError("cnot_item_requires_only_gate_control_target");
        return false;
      }
      if (!isIntegerInRange(object["control"], 0, 1) || !isIntegerInRange(object["target"], 0, 1)) {
        sendControlError("cnot_control_and_target_must_be_in_range_0_1");
        return false;
      }
      if (object["control"].as<int>() != 0 || object["target"].as<int>() != 1) {
        sendControlError("only_cnot_control_0_target_1_is_supported");
        return false;
      }
      validated[validatedLength++] = {GATE_CNOT, 1, 0};
      twoQubit = true;
    } else {
      if (!object.containsKey("target")) {
        sendControlError("single_qubit_gate_requires_target");
        return false;
      }
      if (object.size() != 2) {
        sendControlError("single_qubit_item_requires_only_gate_and_target");
        return false;
      }
      if (!isIntegerInRange(object["target"], 0, 1)) {
        sendControlError("target_must_be_integer_0_or_1");
        return false;
      }
      const uint8_t target = static_cast<uint8_t>(object["target"].as<int>());
      validated[validatedLength++] = {gate, target, 0};
      if (target == 1) twoQubit = true;
    }
  }
  if (sawString && sawObject) {
    sendControlError("chain_items_must_not_mix_legacy_strings_and_gate_objects");
    return false;
  }
  ComplexValue candidateAmplitudes[4];
  float candidateProbabilities[4];
  computeSimulation(validated, validatedLength, twoQubit, candidateAmplitudes, candidateProbabilities);

  // Commit is deliberately last: requests rejected above cannot partially
  // replace either the stored chain or the previous simulation.
  for (size_t i = 0; i < validatedLength; ++i) storedChain[i] = validated[i];
  storedChainLength = validatedLength;
  simulationQubitCount = twoQubit ? 2 : 1;
  for (size_t i = 0; i < 4; ++i) {
    simulationAmplitudes[i] = candidateAmplitudes[i];
    simulationProbabilities[i] = candidateProbabilities[i];
  }
  hasStoredSimulation = true;
  hasStoredChain = true;

  // The HTTP handler serializes the accepted chain and classical simulation.
  return true;
}

void buildAosBaselineAad(const uint8_t primaryHeader[DEMO_AOS_PRIMARY_HEADER_BYTES],
                         const uint8_t securityHeader[DEMO_AOS_SECURITY_HEADER_BYTES],
                         uint8_t aad[DEMO_AOS_PRIMARY_HEADER_BYTES + DEMO_AOS_SECURITY_HEADER_BYTES]) {
  // CCSDS 355.0-B-2 Annex E3 mask: preserve only the AOS VCID bits in the
  // six-octet primary header; preserve SPI, but zero the inline IV in AAD.
  memset(aad, 0, DEMO_AOS_PRIMARY_HEADER_BYTES + DEMO_AOS_SECURITY_HEADER_BYTES);
  aad[1] = static_cast<uint8_t>(primaryHeader[1] & 0x3f);
  aad[DEMO_AOS_PRIMARY_HEADER_BYTES] = securityHeader[0];
  aad[DEMO_AOS_PRIMARY_HEADER_BYTES + 1] = securityHeader[1];
}

void encryptAndRespondAosFrame(const uint8_t primaryHeader[DEMO_AOS_PRIMARY_HEADER_BYTES],
                               uint32_t spiValue,
                               const uint8_t frameData[DEMO_AOS_DATA_BYTES]) {
  uint8_t securityHeader[DEMO_AOS_SECURITY_HEADER_BYTES] = {};
  ScopedByteWipe securityHeaderWiper{securityHeader, sizeof(securityHeader)};
  securityHeader[0] = static_cast<uint8_t>(spiValue >> 8);
  securityHeader[1] = static_cast<uint8_t>(spiValue);
  if (!allocateDemoIv(securityHeader + 2)) {
    sendDemoApiError(503, "demo_iv_counter_unavailable_or_exhausted");
    return;
  }

  uint8_t aad[DEMO_AOS_PRIMARY_HEADER_BYTES + DEMO_AOS_SECURITY_HEADER_BYTES] = {};
  ScopedByteWipe aadWiper{aad, sizeof(aad)};
  buildAosBaselineAad(primaryHeader, securityHeader, aad);
  uint8_t ciphertext[DEMO_AOS_DATA_BYTES] = {};
  ScopedByteWipe ciphertextWiper{ciphertext, sizeof(ciphertext)};
  uint8_t tag[DEMO_AOS_TAG_BYTES] = {};
  ScopedByteWipe tagWiper{tag, sizeof(tag)};

  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  int cryptoStatus = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, demoKey, 256);
  if (cryptoStatus == 0) {
    cryptoStatus = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, DEMO_AOS_DATA_BYTES,
                                             securityHeader + 2, 12, aad, sizeof(aad),
                                             frameData, ciphertext, sizeof(tag), tag);
  }
  mbedtls_gcm_free(&gcm);
  if (cryptoStatus != 0) {
    sendDemoApiError(500, "aes_256_gcm_failed");
    return;
  }

  uint8_t frame[DEMO_AOS_FRAME_BYTES] = {};
  ScopedByteWipe frameWiper{frame, sizeof(frame)};
  size_t offset = 0;
  memcpy(frame + offset, primaryHeader, DEMO_AOS_PRIMARY_HEADER_BYTES); offset += DEMO_AOS_PRIMARY_HEADER_BYTES;
  memcpy(frame + offset, securityHeader, sizeof(securityHeader)); offset += sizeof(securityHeader);
  memcpy(frame + offset, ciphertext, sizeof(ciphertext)); offset += sizeof(ciphertext);
  memcpy(frame + offset, tag, sizeof(tag));

  char primaryHeaderOut[DEMO_AOS_PRIMARY_HEADER_BYTES * 2 + 1];
  char securityHeaderOut[DEMO_AOS_SECURITY_HEADER_BYTES * 2 + 1];
  char ciphertextOut[DEMO_AOS_DATA_BYTES * 2 + 1];
  char tagOut[DEMO_AOS_TAG_BYTES * 2 + 1];
  char frameOut[DEMO_AOS_FRAME_BYTES * 2 + 1];
  encodeLowerHex(primaryHeader, DEMO_AOS_PRIMARY_HEADER_BYTES, primaryHeaderOut);
  encodeLowerHex(securityHeader, sizeof(securityHeader), securityHeaderOut);
  encodeLowerHex(ciphertext, sizeof(ciphertext), ciphertextOut);
  encodeLowerHex(tag, sizeof(tag), tagOut);
  encodeLowerHex(frame, sizeof(frame), frameOut);

  DynamicJsonDocument response(768);
  response["primary_header_hex"] = primaryHeaderOut;
  response["security_header_hex"] = securityHeaderOut;
  response["ciphertext_hex"] = ciphertextOut;
  response["tag_hex"] = tagOut;
  response["frame_hex"] = frameOut;
  char bootSessionIdHex[sizeof(bootSessionId) * 2 + 1];
  encodeLowerHex(bootSessionId, sizeof(bootSessionId), bootSessionIdHex);
  response["boot_id"] = bootSessionIdHex;
  char provisionSessionIdHex[sizeof(provisionSessionId) * 2 + 1];
  encodeLowerHex(provisionSessionId, sizeof(provisionSessionId), provisionSessionIdHex);
  response["provision_id"] = provisionSessionIdHex;
  char keyOut[DEMO_KEY_HEX_CHARS + 1];
  encodeLowerHex(demoKey, sizeof(demoKey), keyOut);
  response["key_hex"] = keyOut;
  sendJsonResponse(200, response);
  secureWipe(keyOut, sizeof(keyOut));
}

void handlePostAosDemoProvision() {
  if (!hasJsonContentType()) {
    sendDemoApiError(415, "content_type_must_be_application_json");
    return;
  }
  String body = server.arg("plain");
  ScopedStringWipe bodyWiper{body};
  if (body.length() == 0 || body.length() > DEMO_PROVISION_BODY_MAX) {
    sendDemoApiError(413, "provision_body_invalid_length");
    return;
  }
  char requestBuffer[DEMO_PROVISION_BODY_MAX + 1] = {};
  ScopedByteWipe requestWiper{reinterpret_cast<uint8_t *>(requestBuffer), sizeof(requestBuffer)};
  memcpy(requestBuffer, body.c_str(), body.length());
  DynamicJsonDocument request(1536);
  const DeserializationError parseError = deserializeJson(request, requestBuffer, body.length());
  if (parseError || !request.is<JsonObject>()) {
    sendDemoApiError(400, "invalid_json_object");
    return;
  }
  JsonObjectConst object = request.as<JsonObjectConst>();
  if (object.size() != 3 || !object.containsKey("password") || !object.containsKey("key_hex") ||
      !object.containsKey("message") || !object["password"].is<const char *>() ||
      !object["key_hex"].is<const char *>() || !object["message"].is<const char *>()) {
    sendDemoApiError(400, "request_must_contain_only_password_key_hex_message");
    return;
  }

  const JsonString password = object["password"].as<JsonString>();
  const JsonString keyHex = object["key_hex"].as<JsonString>();
  const JsonString message = object["message"].as<JsonString>();
  if (!isValidPairingPassword(password.c_str(), password.size())) {
    sendDemoApiError(422, "pairing_password_must_be_fresh_32_character_url_safe_value");
    return;
  }

  uint8_t candidateKey[DEMO_KEY_BYTES] = {};
  ScopedByteWipe candidateKeyWiper{candidateKey, sizeof(candidateKey)};
  if (keyHex.size() != DEMO_KEY_HEX_CHARS ||
      !decodeExactHex(keyHex.c_str(), keyHex.size(), candidateKey, sizeof(candidateKey))) {
    sendDemoApiError(422, "key_must_encode_exactly_32_bytes");
    return;
  }

  uint8_t candidateDataField[DEMO_AOS_DATA_BYTES] = {};
  ScopedByteWipe candidateFieldWiper{candidateDataField, sizeof(candidateDataField)};
  const size_t messageLength = message.size();
  const uint8_t *messageBytes = reinterpret_cast<const uint8_t *>(message.c_str());
  if (messageLength == 0 || !isValidUtf8Text(messageBytes, messageLength)) {
    sendDemoApiError(422, "message_must_be_nonempty_valid_utf8");
    return;
  }
  if (messageLength > DEMO_AOS_DATA_BYTES - 1) {
    sendDemoApiError(413, "message_exceeds_31_utf8_octets_no_truncation");
    return;
  }
  // Byte 0 is the explicit UTF-8 octet length. Remaining bytes are zero padding.
  candidateDataField[0] = static_cast<uint8_t>(messageLength);
  memcpy(candidateDataField + 1, messageBytes, messageLength);
  const char *profileError = aos_demo_profile::validateFixedProfile(
      aos_demo_profile::kRequiredSpi, aos_demo_profile::kRequiredPrimaryHeader);
  if (profileError != nullptr) {
    sendDemoApiError(422, profileError);
    return;
  }

  // Commit only after every password, key, message, and profile check succeeds.
  clearDemoProvisioningRam();
  memcpy(demoPairingPassword, password.c_str(), password.size());
  demoPairingPassword[password.size()] = '\0';
  demoPairingPasswordLength = password.size();
  memcpy(demoKey, candidateKey, sizeof(demoKey));
  memcpy(demoAosDataField, candidateDataField, sizeof(demoAosDataField));
  esp_fill_random(provisionSessionId, sizeof(provisionSessionId));
  demoProvisioned = true;
  request.clear();

  DynamicJsonDocument response(128);
  response["accepted"] = true;
  response["provisioned"] = true;
  sendJsonResponse(200, response);
}

void handlePostAosDemoDownlink() {
  if (!hasJsonContentType()) {
    sendDemoApiError(415, "content_type_must_be_application_json");
    return;
  }
  String body = server.arg("plain");
  ScopedStringWipe bodyWiper{body};
  if (body.length() == 0 || body.length() > DEMO_DOWNLINK_BODY_MAX) {
    sendDemoApiError(400, "downlink_request_body_invalid_length");
    return;
  }
  char requestBuffer[DEMO_DOWNLINK_BODY_MAX + 1] = {};
  ScopedByteWipe requestWiper{reinterpret_cast<uint8_t *>(requestBuffer), sizeof(requestBuffer)};
  memcpy(requestBuffer, body.c_str(), body.length());
  DynamicJsonDocument request(384);
  const DeserializationError parseError = deserializeJson(request, requestBuffer, body.length());
  if (parseError || !request.is<JsonObject>()) {
    sendDemoApiError(400, "invalid_json_object");
    return;
  }
  JsonObjectConst object = request.as<JsonObjectConst>();
  if (object.size() != 1 || !object.containsKey("password") || !object["password"].is<const char *>()) {
    sendDemoApiError(400, "request_must_contain_only_password");
    return;
  }
  if (!demoProvisioned) {
    sendDemoApiError(409, "demo_provision_required_after_reset_or_reboot");
    return;
  }
  const JsonString password = object["password"].as<JsonString>();
  if (!matchesDemoPairingPassword(password.c_str(), password.size())) {
    sendDemoApiError(403, "demo_pairing_rejected");
    return;
  }
  encryptAndRespondAosFrame(aos_demo_profile::kRequiredPrimaryHeader,
                            aos_demo_profile::kRequiredSpi,
                            demoAosDataField);
}

void handleGetTelemetry() {
  DynamicJsonDocument response(16384);
  JsonObject telemetry = response.to<JsonObject>();
  addTelemetry(telemetry);
  sendJsonResponse(200, response);
}

void handleGetSimulationTrigger() {
  DynamicJsonDocument response(128);
  JsonObject root = response.to<JsonObject>();
  const uint32_t countSnapshot = simulationTriggerCount;
  root["device"] = "esp32-bb84-sim-trigger";
  root["trigger_count"] = countSnapshot;
  sendJsonResponse(200, response);
}

void handlePostControl() {
  const String body = server.arg("plain");
  if (body.length() == 0 || body.length() > 4095) {
    sendControlError("control_body_invalid_length");
    return;
  }

  DynamicJsonDocument request(8192);
  const DeserializationError parseError = deserializeJson(request, body);
  if (parseError || !request.is<JsonObject>()) {
    sendControlError("invalid_json_object");
    return;
  }

  JsonObjectConst object = request.as<JsonObjectConst>();
  if (object.size() != 2 || !object["action"].is<const char *>() ||
      strcmp(object["action"].as<const char *>(), "set_chain") != 0 ||
      !object.containsKey("chain")) {
    sendControlError("expected_action_set_chain_and_chain_array");
    return;
  }
  if (!handleSetChain(object)) return;

  DynamicJsonDocument response(16384);
  JsonObject result = response.to<JsonObject>();
  addStoredChain(result);
  addSimulation(result);
  sendJsonResponse(200, response);
}

void setDisplayState(uint8_t value) {
  displayState = value;
}

void handleButtonPress(size_t index) {
  switch (index) {
    case 0:  // PB1 / GPIO18: H button; project display convention H -> |0>
      setDisplayState(0);
      break;
    case 1:  // PB2 / GPIO19: X button; project display convention X -> |1>
      setDisplayState(1);
      break;
    case 2:  // PB3 / GPIO21: cycle message slot 1..5
      messageIndex = (messageIndex % 5) + 1;
      break;
    case 3:  // PB4 / GPIO22: request a new local Python simulation run only.
      ++simulationTriggerCount;
      break;
    case 4:  // PB5 / GPIO25: display mode toggle only
      cipherDisplayMode = !cipherDisplayMode;
      break;
    case 5:  // PB6 / GPIO27: reset the project display convention to |0>
      setDisplayState(0);
      break;
  }
  (void)BUTTON_NAMES[index];  // Names are available for local debugging if needed.
}

void pollButtons() {
  const uint32_t now = millis();
  for (size_t i = 0; i < BUTTON_COUNT; ++i) {
    const uint8_t reading = digitalRead(BUTTON_PINS[i]);
    if (reading != buttonCandidate[i]) {
      buttonCandidate[i] = reading;
      buttonCandidateSince[i] = now;
    }
    if ((now - buttonCandidateSince[i]) >= DEBOUNCE_MS && buttonStable[i] != buttonCandidate[i]) {
      buttonStable[i] = buttonCandidate[i];
      if (buttonStable[i] == LOW) {
        handleButtonPress(i);  // active-low press edge
      }
    }
  }
}

void setup() {
  clearDemoProvisioningRam();
  pinMode(STATUS_LED_PIN, OUTPUT);  // GPIO2 remains output-only.
  digitalWrite(STATUS_LED_PIN, LED_ON_LEVEL);
  for (size_t i = 0; i < BUTTON_COUNT; ++i) {
    pinMode(BUTTON_PINS[i], INPUT_PULLUP);  // active-low; connect each switch to GND
    buttonStable[i] = digitalRead(BUTTON_PINS[i]);
    buttonCandidate[i] = buttonStable[i];
    buttonCandidateSince[i] = millis();
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    pollButtons();
    delay(20);
  }

  // RF is active here, satisfying the documented ESP32 hardware-RNG entropy
  // condition. The non-secret boot ID distinguishes volatile sessions; a random
  // 64-bit nonce prefix plus a non-wrapping counter makes each IV distinct.
  esp_fill_random(bootSessionId, sizeof(bootSessionId));
  esp_fill_random(demoNoncePrefix, sizeof(demoNoncePrefix));
  demoNonceCounter = 0;
  demoNoncePrefixReady = true;

  const char *headerKeys[] = {"Content-Type"};
  server.collectHeaders(headerKeys, 1);
  server.on("/api/telemetry", HTTP_GET, handleGetTelemetry);
  server.on("/api/control", HTTP_POST, handlePostControl);
  server.on("/api/simulation-trigger", HTTP_GET, handleGetSimulationTrigger);
  server.on("/api/message", HTTP_POST, handlePostMessage);
  server.on("/api/aos-demo/provision", HTTP_POST, handlePostAosDemoProvision);
  server.on("/api/aos-demo/downlink", HTTP_POST, handlePostAosDemoDownlink);
  server.begin();
}

void loop() {
  server.handleClient();
  pollButtons();
  delay(2);
}

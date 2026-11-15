#include "character_emotion_logic.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>

static int failures = 0;

static void ExpectName(const char* label, DeviceState state, const char* want) {
    const char* got = CharacterEmotionNameForState(state);
    if ((want == nullptr && got != nullptr) ||
        (want != nullptr && (got == nullptr || std::strcmp(got, want) != 0))) {
        std::fprintf(stderr, "FAIL %s: got %s want %s\n", label, got ? got : "(null)",
                     want ? want : "(null)");
        failures++;
    }
}

static void ExpectAccept(const char* label, DeviceState state, bool want) {
    bool got = CharacterEmotionAcceptsServerEmotion(state);
    if (got != want) {
        std::fprintf(stderr, "FAIL %s: accept=%d want=%d\n", label, got ? 1 : 0, want ? 1 : 0);
        failures++;
    }
}

int main() {
    ExpectName("unknown", kDeviceStateUnknown, "idle");
    ExpectName("idle", kDeviceStateIdle, "idle");
    ExpectName("connecting", kDeviceStateConnecting, "idle");
    ExpectName("listening", kDeviceStateListening, "idle");
    ExpectName("speaking", kDeviceStateSpeaking, "speaking");
    ExpectName("notifying", kDeviceStateNotifying, "speaking");
    ExpectName("starting", kDeviceStateStarting, nullptr);
    ExpectName("wifi", kDeviceStateWifiConfiguring, nullptr);
    ExpectName("upgrading", kDeviceStateUpgrading, nullptr);
    ExpectName("activating", kDeviceStateActivating, nullptr);
    ExpectName("audio", kDeviceStateAudioTesting, nullptr);
    ExpectName("fatal", kDeviceStateFatalError, nullptr);

    ExpectAccept("speaking blocks llm emotion", kDeviceStateSpeaking, false);
    ExpectAccept("notifying blocks llm emotion", kDeviceStateNotifying, false);
    ExpectAccept("listening keeps llm emotion", kDeviceStateListening, true);
    ExpectAccept("idle keeps llm emotion", kDeviceStateIdle, true);

    if (failures != 0) {
        std::fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    std::puts("character emotion state machine ok");
    return 0;
}
